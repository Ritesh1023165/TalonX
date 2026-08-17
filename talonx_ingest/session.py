"""
talonx_ingest.session
-------------------------
Dynamic ET timezone-aware session-state classification for US equities.

Requirement-doc gap fix: run_talonx.PreMarketPoller previously gated its
pre-market window on a flat, hardcoded UTC time-of-day range
(TALONX_PREMARKET_START_UTC/END_UTC, default 08:00-14:30 UTC) sized to
cover the UNION of both EDT and EST offsets for 04:00-09:30 ET, since it
did no DST-awareness at all. That meant real pre-market minutes were
either double-counted (session already ended locally, still "in window"
by the flat UTC clock) or the window could silently start/end up to an
hour off from the actual 04:00/09:30 ET boundary depending on the time of
year -- a correctness gap, not just imprecision, since a mis-classified
bar affects which minutes actually get polled.

`zoneinfo.ZoneInfo("America/New_York")` (stdlib) handles the EDT/EST
transition automatically via `astimezone`, so classification here is
always correct for the calendar date in question, regardless of DST.

Deliberately self-contained (ZoneInfo/stdlib only, no import of
talonx_quant) -- talonx_quant.session already solves this same problem
for the quant module's OWN session tagging (pre_market/regular/closed),
but talonx_ingest and talonx_quant are meant to be independently
deployable/importable (see talonx_quant/config.py's own docstring on this
convention), so this is a deliberate, small re-declaration rather than a
cross-module import -- same "each module owns its own copy of a session/
wire contract" pattern used throughout this project.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Literal
from zoneinfo import ZoneInfo

SessionState = Literal["pre_market", "regular", "after_hours", "closed"]

_ET = ZoneInfo("America/New_York")
_PRE_MARKET_START = time(4, 0)
_REGULAR_START = time(9, 30)
_REGULAR_END = time(16, 0)
_AFTER_HOURS_END = time(20, 0)


def get_session_state(timestamp: datetime | None = None) -> SessionState:
    """Classifies `timestamp` (defaults to now) into the US-equities
    session it falls in, America/New_York wall-clock time. Naive
    timestamps are assumed UTC, matching every other timestamp convention
    in this project. Saturday/Sunday always classify as `closed`
    regardless of time-of-day -- no trading-holiday calendar beyond that,
    same documented tradeoff talonx_quant.session.get_session and the
    previous flat-UTC-window implementation both already accepted (a
    stale "regular"/"closed" read on a holiday is a quieter-than-real
    misclassification, not a correctness hazard worth a holiday-calendar
    dependency)."""
    ts = timestamp if timestamp is not None else datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    local = ts.astimezone(_ET)
    if local.weekday() >= 5:
        return "closed"

    local_time = local.time()
    if _PRE_MARKET_START <= local_time < _REGULAR_START:
        return "pre_market"
    if _REGULAR_START <= local_time < _REGULAR_END:
        return "regular"
    if _REGULAR_END <= local_time < _AFTER_HOURS_END:
        return "after_hours"
    return "closed"


def is_premarket_window(timestamp: datetime | None = None) -> bool:
    """True during US pre-market hours (04:00-09:30 ET), Mon-Fri --
    run_talonx.PreMarketPoller's window check, replacing its old flat
    UTC-time-of-day comparison."""
    return get_session_state(timestamp) == "pre_market"
