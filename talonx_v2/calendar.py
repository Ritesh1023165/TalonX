"""
talonx_v2.calendar -- NYSE (XNYS) trading-session arithmetic (Phase 6, 12)
========================================================================
Explicit exchange-calendar semantics for the frozen causal entry rule and
the 10-trading-day hold.  Uses ``exchange_calendars`` (XNYS) -- the same
proven dependency ``talonx_signals.market_sessions`` already uses.

NEVER fabricates a session for a non-trading day.  Weekends, holidays and
early closes are handled by the calendar itself.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from functools import lru_cache

logger = logging.getLogger("talonx_v2.calendar")

_XNYS_START = "2015-01-01"


@lru_cache(maxsize=1)
def _sessions() -> list[date]:
    import exchange_calendars as xc

    cal = xc.get_calendar("XNYS")
    start = max(cal.first_session, __import__("pandas").Timestamp(_XNYS_START))
    end = cal.last_session
    return [ts.date() for ts in cal.sessions_in_range(start, end)]


def _as_date(d: date | datetime | str) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        return date.fromisoformat(d[:10])
    return d


def is_session(d: date | datetime | str) -> bool:
    return _as_date(d) in set(_sessions())


def next_session_on_or_after(d: date | datetime | str) -> date:
    tgt = _as_date(d)
    for s in _sessions():
        if s >= tgt:
            return s
    raise ValueError(f"no XNYS session on/after {tgt}")


def next_session_strictly_after(d: date | datetime | str) -> date:
    """The frozen entry rule: first NYSE session STRICTLY after ``d``."""
    tgt = _as_date(d)
    for s in _sessions():
        if s > tgt:
            return s
    raise ValueError(f"no XNYS session strictly after {tgt}")


def add_sessions(d: date | datetime | str, n: int) -> date:
    """The session that is ``n`` trading days after session ``d``
    (``d`` must itself be a session; n>=0).  n=10 -> the frozen exit
    session."""
    tgt = _as_date(d)
    sess = _sessions()
    try:
        i = sess.index(tgt)
    except ValueError:
        # d is not a session -> anchor on the next session, then step
        tgt = next_session_on_or_after(tgt)
        i = sess.index(tgt)
    j = i + n
    if j >= len(sess):
        raise ValueError(f"session index {j} out of calendar range")
    return sess[j]


def sessions_between(start: date | datetime | str, end: date | datetime | str) -> int:
    """Count of trading sessions in (start, end] -- 0 if end <= start."""
    a, b = _as_date(start), _as_date(end)
    if b <= a:
        return 0
    return sum(1 for s in _sessions() if a < s <= b)


def trading_days_elapsed(entry_session: date | datetime | str, as_of: date | datetime | str) -> int:
    """How many sessions have elapsed since (and including) the entry
    session, as of ``as_of``.  entry day == day 0."""
    a, b = _as_date(entry_session), _as_date(as_of)
    if b < a:
        return 0
    return sum(1 for s in _sessions() if a <= s <= b) - 1
