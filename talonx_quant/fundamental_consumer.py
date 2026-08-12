"""
talonx_quant.fundamental_consumer
------------------------------------------
Phase 2's LONG_TERM factor-scoring pipeline -- a SIBLING to QuantScanner
(consumer.py), not a second loop inside it. The two pipelines have
genuinely different noise-filter semantics (a 20-minute intraday
cooldown makes no sense applied to a quarterly-cadence signal, and
batch-throttling a handful of quarterly signals would be pointless
complexity), so keeping them as separate classes with separate state --
each with its own reconnect loop, its own cooldown key namespace, its
own counters -- avoids the kind of "one class secretly serving two
different cadences" complexity that would otherwise creep in.

Subscribes to TWO channels on one connection (same dual-subscribe-
single-class pattern talonx_brain.consumer.ResearchAgent already uses
for signals_channel + filings_channel):
  - talonx:fundamentals:events (NewFundamentalsIngestedEvent) -- the
    actual trigger: scores the ticker's latest fiscal year against the
    prior one and, if ROIC/F-Score clear their thresholds, publishes a
    FundamentalFactorSignal.
  - talonx:market:stream (MarketTickEvent) -- price-tracking ONLY, no
    indicator computation (this scanner never touches RSI/MACD/SMA) --
    just keeps a last-known price per ticker in memory, since FCF Yield
    and the Altman Z-Score both need a current market price and this
    module has no other source for one.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timezone

from pydantic import ValidationError

from talonx_quant.config import QuantConfig
from talonx_quant.fundamentals import (
    compute_altman_z_score,
    compute_debt_to_ebitda_proxy,
    compute_fcf_yield,
    compute_piotroski_f_score,
    compute_roic,
)
from talonx_quant.schemas import FundamentalFactorSignal, MarketTickEvent, NewFundamentalsIngestedEvent, TickEventType
from talonx_quant.store import QuantStateStore

from talonx_ingest.common.structured_logging import log_structured

logger = logging.getLogger("talonx_quant.fundamental_consumer")

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None


def _jittered_backoff(attempt: int, base: float, max_delay: float) -> float:
    raw = base * (2 ** (attempt - 1))
    capped = min(raw, max_delay)
    return capped * (0.5 + random.random())


class FundamentalScanner:
    def __init__(self, config: QuantConfig | None = None, store: QuantStateStore | None = None):
        self.config = config or QuantConfig()
        self.store = store
        self._client = None
        self._stop_event = asyncio.Event()
        self._events_processed = 0
        self._signals_published = 0
        self._signals_suppressed_cooldown = 0
        # Last known market price per ticker, fed by market:stream BAR
        # events -- this scanner's only source of a current price.
        self._latest_prices: dict[str, float] = {}

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def events_processed(self) -> int:
        return self._events_processed

    @property
    def signals_published(self) -> int:
        return self._signals_published

    @property
    def signals_suppressed_cooldown(self) -> int:
        return self._signals_suppressed_cooldown

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
        await pubsub.subscribe(self.config.fundamentals_events_channel, self.config.market_stream_channel)
        logger.info(
            "Subscribed to %s and %s",
            self.config.fundamentals_events_channel, self.config.market_stream_channel,
        )

        try:
            while not self._stop_event.is_set():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message is None:
                    continue
                await self._handle_message(message)
        finally:
            await pubsub.unsubscribe(self.config.fundamentals_events_channel, self.config.market_stream_channel)
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

        if channel == self.config.market_stream_channel:
            await self._handle_market_tick(payload)
        elif channel == self.config.fundamentals_events_channel:
            await self._handle_fundamentals_event(payload)
        else:
            logger.warning("Dropping message on unexpected channel %s", channel)

    async def _handle_market_tick(self, payload: dict) -> None:
        try:
            event = MarketTickEvent.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping invalid market tick: %s", exc)
            return
        if event.event_type != TickEventType.BAR or event.close is None:
            return  # only BAR events carry a close price, same filter QuantScanner uses
        self._latest_prices[event.symbol.upper()] = event.close

    async def _handle_fundamentals_event(self, payload: dict) -> None:
        try:
            event = NewFundamentalsIngestedEvent.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping invalid fundamentals event: %s", exc)
            return

        self._events_processed += 1
        if not event.facts:
            return

        ticker = event.ticker.upper()
        if await self._is_on_cooldown(ticker):
            self._signals_suppressed_cooldown += 1
            logger.info("Suppressed fundamental signal for %s -- still in cooldown", ticker)
            if self.store is not None:
                self.store.record_suppressed(ticker, "FUNDAMENTAL_COOLDOWN", 1, datetime.now(timezone.utc))
            return

        current = event.facts[0]  # most recent fiscal year first
        prior = event.facts[1] if len(event.facts) > 1 else current
        price = self._latest_prices.get(ticker, 0.0)

        roic = compute_roic(current)
        f_score = compute_piotroski_f_score(current, prior)
        fcf_yield = compute_fcf_yield(current, price)
        altman_z = compute_altman_z_score(current, price)
        debt_to_ebitda = compute_debt_to_ebitda_proxy(current)

        log_structured(
            logger, "FACTOR_CALCULATED", ticker=ticker,
            fiscal_year=current.fiscal_year, roic=roic, piotroski_f_score=f_score,
            fcf_yield=fcf_yield, altman_z_score=altman_z, debt_to_ebitda_proxy=debt_to_ebitda,
            price=price,
        )

        passes = roic is not None and roic >= self.config.roic_threshold and f_score >= self.config.f_score_threshold
        if not passes:
            logger.info(
                "%s FY%d does not clear fundamental thresholds (ROIC=%s, F-Score=%s)",
                ticker, current.fiscal_year, roic, f_score,
            )
            return

        await self._start_cooldown(ticker)
        signal = FundamentalFactorSignal(
            ticker=ticker,
            fiscal_year=current.fiscal_year,
            roic=roic,
            piotroski_f_score=f_score,
            fcf_yield=fcf_yield,
            altman_z_score=altman_z,
            debt_to_ebitda_proxy=debt_to_ebitda,
            price=price,
            message=(
                f"ROIC {roic:.1%} (>= {self.config.roic_threshold:.0%}), "
                f"F-Score {f_score}/9 (>= {self.config.f_score_threshold})"
            ),
        )
        await self._publish_signal(signal)

    async def _is_on_cooldown(self, ticker: str) -> bool:
        try:
            return bool(await self._client.exists(f"fundamental_cooldown:{ticker}"))
        except Exception as exc:  # noqa: BLE001 -- a Redis hiccup shouldn't block scoring
            logger.warning("Cooldown check failed for %s (%s); treating as not on cooldown", ticker, exc)
            return False

    async def _start_cooldown(self, ticker: str) -> None:
        try:
            await self._client.set(
                f"fundamental_cooldown:{ticker}", "1", ex=int(self.config.fundamental_cooldown_seconds)
            )
        except Exception as exc:  # noqa: BLE001 -- a failed lock shouldn't drop the signal
            logger.warning("Failed to set fundamental cooldown for %s (%s)", ticker, exc)

    async def _publish_signal(self, signal: FundamentalFactorSignal) -> None:
        try:
            await self._client.publish(self.config.fundamental_signals_channel, signal.to_redis_payload())
            self._signals_published += 1
            logger.info("Fundamental signal: %s -- %s", signal.ticker, signal.message)
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the scanner
            logger.warning("Failed to publish fundamental signal to Redis: %s", exc)
