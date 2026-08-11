"""
tests/test_brain_store.py
--------------------------------
Tests talonx_brain.store.BrainStatsStore -- the SQLite-backed research-
report category-count persistence (cache_hit/stale_fallback/degraded/
cold_start/llm_call), same daily-upserted-counter shape as
talonx_core/talonx_quant's suppression_counts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from talonx_brain.store import BrainStatsStore

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


def test_record_report_creates_a_counter_row(tmp_path):
    with BrainStatsStore(tmp_path / "brain.db") as store:
        store.record_report("NVDA", "llm_call", NOW)
        rows = store.report_counts_for_date("2026-08-07")
        assert len(rows) == 1
        assert rows[0]["ticker"] == "NVDA"
        assert rows[0]["category"] == "llm_call"
        assert rows[0]["count"] == 1


def test_record_report_increments_the_same_day_ticker_category_bucket(tmp_path):
    with BrainStatsStore(tmp_path / "brain.db") as store:
        store.record_report("NVDA", "cache_hit", NOW)
        store.record_report("NVDA", "cache_hit", NOW + timedelta(minutes=5))
        rows = store.report_counts_for_date("2026-08-07")
        assert rows[0]["count"] == 2


def test_record_report_keeps_categories_separate(tmp_path):
    with BrainStatsStore(tmp_path / "brain.db") as store:
        store.record_report("NVDA", "cache_hit", NOW)
        store.record_report("NVDA", "llm_call", NOW)
        rows = {r["category"]: r["count"] for r in store.report_counts_for_date("2026-08-07")}
        assert rows == {"cache_hit": 1, "llm_call": 1}


def test_report_counts_for_date_excludes_other_days(tmp_path):
    with BrainStatsStore(tmp_path / "brain.db") as store:
        store.record_report("NVDA", "llm_call", NOW)
        store.record_report("NVDA", "llm_call", NOW + timedelta(days=1))
        assert len(store.report_counts_for_date("2026-08-07")) == 1
        assert len(store.report_counts_for_date("2026-08-08")) == 1


def test_state_persists_across_reopen(tmp_path):
    path = tmp_path / "brain.db"
    with BrainStatsStore(path) as store:
        store.record_report("NVDA", "llm_call", NOW)

    with BrainStatsStore(path) as store2:
        assert store2.report_counts_for_date("2026-08-07")[0]["count"] == 1
