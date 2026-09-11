"""
talonx_ingest.intelligence.sessions
===================================
Deterministic US-equities session bucketing for an event's
``acceptanceDateTime``.

Buckets: ``BMO`` (< 09:30 ET on a trading day), ``RTH`` (09:30-close),
``AMC`` (>= close, including after an early-close half-day),
``NON_TRADING_DAY`` (weekend or NYSE holiday), ``UNKNOWN`` (no usable
timestamp).

NYSE holidays and half-days come from ``exchange_calendars`` (XNYS), which
is present in the environment and works fully offline. If that import ever
fails, the module degrades to a weekday-only classification and stamps
``session_calendar_unavailable`` -- a holiday may then misclassify as a
trading day, which is why the flag is surfaced rather than hidden. This is
a NEW isolated module; ``talonx_ingest/session.py`` (which deliberately
has no holiday calendar) is unchanged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from talonx_ingest.intelligence.config import SESSION_BUCKET_TRANSFORM
from talonx_ingest.intelligence.domain import DataQualityFlag, SessionBucket

logger = logging.getLogger("talonx_ingest.intelligence.sessions")

_ET = ZoneInfo("America/New_York")
_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)

TRANSFORM = SESSION_BUCKET_TRANSFORM

_calendar = None
_calendar_loaded = False


@dataclass(frozen=True)
class SessionResult:
    bucket: SessionBucket
    reason: str | None = None
    flags: tuple[str, ...] = field(default_factory=tuple)
    et_timestamp: datetime | None = None


def _get_calendar():
    """Lazily construct and cache the XNYS calendar. Returns ``None`` if
    ``exchange_calendars`` cannot be used -- the caller then falls back."""
    global _calendar, _calendar_loaded
    if _calendar_loaded:
        return _calendar
    _calendar_loaded = True
    try:  # pragma: no cover - import branch exercised via _reset_calendar_cache in tests
        import exchange_calendars as ec

        _calendar = ec.get_calendar("XNYS")
    except Exception as exc:  # noqa: BLE001 - any failure -> documented fallback
        logger.warning(
            "exchange_calendars unavailable (%s); session bucketing falls back to "
            "weekday-only and flags session_calendar_unavailable",
            exc,
        )
        _calendar = None
    return _calendar


def _reset_calendar_cache() -> None:
    """Test hook -- forces the next call to re-attempt the import."""
    global _calendar, _calendar_loaded
    _calendar = None
    _calendar_loaded = False


def to_et(ts: datetime) -> datetime:
    """Convert to America/New_York. A naive timestamp is assumed UTC, the
    convention used everywhere else in this project."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(_ET)


def _time_of_day_bucket(
    et: datetime, open_t: time, close_t: time
) -> tuple[SessionBucket, str | None]:
    tod = et.time()
    if tod < open_t:
        return SessionBucket.BMO, None
    if tod < close_t:
        return SessionBucket.RTH, None
    reason = "half_day_amc" if close_t < _REGULAR_CLOSE else None
    return SessionBucket.AMC, reason


def bucket_session(accepted_at_utc: datetime | None) -> SessionResult:
    """Classify an event instant into its US-equities session bucket."""
    if accepted_at_utc is None:
        return SessionResult(
            SessionBucket.UNKNOWN,
            reason="missing_acceptance_timestamp",
            flags=(DataQualityFlag.MISSING_ACCEPTANCE_TIMESTAMP.value,),
        )

    et = to_et(accepted_at_utc)
    cal = _get_calendar()

    if cal is None:
        # weekday-only fallback
        if et.weekday() >= 5:
            return SessionResult(
                SessionBucket.NON_TRADING_DAY,
                reason="weekend",
                flags=(DataQualityFlag.SESSION_CALENDAR_UNAVAILABLE.value,),
                et_timestamp=et,
            )
        bucket, reason = _time_of_day_bucket(et, _REGULAR_OPEN, _REGULAR_CLOSE)
        return SessionResult(
            bucket,
            reason=reason,
            flags=(
                DataQualityFlag.SESSION_CALENDAR_UNAVAILABLE.value,
                DataQualityFlag.AMBIGUOUS_SESSION_BUCKET.value,
            ),
            et_timestamp=et,
        )

    try:
        import pandas as pd

        session_label = pd.Timestamp(et.date())
        if not bool(cal.is_session(session_label)):
            reason = "weekend" if et.weekday() >= 5 else "nyse_holiday"
            return SessionResult(
                SessionBucket.NON_TRADING_DAY, reason=reason, et_timestamp=et
            )
        open_et = cal.session_open(session_label).tz_convert(_ET).to_pydatetime()
        close_et = cal.session_close(session_label).tz_convert(_ET).to_pydatetime()
        bucket, reason = _time_of_day_bucket(et, open_et.timetz().replace(tzinfo=None), close_et.timetz().replace(tzinfo=None))
        return SessionResult(bucket, reason=reason, et_timestamp=et)
    except Exception as exc:  # noqa: BLE001 - out-of-range date etc. -> fallback
        logger.warning(
            "session calendar lookup failed for %s (%s); weekday-only fallback", et, exc
        )
        if et.weekday() >= 5:
            return SessionResult(
                SessionBucket.NON_TRADING_DAY,
                reason="weekend",
                flags=(DataQualityFlag.SESSION_CALENDAR_UNAVAILABLE.value,),
                et_timestamp=et,
            )
        bucket, reason = _time_of_day_bucket(et, _REGULAR_OPEN, _REGULAR_CLOSE)
        return SessionResult(
            bucket,
            reason=reason,
            flags=(
                DataQualityFlag.SESSION_CALENDAR_UNAVAILABLE.value,
                DataQualityFlag.AMBIGUOUS_SESSION_BUCKET.value,
            ),
            et_timestamp=et,
        )
