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
    defaults to the real current time.

    Suppression checks, in order:
      1. Missing half of the pair -- no signal yet, or no report yet.
      2. Staleness -- either half is older than
         config.correlation_window_seconds. Guards against correlating a
         report against a signal from hours ago (or vice versa) just
         because both happen to be the most recent thing seen for that
         ticker.
      3. Cooldown -- an alert was already dispatched for this ticker
         within config.ticker_cooldown_seconds. Guards against
         re-alerting on what is functionally the same setup every time a
         new bar nudges an indicator.
      4. Confidence gate -- research confidence below config.min_confidence
         is treated as UNCONFIRMED regardless of verdict, same as
         NEUTRAL/INSUFFICIENT_CONTEXT. This is the module's core risk
         guardrail: don't act on a low-confidence LLM call. SKIPPED
         entirely for a report.is_degraded=True report (talonx_brain
         couldn't produce a real qualitative read at all -- see below).
      5. State-transition + price-delta gate -- if the action this
         evaluation would produce is the SAME action as the last alert
         actually dispatched for this ticker, it's suppressed unless price
         has moved config.price_delta_retrigger_pct since that alert. A
         genuine transition (including a first-ever alert) always passes.
         This runs IN ADDITION to the time cooldown (3), not instead of it
         -- both must pass.

    report.is_degraded=True (talonx_brain's LLM totally failed and no
    cache existed to fall back on -- see talonx_brain/cache.py) bypasses
    checks 4's confidence/verdict matrix entirely and always computes
    AlertAction.DEGRADED_QUANT_ALERT instead -- the point is to still
    surface that a technical signal fired even with zero qualitative
    backing, rather than silently dropping it the way a normal
    confidence=0.0 report would be. DEGRADED_QUANT_ALERT still
    participates in check 5 as its own pseudo-state, so a sustained LLM
    outage doesn't re-alert on every single signal for the same ticker.
    """
    now = now or datetime.now(timezone.utc)

    if state.latest_signal is None or state.latest_report is None:
        return None

    if not _is_fresh(state.latest_signal_at, now, config.correlation_window_seconds):
        return None
    if not _is_fresh(state.latest_report_at, now, config.correlation_window_seconds):
        return None

    if state.last_alert_at is not None:
        elapsed = (now - state.last_alert_at).total_seconds()
        if elapsed < config.ticker_cooldown_seconds:
            return None

    report = state.latest_report
    signal = state.latest_signal

    if report.is_degraded:
        action = AlertAction.DEGRADED_QUANT_ALERT
    else:
        if report.confidence < config.min_confidence:
            return None
        if report.verdict not in (ResearchVerdict.BULLISH, ResearchVerdict.BEARISH):
            return None

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
            return None

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
    )


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
