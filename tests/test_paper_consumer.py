"""
tests/test_paper_consumer.py
----------------------------------
Tests talonx_paper.consumer.PaperTradingEngine's message-routing and
trade-orchestration logic. The store, watchlist store, and Redis client
are all mocked (MagicMock/AsyncMock) -- this is about the orchestration,
not real SQLite/Redis I/O (see test_paper_store.py / test_paper_engine.py
for those), same boundary every other consumer's tests in this project use.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_paper.config import PaperConfig
from talonx_paper.consumer import PaperTradingEngine
from talonx_paper.schemas import AlertAction, AlertSeverity, OrderType, PaperTradeExecution

NOW = datetime(2026, 8, 10, 14, 37, 0, tzinfo=timezone.utc)


def _alert_payload(
    ticker: str = "NVDA", action: str = "confirmed_bullish", price: float = 131.50,
    severity: str = "warning",
) -> dict:
    return {
        "ticker": ticker, "action": action, "severity": severity,
        "triggering_signal": {"price": price},
        "correlated_at": NOW.isoformat(),
    }


def _bar_payload(symbol: str = "NVDA", close: float | None = 131.50) -> dict:
    return {"event_type": "bar", "symbol": symbol, "close": close}


def _msg(config: PaperConfig, payload: dict, channel: str | None = None) -> dict:
    return {"channel": (channel or config.alerts_channel).encode(), "data": json.dumps(payload)}


def _execution(order_type: OrderType = OrderType.BUY, trade_id: int = 1) -> PaperTradeExecution:
    return PaperTradeExecution(
        trade_id=trade_id, ticker="NVDA", order_type=order_type, execution_price=131.50,
        shares=10.0, position_cost=1315.0, portfolio_cash_after=8685.0,
        triggering_action=AlertAction.CONFIRMED_BULLISH,
        session_realized_pnl_usd=0.0, session_realized_pnl_pct=0.0, timestamp=NOW,
    )


@pytest.fixture
def engine() -> PaperTradingEngine:
    # spread_bps=0 here so existing price-pass-through assertions stay
    # exact -- spread's effect is covered by its own dedicated tests below.
    store = MagicMock()
    store.get_position.return_value = None  # flat by default; tests override for an open position
    watchlist_store = MagicMock()
    watchlist_store.list_paper_trading_symbols.return_value = ["NVDA"]
    e = PaperTradingEngine(
        config=PaperConfig(simulated_spread_bps=0.0), store=store, watchlist_store=watchlist_store,
    )
    e._client = AsyncMock()
    return e


# --- Message routing ---------------------------------------------------------

@pytest.mark.asyncio
async def test_market_tick_updates_latest_price(engine):
    await engine._handle_message(_msg(engine.config, _bar_payload(close=131.50), channel=engine.config.market_channel))
    engine.store.update_latest_price.assert_called_once()
    args = engine.store.update_latest_price.call_args.args
    assert args[0] == "NVDA"
    assert args[1] == 131.50


@pytest.mark.asyncio
async def test_non_bar_market_event_is_ignored(engine):
    payload = _bar_payload(close=131.50)
    payload["event_type"] = "trade"
    await engine._handle_message(_msg(engine.config, payload, channel=engine.config.market_channel))
    engine.store.update_latest_price.assert_not_called()


@pytest.mark.asyncio
async def test_bar_with_no_close_is_ignored(engine):
    await engine._handle_message(_msg(engine.config, _bar_payload(close=None), channel=engine.config.market_channel))
    engine.store.update_latest_price.assert_not_called()


@pytest.mark.asyncio
async def test_message_on_unexpected_channel_is_dropped(engine):
    await engine._handle_message(_msg(engine.config, _alert_payload(), channel="some:other:channel"))
    engine.store.get_position.assert_not_called()


# --- Ticker gating (the "configure which ticker can be used" control) --------

@pytest.mark.asyncio
async def test_alert_for_a_ticker_without_paper_trading_enabled_is_skipped(engine):
    engine.watchlist_store.list_paper_trading_symbols.return_value = ["AAPL"]  # NVDA not in it

    await engine._handle_message(_msg(engine.config, _alert_payload(ticker="NVDA")))

    engine.store.get_position.assert_not_called()
    engine.store.record_ignored.assert_not_called()  # config-gate skip, not a trading decision
    assert engine.alerts_processed == 1
    assert engine.trades_executed == 0


# --- BUY -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirmed_bullish_flat_executes_a_buy(engine):
    engine.store.get_position.return_value = None
    engine.store.get_portfolio_summary.return_value = {"current_cash": 10000.0, "trade_allocation_usd": 2500.0}
    engine.store.execute_buy.return_value = _execution(OrderType.BUY)

    await engine._handle_message(_msg(engine.config, _alert_payload(action="confirmed_bullish", price=131.50)))

    engine.store.execute_buy.assert_called_once()
    ticker, shares, price, cost, ts = engine.store.execute_buy.call_args.args
    assert ticker == "NVDA"
    assert price == 131.50
    assert cost == 2500.0
    engine._client.publish.assert_awaited_once()
    channel, payload = engine._client.publish.await_args.args
    assert channel == engine.config.paper_trades_channel
    assert json.loads(payload)["order_type"] == "BUY"
    assert engine.trades_executed == 1


@pytest.mark.asyncio
async def test_confirmed_bullish_already_long_is_ignored_and_not_published(engine):
    engine.store.get_position.return_value = {"ticker": "NVDA", "shares": 5.0, "entry_price": 100.0, "cost_basis": 500.0}

    await engine._handle_message(_msg(engine.config, _alert_payload(action="confirmed_bullish")))

    engine.store.execute_buy.assert_not_called()
    engine._client.publish.assert_not_awaited()
    assert engine.trades_ignored == 1
    engine.store.record_ignored.assert_called_once()
    assert engine.store.record_ignored.call_args.args[1] == "POSITION_ALREADY_OPEN"


@pytest.mark.asyncio
async def test_buy_with_insufficient_cash_is_ignored(engine):
    engine.store.get_position.return_value = None
    engine.store.get_portfolio_summary.return_value = {"current_cash": 0.0, "trade_allocation_usd": 2500.0}

    await engine._handle_message(_msg(engine.config, _alert_payload(action="confirmed_bullish")))

    engine.store.execute_buy.assert_not_called()
    engine._client.publish.assert_not_awaited()
    assert engine.trades_ignored == 1
    engine.store.record_ignored.assert_called_once()
    assert engine.store.record_ignored.call_args.args[1] == "INSUFFICIENT_CASH"


# --- SELL ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_contradicted_long_executes_a_sell(engine):
    engine.store.get_position.return_value = {"ticker": "NVDA", "shares": 10.0, "entry_price": 100.0, "cost_basis": 1000.0}
    engine.store.execute_sell.return_value = _execution(OrderType.SELL)

    await engine._handle_message(_msg(engine.config, _alert_payload(action="contradicted", price=110.0)))

    engine.store.execute_sell.assert_called_once()
    ticker, price, ts, triggering_action = engine.store.execute_sell.call_args.args
    assert ticker == "NVDA"
    assert price == 110.0
    assert triggering_action == AlertAction.CONTRADICTED
    engine._client.publish.assert_awaited_once()
    assert engine.trades_executed == 1


@pytest.mark.asyncio
async def test_confirmed_bearish_flat_is_ignored(engine):
    engine.store.get_position.return_value = None

    await engine._handle_message(_msg(engine.config, _alert_payload(action="confirmed_bearish")))

    engine.store.execute_sell.assert_not_called()
    assert engine.trades_ignored == 1
    engine.store.record_ignored.assert_called_once()
    assert engine.store.record_ignored.call_args.args[1] == "NO_ACTIVE_POSITION"


@pytest.mark.asyncio
async def test_sell_returning_none_from_store_is_not_published(engine):
    # Defensive race: decide_trade thought we were long, but the store
    # found no position at execution time.
    engine.store.get_position.return_value = {"ticker": "NVDA", "shares": 10.0, "entry_price": 100.0, "cost_basis": 1000.0}
    engine.store.execute_sell.return_value = None

    await engine._handle_message(_msg(engine.config, _alert_payload(action="contradicted")))

    engine._client.publish.assert_not_awaited()
    assert engine.trades_executed == 0
    engine.store.record_ignored.assert_called_once()
    assert engine.store.record_ignored.call_args.args[1] == "NO_ACTIVE_POSITION"


# --- DEGRADED_QUANT_ALERT --------------------------------------------------

@pytest.mark.asyncio
async def test_degraded_quant_alert_takes_no_action(engine):
    await engine._handle_message(_msg(engine.config, _alert_payload(action="degraded_quant_alert")))

    engine.store.get_position.assert_called_once()  # gate check + decide_trade both run
    engine.store.execute_buy.assert_not_called()
    engine.store.execute_sell.assert_not_called()
    engine._client.publish.assert_not_awaited()
    assert engine.trades_executed == 0
    assert engine.trades_ignored == 0
    engine.store.record_ignored.assert_called_once()
    assert engine.store.record_ignored.call_args.args[1] == "DEGRADED_NOT_TRADABLE"


# --- Bad payloads ----------------------------------------------------------

@pytest.mark.asyncio
async def test_unparseable_alert_is_dropped(engine):
    await engine._handle_message({"channel": engine.config.alerts_channel.encode(), "data": "not json"})
    assert engine.alerts_processed == 0


@pytest.mark.asyncio
async def test_invalid_alert_payload_is_dropped(engine):
    await engine._handle_message(_msg(engine.config, {"ticker": "NVDA"}))  # missing required fields
    assert engine.alerts_processed == 0


# --- Simulated spread (friction) ---------------------------------------------

@pytest.mark.asyncio
async def test_buy_fill_price_crosses_the_spread():
    store = MagicMock()
    store.get_position.return_value = None
    store.get_portfolio_summary.return_value = {"current_cash": 10000.0, "trade_allocation_usd": 2500.0}
    store.execute_buy.return_value = _execution(OrderType.BUY)
    watchlist_store = MagicMock()
    watchlist_store.list_paper_trading_symbols.return_value = ["NVDA"]
    engine = PaperTradingEngine(
        config=PaperConfig(simulated_spread_bps=10.0), store=store, watchlist_store=watchlist_store,
    )
    engine._client = AsyncMock()

    await engine._handle_message(_msg(engine.config, _alert_payload(action="confirmed_bullish", price=100.0)))

    _, _, fill_price, _, _ = store.execute_buy.call_args.args
    assert round(fill_price, 4) == 100.05  # +half of 10bps


@pytest.mark.asyncio
async def test_sell_fill_price_crosses_the_spread():
    store = MagicMock()
    store.get_position.return_value = {"ticker": "NVDA", "shares": 10.0, "entry_price": 100.0, "cost_basis": 1000.0}
    store.execute_sell.return_value = _execution(OrderType.SELL)
    watchlist_store = MagicMock()
    watchlist_store.list_paper_trading_symbols.return_value = ["NVDA"]
    engine = PaperTradingEngine(
        config=PaperConfig(simulated_spread_bps=10.0), store=store, watchlist_store=watchlist_store,
    )
    engine._client = AsyncMock()

    await engine._handle_message(_msg(engine.config, _alert_payload(action="contradicted", price=100.0)))

    _, fill_price, _, _ = store.execute_sell.call_args.args
    assert round(fill_price, 4) == 99.95  # -half of 10bps


# --- Stop-loss / take-profit (price-driven exit) ----------------------------

def _sl_tp_engine(entry_price: float = 100.0) -> PaperTradingEngine:
    store = MagicMock()
    store.get_position.return_value = {
        "ticker": "NVDA", "shares": 10.0, "entry_price": entry_price, "cost_basis": entry_price * 10.0,
    }
    store.execute_sell.return_value = _execution(OrderType.SELL)
    watchlist_store = MagicMock()
    engine = PaperTradingEngine(
        config=PaperConfig(simulated_spread_bps=0.0, stop_loss_pct=0.005, take_profit_pct=0.01),
        store=store, watchlist_store=watchlist_store,
    )
    engine._client = AsyncMock()
    return engine


@pytest.mark.asyncio
async def test_market_tick_past_stop_loss_closes_the_position():
    engine = _sl_tp_engine(entry_price=100.0)

    await engine._handle_message(
        {"channel": engine.config.market_channel.encode(), "data": json.dumps(_bar_payload(close=99.40))}
    )

    engine.store.execute_sell.assert_called_once()
    ticker, price, ts, triggering_action = engine.store.execute_sell.call_args.args
    assert ticker == "NVDA"
    assert price == 99.40
    assert triggering_action == AlertAction.STOP_LOSS_EXIT
    engine._client.publish.assert_awaited_once()
    assert engine.trades_executed == 1


@pytest.mark.asyncio
async def test_market_tick_past_take_profit_closes_the_position():
    engine = _sl_tp_engine(entry_price=100.0)

    await engine._handle_message(
        {"channel": engine.config.market_channel.encode(), "data": json.dumps(_bar_payload(close=101.10))}
    )

    engine.store.execute_sell.assert_called_once()
    triggering_action = engine.store.execute_sell.call_args.args[3]
    assert triggering_action == AlertAction.TAKE_PROFIT_EXIT


@pytest.mark.asyncio
async def test_market_tick_inside_the_band_does_not_close_the_position():
    engine = _sl_tp_engine(entry_price=100.0)

    await engine._handle_message(
        {"channel": engine.config.market_channel.encode(), "data": json.dumps(_bar_payload(close=100.20))}
    )

    engine.store.execute_sell.assert_not_called()
    engine._client.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_market_tick_with_no_open_position_never_checks_stop_take(engine):
    # fixture's store.get_position already returns None (flat)
    await engine._handle_message(
        _msg(engine.config, _bar_payload(close=99.40), channel=engine.config.market_channel)
    )
    engine.store.execute_sell.assert_not_called()


# --- Entry conviction gate (min_entry_severity) ------------------------------

@pytest.mark.asyncio
async def test_confirmed_bullish_below_min_severity_is_ignored_and_never_reaches_decide_trade(engine):
    engine._min_entry_severity = AlertSeverity.CRITICAL

    await engine._handle_message(
        _msg(engine.config, _alert_payload(action="confirmed_bullish", severity="warning"))
    )

    engine.store.get_position.assert_not_called()
    engine.store.execute_buy.assert_not_called()
    engine.store.record_ignored.assert_called_once()
    assert engine.store.record_ignored.call_args.args[1] == "BELOW_MIN_SEVERITY"


@pytest.mark.asyncio
async def test_confirmed_bullish_at_min_severity_proceeds_normally(engine):
    engine.store.get_portfolio_summary.return_value = {"current_cash": 10000.0, "trade_allocation_usd": 2500.0}
    engine.store.execute_buy.return_value = _execution(OrderType.BUY)

    await engine._handle_message(
        _msg(engine.config, _alert_payload(action="confirmed_bullish", severity="warning"))
    )

    engine.store.execute_buy.assert_called_once()


@pytest.mark.asyncio
async def test_sell_actions_are_never_severity_gated(engine):
    engine._min_entry_severity = AlertSeverity.CRITICAL
    engine.store.get_position.return_value = {"ticker": "NVDA", "shares": 10.0, "entry_price": 100.0, "cost_basis": 1000.0}
    engine.store.execute_sell.return_value = _execution(OrderType.SELL)

    await engine._handle_message(
        _msg(engine.config, _alert_payload(action="contradicted", severity="info"))
    )

    engine.store.execute_sell.assert_called_once()
