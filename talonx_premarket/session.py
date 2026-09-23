"""
Exchange-calendar session logic (XNYS). Never a hard-coded UK clock.

``phase_at(t)`` -> CLOSED | EARLY_PREMARKET | CORE_PREMARKET | NEAR_OPEN | REGULAR | POST_CLOSE
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from talonx_premarket.config import PREMARKET_RESEARCH_V1, PremarketConfig

NY = ZoneInfo("America/New_York")

CLOSED = "CLOSED"
EARLY = "EARLY_PREMARKET"
CORE = "CORE_PREMARKET"
NEAR_OPEN = "NEAR_OPEN"
REGULAR = "REGULAR"
POST_CLOSE = "POST_CLOSE"
PREMARKET_PHASES = (EARLY, CORE, NEAR_OPEN)


@lru_cache(maxsize=1)
def _xnys():
    import exchange_calendars as ec   # fail closed: no calendar -> no scan
    return ec.get_calendar("XNYS")


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


@dataclass(frozen=True)
class SessionDay:
    day: date
    open_utc: datetime
    close_utc: datetime
    premarket_start_utc: datetime
    core_start_utc: datetime
    near_open_start_utc: datetime
    prev_session: date


def is_session(d: date) -> bool:
    return bool(_xnys().is_session(d.isoformat()))


def session_day(d: date, cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> SessionDay:
    cal = _xnys()
    if not cal.is_session(d.isoformat()):
        raise ValueError(f"{d} is not an XNYS session")
    o = cal.session_open(d.isoformat()).to_pydatetime().astimezone(timezone.utc)
    c = cal.session_close(d.isoformat()).to_pydatetime().astimezone(timezone.utc)
    prev = cal.previous_session(d.isoformat()).date()

    def at(hm: str) -> datetime:
        return datetime.combine(d, _hm(hm), tzinfo=NY).astimezone(timezone.utc)

    return SessionDay(d, o, c, at(cfg.premarket_start_et), at(cfg.core_start_et),
                      min(at(cfg.near_open_start_et), o), prev)


def phase_at(t: datetime, cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> str:
    t = t.astimezone(timezone.utc)
    d = t.astimezone(NY).date()
    if not is_session(d):
        return CLOSED
    sd = session_day(d, cfg)
    if t < sd.premarket_start_utc:
        return CLOSED
    if t < sd.core_start_utc:
        return EARLY
    if t < sd.near_open_start_utc:
        return CORE
    if t < sd.open_utc:
        return NEAR_OPEN
    if t < sd.close_utc:
        return REGULAR
    return POST_CLOSE


def scan_interval_s(phase: str, cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> int:
    return {EARLY: cfg.scan_interval_early_s, CORE: cfg.scan_interval_core_s,
            NEAR_OPEN: cfg.scan_interval_near_open_s}.get(phase, cfg.scan_interval_core_s)


def scan_schedule(d: date, cfg: PremarketConfig = PREMARKET_RESEARCH_V1) -> list[datetime]:
    """The deterministic list of scan instants for a session (used by the live loop and the replay).
    The first scan is one SIP-delay after the pre-market start (nothing is visible earlier)."""
    sd = session_day(d, cfg)
    t = sd.premarket_start_utc + timedelta(minutes=cfg.sip_delay_minutes)
    out: list[datetime] = []
    while t < sd.open_utc:
        out.append(t)
        t = t + timedelta(seconds=scan_interval_s(phase_at(t, cfg), cfg))
    return out
