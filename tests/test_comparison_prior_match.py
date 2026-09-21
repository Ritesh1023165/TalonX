"""
tests/test_comparison_prior_match.py
------------------------------------
Task 96C -- deterministic prior-comparable-filing resolution from the
Task 96A text_events store.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from talonx_ingest.intelligence.comparison.domain import ComparisonQualityFlag
from talonx_ingest.intelligence.comparison.prior_match import resolve_prior_comparable
from talonx_ingest.intelligence.domain import (
    EventType,
    FreshnessStatus,
    SessionBucket,
    SourceType,
    TextEvent,
)
from talonx_ingest.intelligence.store import EventStore


def _ev(accession, form_type, accepted, event_type, *, period_end=None, symbol="AAPL"):
    return TextEvent(
        event_id=f"SEC:{accession}:{event_type.value}",
        symbol=symbol,
        company_name="Apple Inc.",
        source_type=SourceType.SEC_EDGAR_SUBMISSIONS,
        source_record_id=accession,
        event_type=event_type,
        form_type=form_type,
        accession=accession,
        accepted_at_utc=accepted,
        report_period_end=period_end,
        session_bucket=SessionBucket.AMC,
        ingested_at_utc=accepted,
        freshness=FreshnessStatus.FRESH,
    )


@pytest.fixture
def store(tmp_path):
    s = EventStore(tmp_path / "e.db")
    # a normal 10-Q chain + a 10-K + an amendment
    s.upsert_event(_ev("0000320193-25-000010", "10-Q", datetime(2025, 2, 1, tzinfo=timezone.utc),
                       EventType.QUARTERLY_FILING, period_end=date(2024, 12, 31)))
    s.upsert_event(_ev("0000320193-25-000040", "10-Q", datetime(2025, 5, 1, tzinfo=timezone.utc),
                       EventType.QUARTERLY_FILING, period_end=date(2025, 3, 31)))
    s.upsert_event(_ev("0000320193-25-000070", "10-Q", datetime(2025, 8, 1, tzinfo=timezone.utc),
                       EventType.QUARTERLY_FILING, period_end=date(2025, 6, 30)))
    s.upsert_event(_ev("0000320193-24-000100", "10-K", datetime(2024, 11, 1, tzinfo=timezone.utc),
                       EventType.ANNUAL_FILING, period_end=date(2024, 9, 30)))
    s.upsert_event(_ev("0000320193-25-000110", "10-K", datetime(2025, 11, 1, tzinfo=timezone.utc),
                       EventType.ANNUAL_FILING, period_end=date(2025, 9, 30)))
    s.upsert_event(_ev("0000320193-25-000045", "10-Q/A", datetime(2025, 6, 1, tzinfo=timezone.utc),
                       EventType.QUARTERLY_FILING))
    yield s
    s.close()


def test_normal_10q_chain(store):
    cur = store.get_event("SEC:0000320193-25-000070:QUARTERLY_FILING")
    res = resolve_prior_comparable(store, cur)
    assert res.has_prior
    assert res.prior_event.accession == "0000320193-25-000040"
    assert res.base_form == "10-Q"
    assert res.flags == ()


def test_first_in_chain_has_no_prior(store):
    cur = store.get_event("SEC:0000320193-25-000010:QUARTERLY_FILING")
    res = resolve_prior_comparable(store, cur)
    assert not res.has_prior
    assert ComparisonQualityFlag.MISSING_PRIOR_FILING.value in res.flags
    assert ComparisonQualityFlag.PRIOR_IS_FIRST_FILING.value in res.flags


def test_10k_chain_does_not_match_a_10q(store):
    cur = store.get_event("SEC:0000320193-25-000110:ANNUAL_FILING")
    res = resolve_prior_comparable(store, cur)
    assert res.has_prior
    assert res.prior_event.accession == "0000320193-24-000100"
    assert res.prior_event.form_type == "10-K"


def test_amendment_current_excludes_other_amendments_and_picks_last_original(store):
    cur = store.get_event("SEC:0000320193-25-000045:QUARTERLY_FILING")
    res = resolve_prior_comparable(store, cur)
    assert res.has_prior
    # prior is the last ORIGINAL 10-Q before the /A's acceptance (2025-06-01)
    assert res.prior_event.accession == "0000320193-25-000040"
    assert res.prior_event.form_type == "10-Q"
    assert ComparisonQualityFlag.AMENDMENT_INVOLVED.value in res.flags


def test_prior_query_never_returns_an_amendment_as_base(store):
    # add a later /A that could otherwise be "most recent before" a newer 10-Q
    cur = store.get_event("SEC:0000320193-25-000070:QUARTERLY_FILING")
    res = resolve_prior_comparable(store, cur)
    assert res.prior_event.form_type == "10-Q"  # not "10-Q/A"


def test_non_periodic_current_is_form_mismatch(store):
    ev = _ev("0000320193-25-000200", "8-K", datetime(2025, 7, 1, tzinfo=timezone.utc),
             EventType.EARNINGS_RESULTS)
    store.upsert_event(ev)
    res = resolve_prior_comparable(store, store.get_event(ev.event_id))
    assert not res.has_prior
    assert ComparisonQualityFlag.PRIOR_FORM_MISMATCH.value in res.flags
