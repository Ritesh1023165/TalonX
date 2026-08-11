"""
tests/test_ticker_watchlist_store.py
-----------------------------------------
Tests talonx_watchlist.store.TickerWatchlistStore -- add/remove/list,
symbol normalization, pause/resume, and the fresh-install-only seeding
behavior. Also covers the ALTER-TABLE migration path from the original
3-column schema (symbol, name, added_at) to the current one (+ exchange,
+ status) -- this protects real, already-populated watchlist.db files
from before those columns existed.
"""
from __future__ import annotations

import sqlite3

import pytest

from talonx_watchlist.store import TickerWatchlistStore


@pytest.fixture
def store(tmp_path) -> TickerWatchlistStore:
    s = TickerWatchlistStore(tmp_path / "watchlist.db")
    yield s
    s.close()


def test_list_tickers_empty_by_default(store):
    assert store.list_tickers() == []
    assert store.list_symbols() == []


def test_add_ticker_normalizes_symbol(store):
    store.add_ticker("  nvda ", "NVIDIA Corporation", " NASDAQ ")

    tickers = store.list_tickers()
    assert len(tickers) == 1
    assert tickers[0]["symbol"] == "NVDA"
    assert tickers[0]["name"] == "NVIDIA Corporation"
    assert tickers[0]["exchange"] == "NASDAQ"
    assert tickers[0]["status"] == "active"
    assert tickers[0]["added_at"]


def test_add_ticker_accepts_an_initial_status(store):
    store.add_ticker("NVDA", "NVIDIA Corporation", "NASDAQ", status="paused")

    tickers = store.list_tickers()
    assert tickers[0]["status"] == "paused"
    assert store.list_active_symbols() == []


def test_add_ticker_rejects_invalid_status(store):
    with pytest.raises(ValueError):
        store.add_ticker("NVDA", "NVIDIA Corporation", status="disabled")


def test_add_ticker_exchange_defaults_to_empty_string(store):
    store.add_ticker("MSFT", "Microsoft Corporation")

    assert store.list_tickers()[0]["exchange"] == ""


def test_add_ticker_rejects_empty_symbol(store):
    with pytest.raises(ValueError):
        store.add_ticker("   ", "Nothing")


def test_add_ticker_upserts_on_duplicate(store):
    store.add_ticker("MSFT", "Microsoft", "NASDAQ")
    store.add_ticker("msft", "Microsoft Corporation", "NASDAQ")  # re-add, different case + name

    tickers = store.list_tickers()
    assert len(tickers) == 1
    assert tickers[0]["name"] == "Microsoft Corporation"


def test_add_ticker_upsert_does_not_reset_paused_status(store):
    store.add_ticker("MSFT", "Microsoft Corporation")
    store.pause_ticker("MSFT")

    store.add_ticker("MSFT", "Microsoft Corporation", "NASDAQ")  # re-add while paused

    assert store.list_tickers()[0]["status"] == "paused"


def test_remove_ticker(store):
    store.add_ticker("AAPL", "Apple Inc.")
    store.add_ticker("MSFT", "Microsoft Corporation")

    store.remove_ticker("aapl")  # case-insensitive removal

    assert store.list_symbols() == ["MSFT"]


def test_remove_nonexistent_ticker_is_a_noop(store):
    store.add_ticker("AAPL", "Apple Inc.")

    store.remove_ticker("NVDA")

    assert store.list_symbols() == ["AAPL"]


def test_list_tickers_sorted_by_symbol(store):
    store.add_ticker("NVDA", "NVIDIA Corporation")
    store.add_ticker("AAPL", "Apple Inc.")
    store.add_ticker("MSFT", "Microsoft Corporation")

    assert store.list_symbols() == ["AAPL", "MSFT", "NVDA"]


def test_ensure_seeded_seeds_an_empty_store(store):
    seeded = store.ensure_seeded("MSFT", "Microsoft Corporation")

    assert seeded is True
    assert store.list_symbols() == ["MSFT"]


def test_ensure_seeded_does_not_touch_a_nonempty_store(store):
    store.add_ticker("AAPL", "Apple Inc.")

    seeded = store.ensure_seeded("MSFT", "Microsoft Corporation")

    assert seeded is False
    assert store.list_symbols() == ["AAPL"]


