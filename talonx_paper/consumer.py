"""
talonx_paper.consumer
--------------------------
Async Redis Pub/Sub consumer -- the virtual broker. Subscribes to BOTH
talonx:alerts:dispatch (trade decisions) and talonx:market:stream (live
mark-to-market pricing), same two-channel subscribe+branch pattern
talonx_core.consumer established.

Only tickers with paper trading enabled are ever traded --
talonx_watchlist's per-ticker flag (see its store.py) is the "configure
which ticker can be used" control surface, checked before any decision
logic runs. engine.decide_trade() (pure) decides BUY/SELL/ignored; a
BUY/SELL executes via PaperTradingStore (which handles the atomic
multi-table write) and publishes the resulting PaperTradeExecution to
talonx:paper:trades for talonx_dispatch to notify on. An "ignored"
decision (duplicate signal while already in that state, or insufficient
cash) is logged AND persisted via store.record_ignored -- there's
nothing for a downstream Redis consumer to act on, so nothing is
published for it, but the reason is kept durably so an EOD report can
explain "why didn't this ticker trade today" without re-deriving it from
logs (see talonx_paper/store.py's ignored_decisions table).

Every fill (BUY or SELL, whatever triggered it) crosses a simulated
bid-ask spread (engine.apply_spread, config.simulated_spread_bps) so
paper PnL isn't unrealistically clean. Every market tick for a ticker
with an open position is also checked against a stop-loss/take-profit
band (engine.check_stop_take) -- an independent, price-driven exit that
runs ALONGSIDE the alert-driven SELL trigger in decide_trade(), not
instead of it: a genuine CONFIRMED_BEARISH/CONTRADICTED reversal alert
still closes a position immediately regardless of where price sits
relative to stop/take. A CONFIRMED_BULLISH alert below
config.min_entry_severity never opens a position at all (recorded as
BELOW_MIN_SEVERITY) -- exits are never severity-gated.

Reconnects with backoff on Redis connection loss, same pattern as every
other consumer in this project.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timezone

from pydantic import ValidationError

from talonx_paper.config import PaperConfig
from talonx_paper.engine import DecisionKind, TradeDecision, apply_spread, calculate_buy, check_stop_take, decide_trade
from talonx_paper.schemas import (
    ActionableAlert,
    AlertAction,
    AlertSeverity,
    MarketTickEvent,
    PaperTradeExecution,
    TickEventType,
)
from talonx_paper.store import PaperTradingStore
from talonx_watchlist.config import WatchlistConfig
from talonx_watchlist.store import TickerWatchlistStore

logger = logging.getLogger("talonx_paper.consumer")

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None


def _jittered_backoff(attempt: int, base: float, max_delay: float) -> float:
    raw = base * (2 ** (attempt - 1))
    capped = min(raw, max_delay)
    return capped * (0.5 + random.random())


class PaperTradingEngine:
    def __init__(
        self,
        config: PaperConfig | None = None,
        store: PaperTradingStore | None = None,
        watchlist_store: TickerWatchlistStore | None = None,
    ):
        self.config = config or PaperConfig()
        self.store = store or PaperTradingStore(
            self.config.db_path,
            self.config.default_initial_balance,
            self.config.default_trade_allocation_usd,
        )
        self.watchlist_store = watchlist_store or TickerWatchlistStore(WatchlistConfig().db_path)
        self._client = None
        self._stop_event = asyncio.Event()
        self._alerts_processed = 0
        self._trades_executed = 0
        self._trades_ignored = 0

        try:
            self._min_entry_severity = AlertSeverity(self.config.min_entry_severity.lower())
        except ValueError:
            logger.warning(
                "Invalid TALONX_PAPER_MIN_ENTRY_SEVERITY=%r, defaulting to 'warning'",
                self.config.min_entry_severity,
            )
            self._min_entry_severity = AlertSeverity.WARNING

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def alerts_processed(self) -> int:
        return self._alerts_processed

    @property
    def trades_executed(self) -> int:
        return self._trades_executed

    @property
    def trades_ignored(self) -> int:
        return self._trades_ignored

    async def run(self) -> None:
        if redis_asyncio is None:
            raise ImportError(
                "The 'redis' package is required. Install it with: pip install redis"
            )

        attempt = 0
        while not self._stop_event.is_set():
            try:
                await self._connect_and_listen()
                return  # clean stop() was called
            except Exception as exc:  # noqa: BLE001 -- any connection/listen failure retries
                attempt += 1
                wait = _jittered_backoff(
                    attempt, self.config.reconnect_backoff_base_seconds,
                    self.config.reconnect_backoff_max_seconds,
                )
                logger.warning(
                    "Redis connection/listen error (%s); reconnecting in %.1fs (attempt %d)",
                    exc, wait, attempt,
                )
                await asyncio.sleep(wait)

    async def _connect_and_listen(self) -> None:
        self._client = redis_asyncio.from_url(
            self.config.redis_url,
            socket_connect_timeout=self.config.connect_timeout_seconds,
            socket_timeout=self.config.socket_timeout_seconds,
        )
        await self._client.ping()
        logger.info("Connected to Redis at %s", self.config.redis_url)

        pubsub = self._client.pubsub()
        await pubsub.subscribe(self.config.alerts_channel, self.config.market_channel)
        logger.info(
            "Subscribed to %s and %s", self.config.alerts_channel, self.config.market_channel,
        )

        try:
            while not self._stop_event.is_set():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    continue  # normal: no message within this poll window
                await self._handle_message(message)
        finally:
            await pubsub.unsubscribe(self.config.alerts_channel, self.config.market_channel)
            await pubsub.aclose()
            await self._client.aclose()

    async def _handle_message(self, message: dict) -> None:
        raw = message.get("data")
        if raw is None:
            return

        channel = message.get("channel")
        if isinstance(channel, bytes):
            channel = channel.decode()

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Dropping unparseable message on %s: %s", channel, exc)
            return

        if channel == self.config.market_channel:
            await self._handle_market_tick(payload)
        elif channel == self.config.alerts_channel:
            await self._handle_alert(payload)
        else:
            logger.warning("Dropping message on unexpected channel %s", channel)

    async def _handle_market_tick(self, payload: dict) -> None:
        try:
            event = MarketTickEvent.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping invalid market tick: %s", exc)
            return
        if event.event_type != TickEventType.BAR or event.close is None:
            return  # only BAR events carry a close price -- same filter talonx_quant.consumer uses

        now = datetime.now(timezone.utc)
        self.store.update_latest_price(event.symbol, event.close, now)

        position = self.store.get_position(event.symbol)
        if position is None:
            return  # flat -- nothing to check a stop/take band against

        trigger = check_stop_take(
            position["entry_price"], event.close, self.config.stop_loss_pct, self.config.take_profit_pct,
        )
        if trigger is None:
            return

        triggering_action = (
            AlertAction.STOP_LOSS_EXIT if trigger == "STOP_LOSS" else AlertAction.TAKE_PROFIT_EXIT
        )
        fill_price = apply_spread(event.close, self.config.simulated_spread_bps, "SELL")
        await self._close_position(event.symbol, fill_price, now, triggering_action)

    async def _handle_alert(self, payload: dict) -> None:
        try:
            alert = ActionableAlert.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping invalid alert: %s", exc)
            return

        self._alerts_processed += 1

        if alert.ticker.upper() not in self.watchlist_store.list_paper_trading_symbols():
            return  # paper trading not enabled for this ticker -- silent skip, not an "ignored" event

        if alert.action == AlertAction.CONFIRMED_BULLISH and alert.severity.rank < self._min_entry_severity.rank:
            # Below the entry conviction bar -- never opens a position.
            # Exits (SELL/stop-loss/take-profit) are never gated by
            # severity, only new entries.
            self.store.record_ignored(
                alert.ticker, "BELOW_MIN_SEVERITY", alert.action,
                alert.triggering_signal.price, alert.correlated_at,
            )
            return

        position = self.store.get_position(alert.ticker)
        decision = decide_trade(alert, position)
        if decision is None:
            # DEGRADED_QUANT_ALERT -- not a trading trigger, but still
            # worth a durable trace so an EOD report can show "N alerts
            # today for this ticker were never tradable at all".
            self.store.record_ignored(
                alert.ticker, "DEGRADED_NOT_TRADABLE", alert.action,
                alert.triggering_signal.price, alert.correlated_at,
            )
            return

        if decision.kind == DecisionKind.IGNORED:
            self._trades_ignored += 1
            logger.info("Paper trade ignored for %s: %s", alert.ticker, decision.reason)
            self.store.record_ignored(
                alert.ticker, decision.reason, alert.action, decision.price, alert.correlated_at,
            )
            return

        if decision.kind == DecisionKind.BUY:
            await self._execute_buy(alert, decision)
        else:
            await self._execute_sell(alert, decision)

    async def _execute_buy(self, alert: ActionableAlert, decision: TradeDecision) -> None:
        fill_price = apply_spread(decision.price, self.config.simulated_spread_bps, "BUY")
        summary = self.store.get_portfolio_summary()
        sized = calculate_buy(summary["current_cash"], summary["trade_allocation_usd"], fill_price)
        if sized is None:
            self._trades_ignored += 1
            logger.warning(
                "Paper trade ignored for %s: INSUFFICIENT_CASH (cash=$%.2f)",
                alert.ticker, summary["current_cash"],
            )
            self.store.record_ignored(
                alert.ticker, "INSUFFICIENT_CASH", alert.action, fill_price, alert.correlated_at,
            )
            return

        shares, cost = sized
        execution = self.store.execute_buy(alert.ticker, shares, fill_price, cost, alert.correlated_at)
        self._trades_executed += 1
        logger.info(
            "Paper BUY: %s %.4f shares @ $%.2f (cost $%.2f, cash after $%.2f)",
            alert.ticker, shares, fill_price, cost, execution.portfolio_cash_after,
        )
        await self._publish_execution(execution)

    async def _execute_sell(self, alert: ActionableAlert, decision: TradeDecision) -> None:
        """Alert-driven exit (CONFIRMED_BEARISH/CONTRADICTED) -- a genuine
        reversal signal, always honored regardless of where price sits
        relative to the stop-loss/take-profit band."""
        fill_price = apply_spread(decision.price, self.config.simulated_spread_bps, "SELL")
        await self._close_position(alert.ticker, fill_price, alert.correlated_at, alert.action)

    async def _close_position(
        self, ticker: str, fill_price: float, timestamp: datetime, triggering_action: AlertAction,
    ) -> None:
        """Shared by the alert-driven SELL path (_execute_sell) and the
        price-driven stop-loss/take-profit path (_handle_market_tick) --
        both end the same way: close the position, record the trade,
        publish the execution."""
        execution = self.store.execute_sell(ticker, fill_price, timestamp, triggering_action)
        if execution is None:
            logger.warning(
                "Paper SELL skipped for %s -- no open position found at execution time", ticker,
            )
            self.store.record_ignored(ticker, "NO_ACTIVE_POSITION", triggering_action, fill_price, timestamp)
            return

        self._trades_executed += 1
        logger.info(
            "Paper SELL: %s @ $%.2f (%s, PnL $%.2f / %.2f%%, cash after $%.2f)",
            ticker, fill_price, triggering_action.value, execution.realized_pnl_usd,
            execution.realized_pnl_pct, execution.portfolio_cash_after,
        )
        await self._publish_execution(execution)

    async def _publish_execution(self, execution: PaperTradeExecution) -> None:
        try:
            await self._client.publish(self.config.paper_trades_channel, execution.to_redis_payload())
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the engine
            logger.warning("Failed to publish paper trade execution to Redis: %s", exc)
