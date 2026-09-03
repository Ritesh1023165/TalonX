"""
tests/test_service_ingest_helpers.py
------------------------------------
Task 96B — the shared low-level ingest helper: form filter, date-window
bound, new-vs-existing accounting, shard merge / overlap.
"""
from __future__ import annotations

from datetime import date

from talonx_ingest.intelligence.service._ingest import (
    _merge_recent,
    _shard_overlaps,
    ingest_symbol_filings,
)
from talonx_ingest.intelligence.store import EventStore

from tests._service_helpers import make_submissions


def test_window_and_forms_filter(tmp_path):
    store = EventStore(tmp_path / "l.db")
    subs = make_submissions()
    # only 8-K + 10-Q, only filings on/after 2026-06-01
    res = ingest_symbol_filings(
        store, subs, symbol="FAKE", forms=("8-K", "10-Q"), since_date=date(2026, 6, 1)
    )
    assert res.filings_seen == 2                       # the 8-K + the recent 10-Q (old 10-Q excluded)
    assert res.events_new >= 2
    assert res.earliest_filing_date == date(2026, 6, 11)
    # second run -> everything already stored
    res2 = ingest_symbol_filings(
        store, subs, symbol="FAKE", forms=("8-K", "10-Q"), since_date=date(2026, 6, 1)
    )
    assert res2.events_new == 0
    assert res2.events_existing == res.events_built
    store.close()


def test_shard_overlap_logic():
    assert _shard_overlaps({"filingTo": "2020-01-01"}, date(2024, 1, 1)) is False
    assert _shard_overlaps({"filingTo": "2025-06-01"}, date(2024, 1, 1)) is True
    assert _shard_overlaps({}, date(2024, 1, 1)) is True          # unknown range -> fetch
    assert _shard_overlaps({"filingTo": "2020-01-01"}, None) is True


def test_merge_recent_concatenates_arrays():
    base = {"filings": {"recent": {"form": ["8-K"], "accessionNumber": ["a-1"]}}}
    _merge_recent(base, {"form": ["10-K"], "accessionNumber": ["a-2"]})
    assert base["filings"]["recent"]["form"] == ["8-K", "10-K"]
    assert base["filings"]["recent"]["accessionNumber"] == ["a-1", "a-2"]
