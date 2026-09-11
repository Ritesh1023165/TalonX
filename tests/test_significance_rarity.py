"""
tests/test_significance_rarity.py
--------------------------------
Task 96E -- metadata-only event rarity for a filer.
"""
from __future__ import annotations

from datetime import timedelta

from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.significance.rarity import event_rarity
from _significance_helpers import NOW, FakeEventStore, mk_event


def _ev(days_ago, et=EventType.RESTRUCTURING, acc=None):
    return mk_event(
        event_type=et,
        accession=acc or f"0000320193-26-{days_ago:06d}",
        accepted_at=NOW - timedelta(days=days_ago),
    )


def test_rare_when_type_absent_24_months():
    store = FakeEventStore([_ev(900, EventType.EARNINGS_RESULTS, "0000320193-24-000001")])
    r = event_rarity(store, symbol="AAPL", event_type=EventType.RESTRUCTURING, as_of=NOW)
    assert r.code == "RARE" and r.points == 2


def test_uncommon_when_in_24_but_not_12_months():
    store = FakeEventStore(
        [
            _ev(900, EventType.EARNINGS_RESULTS, "0000320193-24-000001"),
            _ev(500, EventType.RESTRUCTURING, "0000320193-25-000001"),
        ]
    )
    r = event_rarity(store, symbol="AAPL", event_type=EventType.RESTRUCTURING, as_of=NOW)
    assert r.code == "UNCOMMON" and r.points == 1


def test_common_when_in_12_months():
    store = FakeEventStore(
        [
            _ev(900, EventType.EARNINGS_RESULTS, "0000320193-24-000001"),
            _ev(100, EventType.RESTRUCTURING, "0000320193-26-000001"),
        ]
    )
    r = event_rarity(store, symbol="AAPL", event_type=EventType.RESTRUCTURING, as_of=NOW)
    assert r.code == "COMMON" and r.points == 0


def test_insufficient_history_guard():
    # only 2 months of tracked history -> not "rare", just unobserved
    store = FakeEventStore([_ev(60, EventType.EARNINGS_RESULTS, "0000320193-26-000009")])
    r = event_rarity(store, symbol="AAPL", event_type=EventType.RESTRUCTURING, as_of=NOW)
    assert r.code == "INSUFFICIENT_HISTORY" and r.points == 0


def test_excludes_the_event_being_scored():
    self_ev = _ev(0, EventType.RESTRUCTURING, "0000320193-26-000500")
    store = FakeEventStore([_ev(900, EventType.EARNINGS_RESULTS, "0000320193-24-000001"), self_ev])
    r = event_rarity(
        store,
        symbol="AAPL",
        event_type=EventType.RESTRUCTURING,
        as_of=NOW,
        exclude_event_id=self_ev.event_id,
    )
    assert r.code == "RARE"


def test_only_counts_events_accepted_by_as_of():
    future = _ev(-10, EventType.RESTRUCTURING, "0000320193-26-000600")  # 10 days after as_of
    store = FakeEventStore([_ev(900, EventType.EARNINGS_RESULTS, "0000320193-24-000001"), future])
    r = event_rarity(store, symbol="AAPL", event_type=EventType.RESTRUCTURING, as_of=NOW)
    assert r.code == "RARE"  # the future event is not visible yet
