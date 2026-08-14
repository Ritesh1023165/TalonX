"""
tests/test_paper_consumer_long_term.py
------------------------------------------------
Tests talonx_paper.consumer.LongTermPaperEngine's message-routing,
trade-orchestration, and DCA-cycle logic -- Phase 2's sibling to
test_paper_consumer.py's coverage of the intraday PaperTradingEngine.
The store, watchlist store, and Redis client are all mocked
(MagicMock/AsyncMock), same boundary every consumer test in this project
uses.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import talonx_paper.consumer as consumer_module
from talonx_paper.config import PaperConfig
from talonx_paper.consumer import LongTermPaperEngine
from talonx_paper.schemas import AlertAction, LongTermOrderType, LongTermTradeExecution

NOW = datetime(2026, 8, 10, 14, 37, 0, tzinfo=timezone.utc)


def _alert_payload(
    ticker: str = "AAPL", action: str = "high_conviction_buy", price: float = 100.0,
) -> dict:
    return {
        "ticker": ticker, "action": action, "quality_score": 8, "moat_rating": "wide",
        "market_price": price, "intrinsic_fair_value": 130.0, "margin_of_safety_pct": 0.23,
        "correlated_at": NOW.isoformat(),
    }


def _bar_payload(symbol: str = "AAPL", close: float | None = 100.0) -> dict:
    return {"event_type": "bar", "symbol": symbol, "close": close}


def _msg(config: PaperConfig, payload: dict, channel: str | None = None) -> dict:
    return {"channel": (channel or config.alerts_channel_long_term).encode(), "data": json.dumps(payload)}


def _execution(order_type: LongTermOrderType = LongTermOrderType.BUY, trade_id: int = 1) -> LongTermTradeExecution:
    return LongTermTradeExecution(
        trade_id=trade_id, ticker="AAPL", order_type=order_type, execution_price=100.0,
        shares=20.0, contribution_cost=2000.0, avg_cost_basis_after=100.0, total_shares_after=20.0,
        portfolio_cash_after=18000.0, triggering_action=AlertAction.HIGH_CONVICTION_BUY, timestamp=NOW,
    )


@pytest.fixture
def engine() -> LongTermPaperEngine:
    store = MagicMock()
    store.get_long_term_position.return_value = None
    watchlist_store = MagicMock()
    watchlist_store.list_paper_trading_long_term_symbols.return_value = ["AAPL"]
    e = LongTermPaperEngine(config=PaperConfig(simulated_spread_bps=0.0), store=store, watchlist_store=watchlist_store)
    e._client = AsyncMock()
    return e


# --- Message routing ---------------------------------------------------------

@pytest.mark.asyncio
async def test_market_tick_updates_the_latest_price_cache(engine):
    await engine._handle_message(_msg(engine.config, _bar_payload(close=105.0), channel=engine.config.market_channel))
    engine.store.update_latest_price.assert_called_once()
    args = engine.store.update_latest_price.call_args.args
    assert args[0] == "AAPL"
    assert args[1] == 105.0


@pytest.mark.asyncio
async def test_non_bar_market_event_is_ignored(engine):
    payload = _bar_payload()
    payload["event_type"] = "trade"
    await engine._handle_message(_msg(engine.config, payload, channel=engine.config.market_channel))
    engine.store.update_latest_price.assert_not_called()


@pytest.mark.asyncio
async def test_message_on_unexpected_channel_is_dropped(engine):
    await engine._handle_message(_msg(engine.config, _alert_payload(), channel="some:other:channel"))
    engine.store.get_long_term_position.assert_not_called()


# --- Ticker gating ---------------------------------------------------------

@pytest.mark.asyncio
async def test_alert_for_a_ticker_without_paper_trading_enabled_is_skipped(engine, caplog):
    engine.watchlist_store.list_paper_trading_long_term_symbols.return_value = ["MSFT"]  # AAPL not in it

    with caplog.at_level("INFO"):
        await engine._handle_message(_msg(engine.config, _alert_payload(ticker="AAPL")))

    engine.store.get_long_term_position.assert_not_called()
    assert engine.alerts_processed == 1
    assert engine.trades_executed == 0
    assert "PAPER_TRADING_DISABLED_FOR_TICKER" in caplog.text
    assert "AAPL" in caplog.text


# --- BUY (HIGH_CONVICTION_BUY) -----------------------------------------------

@pytest.mark.asyncio
async def test_high_conviction_buy_flat_executes_a_buy(engine):
    engine.store.get_long_term_position.return_value = None
    engine.store.get_long_term_portfolio_summary.return_value = {"current_cash": 20000.0}
    engine.store.execute_long_term_buy.return_value = _execution(LongTermOrderType.BUY)

    await engine._handle_message(_msg(engine.config, _alert_payload(action="high_conviction_buy", price=100.0)))

    engine.store.execute_long_term_buy.assert_called_once()
    ticker, shares, price, cost, ts = engine.store.execute_long_term_buy.call_args.args
    assert ticker == "AAPL"
    assert price == 100.0
    assert cost == engine.config.long_term_initial_position_usd
    engine._client.publish.assert_awaited_once()
    channel, payload = engine._client.publish.await_args.args
    assert channel == engine.config.paper_trades_channel_long_term
    assert json.loads(payload)["order_type"] == "BUY"
    assert engine.trades_executed == 1


@pytest.mark.asyncio
async def test_high_conviction_buy_already_long_is_ignored_and_not_published(engine):
    engine.store.get_long_term_position.return_value = {
        "ticker": "AAPL", "total_shares": 20.0, "avg_cost_basis": 90.0,
        "first_entry_at": NOW.isoformat(), "total_contributed_usd": 1800.0,
    }

    await engine._handle_message(_msg(engine.config, _alert_payload(action="high_conviction_buy")))

    engine.store.execute_long_term_buy.assert_not_called()
    engine._client.publish.assert_not_awaited()
    assert engine.trades_ignored == 1
    engine.store.record_ignored.assert_called_once()
    args, kwargs = engine.store.record_ignored.call_args
    assert args[1] == "POSITION_ALREADY_OPEN"
    assert kwargs["horizon"] == "long_term"


@pytest.mark.asyncio
async def test_buy_with_insufficient_cash_is_ignored(engine):
    engine.store.get_long_term_position.return_value = None
    engine.store.get_long_term_portfolio_summary.return_value = {"current_cash": 0.0}

    await engine._handle_message(_msg(engine.config, _alert_payload(action="high_conviction_buy")))

    engine.store.execute_long_term_buy.assert_not_called()
    engine._client.publish.assert_not_awaited()
    assert engine.trades_ignored == 1
    args, _ = engine.store.record_ignored.call_args
    assert args[1] == "INSUFFICIENT_CASH"


# --- SELL_PARTIAL / SELL_FULL -------------------------------------------------

@pytest.mark.asyncio
async def test_take_profit_rebalance_long_executes_a_partial_sell(engine):
    engine.store.get_long_term_position.return_value = {
        "ticker": "AAPL", "total_shares": 30.0, "avg_cost_basis": 90.0,
        "first_entry_at": NOW.isoformat(), "total_contributed_usd": 2700.0,
    }
    engine.store.execute_long_term_sell.return_value = _execution(LongTermOrderType.SELL)

    await engine._handle_message(_msg(engine.config, _alert_payload(action="take_profit_rebalance", price=150.0)))

    engine.store.execute_long_term_sell.assert_called_once()
    ticker, trim_fraction, price, ts, action = engine.store.execute_long_term_sell.call_args.args
    assert ticker == "AAPL"
    assert trim_fraction == engine.config.rebalance_trim_pct
    assert price == 150.0
    assert action == AlertAction.TAKE_PROFIT_REBALANCE
    engine._client.publish.assert_awaited_once()
    assert engine.trades_executed == 1


@pytest.mark.asyncio
async def test_under_perform_rebalance_long_executes_a_full_sell(engine):
    engine.store.get_long_term_position.return_value = {
        "ticker": "AAPL", "total_shares": 30.0, "avg_cost_basis": 90.0,
        "first_entry_at": NOW.isoformat(), "total_contributed_usd": 2700.0,
    }
    engine.store.execute_long_term_sell.return_value = _execution(LongTermOrderType.SELL)

    await engine._handle_message(_msg(engine.config, _alert_payload(action="under_perform_rebalance", price=60.0)))

    trim_fraction = engine.store.execute_long_term_sell.call_args.args[1]
    assert trim_fraction == 1.0  # full exit, not a partial trim


@pytest.mark.asyncio
async def test_take_profit_rebalance_flat_is_ignored():
    store = MagicMock()
    store.get_long_term_position.return_value = None
    watchlist_store = MagicMock()
    watchlist_store.list_paper_trading_long_term_symbols.return_value = ["AAPL"]
    engine = LongTermPaperEngine(config=PaperConfig(simulated_spread_bps=0.0), store=store, watchlist_store=watchlist_store)
    engine._client = AsyncMock()

    await engine._handle_message(_msg(engine.config, _alert_payload(action="take_profit_rebalance")))

    store.execute_long_term_sell.assert_not_called()
    assert engine.trades_ignored == 1
    args, _ = store.record_ignored.call_args
    assert args[1] == "NO_ACTIVE_POSITION"


@pytest.mark.asyncio
async def test_sell_returning_none_from_store_is_not_published(engine):
    engine.store.get_long_term_position.return_value = {
        "ticker": "AAPL", "total_shares": 30.0, "avg_cost_basis": 90.0,
        "first_entry_at": NOW.isoformat(), "total_contributed_usd": 2700.0,
    }
    engine.store.execute_long_term_sell.return_value = None  # race: position closed meanwhile

    await engine._handle_message(_msg(engine.config, _alert_payload(action="under_perform_rebalance")))

    engine._client.publish.assert_not_awaited()
    assert engine.trades_executed == 0
    args, _ = engine.store.record_ignored.call_args
    assert args[1] == "NO_ACTIVE_POSITION"


# --- HOLD_QUALITY (no trading action) -----------------------------------------

@pytest.mark.asyncio
async def test_hold_quality_takes_no_action(engine):
    await engine._handle_message(_msg(engine.config, _alert_payload(action="hold_quality")))

    engine.store.execute_long_term_buy.assert_not_called()
    engine.store.execute_long_term_sell.assert_not_called()
    engine._client.publish.assert_not_awaited()
    assert engine.trades_executed == 0
    assert engine.trades_ignored == 0
    engine.store.record_ignored.assert_not_called()


# --- Simulated spread ---------------------------------------------------------

@pytest.mark.asyncio
async def test_buy_fill_price_crosses_the_spread():
    store = MagicMock()
    store.get_long_term_position.return_value = None
    store.get_long_term_portfolio_summary.return_value = {"current_cash": 20000.0}
    store.execute_long_term_buy.return_value = _execution(LongTermOrderType.BUY)
    watchlist_store = MagicMock()
    watchlist_store.list_paper_trading_long_term_symbols.return_value = ["AAPL"]
    engine = LongTermPaperEngine(
        config=PaperConfig(simulated_spread_bps=10.0), store=store, watchlist_store=watchlist_store,
    )
    engine._client = AsyncMock()

    await engine._handle_message(_msg(engine.config, _alert_payload(action="high_conviction_buy", price=100.0)))

    fill_price = store.execute_long_term_buy.call_args.args[2]
    assert round(fill_price, 4) == 100.05


# --- Bad payloads ------------------------------------------------------------

@pytest.mark.asyncio
async def test_unparseable_alert_is_dropped(engine):
    await engine._handle_message({"channel": engine.config.alerts_channel_long_term.encode(), "data": "not json"})
    assert engine.alerts_processed == 0


@pytest.mark.asyncio
async def test_invalid_alert_payload_is_dropped(engine):
    await engine._handle_message(_msg(engine.config, {"ticker": "AAPL"}))
    assert engine.alerts_processed == 0


# ==========================================================================
# DCA cycle (_run_dca_cycle_once)
# ==========================================================================

@pytest.mark.asyncio
async def test_dca_cycle_contributes_to_every_open_position(engine):
    engine.store.get_open_long_term_positions.return_value = [
        {"ticker": "AAPL", "total_shares": 20.0, "avg_cost_basis": 100.0,
         "first_entry_at": NOW.isoformat(), "total_contributed_usd": 2000.0},
        {"ticker": "MSFT", "total_shares": 10.0, "avg_cost_basis": 200.0,
         "first_entry_at": NOW.isoformat(), "total_contributed_usd": 2000.0},
    ]
    engine.store.get_latest_prices.return_value = {"AAPL": 110.0, "MSFT": 210.0}
    engine.store.get_long_term_portfolio_summary.return_value = {
        "current_cash": 20000.0, "dca_contribution_usd": 500.0,
    }
    engine.store.execute_dca_contribution.side_effect = [
        _execution(LongTermOrderType.DCA_CONTRIBUTION, trade_id=1),
        _execution(LongTermOrderType.DCA_CONTRIBUTION, trade_id=2),
    ]

    await engine._run_dca_cycle_once()

    assert engine.store.execute_dca_contribution.call_count == 2
    calls = engine.store.execute_dca_contribution.call_args_list
    assert calls[0].args[0] == "AAPL"
    assert calls[0].args[1] == 500.0
    assert calls[0].args[2] == 110.0
    assert calls[1].args[0] == "MSFT"
    assert engine._client.publish.await_count == 2
    assert engine.dca_contributions_made == 2


@pytest.mark.asyncio
async def test_dca_cycle_skips_a_ticker_with_no_known_price(engine):
    engine.store.get_open_long_term_positions.return_value = [
        {"ticker": "AAPL", "total_shares": 20.0, "avg_cost_basis": 100.0,
         "first_entry_at": NOW.isoformat(), "total_contributed_usd": 2000.0},
    ]
    engine.store.get_latest_prices.return_value = {}  # no known price for AAPL
    engine.store.get_long_term_portfolio_summary.return_value = {
        "current_cash": 20000.0, "dca_contribution_usd": 500.0,
    }

    await engine._run_dca_cycle_once()

    engine.store.execute_dca_contribution.assert_not_called()
    assert engine.dca_contributions_made == 0


@pytest.mark.asyncio
async def test_dca_cycle_skips_when_insufficient_cash(engine):
    engine.store.get_open_long_term_positions.return_value = [
        {"ticker": "AAPL", "total_shares": 20.0, "avg_cost_basis": 100.0,
         "first_entry_at": NOW.isoformat(), "total_contributed_usd": 2000.0},
    ]
    engine.store.get_latest_prices.return_value = {"AAPL": 110.0}
    engine.store.get_long_term_portfolio_summary.return_value = {
        "current_cash": 100.0, "dca_contribution_usd": 500.0,  # not enough cash
    }

    await engine._run_dca_cycle_once()

    engine.store.execute_dca_contribution.assert_not_called()


@pytest.mark.asyncio
async def test_dca_cycle_with_no_open_positions_is_a_noop(engine):
    engine.store.get_open_long_term_positions.return_value = []

    await engine._run_dca_cycle_once()

    engine.store.get_latest_prices.assert_not_called()
    engine._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_dca_cycle_records_last_dca_at_even_with_no_open_positions(engine):
    """Restart-survival fix: the CYCLE, not per-ticker success, is the
    schedulable unit -- the clock must reset even when there's nothing
    to contribute to yet, so a position opened later doesn't inherit a
    months-stale (or never-set) timestamp and immediately fire."""
    engine.store.get_open_long_term_positions.return_value = []

    await engine._run_dca_cycle_once()

    engine.store.set_last_dca_at.assert_called_once()


@pytest.mark.asyncio
async def test_dca_cycle_records_last_dca_at_before_contributing(engine):
    engine.store.get_open_long_term_positions.return_value = [
        {"ticker": "AAPL", "total_shares": 20.0, "avg_cost_basis": 100.0,
         "first_entry_at": NOW.isoformat(), "total_contributed_usd": 2000.0},
    ]
    engine.store.get_latest_prices.return_value = {"AAPL": 110.0}
    engine.store.get_long_term_portfolio_summary.return_value = {
        "current_cash": 20000.0, "dca_contribution_usd": 500.0,
    }
    engine.store.execute_dca_contribution.return_value = _execution(LongTermOrderType.DCA_CONTRIBUTION)

    await engine._run_dca_cycle_once()

    engine.store.set_last_dca_at.assert_called_once()


@pytest.mark.asyncio
async def test_dca_cycle_none_execution_result_is_skipped_gracefully(engine):
    """Defensive race: the position was listed as open, but closed by an
    alert-driven SELL between the listing and the DCA write."""
    engine.store.get_open_long_term_positions.return_value = [
        {"ticker": "AAPL", "total_shares": 20.0, "avg_cost_basis": 100.0,
         "first_entry_at": NOW.isoformat(), "total_contributed_usd": 2000.0},
    ]
    engine.store.get_latest_prices.return_value = {"AAPL": 110.0}
    engine.store.get_long_term_portfolio_summary.return_value = {
        "current_cash": 20000.0, "dca_contribution_usd": 500.0,
    }
    engine.store.execute_dca_contribution.return_value = None

    await engine._run_dca_cycle_once()

    engine._client.publish.assert_not_awaited()
    assert engine.dca_contributions_made == 0


# ==========================================================================
# _seconds_until_next_dca (restart-survival fix)
#
# Before this fix, _dca_loop waited a fixed dca_interval_days*86400
# CONSTANT on every restart, with no persisted checkpoint -- since that
# interval (30 days default) vastly exceeds this project's typical
# scheduled daily uptime window, the timer could never complete at all
# under a daily-restart schedule, and zero DCA_CONTRIBUTION rows had
# EVER been recorded live. These tests exercise the fix directly: the
# wait is now derived from store.get_last_dca_at(), a persisted
# timestamp, so it reflects true wall-clock elapsed time across restarts.
# ==========================================================================

def test_seconds_until_next_dca_is_full_interval_on_first_ever_cycle(engine):
    engine.store.get_last_dca_at.return_value = None

    seconds = engine._seconds_until_next_dca()

    assert seconds == pytest.approx(engine.config.dca_interval_days * 86400.0)


class _FrozenDatetime(datetime):
    """datetime.now() pinned to NOW, everything else (fromisoformat,
    isoformat, arithmetic, __sub__) inherited unchanged -- lets
    _seconds_until_next_dca's `datetime.now(timezone.utc) - last_dca_at`
    be tested deterministically via monkeypatch instead of depending on
    real wall-clock time during the test run."""

    @classmethod
    def now(cls, tz=None):
        return NOW


def test_seconds_until_next_dca_accounts_for_real_elapsed_time_across_a_restart(engine, monkeypatch):
    """Simulates a restart mid-interval: 10 days have genuinely elapsed
    (persisted timestamp), so only interval-10d worth of waiting remains
    -- NOT a fresh full interval, which is what the old constant-timeout
    design would have (incorrectly) waited."""
    engine.store.get_last_dca_at.return_value = NOW - timedelta(days=10)
    monkeypatch.setattr(consumer_module, "datetime", _FrozenDatetime)

    seconds = engine._seconds_until_next_dca()

    expected = engine.config.dca_interval_days * 86400.0 - 10 * 86400.0
    assert seconds == pytest.approx(expected, abs=1.0)


def test_seconds_until_next_dca_is_zero_not_negative_when_overdue(engine, monkeypatch):
    """A restart after a gap LONGER than the interval (e.g. the app was
    down well past its scheduled DCA date) must fire on the very next
    tick, not wait a further (negative, silently-never-elapsing) delay."""
    engine.store.get_last_dca_at.return_value = NOW - timedelta(days=999)
    monkeypatch.setattr(consumer_module, "datetime", _FrozenDatetime)

    seconds = engine._seconds_until_next_dca()

    assert seconds == 0.0


@pytest.mark.asyncio
async def test_dca_loop_catches_up_immediately_when_overdue_after_a_restart(engine):
    """End-to-end: a persisted last_dca_at far enough in the past that
    the interval has already elapsed must cause _dca_loop to run a
    cycle almost immediately, not silently wait a fresh full interval."""
    engine.store.get_last_dca_at.return_value = NOW - timedelta(days=999)
    engine.store.get_open_long_term_positions.return_value = []

    async def _stop_soon():
        await asyncio.sleep(0.05)
        engine.stop()

    await asyncio.gather(engine._dca_loop(), _stop_soon())

    engine.store.set_last_dca_at.assert_called()  # a cycle ran before stop() landed
