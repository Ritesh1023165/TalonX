"""
tests/test_events_schemas.py
--------------------------------
Tests events.schemas -- the Pydantic contracts published to Redis.
Requires the real `pydantic` package (not stubbed) since validation
behavior itself is part of what's being tested.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from talonx_ingest.events.schemas import (
    MarketTickEvent,
    NewFilingIngestedEvent,
    TickEventType,
    TickSource,
)


def test_market_tick_event_serializes_to_valid_json():
    event = MarketTickEvent(
        event_type=TickEventType.TRADE,
        symbol="NVDA",
        source=TickSource.WEBSOCKET,
        timestamp=datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc),
        price=131.5,
        volume=50,
    )
    payload = json.loads(event.to_redis_payload())
    assert payload["symbol"] == "NVDA"
    assert payload["price"] == 131.5
    assert payload["event_type"] == "trade"
    assert payload["source"] == "websocket"


def test_market_tick_event_optional_fields_default_to_none():
    event = MarketTickEvent(
        event_type=TickEventType.QUOTE,
        symbol="AAPL",
        source=TickSource.POLLING,
        timestamp=datetime.now(timezone.utc),
    )
    assert event.price is None
    assert event.bid is None
    assert event.open is None


def test_market_tick_event_rejects_invalid_event_type():
    with pytest.raises(Exception):  # pydantic.ValidationError
        MarketTickEvent(
            event_type="not_a_real_type",
            symbol="AAPL",
            source=TickSource.POLLING,
            timestamp=datetime.now(timezone.utc),
        )


def test_market_tick_event_published_at_auto_populates():
    event = MarketTickEvent(
        event_type=TickEventType.BAR,
        symbol="MSFT",
        source=TickSource.POLLING,
        timestamp=datetime.now(timezone.utc),
    )
    assert event.published_at is not None


def test_new_filing_ingested_event_serializes_to_valid_json():
    event = NewFilingIngestedEvent(
        ticker="AAPL",
        cik="0000320193",
        company_name="Apple Inc.",
        form_type="10-K",
        accession_number="0000320193-24-000123",
        filing_date="2024-11-01",
        report_date="2024-09-28",
        source_document="aapl-20240928.htm",
        chunk_count=187,
        vector_collection="sec_filings",
    )
    payload = json.loads(event.to_redis_payload())
    assert payload["ticker"] == "AAPL"
    assert payload["accession_number"] == "0000320193-24-000123"
    assert payload["chunk_count"] == 187


def test_new_filing_ingested_event_report_date_is_optional():
    event = NewFilingIngestedEvent(
        ticker="AAPL",
        cik="0000320193",
        company_name="Apple Inc.",
        form_type="10-K",
        accession_number="0000320193-24-000123",
        filing_date="2024-11-01",
        report_date=None,
        source_document="aapl-20240928.htm",
        chunk_count=187,
        vector_collection="sec_filings",
    )
    assert event.report_date is None
