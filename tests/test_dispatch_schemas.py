"""
tests/test_dispatch_schemas.py
-----------------------------------
Tests talonx_dispatch.schemas -- the Pydantic contract at this module's
Redis boundary. ActionableAlert must parse the FULL wire shape
talonx_core.schemas.ActionableAlert.to_redis_payload() emits (full
QuantSignal embedded, with all its numeric indicator fields), even though
this module's TriggeringSignalRef mirror only declares a SUBSET (rsi/macd/
volume_surge_ratio/atr/stop_price/target_price/trend_aligned/htf_sma_200/
session are declared as of the Phase 2 requirement doc's technical-detail
reply; sma_fast/sma_slow/volume remain genuinely trimmed) --
Pydantic's default extra="ignore" behavior is what makes the still-omitted
fields safe to receive anyway.
"""
from __future__ import annotations

import json

from talonx_dispatch.schemas import (
    ActionableAlert,
    AlertAction,
    AlertSeverity,
    RejectedCandidateEvent,
    ResearchVerdict,
    SignalDirection,
)


def _full_wire_payload() -> dict:
    # Exact shape talonx_core.schemas.ActionableAlert.to_redis_payload()
    # emits -- triggering_signal carries every QuantSignal field, most of
    # which talonx_dispatch's TriggeringSignalRef doesn't declare.
    return {
        "ticker": "AAPL",
        "action": "confirmed_bullish",
        "severity": "critical",
        "rationale": "Quant and research agree: bullish.",
        "quant_direction": "bullish",
        "research_verdict": "bullish",
        "research_confidence": 0.85,
        "triggering_signal": {
            "ticker": "AAPL",
            "signal_type": "rsi_oversold_volume_surge",
            "direction": "bullish",
            "message": "RSI 24.3 oversold with 2.8x volume surge",
            "price": 312.41,
            "rsi": 24.3,
            "macd": 0.5,
            "macd_signal_line": 0.3,
            "sma_fast": 300.0,
            "sma_slow": 290.0,
            "volume": 1_000_000.0,
            "volume_surge_ratio": 2.8,
            "atr": 4.2,
            "stop_price": 308.21,
            "target_price": 320.81,
            "trend_aligned": True,
            "htf_sma_200": 295.0,
            "session": "regular",
            "bar_timestamp": "2026-08-07T12:00:00Z",
            "published_at": "2026-08-07T12:00:01Z",
        },
        "research_summary": "Data center demand remains strong.",
        "key_findings": ["Revenue up 40% YoY"],
        "risk_factors": ["Export restrictions"],
        "model_used": "gemini-flash-latest",
        "signal_received_at": "2026-08-07T12:00:05Z",
        "report_received_at": "2026-08-07T12:00:30Z",
        "correlated_at": "2026-08-07T12:00:30Z",
        "published_at": "2026-08-07T12:00:30Z",
    }


def test_actionable_alert_parses_full_producer_wire_shape():
    alert = ActionableAlert.model_validate(_full_wire_payload())
    assert alert.ticker == "AAPL"
    assert alert.action == AlertAction.CONFIRMED_BULLISH
    assert alert.severity == AlertSeverity.CRITICAL
    assert alert.research_verdict == ResearchVerdict.BULLISH
    assert alert.quant_direction == SignalDirection.BULLISH
    assert alert.triggering_signal.price == 312.41
    assert alert.triggering_signal.signal_type == "rsi_oversold_volume_surge"
    # Technical-detail fields (Phase 2 requirement doc) ARE declared and parsed now.
    assert alert.triggering_signal.rsi == 24.3
    assert alert.triggering_signal.atr == 4.2
    assert alert.triggering_signal.stop_price == 308.21
    assert alert.triggering_signal.target_price == 320.81
    assert alert.triggering_signal.trend_aligned is True
    assert alert.triggering_signal.htf_sma_200 == 295.0
    assert alert.triggering_signal.session == "regular"
    # sma_fast/sma_slow/volume remain genuinely trimmed -- still not declared.
    assert not hasattr(alert.triggering_signal, "sma_fast")
    assert not hasattr(alert.triggering_signal, "volume")


def test_actionable_alert_round_trips_through_json():
    alert = ActionableAlert.model_validate(_full_wire_payload())
    reparsed = ActionableAlert.model_validate(json.loads(alert.model_dump_json()))
    assert reparsed.ticker == alert.ticker
    assert reparsed.action == alert.action


def test_severity_rank_orders_info_below_warning_below_critical():
    assert AlertSeverity.INFO.rank < AlertSeverity.WARNING.rank
    assert AlertSeverity.WARNING.rank < AlertSeverity.CRITICAL.rank


# --- RejectedCandidateEvent (Rejection Trace Logging) -----------------------

def test_rejected_candidate_event_parses_the_producer_wire_shape():
    # Mirrors talonx_quant.schemas.RejectedCandidateEvent.to_redis_payload()'s
    # actual output shape (a datetime serializes to an ISO-8601 string).
    payload = {
        "ticker": "aapl", "gate": "rr_gate", "reason": "LOW_RISK_REWARD",
        "signal_type": "macd_bullish_cross", "direction": "bullish", "price": 100.0,
        "confluence_score": 2, "risk_reward_ratio": 1.2, "session": "regular",
        "count": 1, "rejected_at": "2026-08-16T15:00:00Z",
    }

    event = RejectedCandidateEvent.model_validate(payload)

    assert event.ticker == "aapl"
    assert event.gate == "rr_gate"
    assert event.reason == "LOW_RISK_REWARD"
    assert event.direction == SignalDirection.BULLISH


def test_rejected_candidate_event_optional_fields_default_to_none():
    payload = {
        "ticker": "AAPL", "gate": "volatility_gate", "reason": "LOW_VOLATILITY",
        "rejected_at": "2026-08-16T15:00:00Z",
    }

    event = RejectedCandidateEvent.model_validate(payload)

    assert event.signal_type is None
    assert event.direction is None
    assert event.confluence_score is None
    assert event.risk_reward_ratio is None


def test_rejected_candidate_event_round_trips_through_json():
    payload = {
        "ticker": "AAPL", "gate": "trend_gate", "reason": "TREND_GATE",
        "rejected_at": "2026-08-16T15:00:00Z",
    }
    event = RejectedCandidateEvent.model_validate(payload)

    reparsed = RejectedCandidateEvent.model_validate(json.loads(event.model_dump_json()))

    assert reparsed.ticker == event.ticker
    assert reparsed.gate == event.gate
