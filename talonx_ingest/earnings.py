"""
talonx_ingest.earnings
---------------------------
Event-Driven Earnings Radar: fetches each LONG_TERM/DUAL_HORIZON ticker's
next known earnings date via yfinance's `.calendar` property -- an
undocumented, best-effort Yahoo Finance endpoint (same "unofficial API,
wrap defensively" posture yfinance_poll.py already takes for price data).

yfinance's `.calendar` shape has varied across versions (a plain dict in
newer releases, a pandas DataFrame in older ones) and reliably provides
only a DATE, never a BEFORE_MARKET/AFTER_MARKET session tag -- so
`session` on the returned EarningsCalendarEntry resolves to UNSPECIFIED
far more often than not. This is an accepted data-availability
limitation, not a bug: `upcoming_earnings`'s schema already models
UNSPECIFIED as a real value for exactly this reason.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger("talonx_ingest.earnings")


@dataclass(frozen=True)
class EarningsCalendarEntry:
    ticker: str
    earnings_date: date
    session: str = "UNSPECIFIED"
    reporting_period: str = ""


def fetch_earnings_calendar(ticker: str) -> EarningsCalendarEntry | None:
    """
    Blocking call -- run via asyncio.to_thread, same as every other
    yfinance call in this codebase. Returns None if yfinance has no
    calendar data for this ticker (delisted, illiquid, or just not
    covered) or if the call fails outright -- callers should skip the
    ticker for this sync cycle rather than treat it as fatal.
    """
    import yfinance as yf  # imported lazily so this stays optional

    try:
        calendar = yf.Ticker(ticker.upper()).calendar
    except Exception as exc:  # noqa: BLE001 -- an unofficial endpoint, fail soft
        logger.warning("yfinance calendar fetch failed for %s: %s", ticker, exc)
        return None

    earnings_date = _extract_earnings_date(calendar)
    if earnings_date is None:
        logger.info("No earnings date available from yfinance for %s", ticker)
        return None

    return EarningsCalendarEntry(ticker=ticker.upper(), earnings_date=earnings_date)


def _extract_earnings_date(calendar) -> date | None:
    """`calendar` is a dict in modern yfinance
    (`{"Earnings Date": [date(...), date(...)]}` -- a RANGE of estimated
    dates, take the EARLIEST) or a pandas DataFrame in older versions
    (same "Earnings Date" row, list-shaped). Returns None for any shape
    this function doesn't recognize rather than raising -- an unofficial,
    version-drifting endpoint should degrade gracefully, not crash the
    sync loop."""
    if calendar is None:
        return None

    try:
        if isinstance(calendar, dict):
            raw = calendar.get("Earnings Date")
        elif "Earnings Date" in getattr(calendar, "index", []):
            raw = calendar.loc["Earnings Date"].tolist()
        else:
            raw = None
    except Exception:  # noqa: BLE001 -- unrecognized shape, degrade to None
        return None

    if not raw:
        return None
    dates = raw if isinstance(raw, (list, tuple)) else [raw]
    dates = [d for d in dates if d is not None]
    if not dates:
        return None
    return min(dates)
