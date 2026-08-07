"""
tests/test_core_schemas.py
-------------------------------
Tests talonx_core.schemas -- the Pydantic contracts at this module's
Redis boundary. QuantSignal must parse talonx_quant's wire shape;
ResearchReport must parse talonx_brain's wire shape EVEN THOUGH it's a
deliberately trimmed mirror that omits `citations` (Pydantic's default
extra="ignore" behavior is what makes that safe -- this test proves it,
not just asserts it in a docstring). ActionableAlert must round-trip
through JSON the way every other event contract in this project does.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from talonx_core.schemas import (
    ActionableAlert,
    AlertAction,
    AlertSeverity,
    QuantSignal,
    ResearchReport,
    ResearchVerdict,
    SignalDirection,
    SignalType,
)


def _sample_signal() -> QuantSignal:
    return QuantSignal(
        ticker="NVDA",
        signal_type=SignalType.RSI_OVERSOLD_VOLUME_SURGE,
        direction=SignalDirection.BULLISH,
        message="RSI 24.3 oversold with 2.8x volume surge",
        price=131.5,
        rsi=24.3,
        bar_timestamp=datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc),
    )


def test_quant_signal_parses_producer_wire_shape():
    raw = {
        "ticker": "AAPL",
        "signal_type": "macd_bullish_cross",
        "direction": "bullish",
        "message": "MACD (0.120) crossed above signal line (0.080)",
        "price": 210.4,
        "rsi": None,
        "macd": 0.12,
        "macd_signal_line": 0.08,
        "sma_fast": None,
        "sma_slow": None,
        "volume": None,
        "volume_surge_ratio": None,
        "bar_timestamp": "2026-08-04T12:00:00Z",
        "published_at": "2026-08-04T12:00:01Z",
    }
    signal = QuantSignal.model_validate(raw)
    assert signal.ticker == "AAPL"
    assert signal.signal_type == SignalType.MACD_BULLISH_CROSS
    assert signal.direction == SignalDirection.BULLISH


def test_research_report_parses_full_wire_shape_and_drops_citations():
    # This is the FULL shape talonx_brain.schemas.ResearchReport.to_redis_payload()
    # emits, citations and all -- talonx_core's trimmed model doesn't declare
    # `citations`, so Pydantic's default extra="ignore" should just drop it.
    raw = {
        "ticker": "AAPL",
        "triggering_signal": {
            "ticker": "AAPL",
            "signal_type": "rsi_overbought_volume_surge",
            "direction": "bearish",
            "message": "RSI 94.3 overbought with 3.3x volume surge",
            "price": 312.41,
            "rsi": 94.3,
            "macd": None, "macd_signal_line": None, "sma_fast": None, "sma_slow": None,
            "volume": 46076800.0, "volume_surge_ratio": 3.3,
            "bar_timestamp": "2026-08-07T12:34:01Z",
            "published_at": "2026-08-07T12:34:08Z",
        },
        "verdict": "insufficient_context",
        "confidence": 0.1,
        "summary": "Filings contain only boilerplate disclosures.",
        "key_findings": ["Legal proceedings settled with no material impact."],
        "risk_factors": ["Trading without fundamental grounding is risky."],
        "citations": [
            {
                "chunk_id": "c1", "excerpt": "some filing text", "source_type": "filing",
                "source_document": "aapl-10k.htm", "form_type": "10-K",
                "filing_date": "2025-10-31", "accession_number": "0000320193-25-000079",
                "relevance_distance": 0.64,
            }
        ],
        "model_used": "gemini-flash-latest",
        "generated_at": "2026-08-07T12:34:28Z",
        "published_at": "2026-08-07T12:34:28Z",
    }
    report = ResearchReport.model_validate(raw)
    assert report.ticker == "AAPL"
    assert report.verdict == ResearchVerdict.INSUFFICIENT_CONTEXT
    assert report.triggering_signal.signal_type == SignalType.RSI_OVERBOUGHT_VOLUME_SURGE
    assert not hasattr(report, "citations")


def test_actionable_alert_serializes_to_valid_json():
    alert = ActionableAlert(
        ticker="NVDA",
        action=AlertAction.CONFIRMED_BULLISH,
        severity=AlertSeverity.CRITICAL,
        rationale="Quant and research agree: bullish.",
        quant_direction=SignalDirection.BULLISH,
        research_verdict=ResearchVerdict.BULLISH,
        research_confidence=0.85,
        triggering_signal=_sample_signal(),
        research_summary="Data center demand remains strong.",
        key_findings=["Revenue up 40% YoY"],
        risk_factors=["Export restrictions"],
        model_used="gemini-flash-latest",
        signal_received_at=datetime(2026, 8, 4, 12, 0, 5, tzinfo=timezone.utc),
        report_received_at=datetime(2026, 8, 4, 12, 0, 30, tzinfo=timezone.utc),
    )
    payload = json.loads(alert.to_redis_payload())
    assert payload["ticker"] == "NVDA"
    assert payload["action"] == "confirmed_bullish"
    assert payload["severity"] == "critical"
    assert payload["triggering_signal"]["signal_type"] == "rsi_oversold_volume_surge"
    assert 0.0 <= payload["research_confidence"] <= 1.0
