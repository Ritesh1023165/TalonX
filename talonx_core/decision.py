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
    LongTermActionableAlert,
    MoatRating,
    ResearchVerdict,
    SignalDirection,
)
from talonx_core.state import LongTermTickerState, TickerState

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


# ------------------------------------------------------------------
# Phase 2 LONG_TERM decision matrix
#
#   Fundamental stop (checked FIRST, unconditional -- overrides quality/
#   valuation entirely): ROIC below WACC for 2 consecutive annual
#   observations, OR Debt/EBITDA proxy > max_debt_to_ebitda, OR the
#   economic moat rating was downgraded since the last report.
#       -> UNDER_PERFORM_REBALANCE
#
#   Otherwise, quality + valuation:
#     price > (1 + valuation_premium_pct) * fair_value
#       -> TAKE_PROFIT_REBALANCE (no quality gate -- an overvalued
#          position should be trimmed regardless of how good the
#          business is)
#     quality_score >= quality_score_min AND moat in (WIDE, NARROW)
#       AND price <= (1 - margin_of_safety_pct) * fair_value
#       -> HIGH_CONVICTION_BUY
#     quality_score >= quality_score_min AND price within the fair-value
#       band ((1 - margin_of_safety_pct) * fair_value < price <=
#       (1 + valuation_premium_pct) * fair_value)
#       -> HOLD_QUALITY
#     else -> no alert (LOW_QUALITY_OR_FAIR_VALUE)
#
# Same "one real function, two thin public wrappers" shape as the
# intraday matrix above, and the same suppression-reason-string
# convention (MISSING_PAIR / STALE_SIGNAL / STALE_REPORT / COOLDOWN /
# DEGRADED_REPORT / LOW_QUALITY_OR_FAIR_VALUE / NO_STATE_CHANGE).
# ------------------------------------------------------------------

def evaluate_long_term(
    state: LongTermTickerState, config: CoreConfig, now: datetime | None = None
) -> LongTermActionableAlert | None:
    """Long-term sibling of evaluate() -- see module-level comment above
    the long-term section for the matrix, and evaluate_long_term_verbose()
    for the same result plus a suppression reason."""
    alert, _reason = _evaluate_long_term_with_reason(state, config, now)
    return alert


def evaluate_long_term_verbose(
    state: LongTermTickerState, config: CoreConfig, now: datetime | None = None
) -> tuple[LongTermActionableAlert | None, str | None]:
    """Same decision as evaluate_long_term(), but also returns the
    suppression reason when the result is None."""
    return _evaluate_long_term_with_reason(state, config, now)


