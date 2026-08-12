"""
tests/test_quant_store.py
--------------------------------
Tests talonx_quant.store.QuantStateStore -- the SQLite-backed
cooldown/throttle suppression-count persistence, same daily-upserted-
counter shape as talonx_core.store's suppression_counts (see
test_core_store.py's equivalent tests).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from talonx_quant.store import QuantStateStore

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


def test_record_suppressed_creates_a_counter_row(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.record_suppressed("AAPL", "COOLDOWN", 1, NOW)
        rows = store.suppression_counts_for_date("2026-08-07")
        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAPL"
        assert rows[0]["reason"] == "COOLDOWN"
        assert rows[0]["count"] == 1


def test_record_suppressed_increments_by_the_given_count(tmp_path):
    """A single cooldown check or throttle flush can suppress several
    signals at once -- count is additive, not always +1."""
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.record_suppressed("AAPL", "COOLDOWN", 3, NOW)
        store.record_suppressed("AAPL", "COOLDOWN", 2, NOW + timedelta(minutes=5))
        rows = store.suppression_counts_for_date("2026-08-07")
        assert rows[0]["count"] == 5


def test_record_suppressed_keeps_reasons_separate(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.record_suppressed("AAPL", "COOLDOWN", 1, NOW)
        store.record_suppressed("AAPL", "THROTTLE", 2, NOW)
        rows = {r["reason"]: r["count"] for r in store.suppression_counts_for_date("2026-08-07")}
        assert rows == {"COOLDOWN": 1, "THROTTLE": 2}


def test_suppression_counts_for_date_excludes_other_days(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.record_suppressed("AAPL", "COOLDOWN", 1, NOW)
        store.record_suppressed("AAPL", "COOLDOWN", 1, NOW + timedelta(days=1))
        assert len(store.suppression_counts_for_date("2026-08-07")) == 1
        assert len(store.suppression_counts_for_date("2026-08-08")) == 1


def test_state_persists_across_reopen(tmp_path):
    path = tmp_path / "quant.db"
    with QuantStateStore(path) as store:
        store.record_suppressed("AAPL", "COOLDOWN", 1, NOW)

    with QuantStateStore(path) as store2:
        assert store2.suppression_counts_for_date("2026-08-07")[0]["count"] == 1


# ==========================================================================
# Event-Driven Earnings Radar -- latest_fundamental_factors
# ==========================================================================

def test_get_latest_factors_returns_none_when_unknown(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        assert store.get_latest_factors("AAPL") is None


def test_save_and_get_latest_factors_round_trips(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.save_latest_factors("aapl", 2025, 0.21, 8, 0.05, 5.5, 1.2, NOW)

        row = store.get_latest_factors("AAPL")
        assert row["ticker"] == "AAPL"  # normalized
        assert row["fiscal_year"] == 2025
        assert row["roic"] == 0.21
        assert row["piotroski_f_score"] == 8
        assert row["fcf_yield"] == 0.05
        assert row["altman_z_score"] == 5.5
        assert row["debt_to_ebitda_proxy"] == 1.2


def test_save_latest_factors_overwrites_not_appends(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.save_latest_factors("AAPL", 2024, 0.15, 7, 0.03, 4.0, 1.5, NOW)
        store.save_latest_factors("AAPL", 2025, 0.21, 8, 0.05, 5.5, 1.2, NOW + timedelta(days=90))

        row = store.get_latest_factors("AAPL")
        assert row["fiscal_year"] == 2025
        assert row["roic"] == 0.21


def test_save_latest_factors_allows_none_values(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.save_latest_factors("AAPL", 2025, None, None, None, None, None, NOW)

        row = store.get_latest_factors("AAPL")
        assert row["roic"] is None
        assert row["piotroski_f_score"] is None


def test_latest_factors_persist_across_reopen(tmp_path):
    path = tmp_path / "quant.db"
    with QuantStateStore(path) as store:
        store.save_latest_factors("AAPL", 2025, 0.21, 8, 0.05, 5.5, 1.2, NOW)

    with QuantStateStore(path) as store2:
        assert store2.get_latest_factors("AAPL")["fiscal_year"] == 2025
