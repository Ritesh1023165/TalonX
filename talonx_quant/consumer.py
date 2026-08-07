"""
talonx_quant.consumer
-------------------------
Async Redis Pub/Sub consumer: subscribes to talonx:market:stream, feeds
BAR events into the per-symbol rolling buffer, computes indicators, and
publishes any triggered QuantSignals to talonx:signals:quant.

Reconnects with backoff on connection loss -- a long-running listener
process should recover from a Redis restart/network blip on its own
rather than requiring a manual restart.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random

from pydantic import ValidationError

from talonx_quant.buffer import RollingBarBuffer
from talonx_quant.config import QuantConfig
from talonx_quant.indicators import compute_indicators
from talonx_quant.schemas import MarketTickEvent, QuantSignal, TickEventType
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
    def __init__(self, config: QuantConfig | None = None):
        self.config = config or QuantConfig()
        self.buffer = RollingBarBuffer(self.config.max_bars_per_symbol)
        self._client = None
        self._stop_event = asyncio.Event()
        self._signals_published = 0
        self._bars_processed = 0

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def signals_published(self) -> int:
        return self._signals_published

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
        await pubsub.subscribe(self.config.market_stream_channel)
        logger.info("Subscribed to %s", self.config.market_stream_channel)

        try:
            while not self._stop_event.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    continue  # normal: no message within this poll window
                await self._handle_message(message)
        finally:
            await pubsub.unsubscribe(self.config.market_stream_channel)
            await pubsub.aclose()
            await self._client.aclose()

    async def _handle_message(self, message: dict) -> None:
        raw = message.get("data")
        if raw is None:
            return

        try:
            payload = json.loads(raw)
            event = MarketTickEvent.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Dropping unparseable message on market stream: %s", exc)
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
        for signal in signals:
            await self._publish_signal(signal)

    async def _publish_signal(self, signal: QuantSignal) -> None:
        try:
            await self._client.publish(self.config.signals_channel, signal.to_redis_payload())
            self._signals_published += 1
            logger.info("Signal: %s %s -- %s", signal.ticker, signal.signal_type.value, signal.message)
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the scanner
            logger.warning("Failed to publish signal to Redis: %s", exc)