def _evaluate_long_term_with_reason(
    state: LongTermTickerState, config: CoreConfig, now: datetime | None = None
) -> tuple[LongTermActionableAlert | None, str | None]:
    now = now or datetime.now(timezone.utc)

    if state.fundamental_signal is None or state.longterm_report is None:
        return None, "MISSING_PAIR"

    if not _is_fresh(state.fundamental_signal_at, now, config.correlation_window_long_term_seconds):
        return None, "STALE_SIGNAL"
    if not _is_fresh(state.longterm_report_at, now, config.correlation_window_long_term_seconds):
        return None, "STALE_REPORT"

    if state.last_alert_at is not None:
        elapsed = (now - state.last_alert_at).total_seconds()
        if elapsed < config.ticker_cooldown_long_term_seconds:
            return None, "COOLDOWN"

    signal = state.fundamental_signal
    report = state.longterm_report

    # A degraded report carries no usable moat/quality/fair-value data
    # (all placeholder defaults -- see talonx_brain.consumer's degraded
    # long-term report) -- unlike the intraday path, there's no
    # quant-only long-term action defined to fall back to, so this is a
    # clean suppression rather than a DEGRADED_QUANT_ALERT-style
    # placeholder alert.
    if report.is_degraded:
        return None, "DEGRADED_REPORT"

    fair_value = report.dcf_fair_value_per_share
    price = signal.price
    moat_downgraded = (
        state.previous_moat_rating is not None
        and _moat_rank(report.moat_rating) < _moat_rank(state.previous_moat_rating)
    )
    debt_to_ebitda_breach = (
        signal.debt_to_ebitda_proxy is not None and signal.debt_to_ebitda_proxy > config.max_debt_to_ebitda
    )
    roic_streak_breach = state.roic_below_wacc_streak >= 2

    if roic_streak_breach or debt_to_ebitda_breach or moat_downgraded:
        action = AlertAction.UNDER_PERFORM_REBALANCE
    elif fair_value <= 0:
        # No usable fair-value estimate -- can't evaluate the valuation
        # bands at all (would divide by zero / produce nonsense ratios).
        return None, "NO_FAIR_VALUE_ESTIMATE"
    elif price > (1 + config.valuation_premium_pct) * fair_value:
        action = AlertAction.TAKE_PROFIT_REBALANCE
    elif (
        report.quality_score >= config.quality_score_min
        and report.moat_rating in (MoatRating.WIDE, MoatRating.NARROW)
        and price <= (1 - config.margin_of_safety_pct) * fair_value
    ):
        action = AlertAction.HIGH_CONVICTION_BUY
    elif (
        report.quality_score >= config.quality_score_min
        and (1 - config.margin_of_safety_pct) * fair_value < price
    ):
        # Explicitly re-checks the lower band edge -- a deep-discount
        # name that failed HIGH_CONVICTION_BUY's moat requirement must
        # NOT fall through to HOLD_QUALITY just because it also clears
        # the quality bar; it's genuinely below the "fairly priced" band,
        # just not moat-qualified enough to act on the discount.
        action = AlertAction.HOLD_QUALITY
    else:
        return None, "LOW_QUALITY_OR_FAIR_VALUE"

    if (
        state.last_alert_action is not None
        and action == state.last_alert_action
        and state.last_alert_price is not None
    ):
        delta_pct = abs(price - state.last_alert_price) / state.last_alert_price
        if delta_pct < config.price_delta_retrigger_pct_long_term:
            return None, "NO_STATE_CHANGE"

    margin_of_safety_pct = (fair_value - price) / fair_value if fair_value > 0 else 0.0

    return LongTermActionableAlert(
        ticker=signal.ticker,
        action=action,
        severity=_severity_for_long_term(action),
        rationale=_build_long_term_rationale(
            action, signal, report, moat_downgraded, debt_to_ebitda_breach, roic_streak_breach,
        ),
        quality_score=report.quality_score,
        moat_rating=report.moat_rating,
        market_price=price,
        intrinsic_fair_value=fair_value,
        margin_of_safety_pct=margin_of_safety_pct,
        triggering_signal=signal,
        capital_allocation_assessment=report.capital_allocation_assessment,
        key_findings=report.key_findings,
        risk_factors=report.risk_factors,
        model_used=report.model_used,
        is_degraded=report.is_degraded,
        signal_received_at=state.fundamental_signal_at,
        report_received_at=state.longterm_report_at,
    ), None


def _moat_rank(moat: MoatRating) -> int:
    return {MoatRating.NONE: 0, MoatRating.NARROW: 1, MoatRating.WIDE: 2}[moat]


def _severity_for_long_term(action: AlertAction) -> AlertSeverity:
    if action in (AlertAction.HIGH_CONVICTION_BUY, AlertAction.UNDER_PERFORM_REBALANCE):
        return AlertSeverity.CRITICAL
    if action == AlertAction.TAKE_PROFIT_REBALANCE:
        return AlertSeverity.WARNING
    return AlertSeverity.INFO  # HOLD_QUALITY -- informational, no action needed


def _build_long_term_rationale(
    action: AlertAction, signal, report, moat_downgraded: bool, debt_to_ebitda_breach: bool, roic_streak_breach: bool,
) -> str:
    if action == AlertAction.UNDER_PERFORM_REBALANCE:
        reasons = []
        if roic_streak_breach:
            reasons.append("ROIC has been below the assumed WACC for 2+ consecutive annual observations")
        if debt_to_ebitda_breach:
            reasons.append(f"Debt/EBITDA proxy ({signal.debt_to_ebitda_proxy:.2f}x) exceeds the leverage cap")
        if moat_downgraded:
            reasons.append(f"economic moat was downgraded to {report.moat_rating.value}")
        return (
            f"Fundamental stop triggered for {signal.ticker}: " + "; ".join(reasons) + ". "
            f"{report.summary}"
        )
    return (
        f"FY{signal.fiscal_year} fundamentals ({signal.message}) -- quality score "
        f"{report.quality_score}/10, {report.moat_rating.value} moat. Market price ${signal.price:,.2f} "
        f"vs. intrinsic fair value ${report.dcf_fair_value_per_share:,.2f}. {report.summary}"
    )
