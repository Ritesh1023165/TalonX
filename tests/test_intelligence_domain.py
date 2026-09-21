"""
tests/test_intelligence_domain.py
---------------------------------
Task 96A -- canonical domain value objects: enums, TextEvent / AlertCard
schema, immutability, and the no-predictive-claim guard on AlertCard.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from talonx_ingest.intelligence.config import (
    ALERT_CARD_SCHEMA_VERSION,
    EVENT_SCHEMA_VERSION,
)
from talonx_ingest.intelligence.domain import (
    AlertCard,
    EventType,
    EvidenceRecord,
    FreshnessStatus,
    SessionBucket,
    SignificanceBand,
    SourceType,
    TextEvent,
    utc_now,
)

_NOW = datetime(2026, 7, 31, 20, 5, 12, tzinfo=timezone.utc)


def _text_event(**overrides) -> TextEvent:
    base = dict(
        event_id="SEC:0000320193-26-000070:EARNINGS_RESULTS",
        symbol="aapl",
        company_name="Apple Inc.",
        source_type=SourceType.SEC_EDGAR_SUBMISSIONS,
        source_record_id="0000320193-26-000070",
        event_type=EventType.EARNINGS_RESULTS,
        form_type="8-K",
        filing_items=("2.02", "9.01"),
        accession="0000320193-26-000070",
        accepted_at_utc=_NOW,
        ingested_at_utc=_NOW,
    )
    base.update(overrides)
    return TextEvent(**base)


def test_text_event_defaults_and_schema_version():
    ev = _text_event()
    assert ev.schema_version == EVENT_SCHEMA_VERSION
    assert ev.symbol == "AAPL"  # upper-cased by validator
    assert ev.session_bucket is SessionBucket.UNKNOWN
    assert ev.freshness is FreshnessStatus.UNKNOWN
    assert ev.is_amendment is False
    assert ev.data_quality_flags == ()


def test_text_event_is_frozen():
    ev = _text_event()
    with pytest.raises(ValidationError):
        ev.symbol = "MSFT"


def test_text_event_rejects_unknown_field():
    with pytest.raises(ValidationError):
        _text_event(expected_return=0.05)


def test_text_event_roundtrips_json():
    ev = _text_event(
        evidence=(
            EvidenceRecord(
                source_provider=SourceType.SEC_EDGAR_SUBMISSIONS,
                source_record_id="0000320193-26-000070",
                retrieved_at=_NOW,
                transform="edgar_taxonomy@v1",
            ),
        )
    )
    restored = TextEvent.model_validate_json(ev.model_dump_json())
    assert restored == ev


def test_alert_card_schema_only_no_significance():
    card = AlertCard(
        alert_id="card:SEC:0000320193-26-000070:EARNINGS_RESULTS",
        event_id="SEC:0000320193-26-000070:EARNINGS_RESULTS",
        symbol="AAPL",
        company_name="Apple Inc.",
        title="AAPL filed an 8-K with results of operations (Item 2.02)",
        event_type=EventType.EARNINGS_RESULTS,
    )
    assert card.schema_version == ALERT_CARD_SCHEMA_VERSION
    assert card.significance is None
    assert card.significance_reasons == ()
    assert card.status == "EMITTED"
    assert "no prediction" in card.disclaimer.lower()


@pytest.mark.parametrize(
    "bad_key",
    ["recommendation", "action", "outlook", "target_price", "direction",
     "probability", "expected_return", "bullish", "bearish", "buy", "sell",
     "alpha", "opportunity_score", "edge", "price_target", "rating"],
)
def test_alert_card_rejects_predictive_summary_keys(bad_key):
    with pytest.raises(ValidationError):
        AlertCard(
            alert_id="card:x",
            event_id="x",
            symbol="AAPL",
            company_name="Apple Inc.",
            title="t",
            event_type=EventType.EARNINGS_RESULTS,
            summary_fields={bad_key: "whatever"},
        )


def test_alert_card_allows_factual_summary_keys():
    card = AlertCard(
        alert_id="card:x",
        event_id="x",
        symbol="AAPL",
        company_name="Apple Inc.",
        title="t",
        event_type=EventType.EARNINGS_RESULTS,
        summary_fields={"form": "8-K", "items": "2.02,9.01", "session": "AMC"},
    )
    assert card.summary_fields["form"] == "8-K"


def test_significance_band_enum_values():
    assert [b.value for b in SignificanceBand] == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def test_utc_now_is_tz_aware_utc():
    now = utc_now()
    assert now.tzinfo is timezone.utc
