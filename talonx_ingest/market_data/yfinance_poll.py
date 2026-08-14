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

        A cycle where most/all symbols fail per-symbol (see
        _fetch_snapshots) is treated as a DEGRADED cycle, not a silent
        success -- it gets the same backoff a hard exception would, and
        after enough consecutive degraded/failed cycles proactively
        resets yfinance's cached session (_reset_session) rather than
        repeating the same doomed request pattern indefinitely. Without
        this, a stuck yfinance session previously required a manual
        process restart to recover from.
        """
        logger.info(
            "Starting yfinance polling for %d symbols every %.0fs",
            len(symbols), self.config.yfinance_poll_interval_seconds,
        )
        consecutive_failures = 0

        while not self._stop_event.is_set():
            try:
                snapshots = await asyncio.to_thread(self._fetch_snapshots, symbols)
            except Exception as exc:  # noqa: BLE001 -- keep polling alive regardless
                consecutive_failures += 1
                self._maybe_reset_session(consecutive_failures)
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

            for event in snapshots:
                await on_event(event)

            failure_rate = 1.0 - (len(snapshots) / len(symbols) if symbols else 1.0)
            if len(symbols) >= 3 and failure_rate >= self.config.yfinance_degraded_cycle_failure_rate:
                consecutive_failures += 1
                self._maybe_reset_session(consecutive_failures)
                wait = jittered_backoff_seconds(
                    consecutive_failures,
                    self.config.yfinance_backoff_base_seconds,
                    self.config.yfinance_backoff_max_seconds,
                )
                logger.warning(
                    "yfinance poll cycle degraded: only %d/%d symbols returned data "
                    "(%.0f%% failure, %d consecutive); backing off %.1fs",
                    len(snapshots), len(symbols), failure_rate * 100, consecutive_failures, wait,
                )
                await asyncio.sleep(wait)
                continue

            consecutive_failures = 0
            await self._sleep_or_stop(self.config.yfinance_poll_interval_seconds)

    def _maybe_reset_session(self, consecutive_failures: int) -> None:
        if consecutive_failures > 0 and consecutive_failures % self.config.yfinance_session_reset_after_failures == 0:
            _reset_yfinance_session()

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


def _reset_yfinance_session() -> None:
    """
    yfinance.data.YfData is a process-wide singleton holding one cached
    HTTP session + auth 'crumb' for the whole process (its own docstring:
    "Singleton means one session one cookie shared by all threads"). A
    long enough run can get that singleton stuck in a bad state -- e.g.
    Yahoo rate-limiting or otherwise degrading the cached session's
    responses, which surfaces as a bare KeyError deep in yfinance's own
    parsing code (scrapers/quote.py's timezone lookup has no fallback
    for a malformed/incomplete response) rather than a clean, retryable
    exception. A fresh Python process gets a brand new singleton and
    immediately works again -- this reproduces that same fresh-start
    effect in-process by dropping the cached crumb/cookie and building a
    new underlying requests session, so the NEXT poll cycle re-authenticates
    from scratch instead of repeating the same doomed request pattern.

    Reaches into yfinance's private (`_`-prefixed) internals since there's
    no public reset API for this -- deliberately wrapped in a single
    broad except so a yfinance internals change in a future version
    degrades this to a no-op (logged) rather than crashing the poller.
    """
    try:
        from yfinance.data import YfData, new_session

        data = YfData()
        data._crumb = None
        data._cookie = None
        data._set_session(new_session())
        logger.warning("Reset yfinance's cached session/crumb after repeated degraded poll cycles")
    except Exception as exc:  # noqa: BLE001 -- best-effort; never let this crash the poller
        logger.debug("yfinance session reset failed (non-fatal): %s", exc)


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
