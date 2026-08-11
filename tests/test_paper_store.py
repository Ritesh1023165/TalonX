"""
tests/test_paper_store.py
-------------------------------
Tests talonx_paper.store.PaperTradingStore -- the SQLite-backed paper
trading ledger. Uses real sqlite3 (stdlib, no mocking needed), same
approach as tests/test_core_store.py / test_ticker_watchlist_store.py
for this project's other local SQLite stores.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from talonx_paper.schemas import AlertAction
from talonx_paper.store import PaperTradingStore

NOW = datetime(2026, 8, 10, 14, 37, 0, tzinfo=timezone.utc)


def _store(tmp_path, initial_balance=10000.0, allocation=2500.0) -> PaperTradingStore:
    return PaperTradingStore(tmp_path / "paper.db", initial_balance, allocation)


def test_fresh_store_seeds_portfolio_state(tmp_path):
    with _store(tmp_path) as store:
        summary = store.get_portfolio_summary()
        assert summary["initial_balance"] == 10000.0
        assert summary["current_cash"] == 10000.0
        assert summary["trade_allocation_usd"] == 2500.0
        assert summary["open_positions_count"] == 0
        assert summary["win_count"] == 0
        assert summary["loss_count"] == 0
        assert summary["win_rate_pct"] == 0.0
        assert summary["total_realized_pnl_pct"] == 0.0


def test_reopening_the_same_file_does_not_reseed(tmp_path):
    path = tmp_path / "paper.db"
    with PaperTradingStore(path, 10000.0, 2500.0) as store:
        store.execute_buy("NVDA", shares=10, price=100.0, cost=1000.0, timestamp=NOW)

    with PaperTradingStore(path, 99999.0, 1.0) as store2:
        summary = store2.get_portfolio_summary()
        assert summary["initial_balance"] == 10000.0  # NOT 99999 -- existing row wins
        assert summary["current_cash"] == 9000.0


# --- execute_buy -----------------------------------------------------------

def test_execute_buy_opens_a_position_and_debits_cash(tmp_path):
    with _store(tmp_path) as store:
        execution = store.execute_buy("nvda", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)

        assert execution.ticker == "NVDA"
        assert execution.order_type.value == "BUY"
        assert execution.portfolio_cash_after == 9000.0
        assert execution.triggering_action == AlertAction.CONFIRMED_BULLISH

        position = store.get_position("NVDA")
        assert position["shares"] == 10.0
        assert position["entry_price"] == 100.0
        assert store.get_portfolio_summary()["current_cash"] == 9000.0


def test_execute_buy_records_trade_history(tmp_path):
    with _store(tmp_path) as store:
        store.execute_buy("NVDA", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        history = store.get_trade_history()
        assert len(history) == 1
        assert history[0]["order_type"] == "BUY"
        assert history[0]["ticker"] == "NVDA"


# --- execute_sell ------------------------------------------------------------

def test_execute_sell_closes_position_and_credits_cash(tmp_path):
    with _store(tmp_path) as store:
        store.execute_buy("NVDA", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        execution = store.execute_sell("NVDA", exit_price=110.0, timestamp=NOW, triggering_action=AlertAction.CONFIRMED_BEARISH)

        assert execution.realized_pnl_usd == 100.0
        assert round(execution.realized_pnl_pct, 2) == 10.0
        assert execution.portfolio_cash_after == 10100.0  # 9000 cash + 1100 proceeds
        assert store.get_position("NVDA") is None  # flat again


def test_execute_sell_updates_win_loss_counts(tmp_path):
    with _store(tmp_path) as store:
        store.execute_buy("NVDA", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        store.execute_sell("NVDA", exit_price=110.0, timestamp=NOW, triggering_action=AlertAction.CONTRADICTED)

        store.execute_buy("AAPL", shares=5.0, price=200.0, cost=1000.0, timestamp=NOW)
        store.execute_sell("AAPL", exit_price=180.0, timestamp=NOW, triggering_action=AlertAction.CONFIRMED_BEARISH)

        summary = store.get_portfolio_summary()
        assert summary["win_count"] == 1
        assert summary["loss_count"] == 1
        assert summary["win_rate_pct"] == 50.0
        assert summary["total_realized_pnl_usd"] == 0.0  # +100 then -100


def test_execute_sell_returns_none_when_no_open_position(tmp_path):
    with _store(tmp_path) as store:
        result = store.execute_sell("NVDA", exit_price=100.0, timestamp=NOW, triggering_action=AlertAction.CONTRADICTED)
        assert result is None


def test_execute_sell_records_entry_price_for_the_telegram_formatter(tmp_path):
    with _store(tmp_path) as store:
        store.execute_buy("SPCX", shares=18.5185, price=135.0, cost=2500.0, timestamp=NOW)
        execution = store.execute_sell("SPCX", exit_price=135.60, timestamp=NOW, triggering_action=AlertAction.CONTRADICTED)
        assert execution.entry_price == 135.0
        assert execution.execution_price == 135.60


# --- reset_portfolio / update_trade_allocation ------------------------------

def test_reset_portfolio_clears_positions_and_history(tmp_path):
    with _store(tmp_path) as store:
        store.execute_buy("NVDA", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)

        store.reset_portfolio(initial_balance=5000.0, trade_allocation_usd=500.0)

        summary = store.get_portfolio_summary()
        assert summary["initial_balance"] == 5000.0
        assert summary["current_cash"] == 5000.0
        assert summary["trade_allocation_usd"] == 500.0
        assert summary["win_count"] == 0
        assert summary["loss_count"] == 0
        assert store.get_open_positions() == []
        assert store.get_trade_history() == []


def test_update_trade_allocation_changes_only_that_field(tmp_path):
    with _store(tmp_path) as store:
        store.update_trade_allocation(999.0)
        summary = store.get_portfolio_summary()
        assert summary["trade_allocation_usd"] == 999.0
        assert summary["current_cash"] == 10000.0  # untouched


# --- latest_prices -----------------------------------------------------------

def test_latest_prices_round_trip(tmp_path):
    with _store(tmp_path) as store:
        store.update_latest_price("nvda", 131.50, NOW)
        store.update_latest_price("AAPL", 200.00, NOW)
        prices = store.get_latest_prices()
        assert prices == {"NVDA": 131.50, "AAPL": 200.00}


def test_update_latest_price_upserts(tmp_path):
    with _store(tmp_path) as store:
        store.update_latest_price("NVDA", 100.0, NOW)
        store.update_latest_price("NVDA", 105.0, NOW)
        assert store.get_latest_prices() == {"NVDA": 105.0}


# --- Concurrent positions across tickers (the point of fixed-$ sizing) ------

# --- Date-range queries (the EOD report's read path) -----------------------

def test_get_trade_history_between_filters_to_the_window(tmp_path):
    with _store(tmp_path) as store:
        store.execute_buy("OLD", shares=1.0, price=100.0, cost=100.0, timestamp=NOW - timedelta(days=1))
        store.execute_buy("IN", shares=1.0, price=100.0, cost=100.0, timestamp=NOW)

        rows = store.get_trade_history_between(NOW - timedelta(hours=1), NOW + timedelta(hours=1))

        assert [r["ticker"] for r in rows] == ["IN"]


def test_get_trade_history_between_end_is_exclusive(tmp_path):
    with _store(tmp_path) as store:
        store.execute_buy("NVDA", shares=1.0, price=100.0, cost=100.0, timestamp=NOW)
        rows = store.get_trade_history_between(NOW - timedelta(hours=1), NOW)
        assert rows == []


# --- Ignored decisions (the "why didn't it trade" trail) -------------------

def test_record_ignored_round_trips_through_the_date_range_query(tmp_path):
    with _store(tmp_path) as store:
        store.record_ignored("NVDA", "NO_ACTIVE_POSITION", AlertAction.CONTRADICTED, 131.50, NOW)

        rows = store.get_ignored_decisions_between(NOW - timedelta(hours=1), NOW + timedelta(hours=1))

        assert len(rows) == 1
        assert rows[0]["ticker"] == "NVDA"
        assert rows[0]["reason"] == "NO_ACTIVE_POSITION"
        assert rows[0]["triggering_action"] == "contradicted"
        assert rows[0]["price"] == 131.50


def test_get_ignored_decisions_between_filters_to_the_window(tmp_path):
    with _store(tmp_path) as store:
        store.record_ignored("OLD", "NO_ACTIVE_POSITION", AlertAction.CONTRADICTED, 100.0, NOW - timedelta(days=1))
        store.record_ignored("IN", "NO_ACTIVE_POSITION", AlertAction.CONTRADICTED, 100.0, NOW)

        rows = store.get_ignored_decisions_between(NOW - timedelta(hours=1), NOW + timedelta(hours=1))

        assert [r["ticker"] for r in rows] == ["IN"]


def test_multiple_tickers_can_hold_concurrent_positions(tmp_path):
    with _store(tmp_path, initial_balance=10000.0, allocation=2500.0) as store:
        store.execute_buy("AAPL", shares=25.0, price=100.0, cost=2500.0, timestamp=NOW)
        store.execute_buy("NVDA", shares=25.0, price=100.0, cost=2500.0, timestamp=NOW)

        positions = store.get_open_positions()
        assert {p["ticker"] for p in positions} == {"AAPL", "NVDA"}
        assert store.get_portfolio_summary()["current_cash"] == 5000.0
