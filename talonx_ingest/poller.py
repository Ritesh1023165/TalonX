"""
talonx_ingest.poller
-------------------------
Vectorized multi-quote poller for extended-hours (pre/post-market) data.

Requirement: refresh the full watchlist (50+ tickers) in under ~30s
during pre-market. run_talonx.PreMarketPoller's original implementation
called fetch_extended_hours_quote (talonx_ingest.market_data.yfinance_poll)
once PER SYMBOL, sequentially awaited, and deliberately rotated through
only a small batch (5 symbols) per tick rather than the whole watchlist --
each call opens its own native curl_cffi HTTP handle via
`yf.Ticker(...).history(prepost=True)`, and the installed curl_cffi build
(0.16.0) leaks that handle on teardown (see PreMarketPoller's own
docstring for the full incident). Hitting the full watchlist every tick
that way was confirmed live to OOM the whole machine within ~15 minutes,
so the watchlist was only ever covered gradually, over many ticks -- never
within one 30s cycle.

fetch_watchlist_quotes wraps yfinance_poll.fetch_quotes_vectorized (a
SINGLE batched `yf.download(..., group_by="ticker")` call covering every
symbol) with timing and a slow-cycle warning, so a full-watchlist refresh
happens every tick, and a poll cycle creeping toward or past the 30s
target is visible in logs rather than silently regressing.
"""
from __future__ import annotations

import logging
import time as _time

from talonx_ingest.market_data.models import MarketEvent
from talonx_ingest.market_data.yfinance_poll import fetch_quotes_vectorized

logger = logging.getLogger("talonx_ingest.poller")

DEFAULT_REFRESH_WARN_SECONDS = 30.0


def fetch_watchlist_quotes(
    symbols: list[str], warn_threshold_seconds: float = DEFAULT_REFRESH_WARN_SECONDS,
) -> list[MarketEvent]:
    """
    Blocking -- run via asyncio.to_thread, same convention as every other
    yfinance call in this package. Returns whatever quotes were found (one
    per symbol that had usable data); logs a warning if the whole batch
    took longer than warn_threshold_seconds so a regression toward the
    30s SLA is visible without needing to time it externally.
    """
    if not symbols:
        return []

    started = _time.monotonic()
    quotes = fetch_quotes_vectorized(symbols)
    elapsed = _time.monotonic() - started

    over_target = elapsed > warn_threshold_seconds
    log = logger.warning if over_target else logger.info
    log(
        "Vectorized watchlist quote refresh: %d/%d symbol(s) in %.1fs (%s the %.0fs target)",
        len(quotes), len(symbols), elapsed, "OVER" if over_target else "within", warn_threshold_seconds,
    )
    return list(quotes.values())
