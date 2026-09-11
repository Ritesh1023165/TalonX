"""
tests/test_intelligence_pipeline.py
-----------------------------------
Task 96A -- end-to-end (offline): submissions JSON -> classified,
session-bucketed TextEvents -> EventStore, idempotent, with an AlertCard
contract that carries no predictive claim.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from talonx_ingest.intelligence.domain import (
    EventType,
    FreshnessStatus,
    SessionBucket,
    SourceType,
)
from talonx_ingest.intelligence.freshness import SourceFreshnessTracker
from talonx_ingest.intelligence.pipeline import (
    build_alert_card,
    build_events_from_filing,
    ingest_submissions,
    make_card_id,
)
from talonx_ingest.intelligence.edgar_normalize import iter_normalized_filings
from talonx_ingest.intelligence.store import EventStore


def _submissions() -> dict:
    return {
        "cik": 320193,
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q", "8-K", "8-K/A"],
                "accessionNumber": [
                    "0000320193-26-000070",
                    "0000320193-26-000065",
                    "0000320193-26-000050",
                    "0000320193-26-000051",
                ],
                "acceptanceDateTime": [
                    "2026-07-31T20:05:12.000Z",  # 16:05 ET -> AMC
                    "2026-07-31T11:00:00.000Z",  # 07:00 ET -> BMO
                    "2026-06-15T17:45:00.000Z",  # 13:45 ET -> RTH
                    "2026-06-13T14:00:00.000Z",  # Saturday -> NON_TRADING_DAY
                ],
                "filingDate": ["2026-07-31", "2026-07-31", "2026-06-15", "2026-06-13"],
                "reportDate": ["", "2026-06-27", "", ""],
                "primaryDocument": ["a.htm", "b.htm", "c.htm", "d.htm"],
                "items": ["2.02,9.01", "", "5.02,1.01,9.01", "8.01"],
            }
        },
    }


@pytest.fixture
def store(tmp_path):
    s = EventStore(tmp_path / "pipe.db")
    yield s
    s.close()


def test_ingest_builds_expected_events(store):
    res = ingest_submissions(store, _submissions(), symbol="AAPL")
    # 8-K 2.02 -> 1, 10-Q -> 1, 8-K 5.02+1.01 -> 2, 8-K/A 8.01 -> 1  == 5
    assert res.filings_seen == 4
    assert res.events_built == 5
    assert res.events_new == 5
    types = {store.get_event(eid).event_type for eid in res.event_ids}
    assert EventType.EARNINGS_RESULTS in types
    assert EventType.QUARTERLY_FILING in types
    assert EventType.EXECUTIVE_CHANGE in types
    assert EventType.MATERIAL_AGREEMENT in types
    assert EventType.OTHER_MATERIAL_EVENT in types


def test_ingest_session_buckets(store):
    ingest_submissions(store, _submissions(), symbol="AAPL")
    by_type = {e.event_type: e for e in store.query_events()}
    assert by_type[EventType.EARNINGS_RESULTS].session_bucket is SessionBucket.AMC
    assert by_type[EventType.QUARTERLY_FILING].session_bucket is SessionBucket.BMO
    assert by_type[EventType.EXECUTIVE_CHANGE].session_bucket is SessionBucket.RTH
    assert by_type[EventType.OTHER_MATERIAL_EVENT].session_bucket is SessionBucket.NON_TRADING_DAY


def test_ingest_is_idempotent(store):
    ingest_submissions(store, _submissions(), symbol="AAPL")
    res2 = ingest_submissions(store, _submissions(), symbol="AAPL")
    assert res2.events_new == 0
    assert res2.events_existing == 5
    assert store.count_events() == 5


def test_events_have_full_evidence_trace(store):
    res = ingest_submissions(store, _submissions(), symbol="AAPL")
    ev = store.get_event(res.event_ids[0])
    transforms = {e.transform for e in ev.evidence}
    assert transforms == {
        "edgar_submission_normalize@v1",
        "edgar_taxonomy@v1",
        "session_bucket@v1",
    }
    for rec in ev.evidence:
        assert rec.source_provider is SourceType.SEC_EDGAR_SUBMISSIONS
        assert rec.source_record_id == ev.accession
        assert rec.retrieved_at is not None
    assert ev.source_hash and len(ev.source_hash) == 64


def test_multi_item_event_ids_share_accession(store):
    res = ingest_submissions(store, _submissions(), symbol="AAPL")
    acc = "0000320193-26-000050"
    sibling_ids = [i for i in res.event_ids if acc in i]
    assert len(sibling_ids) == 2
    assert {i.rsplit(":", 1)[0] for i in sibling_ids} == {f"SEC:{acc}"}
    assert store.get_items(acc) == ["1.01", "5.02", "9.01"]


def test_freshness_recorded_via_tracker(store):
    tracker = SourceFreshnessTracker(store)
    res = ingest_submissions(store, _submissions(), symbol="AAPL", tracker=tracker)
    snap = tracker.snapshot(SourceType.SEC_EDGAR_SUBMISSIONS)
    assert snap.status is FreshnessStatus.FRESH
    assert snap.latest_source_event_utc == datetime(2026, 7, 31, 20, 5, 12, tzinfo=timezone.utc)
    # events were stamped with the poll's freshness
    assert store.get_event(res.event_ids[0]).freshness is FreshnessStatus.FRESH


def test_build_alert_card_contract(store):
    res = ingest_submissions(store, _submissions(), symbol="AAPL")
    ev = next(
        store.get_event(i) for i in res.event_ids
        if store.get_event(i).event_type is EventType.EARNINGS_RESULTS
    )
    card = build_alert_card(ev)
    assert card.event_id == ev.event_id
    assert card.alert_id == f"card:{ev.event_id}"
    assert card.significance is None
    assert card.significance_reasons == ()
    assert card.symbol == "AAPL"
    assert "2.02" in card.title
    assert card.summary_fields["form"] == "8-K"
    assert card.summary_fields["session"] == "AMC"
    assert "no prediction" in card.disclaimer.lower()
    assert make_card_id(ev) == f"AAPL:{ev.accession}:EARNINGS_RESULTS"
    # no forbidden key slipped in
    assert not ({"direction", "target", "recommendation", "expected_return"}
                & set(card.summary_fields))


def test_build_events_from_filing_direct():
    nf = next(iter_normalized_filings(_submissions(), symbol="AAPL"))
    events = build_events_from_filing(nf, freshness=FreshnessStatus.FRESH)
    assert len(events) == 1
    assert events[0].event_type is EventType.EARNINGS_RESULTS
    assert events[0].freshness is FreshnessStatus.FRESH
