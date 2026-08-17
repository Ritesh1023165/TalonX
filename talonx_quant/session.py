"""
talonx_quant.session
------------------------
Pre-market vs. regular-session classification for a bar timestamp (US
equities, America/New_York), used by strategy.py/consumer.py to pick
session-specific thresholds (volume surge, liquidity gate, news-catalyst
gate). Deliberately ignores the market holiday calendar/early closes --
the gates this feeds are volatility/liquidity safety checks, not a
trading-calendar authority. A false "regular" classification on a holiday
just means the (normally quieter) regular-session thresholds apply
instead of the stricter pre-market ones -- not a correctness bug worth
the added dependency of a holiday calendar.

is_operating_window_open, below, is an UNRELATED, orthogonal concept
living in this file purely because it's also a timestamp/timezone
session classifier -- see its own docstring.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Literal
from zoneinfo import ZoneInfo

Session = Literal["pre_market", "regular", "closed"]

_ET = ZoneInfo("America/New_York")
_PRE_MARKET_START = time(4, 0)
_REGULAR_START = time(9, 30)
_REGULAR_END = time(16, 0)


def get_session(timestamp) -> Session:
    """`timestamp` may be tz-aware (any zone) or naive -- naive is assumed
    UTC, matching every other bar_timestamp in this module (MarketTickEvent's
    wire contract always carries UTC)."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    local_time = timestamp.astimezone(_ET).time()
    if _PRE_MARKET_START <= local_time < _REGULAR_START:
        return "pre_market"
    if _REGULAR_START <= local_time < _REGULAR_END:
        return "regular"
    return "closed"


EntryBlackout = Literal["none", "opening", "closing"]

# Carved out of the `regular` session purely for consumer.py's entry gate --
# deliberately NOT folded into get_session/Session above, which also drives
# bar-buffer session tagging (buffer.py) and the volume-surge baseline's
# session-scoped reset (indicators.py's _same_session_tail -- ATR itself
# is deliberately continuous across sessions as of a 2026-08-16 quant
# audit, and no longer uses this helper): widening Session to 5 states
# would make the volume baseline reset itself every day at 09:30, 09:45,
# 15:30 AND 16:00 instead of just at the pre-market/regular boundary,
# right during the highest-volume parts of the session -- an unrelated
# regression this module must not cause. This is an orthogonal, narrower
# classification layered on top.
_OPENING_BLACKOUT_START = time(9, 30)
_OPENING_BLACKOUT_END = time(9, 45)
_CLOSING_BLACKOUT_START = time(15, 30)
_CLOSING_BLACKOUT_END = time(16, 0)


def get_entry_blackout(timestamp) -> EntryBlackout:
    """"opening" (09:30-09:45 ET) or "closing" (15:30-16:00 ET), else
    "none" -- same tz handling as get_session (naive assumed UTC)."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    local_time = timestamp.astimezone(_ET).time()
    if _OPENING_BLACKOUT_START <= local_time < _OPENING_BLACKOUT_END:
        return "opening"
    if _CLOSING_BLACKOUT_START <= local_time < _CLOSING_BLACKOUT_END:
        return "closing"
    return "none"


# ------------------------------------------------------------------
# TalonX's own UK-local operating window (2026-08-16 quant audit,
# round 5) -- unrelated to the US-market ET session above. See
# is_operating_window_open's own docstring.
# ------------------------------------------------------------------

_UK_TZ = ZoneInfo("Europe/London")
_OPERATING_WINDOW_START = time(8, 0)
_OPERATING_WINDOW_END = time(22, 0)
# datetime.weekday(): Monday=0 .. Sunday=6 -- Mon-Fri only, Sat/Sun
# unconditionally excluded regardless of time of day.
_OPERATING_WEEKDAYS = frozenset({0, 1, 2, 3, 4})


def is_operating_window_open(timestamp: datetime | None = None) -> bool:
    """True if `timestamp` (default: the current wall-clock instant)
    falls inside TalonX's own declared UK-local operating window
    (Mon-Fri 08:00-22:00 Europe/London).

    This is a SEPARATE, orthogonal concept from get_session/
    get_entry_blackout above, which classify a bar's timestamp against
    the US EQUITIES MARKET's own ET session -- this function instead
    answers "is TalonX allowed to publish signals right now, per the
    operator's own declared schedule" (see consumer.py's
    _handle_market_tick/_revalidate_candidate for where it gates
    publication).

    Deliberately evaluated FRESH from the current time (or an explicit
    `timestamp`, mainly for testing) on every call -- never cached, and
    never derived from when the process itself started. "08:00-22:00
    Monday-Friday is a trading-session rule, not an application-startup
    rule": TalonX can be started at any time of day (mid-session, before
    the window opens, on a weekend, after an unplanned restart) and this
    function's answer depends only on the CURRENT UK date/time, never on
    process uptime or launch time.

    Europe/London via zoneinfo (not a fixed UTC+0/UTC+1 offset) so the
    08:00/22:00 boundary stays the correct LOCAL time across the
    GMT/BST transition -- same "use a real IANA tz, not a hardcoded
    offset" convention _ET above already follows for the US market side.

    Boundary semantics (half-open interval, matching get_session/
    get_entry_blackout's own convention above): 08:00:00 local is OPEN
    (inclusive), 22:00:00 local is CLOSED (exclusive) -- so 07:59:59 is
    CLOSED and 21:59:59 is OPEN."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    elif timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    local = timestamp.astimezone(_UK_TZ)
    if local.weekday() not in _OPERATING_WEEKDAYS:
        return False
    return _OPERATING_WINDOW_START <= local.time() < _OPERATING_WINDOW_END
