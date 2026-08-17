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

from talonx_ingest.common.structured_logging import log_structured

from talonx_paper.config import PaperConfig
from talonx_paper.engine import (
    DecisionKind,
    LongTermDecisionKind,
    LongTermTradeDecision,
    TradeDecision,
    apply_spread,
    calculate_buy,
    check_stop_take,
    decide_long_term_trade,
    decide_trade,
    seconds_until_next_eod_flatten,
)
from talonx_paper.schemas import (
    ActionableAlert,
    AlertAction,
    AlertSeverity,
    LongTermActionableAlert,
    LongTermTradeExecution,
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
            await asyncio.gather(self._poll_messages(pubsub), self._eod_flatten_loop())
        finally:
            await pubsub.unsubscribe(self.config.alerts_channel, self.config.market_channel)
            await pubsub.aclose()
            await self._client.aclose()

    async def _poll_messages(self, pubsub) -> None:
        while not self._stop_event.is_set():
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                continue  # normal: no message within this poll window
            await self._handle_message(message)

    async def _eod_flatten_loop(self) -> None:
        """Daily sweep (config.eod_flatten_hour_et:eod_flatten_minute_et,
        default 15:50 ET) that liquidates every still-open INTRADAY
        position -- same while-not-stopped/wait_for(stop.wait(), timeout=…)
        shape as LongTermPaperEngine._dca_loop, but computed from a fixed
        daily wall-clock target (engine.seconds_until_next_eod_flatten)
        rather than a persisted last-run timestamp: unlike the DCA loop's
        ~30-day interval, a single missed day here just means tomorrow's
        cycle runs on schedule -- there's no multi-week drift to protect
        against by persisting state across a restart. Returns immediately
        (a no-op sibling task under asyncio.gather) if disabled via
        config.eod_flatten_enabled."""
        if not self.config.eod_flatten_enabled:
            return
        while not self._stop_event.is_set():
            wait_seconds = seconds_until_next_eod_flatten(
                datetime.now(timezone.utc), self.config.eod_flatten_hour_et, self.config.eod_flatten_minute_et,
            )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass  # normal: target time reached, run the flatten sweep
            else:
                return  # stop() was called during the wait
            if not self._stop_event.is_set():
                try:
                    await self._run_eod_flatten_once()
                except Exception as exc:  # noqa: BLE001 -- one bad cycle shouldn't kill the loop
                    logger.error("EOD flatten cycle failed: %s", exc)

    async def _run_eod_flatten_once(self) -> None:
        """Closes every open position in the INTRADAY `positions` table
        only -- store.get_open_positions() never touches
        long_term_positions (a separate table/ledger entirely), so the
        LONG_TERM DCA-aware path is structurally unreachable from here,
        not just untouched by convention."""
        positions = self.store.get_open_positions()
        if not positions:
            return
        latest_prices = self.store.get_latest_prices()
        now = datetime.now(timezone.utc)
        for position in positions:
            ticker = position["ticker"]
            price = latest_prices.get(ticker)
            if price is None or price <= 0:
                logger.warning("Skipping EOD flatten for %s -- no known current price", ticker)
                continue
            fill_price = apply_spread(price, self.config.simulated_spread_bps, "SELL")
            await self._close_position(ticker, fill_price, now, AlertAction.EOD_FLAT_LIQUIDATION)

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
            stop_price=position.get("stop_price"), target_price=position.get("target_price"),
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
            logger.info("PAPER_TRADING_DISABLED_FOR_TICKER: %s -- skipping alert", alert.ticker.upper())
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
        execution = self.store.execute_buy(
            alert.ticker, shares, fill_price, cost, alert.correlated_at,
            stop_price=alert.triggering_signal.stop_price, target_price=alert.triggering_signal.target_price,
        )
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


class LongTermPaperEngine:
    """
    Phase 2's DCA-aware virtual broker -- a SEPARATE class from
    PaperTradingEngine above, not a second code path folded into it: the
    two ledgers have genuinely different position lifecycles (single-lot
    entry/exit vs. an accumulated-cost-basis position that grows via
    recurring DCA contributions and can be partially trimmed), so keeping
    them separate avoids the kind of "one class secretly serving two
    different trade models" complexity that would otherwise creep in --
    same reasoning talonx_quant.fundamental_consumer.FundamentalScanner
    documents for staying a sibling of QuantScanner rather than a second
    loop inside it.

    Subscribes to talonx:alerts:longterm (trade decisions) and
    talonx:market:stream (mark-to-market pricing, SAME shared
    latest_prices cache in the store PaperTradingEngine also writes to --
    a price is a price regardless of horizon). A SECOND, independent
    async task runs the monthly DCA contribution loop -- same
    while-not-stopped/wait_for(stop.wait(), timeout=interval) shape as
    run_talonx.py's periodic_ingestion_loop / talonx_dispatch.consumer's
    retention sweep -- contributing config.dca_contribution_usd into
    EVERY currently-open long-term position each cycle, using whatever
    price update_latest_price last saw for that ticker.

    Gated by its OWN watchlist flag -- paper_trading_enabled_long_term,
    checked via list_paper_trading_long_term_symbols() -- independent of
    the paper_trading_enabled flag PaperTradingEngine checks. A
    DUAL_HORIZON ticker can therefore have one engine paper-trading it
    and not the other (e.g. long-term conviction without wanting the
    intraday noise, or vice versa). Both flags are themselves orthogonal
    to which horizon(s) a ticker is even eligible to receive alerts for
    in the first place -- that's talonx_watchlist's separate
    strategy_horizon field, checked far upstream by every module that
    routes on it.
    """

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
            self.config.default_long_term_initial_balance,
            self.config.dca_contribution_usd,
        )
        self.watchlist_store = watchlist_store or TickerWatchlistStore(WatchlistConfig().db_path)
        self._client = None
        self._stop_event = asyncio.Event()
        self._alerts_processed = 0
        self._trades_executed = 0
        self._trades_ignored = 0
        self._dca_contributions_made = 0

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

    @property
    def dca_contributions_made(self) -> int:
        return self._dca_contributions_made

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
        await pubsub.subscribe(self.config.alerts_channel_long_term, self.config.market_channel)
        logger.info(
            "Subscribed to %s and %s", self.config.alerts_channel_long_term, self.config.market_channel,
        )

        try:
            await asyncio.gather(self._poll_messages(pubsub), self._dca_loop())
        finally:
            await pubsub.unsubscribe(self.config.alerts_channel_long_term, self.config.market_channel)
            await pubsub.aclose()
            await self._client.aclose()

    async def _poll_messages(self, pubsub) -> None:
        while not self._stop_event.is_set():
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                continue  # normal: no message within this poll window
            await self._handle_message(message)

    async def _dca_loop(self) -> None:
        """Monthly (dca_interval_days) recurring contribution into every
        currently-open long-term position -- fires once immediately isn't
        the pattern here (unlike periodic_ingestion_loop's startup
        catch-up), since a freshly-opened position shouldn't get an
        immediate DCA top-up the same session it was bought.

        The wait is computed from store.get_last_dca_at() (a PERSISTED
        timestamp), not a fixed interval_seconds constant -- a plain
        `asyncio.wait_for(timeout=dca_interval_days*86400)` resets to
        zero on every restart, and since that interval (30 days default)
        vastly exceeds this project's typical scheduled daily uptime
        window (register_scheduled_tasks.ps1's default 10:00-22:00,
        ~12h), the timer could never complete at all -- confirmed live,
        zero DCA_CONTRIBUTION rows had EVER been recorded under the old
        design. Recomputing the wait from a persisted last-cycle
        timestamp each loop iteration means a restart mid-interval
        resumes with the correct REMAINING wait, and an interval that's
        already elapsed while the app was down fires on the very next
        tick (asyncio.wait_for(timeout=0) resolves virtually
        immediately) rather than silently losing the cycle."""
        while not self._stop_event.is_set():
            wait_seconds = self._seconds_until_next_dca()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass  # normal: interval elapsed, run a DCA cycle
            else:
                return  # stop() was called during the wait
            if not self._stop_event.is_set():
                try:
                    await self._run_dca_cycle_once()
                except Exception as exc:  # noqa: BLE001 -- one bad cycle shouldn't kill the loop
                    logger.error("DCA cycle failed: %s", exc)

    def _seconds_until_next_dca(self) -> float:
        interval_seconds = self.config.dca_interval_days * 86400.0
        last_dca_at = self.store.get_last_dca_at()
        if last_dca_at is None:
            return interval_seconds  # first-ever cycle -- wait the full interval, same original intent
        elapsed = (datetime.now(timezone.utc) - last_dca_at).total_seconds()
        return max(0.0, interval_seconds - elapsed)

    async def _run_dca_cycle_once(self) -> None:
        # Recorded FIRST, before any per-position work -- the "cycle"
        # itself is the schedulable unit (see _seconds_until_next_dca),
        # not per-ticker success/failure, so the clock resets even when
        # there are no open positions yet or every contribution this
        # cycle gets skipped (insufficient cash/no price).
        self.store.set_last_dca_at(datetime.now(timezone.utc))
        positions = self.store.get_open_long_term_positions()
        if not positions:
            return
        latest_prices = self.store.get_latest_prices()
        summary = self.store.get_long_term_portfolio_summary()
        contribution_usd = summary["dca_contribution_usd"]
        now = datetime.now(timezone.utc)

        for position in positions:
            ticker = position["ticker"]
            price = latest_prices.get(ticker)
            if price is None or price <= 0:
                logger.warning("Skipping DCA contribution for %s -- no known current price", ticker)
                continue
            if contribution_usd > summary["current_cash"]:
                logger.warning(
                    "Skipping DCA contribution for %s -- insufficient cash ($%.2f available)",
                    ticker, summary["current_cash"],
                )
                continue
            execution = self.store.execute_dca_contribution(ticker, contribution_usd, price, now)
            if execution is None:
                continue  # position closed between the listing above and this write -- skip
            self._dca_contributions_made += 1
            summary = self.store.get_long_term_portfolio_summary()  # refresh cash for the next ticker this cycle
            logger.info(
                "DCA contribution: %s $%.2f @ $%.2f (avg cost now $%.2f)",
                ticker, contribution_usd, price, execution.avg_cost_basis_after,
            )
            log_structured(
                logger, "TRADE_EXECUTED", ticker=ticker, order_type="DCA_CONTRIBUTION",
                contribution_usd=contribution_usd, price=price,
                avg_cost_basis_after=execution.avg_cost_basis_after,
            )
            await self._publish_execution(execution)

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
        elif channel == self.config.alerts_channel_long_term:
            await self._handle_alert(payload)
        else:
            logger.warning("Dropping message on unexpected channel %s", channel)

    async def _handle_market_tick(self, payload: dict) -> None:
        """Price-tracking ONLY -- writes to the SAME latest_prices table
        PaperTradingEngine does (shared cache), feeds both the DCA loop's
        pricing and any dashboard mark-to-market view. No stop-loss/
        take-profit here -- Phase 2's long-term horizon has no
        price-driven exit, only the alert-driven matrix."""
        try:
            event = MarketTickEvent.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping invalid market tick: %s", exc)
            return
        if event.event_type != TickEventType.BAR or event.close is None:
            return
        self.store.update_latest_price(event.symbol, event.close, datetime.now(timezone.utc))

    async def _handle_alert(self, payload: dict) -> None:
        try:
            alert = LongTermActionableAlert.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping invalid long-term alert: %s", exc)
            return

        self._alerts_processed += 1

        if alert.ticker.upper() not in self.watchlist_store.list_paper_trading_long_term_symbols():
            logger.info("PAPER_TRADING_DISABLED_FOR_TICKER: %s -- skipping long-term alert", alert.ticker.upper())
            return  # long-term paper trading not enabled for this ticker -- silent skip, not an "ignored" event

        position = self.store.get_long_term_position(alert.ticker)
        decision = decide_long_term_trade(alert, position, self.config.rebalance_trim_pct)
        if decision is None:
            return  # HOLD_QUALITY -- informational, no trading action at all

        if decision.kind == LongTermDecisionKind.IGNORED:
            self._trades_ignored += 1
            logger.info("Long-term paper trade ignored for %s: %s", alert.ticker, decision.reason)
            self.store.record_ignored(
                alert.ticker, decision.reason, alert.action, decision.price, alert.correlated_at,
                horizon="long_term",
            )
            return

        if decision.kind == LongTermDecisionKind.BUY:
            await self._execute_buy(alert, decision)
        else:
            await self._execute_sell(alert, decision)

    async def _execute_buy(self, alert: LongTermActionableAlert, decision: LongTermTradeDecision) -> None:
        fill_price = apply_spread(decision.price, self.config.simulated_spread_bps, "BUY")
        summary = self.store.get_long_term_portfolio_summary()
        # The opening position's fixed-dollar size -- reuses
        # calculate_buy's identical "spend min(allocation, cash)" math
        # against the long-term cash pool, same as the intraday module's
        # fixed trade_allocation_usd. Separate from dca_contribution_usd,
        # which only ever tops up an ALREADY-open position afterward.
        sized = calculate_buy(summary["current_cash"], self.config.long_term_initial_position_usd, fill_price)
        if sized is None:
            self._trades_ignored += 1
            logger.warning(
                "Long-term paper trade ignored for %s: INSUFFICIENT_CASH (cash=$%.2f)",
                alert.ticker, summary["current_cash"],
            )
            self.store.record_ignored(
                alert.ticker, "INSUFFICIENT_CASH", alert.action, fill_price, alert.correlated_at,
                horizon="long_term",
            )
            return

        shares, cost = sized
        execution = self.store.execute_long_term_buy(alert.ticker, shares, fill_price, cost, alert.correlated_at)
        self._trades_executed += 1
        logger.info(
            "Long-term BUY: %s %.4f shares @ $%.2f (cost $%.2f, cash after $%.2f)",
            alert.ticker, shares, fill_price, cost, execution.portfolio_cash_after,
        )
        log_structured(
            logger, "TRADE_EXECUTED", ticker=alert.ticker, order_type="BUY",
            shares=shares, price=fill_price, cost=cost, cash_after=execution.portfolio_cash_after,
        )
        await self._publish_execution(execution)

    async def _execute_sell(self, alert: LongTermActionableAlert, decision: LongTermTradeDecision) -> None:
        fill_price = apply_spread(decision.price, self.config.simulated_spread_bps, "SELL")
        trim_fraction = decision.trim_fraction if decision.kind == LongTermDecisionKind.SELL_PARTIAL else 1.0
        execution = self.store.execute_long_term_sell(
            alert.ticker, trim_fraction, fill_price, alert.correlated_at, alert.action,
        )
        if execution is None:
            logger.warning(
                "Long-term SELL skipped for %s -- no open position found at execution time", alert.ticker,
            )
            self.store.record_ignored(
                alert.ticker, "NO_ACTIVE_POSITION", alert.action, fill_price, alert.correlated_at,
                horizon="long_term",
            )
            return

        self._trades_executed += 1
        logger.info(
            "Long-term SELL: %s %.4f shares @ $%.2f (%s, PnL $%.2f / %.2f%%, cash after $%.2f)",
            alert.ticker, execution.shares, fill_price, alert.action.value,
            execution.realized_pnl_usd, execution.realized_pnl_pct, execution.portfolio_cash_after,
        )
        log_structured(
            logger, "TRADE_EXECUTED", ticker=alert.ticker, order_type="SELL",
            triggering_action=alert.action.value, shares=execution.shares, price=fill_price,
            realized_pnl_usd=execution.realized_pnl_usd, realized_pnl_pct=execution.realized_pnl_pct,
            cash_after=execution.portfolio_cash_after,
        )
        await self._publish_execution(execution)

    async def _publish_execution(self, execution: LongTermTradeExecution) -> None:
        try:
            await self._client.publish(self.config.paper_trades_channel_long_term, execution.to_redis_payload())
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the engine
            logger.warning("Failed to publish long-term paper trade execution to Redis: %s", exc)
