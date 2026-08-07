"""
talonx_ingest.market_data.yfinance_poll
-------------------------------------------
Polling-based market data backup using yfinance.

yfinance has no push/streaming API -- it's a synchronous HTTP client
wrapping Yahoo Finance's undocumented endpoints. This module:
  - Wraps each blocking yfinance call in `asyncio.to_thread` so it doesn't
    block the event loop (needed since the rest of the pipeline is asyncio).
  - Batches all symbols into a single `yf.Tickers(...)` call per poll cycle
    rather than one request per symbol, to reduce request volume.
  - Retries a poll cycle with backoff on failure, but never gives up
    permanently -- this IS the fallback path, so it should keep trying
    indefinitely (with backoff) rather than raising and killing the stream.

Emits the same `MarketEvent` shape as the WebSocket client (event_type=BAR,
source=POLLING) so downstream consumers don't need source-specific logic.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from talonx_ingest.common.backoff import jittered_backoff_seconds
from talonx_ingest.config import MarketDataConfig, settings
from talonx_ingest.market_data.models import DataSource, MarketEvent, MarketEventType

logger = logging.getLogger("talonx_ingest.market_data.yfinance_poll")

EventCallback = Callable[[MarketEvent], Awaitable[None]]


class YFinancePoller:
    def __init__(self, config: MarketDataConfig | None = None):
        self.config = config or settings.market_data
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def stream(self, symbols: list[str], on_event: EventCallback) -> None:
        """
        Poll all symbols every `yfinance_poll_interval_seconds`, emitting
        one BAR-type MarketEvent per symbol per successful cycle. Runs
        until `stop()` is called.
        """
        logger.info(
            "Starting yfinance polling for %d symbols every %.0fs",
            len(symbols), self.config.yfinance_poll_interval_seconds,
        )
        consecutive_failures = 0

        while not self._stop_event.is_set():
            try:
                snapshots = await asyncio.to_thread(self._fetch_snapshots, symbols)
                consecutive_failures = 0
                for event in snapshots:
                    await on_event(event)
            except Exception as exc:  # noqa: BLE001 -- keep polling alive regardless
                consecutive_failures += 1
                wait = jittered_backoff_seconds(
                    consecutive_failures,
                    self.config.yfinance_backoff_base_seconds,
                    self.config.yfinance_backoff_max_seconds,
                )
                logger.warning(
                    "yfinance poll cycle failed (%d consecutive): %s; "
                    "retrying in %.1fs", consecutive_failures, exc, wait,
                )
                await asyncio.sleep(wait)
                continue

            await self._sleep_or_stop(self.config.yfinance_poll_interval_seconds)

    async def _sleep_or_stop(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass  # normal case: timeout means "keep polling"

    def _fetch_snapshots(self, symbols: list[str]) -> list[MarketEvent]:
        """
        Blocking call, run off the event loop via asyncio.to_thread.
        Uses `fast_info` per ticker for lightweight last-price/volume data
        rather than full `.history()`, which is much slower per call.
        """
        import yfinance as yf  # imported lazily so this stays optional

        tickers = yf.Tickers(" ".join(symbols))
        now = datetime.now(timezone.utc)
        events: list[MarketEvent] = []

        for symbol in symbols:
            try:
                ticker = tickers.tickers.get(symbol.upper())
                if ticker is None:
                    logger.warning("yfinance returned no ticker object for %s", symbol)
                    continue

                info = ticker.fast_info
                last_price = getattr(info, "last_price", None)
                if last_price is None:
                    continue

                events.append(
                    MarketEvent(
                        symbol=symbol.upper(),
                        event_type=MarketEventType.BAR,
                        source=DataSource.POLLING,
                        timestamp=now,
                        open=getattr(info, "open", None),
                        high=getattr(info, "day_high", None),
                        low=getattr(info, "day_low", None),
                        close=last_price,
                        volume=getattr(info, "last_volume", None),
                        raw={},
                    )
                )
            except Exception as exc:  # noqa: BLE001 -- isolate per-symbol failures
                logger.warning("yfinance fetch failed for %s: %s", symbol, exc)
                continue

        return events
