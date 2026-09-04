"""Task 99G -- deterministic, holiday-aware US-equities session-close
instants for causal forward-outcome (EOD / +1D) resolution.

Self-contained (does not import across the talonx_ingest.intelligence /
talonx_quant package boundaries) -- the same per-package session-helper
convention already used by talonx_quant.session, talonx_ingest.session, and
talonx_ingest.intelligence.sessions elsewhere in this repo.

Uses ``exchange_calendars`` (XNYS) -- already an installed, proven
dependency (Task 96A's requirements.txt addition). Falls back to a fixed
16:00 ET weekday-only close if the calendar is unavailable, exactly the
degraded-mode posture ``talonx_ingest.intelligence.sessions`` already
established (documented, not hidden). No decision here ever fabricates a
close for a non-trading day -- ``None`` is returned instead.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger("talonx_signals.market_sessions")

ET = ZoneInfo("America/New_York")
_FALLBACK_CLOSE = time(16, 0)

_calendar = None
_calendar_loaded = False
_calendar_unavailable = False


def _get_calendar():
    global _calendar, _calendar_loaded, _calendar_unavailable
    if _calendar_loaded:
        return _calendar
    _calendar_loaded = True
    try:
        import exchange_calendars as ec

        _calendar = ec.get_calendar("XNYS")
    except Exception as exc:  # noqa: BLE001 - any failure -> documented fallback
        logger.warning(
            "exchange_calendars unavailable (%s); forward-outcome EOD/+1D resolution "
            "falls back to a fixed weekday-only 16:00 ET close", exc,
        )
        _calendar = None
        _calendar_unavailable = True
    return _calendar


def calendar_unavailable() -> bool:
    _get_calendar()
    return _calendar_unavailable


def _reset_calendar_cache() -> None:
    """Test hook -- forces the next call to re-attempt the import."""
    global _calendar, _calendar_loaded, _calendar_unavailable
    _calendar = None
    _calendar_loaded = False
    _calendar_unavailable = False


def session_close_utc(d: date) -> datetime | None:
    """The regular-session close instant (UTC, tz-aware) for calendar date
    ``d``, or ``None`` if ``d`` is not a valid NYSE trading day. Never
    fabricates a close for a non-trading day."""
    cal = _get_calendar()
    if cal is None:
        if d.weekday() >= 5:
            return None
        local_close = datetime.combine(d, _FALLBACK_CLOSE, tzinfo=ET)
        return local_close.astimezone(timezone.utc)
    try:
        import pandas as pd

        ts = pd.Timestamp(d)
        if not bool(cal.is_session(ts)):
            return None
        close = cal.session_close(ts)
        return close.to_pydatetime().astimezone(timezone.utc)
    except Exception:  # noqa: BLE001 - never let a calendar quirk raise into the caller
        logger.exception("session_close_utc failed for %s; treating as unknown", d)
        return None


def next_session_close_utc(d: date) -> datetime | None:
    """The close instant (UTC) of the first valid NYSE trading session
    strictly after ``d``. Weekend/holiday-aware via exchange_calendars;
    the degraded fallback skips weekends only (documented limitation, same
    as the rest of this module's fallback path)."""
    cal = _get_calendar()
    if cal is None:
        nd = d + timedelta(days=1)
        while nd.weekday() >= 5:
            nd += timedelta(days=1)
        return session_close_utc(nd)
    try:
        import pandas as pd

        ts = pd.Timestamp(d)
        anchor = ts if bool(cal.is_session(ts)) else cal.date_to_session(ts, direction="next")
        next_session = cal.next_session(anchor)
        close = cal.session_close(next_session)
        return close.to_pydatetime().astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        logger.exception("next_session_close_utc failed for %s; treating as unknown", d)
        return None
