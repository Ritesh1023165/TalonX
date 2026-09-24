"""
Market-phase model on the XNYS calendar (America/New_York wall clock, early closes included).

A **trading window** belongs to one XNYS session D and uses the previous session's close as its reference price:

    OVERNIGHT    20:00 ET on the calendar evening before D (only if that evening is a Sun-Thu trading night)
                 -> 04:00 ET on D
    PREMARKET    04:00 ET -> regular open
    REGULAR      regular open -> regular close (early close respected)
    AFTER_HOURS  regular close -> min(20:00 ET, close + 4h)
    CLOSED       everything else (weekends, holidays, the gap after an early-close after-hours session)

Crossing 04:00 / 09:30 / 16:00 ET never changes the window, so candidate identity is continuous inside a
window. The 20:00 ET roll starts the next window (new reference close); discovery carries still-active
identities forward as lineage rather than resetting them (see discovery.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from talonx_premarket.session import _xnys, is_session

NY = ZoneInfo("America/New_York")

OVERNIGHT = "OVERNIGHT"
PREMARKET = "PREMARKET"
REGULAR = "REGULAR"
AFTER_HOURS = "AFTER_HOURS"
CLOSED = "CLOSED"
PHASES = (OVERNIGHT, PREMARKET, REGULAR, AFTER_HOURS, CLOSED)
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"      # a phase whose provider capability is not usable (fail closed)


def _at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=NY).astimezone(timezone.utc)


@dataclass(frozen=True)
class TradingWindow:
    session: date                 # the XNYS session D this window belongs to
    reference_session: date       # previous XNYS session (reference close)
    overnight_start_utc: datetime | None
    premarket_start_utc: datetime
    open_utc: datetime
    close_utc: datetime
    after_hours_end_utc: datetime

    @property
    def window_id(self) -> str:
        return self.session.isoformat()

    @property
    def start_utc(self) -> datetime:
        return self.overnight_start_utc or self.premarket_start_utc

    def phase_at(self, t: datetime) -> str:
        t = t.astimezone(timezone.utc)
        if self.overnight_start_utc and self.overnight_start_utc <= t < self.premarket_start_utc:
            return OVERNIGHT
        if self.premarket_start_utc <= t < self.open_utc:
            return PREMARKET
        if self.open_utc <= t < self.close_utc:
            return REGULAR
        if self.close_utc <= t < self.after_hours_end_utc:
            return AFTER_HOURS
        return CLOSED

    def phase_bounds(self, phase: str) -> tuple[datetime, datetime] | None:
        return {OVERNIGHT: (self.overnight_start_utc, self.premarket_start_utc) if self.overnight_start_utc else None,
                PREMARKET: (self.premarket_start_utc, self.open_utc),
                REGULAR: (self.open_utc, self.close_utc),
                AFTER_HOURS: (self.close_utc, self.after_hours_end_utc)}.get(phase)


def trading_window(d: date) -> TradingWindow:
    cal = _xnys()
    if not cal.is_session(d.isoformat()):
        raise ValueError(f"{d} is not an XNYS session")
    o = cal.session_open(d.isoformat()).to_pydatetime().astimezone(timezone.utc)
    c = cal.session_close(d.isoformat()).to_pydatetime().astimezone(timezone.utc)
    prev = cal.previous_session(d.isoformat()).date()
    eve = d - timedelta(days=1)
    # an overnight session exists on Sun-Thu evenings; the evening before D must not be a Fri/Sat
    overnight = _at(eve, 20) if eve.weekday() in (6, 0, 1, 2, 3) else None
    if overnight is not None and eve.weekday() != 6 and not is_session(eve):
        overnight = None          # the evening after a weekday holiday is not an overnight trading night
    ah_end = min(_at(c.astimezone(NY).date(), 20), c + timedelta(hours=4))
    return TradingWindow(d, prev, overnight, _at(d, 4), o, c, ah_end)


def window_at(t: datetime) -> TradingWindow | None:
    """The trading window containing ``t`` (whose extended session has not ended yet), or None in a CLOSED gap."""
    t = t.astimezone(timezone.utc)
    d = t.astimezone(NY).date()
    for k in range(0, 6):
        cand = d + timedelta(days=k)
        if not is_session(cand):
            continue
        w = trading_window(cand)
        if t >= w.after_hours_end_utc:
            continue
        return w if t >= w.start_utc else None
    return None


def phase_at(t: datetime) -> tuple[str, TradingWindow | None]:
    w = window_at(t)
    return (w.phase_at(t), w) if w else (CLOSED, None)


def next_window_start(t: datetime) -> datetime | None:
    d = t.astimezone(NY).date()
    for k in range(0, 10):
        cand = d + timedelta(days=k)
        if is_session(cand):
            w = trading_window(cand)
            if w.start_utc > t:
                return w.start_utc
    return None
