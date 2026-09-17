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
from datetime import date, datetime, timezone
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


@lru_cache(maxsize=1)
def _ord_map() -> dict[date, int]:
    return {d: i for i, d in enumerate(_sessions())}


@lru_cache(maxsize=1)
def _session_set() -> frozenset[date]:
    return frozenset(_sessions())


def session_ordinal(d: date | datetime | str, *, anchor_forward: bool = True) -> int:
    """Trading-day ordinal of ``d``.  If ``d`` is not itself a session and
    ``anchor_forward`` is True, returns the ordinal of the next session."""
    tgt = _as_date(d)
    m = _ord_map()
    i = m.get(tgt)
    if i is not None:
        return i
    if anchor_forward:
        return m[next_session_on_or_after(tgt)]
    sess = _sessions()
    for k in range(len(sess) - 1, -1, -1):
        if sess[k] <= tgt:
            return k
    raise ValueError(f"no session on/before {tgt}")


def _as_date(d: date | datetime | str) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        return date.fromisoformat(d[:10])
    return d


def is_session(d: date | datetime | str) -> bool:
    return _as_date(d) in _session_set()


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
    sess = _sessions()
    i = _ord_map().get(_as_date(d))
    if i is None:
        i = _ord_map()[next_session_on_or_after(d)]
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


def session_close_utc(d: date | datetime | str) -> datetime:
    """Package 3 P3-D: the REAL, official XNYS close timestamp (UTC) for
    session ``d`` -- honors early closes via ``exchange_calendars``' own
    calendar data (e.g. 13:00 ET / 18:00 UTC the day after Thanksgiving),
    never approximated as midnight UTC/local or a fixed hour offset.
    ``d`` must be an actual trading session (raises if not -- callers
    resolve to a real session first, e.g. via ``add_sessions``)."""
    import exchange_calendars as xc
    ts = xc.get_calendar("XNYS").session_close(_as_date(d).isoformat())
    return ts.to_pydatetime().astimezone(timezone.utc)


def trading_days_elapsed(entry_session: date | datetime | str, as_of: date | datetime | str) -> int:
    """How many sessions have elapsed since (and including) the entry
    session, as of ``as_of``.  entry day == day 0."""
    a, b = _as_date(entry_session), _as_date(as_of)
    if b < a:
        return 0
    ia = session_ordinal(a, anchor_forward=True)
    ib = session_ordinal(b, anchor_forward=False)
    return max(0, ib - ia)
