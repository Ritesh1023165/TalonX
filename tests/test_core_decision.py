"""
tests/test_core_decision.py
--------------------------------
Tests talonx_core.decision.evaluate() -- the Decision Matrix. Pure logic,
no I/O: given a TickerState snapshot and a CoreConfig, does it produce
the right ActionableAlert (or correctly produce none)? Covers each
suppression check independently (missing half, staleness, cooldown,
confidence gate, non-directional verdict) plus the matrix outcomes
(CONFIRMED_BULLISH, CONFIRMED_BEARISH, CONTRADICTED) and severity bands,
plus the newer state-transition + price-delta re-trigger gate and the
is_degraded -> DEGRADED_QUANT_ALERT bypass.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from talonx_core.config import CoreConfig
from talonx_core.decision import evaluate, evaluate_verbose
from talonx_core.schemas import (
    AlertAction,
    AlertSeverity,
    QuantSignal,
    ResearchReport,
    ResearchVerdict,
    SignalDirection,
    SignalType,
)
from talonx_core.state import TickerState

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


def _signal(direction: SignalDirection = SignalDirection.BULLISH, price: float = 200.0) -> QuantSignal:
    return QuantSignal(
        ticker="AAPL",
        signal_type=SignalType.RSI_OVERSOLD_VOLUME_SURGE,
        direction=direction,
        message="RSI oversold with volume surge",
        price=price,
        bar_timestamp=NOW - timedelta(minutes=1),
    )


def _report(
    verdict: ResearchVerdict = ResearchVerdict.BULLISH,
    confidence: float = 0.8,
    is_degraded: bool = False,
    price: float = 200.0,
) -> ResearchReport:
    return ResearchReport(
        ticker="AAPL",
        triggering_signal=_signal(price=price),
        verdict=verdict,
        confidence=confidence,
        summary="Fundamentals support the move.",
        model_used="gemini-flash-latest",
        is_degraded=is_degraded,
        generated_at=NOW - timedelta(seconds=30),
        published_at=NOW - timedelta(seconds=30),
    )


def test_no_alert_when_signal_missing():
    state = TickerState(latest_report=_report(), latest_report_at=NOW)
    assert evaluate(state, CoreConfig(), now=NOW) is None


def test_no_alert_when_report_missing():
    state = TickerState(latest_signal=_signal(), latest_signal_at=NOW)
    assert evaluate(state, CoreConfig(), now=NOW) is None


def test_no_alert_when_signal_is_stale():
    config = CoreConfig(correlation_window_seconds=60)
    state = TickerState(
        latest_signal=_signal(), latest_signal_at=NOW - timedelta(seconds=120),
        latest_report=_report(), latest_report_at=NOW,
    )
    assert evaluate(state, config, now=NOW) is None


def test_no_alert_when_report_is_stale():
    config = CoreConfig(correlation_window_seconds=60)
    state = TickerState(
        latest_signal=_signal(), latest_signal_at=NOW,
        latest_report=_report(), latest_report_at=NOW - timedelta(seconds=120),
    )
    assert evaluate(state, config, now=NOW) is None


def test_no_alert_during_cooldown():
    config = CoreConfig(ticker_cooldown_seconds=300)
    state = TickerState(
        latest_signal=_signal(), latest_signal_at=NOW,
        latest_report=_report(), latest_report_at=NOW,
        last_alert_at=NOW - timedelta(seconds=60),
    )
    assert evaluate(state, config, now=NOW) is None


def test_alert_allowed_after_cooldown_elapses():
    config = CoreConfig(ticker_cooldown_seconds=300)
    state = TickerState(
        latest_signal=_signal(), latest_signal_at=NOW,
        latest_report=_report(), latest_report_at=NOW,
        last_alert_at=NOW - timedelta(seconds=301),
    )
    assert evaluate(state, config, now=NOW) is not None


def test_no_alert_below_confidence_threshold():
    config = CoreConfig(min_confidence=0.5)
    state = TickerState(
        latest_signal=_signal(), latest_signal_at=NOW,
        latest_report=_report(confidence=0.3), latest_report_at=NOW,
    )
    assert evaluate(state, config, now=NOW) is None


def test_no_alert_for_neutral_verdict():
    state = TickerState(
        latest_signal=_signal(), latest_signal_at=NOW,
        latest_report=_report(verdict=ResearchVerdict.NEUTRAL), latest_report_at=NOW,
    )
    assert evaluate(state, CoreConfig(), now=NOW) is None


def test_no_alert_for_insufficient_context():
    state = TickerState(
        latest_signal=_signal(), latest_signal_at=NOW,
        latest_report=_report(verdict=ResearchVerdict.INSUFFICIENT_CONTEXT), latest_report_at=NOW,
    )
    assert evaluate(state, CoreConfig(), now=NOW) is None


def test_confirmed_bullish_when_directions_agree():
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.BULLISH, confidence=0.9), latest_report_at=NOW,
    )
    alert = evaluate(state, CoreConfig(), now=NOW)
    assert alert is not None
    assert alert.action == AlertAction.CONFIRMED_BULLISH
    assert alert.severity == AlertSeverity.CRITICAL


def test_confirmed_bearish_when_directions_agree():
    state = TickerState(
        latest_signal=_signal(SignalDirection.BEARISH), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.BEARISH, confidence=0.7), latest_report_at=NOW,
    )
    alert = evaluate(state, CoreConfig(), now=NOW)
    assert alert is not None
    assert alert.action == AlertAction.CONFIRMED_BEARISH
    assert alert.severity == AlertSeverity.WARNING


def test_contradicted_when_directions_disagree():
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.BEARISH, confidence=0.55), latest_report_at=NOW,
    )
    alert = evaluate(state, CoreConfig(min_confidence=0.5), now=NOW)
    assert alert is not None
    assert alert.action == AlertAction.CONTRADICTED
    # Low confidence for a CONFIRMED alert would be INFO, but a
    # CONTRADICTED alert is never "just FYI" -- floor is WARNING.
    assert alert.severity == AlertSeverity.WARNING


def test_confirmed_low_confidence_is_info_severity():
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.BULLISH, confidence=0.55), latest_report_at=NOW,
    )
    alert = evaluate(state, CoreConfig(min_confidence=0.5), now=NOW)
    assert alert is not None
    assert alert.severity == AlertSeverity.INFO


def test_alert_embeds_full_triggering_signal_and_research_fields():
    signal = _signal(SignalDirection.BULLISH)
    report = _report(ResearchVerdict.BULLISH, confidence=0.9)
    state = TickerState(
        latest_signal=signal, latest_signal_at=NOW,
        latest_report=report, latest_report_at=NOW,
    )
    alert = evaluate(state, CoreConfig(), now=NOW)
    assert alert.triggering_signal == signal
    assert alert.research_summary == report.summary
    assert alert.ticker == "AAPL"
    assert signal.message in alert.rationale


# --- State-transition + price-delta re-trigger gate -----------------------
# No `last_alert_at`/cooldown is set in these -- the gate under test here
# runs IN ADDITION to the time cooldown (see the dedicated test at the
# bottom confirming both are enforced together), so it's isolated here by
# simply not tripping the cooldown check at all.

def test_first_ever_alert_bypasses_the_gate():
    # last_alert_action is None -- nothing to compare against yet.
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH, price=200.0), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.BULLISH, price=200.0), latest_report_at=NOW,
    )
    assert evaluate(state, CoreConfig(), now=NOW) is not None


def test_same_action_with_tiny_price_move_is_suppressed():
    config = CoreConfig(price_delta_retrigger_pct=0.01)
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH, price=200.5), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.BULLISH, price=200.5), latest_report_at=NOW,
        last_alert_action=AlertAction.CONFIRMED_BULLISH, last_alert_price=200.0,  # 0.25% move
    )
    assert evaluate(state, config, now=NOW) is None


def test_same_action_with_large_enough_price_move_passes():
    config = CoreConfig(price_delta_retrigger_pct=0.01)
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH, price=203.0), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.BULLISH, price=203.0), latest_report_at=NOW,
        last_alert_action=AlertAction.CONFIRMED_BULLISH, last_alert_price=200.0,  # 1.5% move
    )
    alert = evaluate(state, config, now=NOW)
    assert alert is not None
    assert alert.action == AlertAction.CONFIRMED_BULLISH


def test_genuine_state_transition_bypasses_the_price_delta_check():
    # Same price as the last alert, but a DIFFERENT action -- a real
    # transition always passes regardless of price movement.
    config = CoreConfig(price_delta_retrigger_pct=0.01)
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH, price=200.0), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.BEARISH, price=200.0), latest_report_at=NOW,
        last_alert_action=AlertAction.CONFIRMED_BULLISH, last_alert_price=200.0,
    )
    alert = evaluate(state, config, now=NOW)
    assert alert is not None
    assert alert.action == AlertAction.CONTRADICTED


def test_time_cooldown_and_state_gate_both_apply():
    # A genuine transition (would pass the state gate) but still within
    # the time cooldown -- must still be suppressed. Confirms the two
    # gates are additive, not either/or.
    config = CoreConfig(ticker_cooldown_seconds=300, price_delta_retrigger_pct=0.01)
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH, price=250.0), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.BEARISH, price=250.0), latest_report_at=NOW,
        last_alert_action=AlertAction.CONFIRMED_BULLISH, last_alert_price=200.0,
        last_alert_at=NOW - timedelta(seconds=60),
    )
    assert evaluate(state, config, now=NOW) is None


# --- Degraded report bypass -------------------------------------------------

def test_degraded_report_bypasses_confidence_gate_into_degraded_alert():
    config = CoreConfig(min_confidence=0.5)
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.NEUTRAL, confidence=0.0, is_degraded=True), latest_report_at=NOW,
    )
    alert = evaluate(state, config, now=NOW)
    assert alert is not None
    assert alert.action == AlertAction.DEGRADED_QUANT_ALERT
    assert alert.severity == AlertSeverity.WARNING
    assert alert.is_degraded is True


def test_repeated_degraded_alerts_are_suppressed_like_any_other_same_state():
    config = CoreConfig(price_delta_retrigger_pct=0.01)
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH, price=200.5), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.NEUTRAL, confidence=0.0, is_degraded=True, price=200.5),
        latest_report_at=NOW,
        last_alert_action=AlertAction.DEGRADED_QUANT_ALERT, last_alert_price=200.0,  # 0.25% move
    )
    assert evaluate(state, config, now=NOW) is None


def test_degraded_alert_price_move_still_retriggers():
    config = CoreConfig(price_delta_retrigger_pct=0.01)
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH, price=203.0), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.NEUTRAL, confidence=0.0, is_degraded=True, price=203.0),
        latest_report_at=NOW,
        last_alert_action=AlertAction.DEGRADED_QUANT_ALERT, last_alert_price=200.0,  # 1.5% move
    )
    alert = evaluate(state, config, now=NOW)
    assert alert is not None
    assert alert.action == AlertAction.DEGRADED_QUANT_ALERT


# --- evaluate_verbose() -- the suppression reason surfaced for the EOD
# report's signal-funnel section. Each case below mirrors an existing
# evaluate()-returns-None test above, just asserting the reason too.

def test_verbose_reason_missing_pair():
    state = TickerState(latest_report=_report(), latest_report_at=NOW)
    alert, reason = evaluate_verbose(state, CoreConfig(), now=NOW)
    assert alert is None
    assert reason == "MISSING_PAIR"


def test_verbose_reason_stale_signal():
    config = CoreConfig(correlation_window_seconds=60)
    state = TickerState(
        latest_signal=_signal(), latest_signal_at=NOW - timedelta(seconds=120),
        latest_report=_report(), latest_report_at=NOW,
    )
    alert, reason = evaluate_verbose(state, config, now=NOW)
    assert alert is None
    assert reason == "STALE_SIGNAL"


def test_verbose_reason_stale_report():
    config = CoreConfig(correlation_window_seconds=60)
    state = TickerState(
        latest_signal=_signal(), latest_signal_at=NOW,
        latest_report=_report(), latest_report_at=NOW - timedelta(seconds=120),
    )
    alert, reason = evaluate_verbose(state, config, now=NOW)
    assert alert is None
    assert reason == "STALE_REPORT"


def test_verbose_reason_cooldown():
    config = CoreConfig(ticker_cooldown_seconds=300)
    state = TickerState(
        latest_signal=_signal(), latest_signal_at=NOW,
        latest_report=_report(), latest_report_at=NOW,
        last_alert_at=NOW - timedelta(seconds=60),
    )
    alert, reason = evaluate_verbose(state, config, now=NOW)
    assert alert is None
    assert reason == "COOLDOWN"


def test_verbose_reason_low_confidence():
    config = CoreConfig(min_confidence=0.5)
    state = TickerState(
        latest_signal=_signal(), latest_signal_at=NOW,
        latest_report=_report(confidence=0.3), latest_report_at=NOW,
    )
    alert, reason = evaluate_verbose(state, config, now=NOW)
    assert alert is None
    assert reason == "LOW_CONFIDENCE"


def test_verbose_reason_neutral_verdict():
    state = TickerState(
        latest_signal=_signal(), latest_signal_at=NOW,
        latest_report=_report(verdict=ResearchVerdict.NEUTRAL), latest_report_at=NOW,
    )
    alert, reason = evaluate_verbose(state, CoreConfig(), now=NOW)
    assert alert is None
    assert reason == "NEUTRAL_VERDICT"


def test_verbose_reason_no_state_change():
    config = CoreConfig(price_delta_retrigger_pct=0.01)
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH, price=200.5), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.BULLISH, price=200.5), latest_report_at=NOW,
        last_alert_action=AlertAction.CONFIRMED_BULLISH, last_alert_price=200.0,
    )
    alert, reason = evaluate_verbose(state, config, now=NOW)
    assert alert is None
    assert reason == "NO_STATE_CHANGE"


def test_verbose_reason_is_none_when_an_alert_is_produced():
    state = TickerState(
        latest_signal=_signal(SignalDirection.BULLISH), latest_signal_at=NOW,
        latest_report=_report(ResearchVerdict.BULLISH, confidence=0.9), latest_report_at=NOW,
    )
    alert, reason = evaluate_verbose(state, CoreConfig(), now=NOW)
    assert alert is not None
    assert reason is None
