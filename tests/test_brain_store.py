"""
tests/test_brain_store.py
--------------------------------
Tests talonx_brain.store.BrainStatsStore -- the SQLite-backed research-
report category-count persistence (cache_hit/stale_fallback/degraded/
cold_start/llm_call), same daily-upserted-counter shape as
talonx_core/talonx_quant's suppression_counts.
"""
from __future__ import annotations

import sqlite3
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


# --- Phase 2: horizon dimension ---------------------------------------------

def test_record_report_defaults_to_intraday_horizon(tmp_path):
    with BrainStatsStore(tmp_path / "brain.db") as store:
        store.record_report("NVDA", "llm_call", NOW)
        assert store.report_counts_for_date("2026-08-07")[0]["horizon"] == "intraday"


def test_intraday_and_long_term_reports_for_the_same_ticker_stay_separate(tmp_path):
    with BrainStatsStore(tmp_path / "brain.db") as store:
        store.record_report("AAPL", "llm_call", NOW, horizon="intraday")
        store.record_report("AAPL", "llm_call", NOW, horizon="long_term")

        rows = {r["horizon"]: r["count"] for r in store.report_counts_for_date("2026-08-07")}
        assert rows == {"intraday": 1, "long_term": 1}


def test_migrates_a_pre_existing_report_counts_table_without_horizon(tmp_path):
    """Regression coverage: a pre-Phase-2 report_counts table has a
    narrower 3-column PRIMARY KEY (date, ticker, category) -- a plain
    ALTER TABLE ADD COLUMN would leave that PK in place and silently
    break the very first DUAL_HORIZON ticker that records both an
    intraday and a long_term report for the same ticker on the same
    day. This must rebuild the table with the wider 4-column PK."""
    db_path = tmp_path / "legacy_brain.db"

    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute(
        "CREATE TABLE report_counts (date TEXT NOT NULL, ticker TEXT NOT NULL, "
        "category TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, last_seen_at TEXT NOT NULL, "
        "PRIMARY KEY (date, ticker, category))"
    )
    legacy_conn.execute(
        "INSERT INTO report_counts (date, ticker, category, count, last_seen_at) "
        "VALUES ('2026-08-07', 'AAPL', 'llm_call', 3, ?)",
        (NOW.isoformat(),),
    )
    legacy_conn.commit()
    legacy_conn.close()

    with BrainStatsStore(db_path) as store:
        rows = store.report_counts_for_date("2026-08-07")
        assert len(rows) == 1
        assert rows[0]["horizon"] == "intraday"
        assert rows[0]["count"] == 3

        # The migrated store must accept a DUAL_HORIZON ticker's second,
        # long_term row for the same date/ticker/category without an
        # IntegrityError -- the exact scenario a plain column-add breaks.
        store.record_report("AAPL", "llm_call", NOW, horizon="long_term")
        rows = {r["horizon"]: r["count"] for r in store.report_counts_for_date("2026-08-07")}
        assert rows == {"intraday": 3, "long_term": 1}
