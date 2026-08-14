"""
talonx_quant.preseed
-------------------------
Historical bar pre-seeding via yfinance -- Requirement 2 ("Instant
Historical Pre-Seeding on Startup / New Ticker Addition"). Eliminates the
~24-minute (1-min buffer, 120 bars at a live 12s poll cadence) and
~50-continuous-hour (15-min HTF buffer, 200 bars) cold-start warm-up
documented in ../docs/bar_buffer_persistence.md by backfilling both
RollingBarBuffers from `yfinance.Ticker(...).history()` the moment a
ticker is seen for the first time (or has too little checkpointed
history to reload), rather than waiting for enough live ticks to
accumulate.

Deliberately plain, synchronous functions -- consumer.py wraps each call
in `asyncio.to_thread` (same blocking-call-off-the-event-loop pattern
talonx_ingest.market_data.yfinance_poll.py already uses), which also
keeps this module trivially unit-testable without an event loop.

Fails soft everywhere, per Requirement 2's own "Fallback Handling"
clause: any yfinance error (rate limit, network, malformed response) is
logged as a warning and an EMPTY list is returned, never raised -- the
caller's job is to fall back to normal live accumulation, not crash the
scanner over a best-effort backfill.
"""
from __future__ import annotations

import logging
from datetime import timezone

from talonx_quant.session import get_session

logger = logging.getLogger("talonx_quant.preseed")


def fetch_1m_history(symbol: str, period: str) -> list[dict]:
    """Up to `period`'s worth of 1-minute OHLCV bars for `symbol`
    (pre/post-market included), oldest first, each tagged with its
    session -- feeds the primary 1-min RollingBarBuffer. Empty list on
    any failure; never raises."""
    return _fetch_history(symbol, period=period, interval="1m")


def fetch_15m_history(symbol: str, period: str) -> list[dict]:
    """Same as fetch_1m_history but 15-minute bars, for the HTF
    (200-SMA trend gate) buffer."""
    return _fetch_history(symbol, period=period, interval="15m")


def _fetch_history(symbol: str, period: str, interval: str) -> list[dict]:
    import yfinance as yf  # imported lazily, same optionality posture as yfinance_poll.py

    try:
        history = yf.Ticker(symbol.upper()).history(period=period, interval=interval, prepost=True)
    except Exception as exc:  # noqa: BLE001 -- pre-seeding is best-effort, never fatal
        logger.warning(
            "Historical pre-seed fetch failed for %s (period=%s, interval=%s): %s",
            symbol, period, interval, exc,
        )
        return []

    if history is None or history.empty:
        return []

    bars: list[dict] = []
    for ts, row in history.iterrows():
        close = _safe_float(row.get("Close"))
        if close is None:
            continue  # a bar with no close is useless -- same drop rule buffer.add_bar applies live

        timestamp = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        bars.append({
            "timestamp": timestamp,
            "open": _safe_float(row.get("Open")),
            "high": _safe_float(row.get("High")),
            "low": _safe_float(row.get("Low")),
            "close": close,
            "volume": _safe_float(row.get("Volume")),
            "session": get_session(timestamp),
        })

    return bars


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
