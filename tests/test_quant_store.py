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


# ==========================================================================
# Buffer persistence -- bar_buffer (survive a restart without a re-warm-up)
# ==========================================================================

def _bars(n: int, start: datetime = NOW, step_seconds: int = 60) -> list[dict]:
    return [
        {
            "timestamp": start + timedelta(seconds=step_seconds * i),
            "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i,
            "close": 100.5 + i, "volume": 1000.0 + i,
        }
        for i in range(n)
    ]


def test_load_buffer_returns_empty_list_when_never_checkpointed(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        assert store.load_buffer("AAPL", "1m") == []


def test_checkpoint_and_load_buffer_round_trips_in_chronological_order(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        bars = _bars(3)
        store.checkpoint_buffer("aapl", "1m", bars)

        loaded = store.load_buffer("AAPL", "1m")
        assert len(loaded) == 3
        assert loaded[0]["close"] == 100.5
        assert loaded[-1]["close"] == 102.5
        assert loaded[0]["timestamp"] == bars[0]["timestamp"].isoformat()


def test_checkpoint_buffer_replaces_not_appends(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.checkpoint_buffer("AAPL", "1m", _bars(3))
        store.checkpoint_buffer("AAPL", "1m", _bars(2, start=NOW + timedelta(hours=1)))

        loaded = store.load_buffer("AAPL", "1m")
        assert len(loaded) == 2  # old snapshot fully replaced, not merged


def test_checkpoint_buffer_keeps_1m_and_15m_independent(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.checkpoint_buffer("AAPL", "1m", _bars(3))
        store.checkpoint_buffer("AAPL", "15m", _bars(2, step_seconds=900))

        assert len(store.load_buffer("AAPL", "1m")) == 3
        assert len(store.load_buffer("AAPL", "15m")) == 2


def test_checkpoint_buffer_keeps_symbols_independent(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.checkpoint_buffer("AAPL", "1m", _bars(3))
        store.checkpoint_buffer("MSFT", "1m", _bars(1))

        assert len(store.load_buffer("AAPL", "1m")) == 3
        assert len(store.load_buffer("MSFT", "1m")) == 1


def test_buffered_symbols_lists_only_symbols_with_that_buffer_type(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.checkpoint_buffer("AAPL", "1m", _bars(1))
        store.checkpoint_buffer("MSFT", "15m", _bars(1))

        assert store.buffered_symbols("1m") == ["AAPL"]
        assert store.buffered_symbols("15m") == ["MSFT"]


def test_checkpoint_buffer_with_empty_list_clears_the_symbol(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.checkpoint_buffer("AAPL", "1m", _bars(3))
        store.checkpoint_buffer("AAPL", "1m", [])

        assert store.load_buffer("AAPL", "1m") == []


def test_buffer_persists_across_reopen(tmp_path):
    path = tmp_path / "quant.db"
    with QuantStateStore(path) as store:
        store.checkpoint_buffer("AAPL", "1m", _bars(3))

    with QuantStateStore(path) as store2:
        assert len(store2.load_buffer("AAPL", "1m")) == 3
