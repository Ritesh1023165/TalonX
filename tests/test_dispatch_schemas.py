"""
tests/test_dispatch_schemas.py
-----------------------------------
Tests talonx_dispatch.schemas -- the Pydantic contract at this module's
Redis boundary. ActionableAlert must parse the FULL wire shape
talonx_core.schemas.ActionableAlert.to_redis_payload() emits (full
QuantSignal embedded, with all its numeric indicator fields), even though
this module's TriggeringSignalRef mirror only declares a subset --
Pydantic's default extra="ignore" behavior is what makes that safe.
"""
from __future__ import annotations

import json

from talonx_dispatch.schemas import (
    ActionableAlert,
    AlertAction,
    AlertSeverity,
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
    # Trimmed mirror -- only the fields TriggeringSignalRef declares.
    assert alert.triggering_signal.price == 312.41
    assert alert.triggering_signal.signal_type == "rsi_oversold_volume_surge"
    assert not hasattr(alert.triggering_signal, "rsi")


def test_actionable_alert_round_trips_through_json():
    alert = ActionableAlert.model_validate(_full_wire_payload())
    reparsed = ActionableAlert.model_validate(json.loads(alert.model_dump_json()))
    assert reparsed.ticker == alert.ticker
    assert reparsed.action == alert.action


def test_severity_rank_orders_info_below_warning_below_critical():
    assert AlertSeverity.INFO.rank < AlertSeverity.WARNING.rank
    assert AlertSeverity.WARNING.rank < AlertSeverity.CRITICAL.rank
