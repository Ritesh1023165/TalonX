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


def test_execute_buy_persists_atr_stop_and_target_prices(tmp_path):
    with _store(tmp_path) as store:
        store.execute_buy(
            "NVDA", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW,
            stop_price=98.0, target_price=104.0,
        )

        position = store.get_position("NVDA")
        assert position["stop_price"] == 98.0
        assert position["target_price"] == 104.0

        open_positions = store.get_open_positions()
        assert open_positions[0]["stop_price"] == 98.0
        assert open_positions[0]["target_price"] == 104.0


def test_execute_buy_without_atr_levels_leaves_them_none(tmp_path):
    with _store(tmp_path) as store:
        store.execute_buy("NVDA", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)

        position = store.get_position("NVDA")
        assert position["stop_price"] is None
        assert position["target_price"] is None


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


# ==========================================================================
# Phase 2 LONG_TERM path
# ==========================================================================

def _lt_store(tmp_path, initial_balance=20000.0, dca=500.0) -> PaperTradingStore:
    return PaperTradingStore(
        tmp_path / "paper.db", default_long_term_initial_balance=initial_balance,
        default_dca_contribution_usd=dca,
    )


def test_fresh_store_seeds_long_term_portfolio_state(tmp_path):
    with _lt_store(tmp_path) as store:
        summary = store.get_long_term_portfolio_summary()
        assert summary["initial_balance"] == 20000.0
        assert summary["current_cash"] == 20000.0
        assert summary["dca_contribution_usd"] == 500.0
        assert summary["open_positions_count"] == 0


