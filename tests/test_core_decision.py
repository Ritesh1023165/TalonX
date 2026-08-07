"""
tests/test_core_decision.py
--------------------------------
Tests talonx_core.decision.evaluate() -- the Decision Matrix. Pure logic,
no I/O: given a TickerState snapshot and a CoreConfig, does it produce
the right ActionableAlert (or correctly produce none)? Covers each
suppression check independently (missing half, staleness, cooldown,
confidence gate, non-directional verdict) plus the matrix outcomes
(CONFIRMED_BULLISH, CONFIRMED_BEARISH, CONTRADICTED) and severity bands.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from talonx_core.config import CoreConfig
from talonx_core.decision import evaluate
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


def _signal(direction: SignalDirection = SignalDirection.BULLISH) -> QuantSignal:
    return QuantSignal(
        ticker="AAPL",
        signal_type=SignalType.RSI_OVERSOLD_VOLUME_SURGE,
        direction=direction,
        message="RSI oversold with volume surge",
        price=200.0,
        bar_timestamp=NOW - timedelta(minutes=1),
    )


def _report(
    verdict: ResearchVerdict = ResearchVerdict.BULLISH, confidence: float = 0.8
) -> ResearchReport:
    return ResearchReport(
        ticker="AAPL",
        triggering_signal=_signal(),
        verdict=verdict,
        confidence=confidence,
        summary="Fundamentals support the move.",
        model_used="gemini-flash-latest",
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
