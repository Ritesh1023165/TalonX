"""
talonx_core.decision
-------------------------
The Decision Matrix: given a ticker's correlated state (freshest
QuantSignal + freshest ResearchReport), decide whether to publish an
ActionableAlert, and if so, which one.

    quant direction \\ research verdict   BULLISH              BEARISH              NEUTRAL / INSUFFICIENT_CONTEXT
    BULLISH                               CONFIRMED_BULLISH    CONTRADICTED         no alert
    BEARISH                               CONTRADICTED         CONFIRMED_BEARISH    no alert

Gated before the matrix even runs by three checks, any of which suppress
the alert entirely (return None) -- see evaluate()'s docstring for what
each one guards against. Nothing here does I/O; this is pure decision
logic over a TickerState snapshot, deliberately kept synchronous and
side-effect-free so it's trivial to unit test and to reason about
independent of Redis/asyncio.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_core.config import CoreConfig
from talonx_core.schemas import (
    ActionableAlert,
    AlertAction,
    AlertSeverity,
    ResearchVerdict,
    SignalDirection,
)
from talonx_core.state import TickerState

# Severity bands for a CONFIRMED alert, keyed off research confidence.
# A CONTRADICTED alert is bumped one band up (see _severity_for) --
# disagreement between the technical and fundamental read is inherently
# more noteworthy than agreement at the same confidence level, never
# just informational.
_CRITICAL_CONFIDENCE = 0.8
_WARNING_CONFIDENCE = 0.65


def evaluate(
    state: TickerState, config: CoreConfig, now: datetime | None = None
) -> ActionableAlert | None:
    """
    Returns an ActionableAlert if this ticker's current state clears the
    decision matrix, else None. `now` is injectable for testing;
    defaults to the real current time. Thin wrapper over
    _evaluate_with_reason -- see evaluate_verbose() for the same result
    plus WHY a None was suppressed (used by consumer.py to persist a
    durable trace for the EOD report; kept as a separate function rather
    than changing this one's signature so every existing caller/test is
    unaffected).
    """
    alert, _reason = _evaluate_with_reason(state, config, now)
    return alert


def evaluate_verbose(
    state: TickerState, config: CoreConfig, now: datetime | None = None
) -> tuple[ActionableAlert | None, str | None]:
    """
    Same decision as evaluate(), but also returns the suppression reason
    when the result is None -- MISSING_PAIR / STALE_SIGNAL / STALE_REPORT
    / COOLDOWN / LOW_CONFIDENCE / NEUTRAL_VERDICT / NO_STATE_CHANGE.
    `reason` is always None when an alert IS returned. See
    _evaluate_with_reason for what each one guards against.
    """
    return _evaluate_with_reason(state, config, now)


def _evaluate_with_reason(
    state: TickerState, config: CoreConfig, now: datetime | None = None
) -> tuple[ActionableAlert | None, str | None]:
    """
    The actual decision matrix -- evaluate() and evaluate_verbose() are
    both thin wrappers over this, so the gate logic lives in exactly one
    place and can never drift between the two entry points.

    Suppression checks, in order (each returns (None, "<REASON>")):
      1. MISSING_PAIR -- no signal yet, or no report yet.
      2. STALE_SIGNAL / STALE_REPORT -- either half is older than
         config.correlation_window_seconds. Guards against correlating a
         report against a signal from hours ago (or vice versa) just
         because both happen to be the most recent thing seen for that
         ticker.
      3. COOLDOWN -- an alert was already dispatched for this ticker
         within config.ticker_cooldown_seconds. Guards against
         re-alerting on what is functionally the same setup every time a
         new bar nudges an indicator.
      4. LOW_CONFIDENCE / NEUTRAL_VERDICT -- research confidence below
         config.min_confidence is treated as UNCONFIRMED regardless of
         verdict, same as NEUTRAL/INSUFFICIENT_CONTEXT. This is the
         module's core risk guardrail: don't act on a low-confidence LLM
         call. SKIPPED entirely for a report.is_degraded=True report
         (talonx_brain couldn't produce a real qualitative read at all --
         see below).
      5. NO_STATE_CHANGE -- if the action this evaluation would produce is
         the SAME action as the last alert actually dispatched for this
         ticker, it's suppressed unless price has moved
         config.price_delta_retrigger_pct since that alert. A genuine
         transition (including a first-ever alert) always passes. This
         runs IN ADDITION to the time cooldown (3), not instead of it --
         both must pass.

    report.is_degraded=True (talonx_brain's LLM totally failed and no
    cache existed to fall back on -- see talonx_brain/cache.py) bypasses
    check 4's confidence/verdict matrix entirely and always computes
    AlertAction.DEGRADED_QUANT_ALERT instead -- the point is to still
    surface that a technical signal fired even with zero qualitative
    backing, rather than silently dropping it the way a normal
    confidence=0.0 report would be. DEGRADED_QUANT_ALERT still
    participates in check 5 as its own pseudo-state, so a sustained LLM
    outage doesn't re-alert on every single signal for the same ticker.
    """
    now = now or datetime.now(timezone.utc)

    if state.latest_signal is None or state.latest_report is None:
        return None, "MISSING_PAIR"

    if not _is_fresh(state.latest_signal_at, now, config.correlation_window_seconds):
        return None, "STALE_SIGNAL"
    if not _is_fresh(state.latest_report_at, now, config.correlation_window_seconds):
        return None, "STALE_REPORT"

    if state.last_alert_at is not None:
        elapsed = (now - state.last_alert_at).total_seconds()
        if elapsed < config.ticker_cooldown_seconds:
            return None, "COOLDOWN"

    report = state.latest_report
    signal = state.latest_signal

    if report.is_degraded:
        action = AlertAction.DEGRADED_QUANT_ALERT
    else:
        if report.confidence < config.min_confidence:
            return None, "LOW_CONFIDENCE"
        if report.verdict not in (ResearchVerdict.BULLISH, ResearchVerdict.BEARISH):
            return None, "NEUTRAL_VERDICT"

        agrees = (
            signal.direction == SignalDirection.BULLISH and report.verdict == ResearchVerdict.BULLISH
        ) or (
            signal.direction == SignalDirection.BEARISH and report.verdict == ResearchVerdict.BEARISH
        )

        if agrees:
            action = (
                AlertAction.CONFIRMED_BULLISH
                if signal.direction == SignalDirection.BULLISH
                else AlertAction.CONFIRMED_BEARISH
            )
        else:
            action = AlertAction.CONTRADICTED

    if (
        state.last_alert_action is not None
        and action == state.last_alert_action
        and state.last_alert_price is not None
    ):
        delta_pct = abs(signal.price - state.last_alert_price) / state.last_alert_price
        if delta_pct < config.price_delta_retrigger_pct:
            return None, "NO_STATE_CHANGE"

    return ActionableAlert(
        ticker=signal.ticker,
        action=action,
        severity=_severity_for(action, report.confidence),
        rationale=_build_rationale(action, signal, report),
        quant_direction=signal.direction,
        research_verdict=report.verdict,
        research_confidence=report.confidence,
        triggering_signal=signal,
        research_summary=report.summary,
        key_findings=report.key_findings,
        risk_factors=report.risk_factors,
        model_used=report.model_used,
        is_degraded=report.is_degraded,
        signal_received_at=state.latest_signal_at,
        report_received_at=state.latest_report_at,
    ), None


def _is_fresh(received_at: datetime | None, now: datetime, window_seconds: float) -> bool:
    if received_at is None:
        return False
    return (now - received_at).total_seconds() <= window_seconds


def _severity_for(action: AlertAction, confidence: float) -> AlertSeverity:
    # A degraded alert means "no qualitative read at all" -- a
    # data-quality/availability issue worth noticing regardless of
    # confidence (which is a meaningless 0.0 placeholder for this action),
    # so it's never downgraded to INFO the way a genuinely low-confidence
    # real report would be.
    if action == AlertAction.DEGRADED_QUANT_ALERT:
        return AlertSeverity.WARNING
    if confidence >= _CRITICAL_CONFIDENCE:
        return AlertSeverity.CRITICAL
    if confidence >= _WARNING_CONFIDENCE:
        return AlertSeverity.WARNING
    # A CONTRADICTED alert is never "just FYI" -- it already cleared the
    # confidence gate, so the lowest it can be is a warning.
    if action == AlertAction.CONTRADICTED:
        return AlertSeverity.WARNING
    return AlertSeverity.INFO


def _build_rationale(action: AlertAction, signal, report) -> str:
    if action == AlertAction.DEGRADED_QUANT_ALERT:
        return (
            f"Quant signal ({signal.direction.value}): {signal.message}. "
            f"No research verdict available -- talonx_brain could not produce a "
            f"qualitative read for this ticker (LLM unavailable and no cached "
            f"report to fall back on). Dispatched on quantitative data alone."
        )
    relation = "agrees with" if action != AlertAction.CONTRADICTED else "CONTRADICTS"
    return (
        f"Quant signal ({signal.direction.value}): {signal.message}. "
        f"Research verdict {relation} the technical setup: {report.verdict.value} "
        f"at {report.confidence:.0%} confidence -- {report.summary}"
    )
