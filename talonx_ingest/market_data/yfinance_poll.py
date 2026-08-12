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


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        import pandas as pd  # imported lazily, same optionality posture as yfinance
        if pd.isna(value):
            return None
    except Exception:  # noqa: BLE001 -- pd.isna choking on an odd type shouldn't crash the caller
        pass
    return float(value)


def fetch_extended_hours_quote(symbol: str) -> MarketEvent | None:
    """
    Blocking call -- run via asyncio.to_thread, same as _fetch_snapshots
    above. Event-Driven Earnings Radar, Requirement 6: captures the
    LATEST minute bar including pre/post-market sessions
    (`history(prepost=True)`), unlike _fetch_snapshots's `fast_info`
    (regular-session only). Deliberately NOT part of the regular batch
    poll -- `history(prepost=True)` is a heavier call than `fast_info`,
    so it's only worth paying for a ticker currently inside its active
    earnings window (run_talonx.EarningsFastTrackPoller), not every
    tracked ticker every cycle.

    Returns None if yfinance has nothing usable -- the caller should
    skip this symbol for the current poll rather than publish a
    zero/garbage price.
    """
    import yfinance as yf  # imported lazily so this stays optional

    try:
        history = yf.Ticker(symbol.upper()).history(period="1d", interval="1m", prepost=True)
    except Exception as exc:  # noqa: BLE001 -- an unofficial endpoint, fail soft
        logger.warning("Extended-hours quote fetch failed for %s: %s", symbol, exc)
        return None

    if history is None or history.empty:
        return None

    latest = history.iloc[-1]
    close = _safe_float(latest.get("Close"))
    if close is None:
        return None

    timestamp = history.index[-1]
    if hasattr(timestamp, "to_pydatetime"):
        timestamp = timestamp.to_pydatetime()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return MarketEvent(
        symbol=symbol.upper(),
        event_type=MarketEventType.BAR,
        source=DataSource.POLLING,
        timestamp=timestamp,
        open=_safe_float(latest.get("Open")),
        high=_safe_float(latest.get("High")),
        low=_safe_float(latest.get("Low")),
        close=close,
        volume=_safe_float(latest.get("Volume")),
        raw={},
    )