def test_intraday_and_long_term_portfolios_are_independent_pools(tmp_path):
    with PaperTradingStore(
        tmp_path / "paper.db", default_initial_balance=10000.0, default_trade_allocation_usd=2500.0,
        default_long_term_initial_balance=20000.0, default_dca_contribution_usd=500.0,
    ) as store:
        store.execute_buy("NVDA", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        store.execute_long_term_buy("AAPL", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)

        assert store.get_portfolio_summary()["current_cash"] == 9000.0
        assert store.get_long_term_portfolio_summary()["current_cash"] == 19000.0
        # A DUAL_HORIZON position for the SAME ticker on both ledgers must
        # not collide with each other.
        store.execute_buy("MSFT", shares=5.0, price=200.0, cost=1000.0, timestamp=NOW)
        store.execute_long_term_buy("MSFT", shares=5.0, price=200.0, cost=1000.0, timestamp=NOW)
        assert store.get_position("MSFT")["shares"] == 5.0
        assert store.get_long_term_position("MSFT")["total_shares"] == 5.0


def test_execute_long_term_buy_opens_a_position(tmp_path):
    with _lt_store(tmp_path) as store:
        execution = store.execute_long_term_buy("AAPL", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)

        assert execution.ticker == "AAPL"
        assert execution.order_type.value == "BUY"
        assert execution.avg_cost_basis_after == 100.0
        assert execution.total_shares_after == 10.0
        assert execution.portfolio_cash_after == 19000.0

        position = store.get_long_term_position("AAPL")
        assert position["total_shares"] == 10.0
        assert position["avg_cost_basis"] == 100.0
        assert position["total_contributed_usd"] == 1000.0


def test_execute_dca_contribution_recomputes_the_weighted_average(tmp_path):
    with _lt_store(tmp_path) as store:
        store.execute_long_term_buy("AAPL", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        execution = store.execute_dca_contribution("AAPL", contribution_usd=1200.0, price=120.0, timestamp=NOW)

        # 10 shares @ 100 (existing) + 10 shares @ 120 (new, 1200/120=10)
        # -> avg = (1000 + 1200) / 20 = 110.0
        assert round(execution.avg_cost_basis_after, 2) == 110.0
        assert execution.total_shares_after == 20.0
        assert execution.order_type.value == "DCA_CONTRIBUTION"

        position = store.get_long_term_position("AAPL")
        assert round(position["avg_cost_basis"], 2) == 110.0
        assert position["total_shares"] == 20.0
        assert position["total_contributed_usd"] == 2200.0


def test_execute_dca_contribution_debits_the_shared_cash_pool(tmp_path):
    with _lt_store(tmp_path) as store:
        store.execute_long_term_buy("AAPL", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        store.execute_dca_contribution("AAPL", contribution_usd=500.0, price=100.0, timestamp=NOW)

        assert store.get_long_term_portfolio_summary()["current_cash"] == 20000.0 - 1000.0 - 500.0


def test_execute_dca_contribution_returns_none_without_an_open_position(tmp_path):
    with _lt_store(tmp_path) as store:
        result = store.execute_dca_contribution("AAPL", contribution_usd=500.0, price=100.0, timestamp=NOW)
        assert result is None


def test_execute_long_term_sell_full_exit_closes_the_position(tmp_path):
    with _lt_store(tmp_path) as store:
        store.execute_long_term_buy("AAPL", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        execution = store.execute_long_term_sell(
            "AAPL", trim_fraction=1.0, exit_price=120.0, timestamp=NOW + timedelta(days=200),
            triggering_action=AlertAction.UNDER_PERFORM_REBALANCE,
        )

        assert execution.shares == 10.0
        assert execution.realized_pnl_usd == 200.0  # 10 * (120-100)
        assert execution.avg_cost_basis_after is None
        assert execution.total_shares_after is None
        assert execution.holding_period_days == 200
        assert store.get_long_term_position("AAPL") is None  # flat again


def test_execute_long_term_sell_partial_trim_leaves_the_remainder_open(tmp_path):
    with _lt_store(tmp_path) as store:
        store.execute_long_term_buy("AAPL", shares=30.0, price=100.0, cost=3000.0, timestamp=NOW)
        execution = store.execute_long_term_sell(
            "AAPL", trim_fraction=0.33, exit_price=120.0, timestamp=NOW,
            triggering_action=AlertAction.TAKE_PROFIT_REBALANCE,
        )

        assert round(execution.shares, 2) == 9.9  # 30 * 0.33
        assert execution.avg_cost_basis_after == 100.0  # trimming doesn't change the average

        position = store.get_long_term_position("AAPL")
        assert round(position["total_shares"], 2) == 20.1  # 30 - 9.9


def test_execute_long_term_sell_returns_none_without_an_open_position(tmp_path):
    with _lt_store(tmp_path) as store:
        result = store.execute_long_term_sell(
            "AAPL", trim_fraction=1.0, exit_price=100.0, timestamp=NOW,
            triggering_action=AlertAction.UNDER_PERFORM_REBALANCE,
        )
        assert result is None


def test_execute_long_term_sell_credits_cash_and_updates_win_loss(tmp_path):
    with _lt_store(tmp_path) as store:
        store.execute_long_term_buy("AAPL", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        store.execute_long_term_sell(
            "AAPL", trim_fraction=1.0, exit_price=120.0, timestamp=NOW,
            triggering_action=AlertAction.UNDER_PERFORM_REBALANCE,
        )

        summary = store.get_long_term_portfolio_summary()
        assert summary["current_cash"] == 20000.0 - 1000.0 + 1200.0
        assert summary["win_count"] == 1
        assert summary["loss_count"] == 0


def test_long_term_trade_history_records_buy_dca_and_sell(tmp_path):
    with _lt_store(tmp_path) as store:
        store.execute_long_term_buy("AAPL", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        store.execute_dca_contribution("AAPL", contribution_usd=500.0, price=110.0, timestamp=NOW)
        store.execute_long_term_sell(
            "AAPL", trim_fraction=1.0, exit_price=120.0, timestamp=NOW,
            triggering_action=AlertAction.UNDER_PERFORM_REBALANCE,
        )

        history = store.get_long_term_trade_history()
        order_types = [h["order_type"] for h in history]
        assert set(order_types) == {"BUY", "DCA_CONTRIBUTION", "SELL"}


def test_total_dca_contributed_is_computable_from_trade_history(tmp_path):
    with _lt_store(tmp_path) as store:
        store.execute_long_term_buy("AAPL", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        store.execute_dca_contribution("AAPL", contribution_usd=500.0, price=110.0, timestamp=NOW)
        store.execute_dca_contribution("AAPL", contribution_usd=500.0, price=115.0, timestamp=NOW)

        history = store.get_long_term_trade_history()
        total_dca = sum(h["contribution_cost"] for h in history if h["order_type"] == "DCA_CONTRIBUTION")
        assert total_dca == 1000.0


def test_get_long_term_trade_history_between_filters_to_the_window(tmp_path):
    with _lt_store(tmp_path) as store:
        store.execute_long_term_buy("OLD", shares=1.0, price=100.0, cost=100.0, timestamp=NOW - timedelta(days=1))
        store.execute_long_term_buy("IN", shares=1.0, price=100.0, cost=100.0, timestamp=NOW)

        rows = store.get_long_term_trade_history_between(NOW - timedelta(hours=1), NOW + timedelta(hours=1))
        assert [r["ticker"] for r in rows] == ["IN"]


def test_reset_long_term_portfolio_clears_positions_and_history(tmp_path):
    with _lt_store(tmp_path) as store:
        store.execute_long_term_buy("AAPL", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)

        store.reset_long_term_portfolio(initial_balance=5000.0, dca_contribution_usd=250.0)

        summary = store.get_long_term_portfolio_summary()
        assert summary["initial_balance"] == 5000.0
        assert summary["current_cash"] == 5000.0
        assert summary["dca_contribution_usd"] == 250.0
        assert store.get_open_long_term_positions() == []
        assert store.get_long_term_trade_history() == []


def test_update_dca_contribution_amount_changes_only_that_field(tmp_path):
    with _lt_store(tmp_path) as store:
        store.update_dca_contribution_amount(999.0)
        summary = store.get_long_term_portfolio_summary()
        assert summary["dca_contribution_usd"] == 999.0
        assert summary["current_cash"] == 20000.0  # untouched


def test_multiple_long_term_positions_are_independent(tmp_path):
    with _lt_store(tmp_path) as store:
        store.execute_long_term_buy("AAPL", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        store.execute_long_term_buy("MSFT", shares=5.0, price=200.0, cost=1000.0, timestamp=NOW)

        positions = store.get_open_long_term_positions()
        assert {p["ticker"] for p in positions} == {"AAPL", "MSFT"}


def test_record_ignored_defaults_to_intraday_horizon(tmp_path):
    with _store(tmp_path) as store:
        store.record_ignored("NVDA", "NO_ACTIVE_POSITION", AlertAction.CONTRADICTED, 131.50, NOW)
        rows = store.get_ignored_decisions_between(NOW - timedelta(hours=1), NOW + timedelta(hours=1))
        assert rows[0]["horizon"] == "intraday"


def test_record_ignored_accepts_a_long_term_horizon(tmp_path):
    with _store(tmp_path) as store:
        store.record_ignored(
            "AAPL", "NO_ACTIVE_POSITION", AlertAction.UNDER_PERFORM_REBALANCE, 100.0, NOW, horizon="long_term",
        )
        rows = store.get_ignored_decisions_between(NOW - timedelta(hours=1), NOW + timedelta(hours=1))
        assert rows[0]["horizon"] == "long_term"


def test_migrates_a_pre_existing_ignored_decisions_table_without_horizon(tmp_path):
    import sqlite3

    db_path = tmp_path / "legacy_paper.db"
    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.execute(
        "CREATE TABLE ignored_decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL, "
        "reason TEXT NOT NULL, triggering_action TEXT NOT NULL, price REAL NOT NULL, timestamp TEXT NOT NULL)"
    )
    legacy_conn.execute(
        "INSERT INTO ignored_decisions (ticker, reason, triggering_action, price, timestamp) "
        "VALUES ('AAPL', 'NO_ACTIVE_POSITION', 'contradicted', 100.0, ?)",
        (NOW.isoformat(),),
    )
    legacy_conn.commit()
    legacy_conn.close()

    with PaperTradingStore(db_path) as store:
        rows = store.get_ignored_decisions_between(NOW - timedelta(hours=1), NOW + timedelta(hours=1))
        assert len(rows) == 1
        assert rows[0]["horizon"] == "intraday"

        store.record_ignored("MSFT", "NO_ACTIVE_POSITION", AlertAction.CONTRADICTED, 100.0, NOW, horizon="long_term")
        rows = store.get_ignored_decisions_between(NOW - timedelta(hours=1), NOW + timedelta(hours=1))
        assert len(rows) == 2


# ==========================================================================
# WAL checkpoint (fixes the dashboard-slowdown-over-a-session issue --
# see run_talonx.periodic_wal_checkpoint_loop's own docstring)
# ==========================================================================

def test_checkpoint_does_not_raise(tmp_path):
    with _store(tmp_path) as store:
        store.checkpoint()


def test_checkpoint_shrinks_the_wal_file(tmp_path):
    db_path = tmp_path / "paper.db"
    wal_path = tmp_path / "paper.db-wal"
    with _store(tmp_path) as store:
        # update_latest_price commits every call -- this is the exact
        # high-frequency write path (once per market tick, per ticker)
        # that grows the WAL in real usage.
        for i in range(50):
            store.update_latest_price("AAPL", 100.0 + i, NOW + timedelta(seconds=i))
        assert wal_path.exists()
        size_before = wal_path.stat().st_size

        store.checkpoint()

        size_after = wal_path.stat().st_size
        assert size_after <= size_before
        # And the data itself survives the checkpoint intact.
        assert store.get_latest_prices()["AAPL"] == 149.0
