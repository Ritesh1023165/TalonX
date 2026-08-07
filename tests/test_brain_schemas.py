"""
tests/test_brain_schemas.py
--------------------------------
Tests talonx_brain.schemas -- the Pydantic contracts at this module's
Redis boundary. QuantSignal must parse the exact wire shape
talonx_quant.schemas.QuantSignal publishes (that's the whole point of the
mirrored re-declaration); ResearchReport must round-trip through JSON the
way every other event contract in this project does.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from talonx_brain.schemas import (
    Citation,
    CitationSourceType,
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
        volume=1_000_000,
        volume_surge_ratio=2.8,
        bar_timestamp=datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc),
    )


def test_quant_signal_parses_producer_wire_shape():
    # Exact shape talonx_quant.schemas.QuantSignal.to_redis_payload() emits.
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
    assert signal.macd == 0.12


def test_research_report_serializes_to_valid_json():
    report = ResearchReport(
        ticker="NVDA",
        triggering_signal=_sample_signal(),
        verdict=ResearchVerdict.BULLISH,
        confidence=0.72,
        summary="Filings show strong data center demand consistent with the surge.",
        key_findings=["Data center revenue up 40% YoY per latest 10-Q"],
        risk_factors=["Export restrictions to China cited as a material risk"],
        citations=[
            Citation(
                chunk_id="0000320193-24-000123-00042-abc1234567",
                excerpt="Data center revenue increased 40% year over year...",
                source_type=CitationSourceType.FILING,
                source_document="nvda-20250427.htm",
                form_type="10-Q",
                filing_date="2025-04-27",
                accession_number="0000320193-24-000123",
                relevance_distance=0.18,
            ),
            Citation(
                chunk_id="article-00001-hash",
                excerpt="NVIDIA announces record data center demand ahead of earnings.",
                source_type=CitationSourceType.NEWS,
                article_title="NVIDIA announces record data center demand",
                article_url="https://example.com/nvda-news",
                article_source="rss:finance.yahoo.com",
                published_at="2026-08-01T00:00:00+00:00",
                relevance_distance=0.25,
            ),
        ],
        model_used="gemini-flash-latest",
    )
    payload = json.loads(report.to_redis_payload())
    assert payload["ticker"] == "NVDA"
    assert payload["verdict"] == "bullish"
    assert payload["triggering_signal"]["signal_type"] == "rsi_oversold_volume_surge"
    assert payload["citations"][0]["source_type"] == "filing"
    assert payload["citations"][0]["form_type"] == "10-Q"
    assert payload["citations"][1]["source_type"] == "news"
    assert payload["citations"][1]["article_title"] == "NVIDIA announces record data center demand"
    assert 0.0 <= payload["confidence"] <= 1.0


def test_research_report_defaults_to_empty_lists_and_no_citations():
    report = ResearchReport(
        ticker="TSLA",
        triggering_signal=_sample_signal(),
        verdict=ResearchVerdict.INSUFFICIENT_CONTEXT,
        confidence=0.0,
        summary="No relevant filing context was retrieved for this ticker.",
        model_used="gemini-flash-latest",
    )
    assert report.key_findings == []
    assert report.risk_factors == []
    assert report.citations == []
