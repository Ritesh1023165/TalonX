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


def test_get_ticker_returns_the_matching_row(store):
    store.add_ticker("nvda", "NVIDIA Corporation", "NASDAQ")

    ticker = store.get_ticker("NVDA")

    assert ticker is not None
    assert ticker["symbol"] == "NVDA"
    assert ticker["name"] == "NVIDIA Corporation"


def test_get_ticker_is_case_insensitive(store):
    store.add_ticker("NVDA", "NVIDIA Corporation")

    assert store.get_ticker("nvda") is not None


def test_get_ticker_returns_none_for_an_untracked_symbol(store):
    assert store.get_ticker("NVDA") is None


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


# --- Long-term paper trading toggle (independent of the intraday one) ------

def test_new_ticker_defaults_long_term_paper_trading_disabled(store):
    store.add_ticker("AAPL", "Apple Inc.")

    assert store.list_tickers()[0]["paper_trading_enabled_long_term"] is False
    assert store.list_paper_trading_long_term_symbols() == []


def test_set_paper_trading_long_term_enables_and_disables(store):
    store.add_ticker("AAPL", "Apple Inc.")
    store.add_ticker("MSFT", "Microsoft Corporation")

    store.set_paper_trading_long_term("aapl", True)  # case-insensitive

    assert store.list_paper_trading_long_term_symbols() == ["AAPL"]
    assert store.list_tickers()[0]["paper_trading_enabled_long_term"] is True

    store.set_paper_trading_long_term("AAPL", False)
    assert store.list_paper_trading_long_term_symbols() == []


def test_intraday_and_long_term_paper_trading_flags_are_independent(store):
    store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="DUAL_HORIZON")

    store.set_paper_trading("AAPL", True)
    store.set_paper_trading_long_term("AAPL", False)

    assert store.list_paper_trading_symbols() == ["AAPL"]
    assert store.list_paper_trading_long_term_symbols() == []

    store.set_paper_trading("AAPL", False)
    store.set_paper_trading_long_term("AAPL", True)

    assert store.list_paper_trading_symbols() == []
    assert store.list_paper_trading_long_term_symbols() == ["AAPL"]


def test_add_ticker_upsert_does_not_reset_long_term_paper_trading_flag(store):
    store.add_ticker("MSFT", "Microsoft Corporation")
    store.set_paper_trading_long_term("MSFT", True)

    store.add_ticker("MSFT", "Microsoft Corporation", "NASDAQ")  # re-add

    assert store.list_tickers()[0]["paper_trading_enabled_long_term"] is True


# --- Strategy horizon (Phase 2's intraday/long-term routing control) ------

def test_new_ticker_defaults_to_intraday_horizon(store):
    store.add_ticker("AAPL", "Apple Inc.")

    assert store.list_tickers()[0]["strategy_horizon"] == "INTRADAY"
    assert store.list_by_horizon("INTRADAY") == ["AAPL"]
    assert store.list_by_horizon("LONG_TERM") == []


def test_add_ticker_accepts_an_initial_horizon(store):
    store.add_ticker("BRK.B", "Berkshire Hathaway", strategy_horizon="LONG_TERM")

    assert store.list_tickers()[0]["strategy_horizon"] == "LONG_TERM"
    assert store.list_by_horizon("LONG_TERM") == ["BRK.B"]
    assert store.list_by_horizon("INTRADAY") == []


def test_add_ticker_rejects_invalid_horizon(store):
    with pytest.raises(ValueError):
        store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="WEEKLY")


def test_set_strategy_horizon_changes_routing(store):
    store.add_ticker("AAPL", "Apple Inc.")

    store.set_strategy_horizon("aapl", "LONG_TERM")  # case-insensitive

    assert store.list_tickers()[0]["strategy_horizon"] == "LONG_TERM"
    assert store.list_by_horizon("LONG_TERM") == ["AAPL"]
    assert store.list_by_horizon("INTRADAY") == []


