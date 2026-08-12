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


def _fetch_last_close(ticker: str) -> float | None:
    """Blocking call, run off the event loop via asyncio.to_thread -- same
    yf.Tickers().fast_info.last_price pattern talonx_ingest.market_data.
    yfinance_poll.py already uses for its own live-price fallback. Only
    reached when a fundamentals event arrives before this scanner has
    seen ANY market:stream tick for the ticker yet (e.g. right after a
    fresh startup, or a LONG_TERM-only ticker whose slow daily-close
    poller hasn't run its first cycle) -- see _get_price_with_fallback."""
    import yfinance as yf  # imported lazily so this stays optional

    info = yf.Tickers(ticker.upper()).tickers.get(ticker.upper())
    if info is None:
        return None
    last_price = getattr(info.fast_info, "last_price", None)
    return float(last_price) if last_price is not None else None


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

    async def _get_price_with_fallback(self, ticker: str) -> float:
        """Only called right before publishing a signal (see
        _handle_fundamentals_event) -- NOT on every fundamentals event --
        since the fallback below is a real network call, not worth paying
        for a ticker whose ROIC/F-Score won't clear the threshold anyway.

        A fundamentals event can arrive before this scanner has seen ANY
        market:stream tick for the ticker (a fresh startup, or a
        LONG_TERM-only ticker whose slow daily-close poller hasn't run
        its first cycle yet). Publishing a signal with price=0.0 in that
        case is actively dangerous, not just cosmetically wrong: talonx_core's
        HIGH_CONVICTION_BUY check is `price <= (1 - margin_of_safety_pct) *
        fair_value`, and 0 <= any positive number, so a zero price would
        ALWAYS satisfy it -- a false BUY trigger -- and margin_of_safety_pct
        itself would read as a nonsense +100%. Falls back to yfinance's
        last close instead of publishing 0.0; caches a successful fallback
        into _latest_prices too, so a second fundamentals event this
        session doesn't re-fetch."""
        price = self._latest_prices.get(ticker)
        if price is not None and price > 0:
            return price
        try:
            fallback = await asyncio.to_thread(_fetch_last_close, ticker)
        except Exception as exc:  # noqa: BLE001 -- a fallback-fetch failure isn't fatal
            logger.warning("Fallback price fetch failed for %s: %s", ticker, exc)
            return 0.0
        if fallback is not None and fallback > 0:
            logger.info("No live price for %s yet -- using yfinance last close $%.2f as fallback", ticker, fallback)
            self._latest_prices[ticker] = fallback
            return fallback
        return 0.0

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

        if price <= 0:
            # No live market:stream tick yet -- try the yfinance fallback
            # NOW (only reached once we know the signal would otherwise
            # publish, so this network call isn't wasted on tickers whose
            # ROIC/F-Score wouldn't have cleared the threshold anyway).
            price = await self._get_price_with_fallback(ticker)
            if price <= 0:
                # Fallback also failed -- suppress rather than publish a
                # signal talonx_core's decision matrix would misread.
                logger.warning("No usable price (live or fallback) for %s -- suppressing fundamental signal", ticker)
                if self.store is not None:
                    self.store.record_suppressed(ticker, "NO_PRICE_AVAILABLE", 1, datetime.now(timezone.utc))
                return
            # Recompute the price-dependent factors now that a real price
            # is known -- they were computed against the 0.0 placeholder
            # above, purely for the FACTOR_CALCULATED observability log.
            fcf_yield = compute_fcf_yield(current, price)
            altman_z = compute_altman_z_score(current, price)

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
