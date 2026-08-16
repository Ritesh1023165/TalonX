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
"""
from __future__ import annotations

from datetime import time, timezone
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