def test_set_strategy_horizon_rejects_invalid_value(store):
    store.add_ticker("AAPL", "Apple Inc.")
    with pytest.raises(ValueError):
        store.set_strategy_horizon("AAPL", "NOT_A_HORIZON")


def test_dual_horizon_ticker_appears_in_both_lists(store):
    store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="DUAL_HORIZON")
    store.add_ticker("NVDA", "NVIDIA Corporation", strategy_horizon="INTRADAY")
    store.add_ticker("BRK.B", "Berkshire Hathaway", strategy_horizon="LONG_TERM")

    assert store.list_by_horizon("INTRADAY") == ["AAPL", "NVDA"]
    assert store.list_by_horizon("LONG_TERM") == ["AAPL", "BRK.B"]
    assert store.list_by_horizon("DUAL_HORIZON") == ["AAPL"]


def test_add_ticker_upsert_does_not_reset_strategy_horizon(store):
    store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")

    store.add_ticker("AAPL", "Apple Inc.", "NASDAQ")  # re-add, horizon omitted

    assert store.list_tickers()[0]["strategy_horizon"] == "LONG_TERM"


def test_list_by_horizon_rejects_invalid_value(store):
    with pytest.raises(ValueError):
        store.list_by_horizon("NOT_A_HORIZON")


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
        assert tickers[0]["paper_trading_enabled_long_term"] is False
        assert tickers[0]["strategy_horizon"] == "INTRADAY"
        assert store.list_active_symbols() == ["MSFT"]
        assert store.list_paper_trading_symbols() == []
        assert store.list_paper_trading_long_term_symbols() == []
        assert store.list_by_horizon("INTRADAY") == ["MSFT"]

        # And the migrated store is fully usable afterward.
        store.pause_ticker("MSFT")
        assert store.list_active_symbols() == []
        store.set_paper_trading("MSFT", True)
        assert store.list_paper_trading_symbols() == ["MSFT"]
        store.set_paper_trading_long_term("MSFT", True)
        assert store.list_paper_trading_long_term_symbols() == ["MSFT"]
        store.set_strategy_horizon("MSFT", "LONG_TERM")
        assert store.list_by_horizon("LONG_TERM") == ["MSFT"]
    finally:
        store.close()


def test_migrates_a_database_from_before_the_long_term_paper_trading_split(tmp_path):
    """Narrower migration than the legacy 3-column test above -- simulates
    a watchlist.db from right before paper_trading_enabled_long_term was
    added (everything else already present), the migration path an
    existing Phase 2 install actually hits."""
    db_path = tmp_path / "pre_split_watchlist.db"

    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute(
        "CREATE TABLE tickers ("
        "symbol TEXT PRIMARY KEY, name TEXT NOT NULL, exchange TEXT NOT NULL DEFAULT '', "
        "status TEXT NOT NULL DEFAULT 'active', paper_trading_enabled INTEGER NOT NULL DEFAULT 0, "
        "strategy_horizon TEXT NOT NULL DEFAULT 'INTRADAY', added_at TEXT NOT NULL)"
    )
    legacy_conn.execute(
        "INSERT INTO tickers (symbol, name, paper_trading_enabled, strategy_horizon, added_at) "
        "VALUES ('MSFT', 'Microsoft Corporation', 1, 'DUAL_HORIZON', '2026-01-01T00:00:00+00:00')"
    )
    legacy_conn.commit()
    legacy_conn.close()

    store = TickerWatchlistStore(db_path)
    try:
        ticker = store.list_tickers()[0]
        assert ticker["paper_trading_enabled"] is True  # pre-existing value preserved
        assert ticker["paper_trading_enabled_long_term"] is False  # new column defaults off
        assert store.list_paper_trading_symbols() == ["MSFT"]
        assert store.list_paper_trading_long_term_symbols() == []

        store.set_paper_trading_long_term("MSFT", True)
        assert store.list_paper_trading_long_term_symbols() == ["MSFT"]
    finally:
        store.close()
