"""
tests/test_intelligence_store.py
--------------------------------
Task 96A -- EventStore persistence, query, restart survival, idempotency.
Uses real sqlite3 (stdlib), a tmp_path DB file.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from talonx_ingest.intelligence.domain import (
    EventType,
    EvidenceRecord,
    ExhibitRef,
    FreshnessStatus,
    SessionBucket,
    SourceType,
    TextEvent,
)
from talonx_ingest.intelligence.store import EventStore

_NOW = datetime(2026, 7, 31, 20, 5, 12, tzinfo=timezone.utc)


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "event_store.db"


def _event(event_type=EventType.EARNINGS_RESULTS, accession="0000320193-26-000070", **kw) -> TextEvent:
    base = dict(
        event_id=f"SEC:{accession}:{event_type.value}",
        symbol="AAPL",
        company_name="Apple Inc.",
        source_type=SourceType.SEC_EDGAR_SUBMISSIONS,
        source_record_id=accession,
        event_type=event_type,
        form_type="8-K",
        filing_items=("2.02", "9.01"),
        accession=accession,
        accepted_at_utc=_NOW,
        filing_date=date(2026, 7, 31),
        report_period_end=None,
        session_bucket=SessionBucket.AMC,
        session_reason=None,
        primary_document="a.htm",
        primary_document_url="https://www.sec.gov/Archives/edgar/data/320193/000.../a.htm",
        filing_index_url="https://www.sec.gov/Archives/edgar/data/320193/000.../index.htm",
        exhibits=(
            ExhibitRef(filename="ex99-1.htm", source_url="https://x/ex99-1.htm",
                       sequence=2, document_type="EX-99.1", description="Press release"),
        ),
        source_hash="deadbeef",
        ingested_at_utc=_NOW,
        freshness=FreshnessStatus.FRESH,
        data_quality_flags=("multi_item_filing",),
        evidence=(
            EvidenceRecord(
                source_provider=SourceType.SEC_EDGAR_SUBMISSIONS,
                source_record_id=accession,
                source_url="https://x/index.htm",
                exact_timestamp=_NOW,
                retrieved_at=_NOW,
                transform="edgar_taxonomy@v1",
                input_hash="abc",
            ),
        ),
    )
    base.update(kw)
    return TextEvent(**base)


def test_schema_version_and_new_tables(store_path):
    with EventStore(store_path) as store:
        assert store.schema_version() == 1
        names = {
            r[0]
            for r in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {
        "schema_meta", "text_events", "text_event_items",
        "text_event_exhibits", "event_evidence", "source_freshness",
    } <= names


def test_insert_get_roundtrip(store_path):
    ev = _event()
    with EventStore(store_path) as store:
        assert store.upsert_event(ev) is True
        got = store.get_event(ev.event_id)
    assert got.event_id == ev.event_id
    assert got.event_type is EventType.EARNINGS_RESULTS
    assert got.filing_items == ("2.02", "9.01")
    assert got.session_bucket is SessionBucket.AMC
    assert got.data_quality_flags == ("multi_item_filing",)
    assert got.exhibits[0].filename == "ex99-1.htm"
    assert got.evidence[0].transform == "edgar_taxonomy@v1"
    assert got.accepted_at_utc == _NOW


def test_upsert_is_idempotent(store_path):
    ev = _event()
    with EventStore(store_path) as store:
        assert store.upsert_event(ev) is True
        assert store.upsert_event(ev) is False
        assert store.upsert_event(ev) is False
        assert store.count_events() == 1
        assert store.get_items(ev.accession) == ["2.02", "9.01"]
        assert len(store.get_exhibits(ev.accession)) == 1
        assert len(store.get_evidence(ev.event_id)) == 1


def test_evidence_is_replaced_not_duplicated(store_path):
    ev = _event()
    with EventStore(store_path) as store:
        store.upsert_event(ev)
        improved = ev.model_copy(
            update={
                "evidence": (
                    EvidenceRecord(
                        source_provider=SourceType.SEC_EDGAR_SUBMISSIONS,
                        source_record_id=ev.accession,
                        retrieved_at=_NOW,
                        transform="edgar_taxonomy@v1",
                        input_hash="REFINED",
                        notes="metadata improved",
                    ),
                )
            }
        )
        store.upsert_event(improved)
        ev_rows = store.get_evidence(ev.event_id)
    assert len(ev_rows) == 1
    assert ev_rows[0].input_hash == "REFINED"


def test_multi_item_filing_two_events_one_accession(store_path):
    acc = "0000320193-26-000050"
    e1 = _event(EventType.EXECUTIVE_CHANGE, accession=acc, filing_items=("5.02", "1.01"))
    e2 = _event(EventType.MATERIAL_AGREEMENT, accession=acc, filing_items=("5.02", "1.01"))
    with EventStore(store_path) as store:
        assert store.upsert_event(e1) is True
        assert store.upsert_event(e2) is True
        assert store.count_events() == 2
        assert store.get_items(acc) == ["1.01", "5.02"]


def test_state_persists_across_reopen(store_path):
    ev = _event()
    with EventStore(store_path) as store:
        store.upsert_event(ev)
    with EventStore(store_path) as store2:
        assert store2.has_event(ev.event_id) is True
        assert store2.get_event(ev.event_id).symbol == "AAPL"


def test_query_by_symbol_type_time(store_path):
    with EventStore(store_path) as store:
        store.upsert_event(_event(EventType.EARNINGS_RESULTS, accession="0000320193-26-000070",
                                  accepted_at_utc=_NOW))
        store.upsert_event(_event(EventType.QUARTERLY_FILING, accession="0000320193-26-000065",
                                  form_type="10-Q", accepted_at_utc=_NOW - timedelta(days=30)))
        store.upsert_event(_event(EventType.EARNINGS_RESULTS, accession="0000789019-26-000047",
                                  symbol="MSFT", accepted_at_utc=_NOW - timedelta(days=1)))

        assert len(store.query_events(symbol="AAPL")) == 2
        assert len(store.query_events(symbol="MSFT")) == 1
        assert len(store.query_events(event_type=EventType.EARNINGS_RESULTS)) == 2
        assert len(store.query_events(form_type="10-Q")) == 1
        recent = store.query_events(since=_NOW - timedelta(days=2))
        assert {e.symbol for e in recent} == {"AAPL", "MSFT"}
        newest = store.query_events(limit=1)[0]
        assert newest.accession == "0000320193-26-000070"
        oldest = store.query_events(limit=1, newest_first=False)[0]
        assert oldest.accession == "0000320193-26-000065"


def test_get_event_missing_returns_none(store_path):
    with EventStore(store_path) as store:
        assert store.get_event("nope") is None