def test_ensure_seeded_passes_through_default_exchange(store):
    store.ensure_seeded("MSFT", "Microsoft Corporation", "NASDAQ")

    assert store.list_tickers()[0]["exchange"] == "NASDAQ"


# --- Pause / resume -----------------------------------------------------

def test_new_ticker_defaults_to_active(store):
    store.add_ticker("AAPL", "Apple Inc.")

    assert store.list_tickers()[0]["status"] == "active"
    assert store.list_active_symbols() == ["AAPL"]


def test_pause_ticker_excludes_it_from_active_symbols(store):
    store.add_ticker("AAPL", "Apple Inc.")
    store.add_ticker("MSFT", "Microsoft Corporation")

    store.pause_ticker("aapl")  # case-insensitive

    assert store.list_active_symbols() == ["MSFT"]
    # still tracked, just not active -- list_symbols() includes everything
    assert store.list_symbols() == ["AAPL", "MSFT"]
    assert store.list_tickers()[0]["status"] == "paused"


def test_resume_ticker_restores_it_to_active_symbols(store):
    store.add_ticker("AAPL", "Apple Inc.")
    store.pause_ticker("AAPL")

    store.resume_ticker("aapl")

    assert store.list_active_symbols() == ["AAPL"]


def test_pausing_nonexistent_ticker_is_a_noop(store):
    store.add_ticker("AAPL", "Apple Inc.")

    store.pause_ticker("NVDA")  # never added

    assert store.list_active_symbols() == ["AAPL"]


# --- Paper trading toggle (talonx_paper's "which ticker can be used") ------

def test_new_ticker_defaults_paper_trading_disabled(store):
    store.add_ticker("AAPL", "Apple Inc.")

    assert store.list_tickers()[0]["paper_trading_enabled"] is False
    assert store.list_paper_trading_symbols() == []


def test_set_paper_trading_enables_and_disables(store):
    store.add_ticker("AAPL", "Apple Inc.")
    store.add_ticker("MSFT", "Microsoft Corporation")

    store.set_paper_trading("aapl", True)  # case-insensitive

    assert store.list_paper_trading_symbols() == ["AAPL"]
    assert store.list_tickers()[0]["paper_trading_enabled"] is True

    store.set_paper_trading("AAPL", False)
    assert store.list_paper_trading_symbols() == []


def test_add_ticker_upsert_does_not_reset_paper_trading_flag(store):
    store.add_ticker("MSFT", "Microsoft Corporation")
    store.set_paper_trading("MSFT", True)

    store.add_ticker("MSFT", "Microsoft Corporation", "NASDAQ")  # re-add

    assert store.list_tickers()[0]["paper_trading_enabled"] is True


# --- Migration from the pre-exchange/status schema -----------------------

def test_migrates_a_pre_existing_three_column_database(tmp_path):
    db_path = tmp_path / "legacy_watchlist.db"

    # Simulate a watchlist.db created before `exchange`/`status` existed.
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute(
        "CREATE TABLE tickers (symbol TEXT PRIMARY KEY, name TEXT NOT NULL, added_at TEXT NOT NULL)"
    )
    legacy_conn.execute(
        "INSERT INTO tickers (symbol, name, added_at) VALUES ('MSFT', 'Microsoft Corporation', '2026-01-01T00:00:00+00:00')"
    )
    legacy_conn.commit()
    legacy_conn.close()

    store = TickerWatchlistStore(db_path)
    try:
        tickers = store.list_tickers()
        assert len(tickers) == 1
        assert tickers[0]["symbol"] == "MSFT"
        assert tickers[0]["name"] == "Microsoft Corporation"
        assert tickers[0]["exchange"] == ""
        assert tickers[0]["status"] == "active"
        assert tickers[0]["paper_trading_enabled"] is False
        assert store.list_active_symbols() == ["MSFT"]
        assert store.list_paper_trading_symbols() == []

        # And the migrated store is fully usable afterward.
        store.pause_ticker("MSFT")
        assert store.list_active_symbols() == []
        store.set_paper_trading("MSFT", True)
        assert store.list_paper_trading_symbols() == ["MSFT"]
    finally:
        store.close()
