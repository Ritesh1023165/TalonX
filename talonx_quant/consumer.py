"""
talonx_quant.consumer
-------------------------
Async Redis Pub/Sub consumer: subscribes to talonx:market:stream, feeds
BAR events into the per-symbol rolling buffer, computes indicators, and
publishes any triggered QuantSignals to talonx:signals:quant. ALSO
subscribes to talonx:paper:trades (talonx_paper's execution feed) purely
to detect losing trades -- see the Post-Loss Lockout filter below.

Reconnects with backoff on connection loss -- a long-running listener
process should recover from a Redis restart/network blip on its own
rather than requiring a manual restart.

Filters sit between strategy.py's candidate signals and the actual
publish, on top of strategy.py's own edge-triggering/hysteresis/ATR-move
gate (the latter three all live IN strategy.py, upstream of everything
below):

  1. Post-Loss Lockout (Redis `loss_lockout:{TICKER}` key, TTL
     config.loss_lockout_seconds): a live paper-trading review found 3
     consecutive SMCI losses driving 93% of session losses -- the
     standard cooldown (below) reset in 20 minutes regardless of whether
     the closed trade won or lost, letting the engine repeatedly re-enter
     a stock that had just proven it was chopping/declining. This module
     subscribes to talonx_paper's own trade-execution channel and, on a
     SELL closing at a loss, locks that ticker out for LONGER than the
     standard cooldown -- 75 minutes by default. Only ever engages for a
     ticker with paper trading ENABLED (one with it off never publishes
     an execution, so it only ever sees the standard cooldown).
  2. Per-ticker cooldown (Redis `cooldown:{TICKER}` key, TTL
     config.cooldown_seconds): once ANY signal is accepted for a ticker,
     that ticker is locked out of producing further candidates -- of any
     signal_type -- until the cooldown expires. This is what stops e.g.
     an RSI+volume setup and a later, unrelated MACD cross on the same
     ticker from both alerting within a few minutes of each other.
  3. Confluence + risk/reward filters (strategy.py computes both,
     attached to every candidate signal): a candidate below
     config.confluence_score_min or config.min_risk_reward_ratio is
     dropped BEFORE the per-ticker cooldown is started -- a low-
     conviction candidate that never becomes a real signal must not
     still burn the ticker's cooldown slot and block a later, better one.
  4. Batch throttle (tumbling window, config.throttle_window_seconds):
     candidates that pass everything above are buffered, not published
     immediately. Every throttle_window_seconds, the buffer is ranked by
     (confluence_score, volume_surge_ratio) -- confluence first, volume
     surge as the tiebreaker -- and only the top config.throttle_max_signals
     are actually published; the rest are dropped. This means a signal
     can sit for up to throttle_window_seconds before it's published OR
     dropped -- a deliberate latency-for-quality tradeoff, not a bug.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from collections import Counter
from datetime import datetime, timezone

from pydantic import ValidationError

from talonx_quant.buffer import RollingBarBuffer
from talonx_quant.config import QuantConfig
from talonx_quant.indicators import compute_indicators
from talonx_quant.schemas import (
    MarketTickEvent,
    PaperOrderType,
    PaperTradeExecution,
    QuantSignal,
    TickEventType,
)
from talonx_quant.store import QuantStateStore
from talonx_quant.strategy import evaluate_signals

logger = logging.getLogger("talonx_quant.consumer")

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None


def _jittered_backoff(attempt: int, base: float, max_delay: float) -> float:
    raw = base * (2 ** (attempt - 1))
    capped = min(raw, max_delay)
    return capped * (0.5 + random.random())


class QuantScanner:
    def __init__(self, config: QuantConfig | None = None, store: QuantStateStore | None = None):
        self.config = config or QuantConfig()
        self.store = store
        self.buffer = RollingBarBuffer(self.config.max_bars_per_symbol)
        self._client = None
        self._stop_event = asyncio.Event()
        self._signals_published = 0
        self._bars_processed = 0
        self._signals_suppressed_cooldown = 0
        self._signals_suppressed_throttle = 0
        self._signals_suppressed_loss_lockout = 0
        self._signals_suppressed_low_confluence = 0
        self._signals_suppressed_low_risk_reward = 0
        # Candidates that cleared strategy.py's own filters AND the
        # per-ticker cooldown, waiting for the next throttle window flush.
        self._pending_candidates: list[QuantSignal] = []

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def signals_published(self) -> int:
        return self._signals_published

    @property
    def signals_suppressed_cooldown(self) -> int:
        return self._signals_suppressed_cooldown

    @property
    def signals_suppressed_throttle(self) -> int:
        return self._signals_suppressed_throttle

    @property
    def signals_suppressed_loss_lockout(self) -> int:
        return self._signals_suppressed_loss_lockout

    @property
    def signals_suppressed_low_confluence(self) -> int:
        return self._signals_suppressed_low_confluence

    @property
    def signals_suppressed_low_risk_reward(self) -> int:
        return self._signals_suppressed_low_risk_reward

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
        await pubsub.subscribe(self.config.market_stream_channel, self.config.paper_trades_channel)
        logger.info(
            "Subscribed to %s and %s", self.config.market_stream_channel, self.config.paper_trades_channel,
        )

        throttle_task = asyncio.create_task(self._throttle_flush_loop(), name="throttle_flush")

        try:
            while not self._stop_event.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    continue  # normal: no message within this poll window
                await self._handle_message(message)
        finally:
            throttle_task.cancel()
            try:
                await throttle_task
            except asyncio.CancelledError:
                pass
            # Flush whatever's pending rather than silently losing it on
            # every stop/reconnect -- see _flush_throttle_window's own
            # ranking logic; a partial window still gets ranked fairly.
            await self._flush_throttle_window()
            await pubsub.unsubscribe(self.config.market_stream_channel, self.config.paper_trades_channel)
            await pubsub.aclose()
            await self._client.aclose()

    async def _throttle_flush_loop(self) -> None:
        """Ranks and releases self._pending_candidates every throttle_window_seconds."""
        try:
            while True:
                await asyncio.sleep(self.config.throttle_window_seconds)
                await self._flush_throttle_window()
        except asyncio.CancelledError:
            pass

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

        if channel == self.config.paper_trades_channel:
            await self._handle_paper_trade(payload)
        elif channel == self.config.market_stream_channel:
            await self._handle_market_tick(payload)
        else:
            logger.warning("Dropping message on unexpected channel %s", channel)

    async def _handle_paper_trade(self, payload: dict) -> None:
        """Post-Loss Lockout's trigger -- see this module's own docstring.
        Only a closed (SELL) trade carries realized_pnl_usd at all; a BUY
        execution is ignored here entirely."""
        try:
            execution = PaperTradeExecution.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping invalid paper trade execution: %s", exc)
            return

        if execution.order_type != PaperOrderType.SELL:
            return
        if execution.realized_pnl_usd is None or execution.realized_pnl_usd >= 0:
            return  # no loss -- the standard cooldown already covers this ticker

        logger.info(
            "Post-loss lockout: %s closed at a loss ($%.2f) -- locking out for %.0f minutes",
            execution.ticker, execution.realized_pnl_usd, self.config.loss_lockout_seconds / 60.0,
        )
        await self._start_loss_lockout(execution.ticker)

    async def _handle_market_tick(self, payload: dict) -> None:
        try:
            event = MarketTickEvent.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping invalid market tick: %s", exc)
            return

        if event.event_type != TickEventType.BAR:
            return  # only BAR events feed the OHLCV buffer

        self.buffer.add_bar(
            symbol=event.symbol,
            timestamp=event.timestamp,
            open_=event.open,
            high=event.high,
            low=event.low,
            close=event.close,
            volume=event.volume,
        )
        self._bars_processed += 1

        df = self.buffer.get_dataframe(event.symbol)
        if df is None:
            return

        snapshot = compute_indicators(df, self.config)
        if snapshot is None:
            return  # not enough history yet for this symbol

        signals = evaluate_signals(event.symbol, snapshot, self.config)
        if not signals:
            return

        if await self._is_loss_locked_out(event.symbol):
            self._signals_suppressed_loss_lockout += len(signals)
            logger.info(
                "Suppressed %d signal(s) for %s -- in post-loss lockout",
                len(signals), event.symbol,
            )
            if self.store is not None:
                self.store.record_suppressed(
                    event.symbol, "LOSS_LOCKOUT", len(signals), datetime.now(timezone.utc)
                )
            return

        if await self._is_on_cooldown(event.symbol):
            self._signals_suppressed_cooldown += len(signals)
            logger.info(
                "Suppressed %d signal(s) for %s -- still in cooldown",
                len(signals), event.symbol,
            )
            if self.store is not None:
                self.store.record_suppressed(
                    event.symbol, "COOLDOWN", len(signals), datetime.now(timezone.utc)
                )
            return

        # Confluence + risk/reward filters run BEFORE the cooldown lock
        # below is started -- a low-conviction candidate that never
        # becomes a real signal must not still burn the ticker's cooldown
        # slot and block a later, better one.
        qualifying = [s for s in signals if (s.confluence_score or 0) >= self.config.confluence_score_min]
        if not qualifying:
            self._signals_suppressed_low_confluence += len(signals)
            logger.info(
                "Suppressed %d candidate(s) for %s -- confluence score below %d",
                len(signals), event.symbol, self.config.confluence_score_min,
            )
            if self.store is not None:
                self.store.record_suppressed(
                    event.symbol, "LOW_CONFLUENCE", len(signals), datetime.now(timezone.utc)
                )
            return

        survivors = [
            s for s in qualifying
            if s.risk_reward_ratio is not None and s.risk_reward_ratio >= self.config.min_risk_reward_ratio
        ]
        dropped_for_rr = len(qualifying) - len(survivors)
        if dropped_for_rr and self.store is not None:
            self.store.record_suppressed(
                event.symbol, "LOW_RISK_REWARD", dropped_for_rr, datetime.now(timezone.utc)
            )
        self._signals_suppressed_low_risk_reward += dropped_for_rr
        if not survivors:
            logger.info(
                "Suppressed %d candidate(s) for %s -- risk/reward below %.2f:1",
                len(qualifying), event.symbol, self.config.min_risk_reward_ratio,
            )
            return

        # Lock the ticker out NOW, not at publish/flush time -- otherwise a
        # ticker firing twice before the next throttle flush would queue
        # two separate candidate batches into the same window, defeating
        # the point of the cooldown.
        await self._start_cooldown(event.symbol)
        self._pending_candidates.extend(survivors)

    async def _is_on_cooldown(self, ticker: str) -> bool:
        try:
            return bool(await self._client.exists(f"cooldown:{ticker.upper()}"))
        except Exception as exc:  # noqa: BLE001 -- Redis hiccup shouldn't block signal evaluation
            logger.warning("Cooldown check failed for %s (%s); treating as not on cooldown", ticker, exc)
            return False

    async def _start_cooldown(self, ticker: str) -> None:
        try:
            await self._client.set(
                f"cooldown:{ticker.upper()}", "1", ex=int(self.config.cooldown_seconds)
            )
        except Exception as exc:  # noqa: BLE001 -- a failed lock shouldn't drop the candidate
            logger.warning("Failed to set cooldown for %s (%s)", ticker, exc)

    async def _is_loss_locked_out(self, ticker: str) -> bool:
        try:
            return bool(await self._client.exists(f"loss_lockout:{ticker.upper()}"))
        except Exception as exc:  # noqa: BLE001 -- Redis hiccup shouldn't block signal evaluation
            logger.warning("Loss-lockout check failed for %s (%s); treating as not locked out", ticker, exc)
            return False

    async def _start_loss_lockout(self, ticker: str) -> None:
        try:
            await self._client.set(
                f"loss_lockout:{ticker.upper()}", "1", ex=int(self.config.loss_lockout_seconds)
            )
        except Exception as exc:  # noqa: BLE001 -- a failed lock shouldn't crash the handler
            logger.warning("Failed to set loss lockout for %s (%s)", ticker, exc)

    async def _flush_throttle_window(self) -> None:
        if not self._pending_candidates:
            return

        candidates, self._pending_candidates = self._pending_candidates, []
        candidates.sort(key=lambda sig: (sig.confluence_score or 0, sig.volume_surge_ratio or 0.0), reverse=True)

        released, dropped = candidates[: self.config.throttle_max_signals], candidates[self.config.throttle_max_signals :]
        for signal in released:
            await self._publish_signal(signal)

        if dropped:
            self._signals_suppressed_throttle += len(dropped)
            logger.info(
                "Throttle: released %d/%d candidate(s) this window (ranked by confluence "
                "score, then volume surge ratio), dropped %s",
                len(released), len(candidates),
                ", ".join(f"{s.ticker}/{s.signal_type.value}" for s in dropped),
            )
            if self.store is not None:
                now = datetime.now(timezone.utc)
                # dropped can span multiple tickers in one flush -- one
                # counter increment per ticker, not one blanket call.
                for ticker, count in Counter(s.ticker for s in dropped).items():
                    self.store.record_suppressed(ticker, "THROTTLE", count, now)

    async def _publish_signal(self, signal: QuantSignal) -> None:
        try:
            await self._client.publish(self.config.signals_channel, signal.to_redis_payload())
            self._signals_published += 1
            logger.info("Signal: %s %s -- %s", signal.ticker, signal.signal_type.value, signal.message)
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the scanner
            logger.warning("Failed to publish signal to Redis: %s", exc)
