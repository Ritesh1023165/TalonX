"""
tests/test_intelligence_freshness.py
------------------------------------
Task 96A -- per-source freshness. FRESH/STALE from poll-success recency,
DOWN from consecutive failures, and a healthy source with NO new events is
never marked DOWN/DISCONNECTED.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_ingest.intelligence.config import FRESHNESS_THRESHOLDS
from talonx_ingest.intelligence.domain import FreshnessStatus, SourceType
from talonx_ingest.intelligence.freshness import (
    SourceFreshnessTracker,
    compute_status,
)
from talonx_ingest.intelligence.store import EventStore

_EDGAR = FRESHNESS_THRESHOLDS["SEC_EDGAR_SUBMISSIONS"]
_NOW = datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)


def test_never_polled_is_unknown():
    st, reason, age = compute_status(
        last_poll_success_utc=None, consecutive_failures=0, now=_NOW,
        thresholds=_EDGAR, day_hours=True,
    )
    assert st is FreshnessStatus.UNKNOWN and reason == "never_polled" and age is None


def test_recent_success_is_fresh():
    st, _, age = compute_status(
        last_poll_success_utc=_NOW - timedelta(minutes=5),
        consecutive_failures=0, now=_NOW, thresholds=_EDGAR, day_hours=True,
    )
    assert st is FreshnessStatus.FRESH and age == pytest.approx(300, abs=1)


def test_old_success_is_stale_by_day_threshold():
    st, _, _ = compute_status(
        last_poll_success_utc=_NOW - timedelta(minutes=45),  # > 30 min day limit
        consecutive_failures=0, now=_NOW, thresholds=_EDGAR, day_hours=True,
    )
    assert st is FreshnessStatus.STALE


def test_same_age_is_fresh_under_night_threshold():
    st, _, _ = compute_status(
        last_poll_success_utc=_NOW - timedelta(minutes=45),
        consecutive_failures=0, now=_NOW, thresholds=_EDGAR, day_hours=False,
    )
    assert st is FreshnessStatus.FRESH  # night limit is 3h


def test_consecutive_failures_force_down_even_if_recent_success():
    st, reason, _ = compute_status(
        last_poll_success_utc=_NOW - timedelta(seconds=10),
        consecutive_failures=3, now=_NOW, thresholds=_EDGAR, day_hours=True,
    )
    assert st is FreshnessStatus.DOWN and "consecutive" in reason


def test_failures_below_threshold_with_prior_success_still_fresh():
    st, _, _ = compute_status(
        last_poll_success_utc=_NOW - timedelta(seconds=30),
        consecutive_failures=2, now=_NOW, thresholds=_EDGAR, day_hours=True,
    )
    assert st is FreshnessStatus.FRESH


# --- tracker (persistent) ------------------------------------------

@pytest.fixture
def tracker(tmp_path):
    store = EventStore(tmp_path / "f.db")
    clock = {"t": _NOW}
    tr = SourceFreshnessTracker(store, clock=lambda: clock["t"])
    tr._clock_box = clock  # test handle
    yield tr
    store.close()


def test_tracker_success_then_quiet_stays_fresh_not_down(tracker):
    # a successful poll that found NO new events
    snap = tracker.record_attempt(
        SourceType.SEC_EDGAR_SUBMISSIONS, success=True, latest_source_event_utc=None
    )
    assert snap.status is FreshnessStatus.FRESH
    # 10 minutes later, still within the day FRESH window, no events arrived
    tracker._clock_box["t"] = _NOW + timedelta(minutes=10)
    assert tracker.snapshot(SourceType.SEC_EDGAR_SUBMISSIONS).status is FreshnessStatus.FRESH


def test_tracker_counts_consecutive_failures_to_down(tracker):
    tracker.record_attempt(SourceType.SEC_EDGAR_SUBMISSIONS, success=True)
    tracker.record_attempt(SourceType.SEC_EDGAR_SUBMISSIONS, success=False)
    tracker.record_attempt(SourceType.SEC_EDGAR_SUBMISSIONS, success=False)
    snap = tracker.record_attempt(SourceType.SEC_EDGAR_SUBMISSIONS, success=False)
    assert snap.status is FreshnessStatus.DOWN
    assert snap.consecutive_failures == 3


def test_tracker_recovers_on_next_success(tracker):
    for _ in range(4):
        tracker.record_attempt(SourceType.SEC_EDGAR_SUBMISSIONS, success=False)
    assert tracker.snapshot(SourceType.SEC_EDGAR_SUBMISSIONS).status is FreshnessStatus.DOWN
    snap = tracker.record_attempt(SourceType.SEC_EDGAR_SUBMISSIONS, success=True)
    assert snap.status is FreshnessStatus.FRESH
    assert snap.consecutive_failures == 0


def test_tracker_persists_across_reopen(tmp_path):
    path = tmp_path / "g.db"
    store = EventStore(path)
    tr = SourceFreshnessTracker(store, clock=lambda: _NOW)
    tr.record_attempt(SourceType.SEC_EDGAR_SUBMISSIONS, success=True)
    store.close()

    store2 = EventStore(path)
    tr2 = SourceFreshnessTracker(store2, clock=lambda: _NOW + timedelta(minutes=1))
    assert tr2.snapshot(SourceType.SEC_EDGAR_SUBMISSIONS).status is FreshnessStatus.FRESH
    store2.close()


def test_unpolled_source_snapshot_is_unknown(tracker):
    assert tracker.snapshot(SourceType.SEC_XBRL).status is FreshnessStatus.UNKNOWN
