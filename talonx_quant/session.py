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
