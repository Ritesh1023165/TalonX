"""
talonx_ingest.intelligence.freshness
====================================
Per-source data-freshness state for the event-intelligence layer.

Rule (from ``DATA_FRESHNESS_SPEC.md`` and the Task 87B liveness lesson):

  * ``FRESH`` / ``STALE`` are decided by **how long ago the last successful
    poll was**, split by US market session (day vs. overnight). They are
    NOT decided by whether a new event arrived -- EDGAR legitimately has
    long quiet periods.
  * ``DOWN`` is decided by **consecutive poll failures**.
  * ``UNKNOWN`` means the source has never been polled successfully and is
    not yet failing hard.

``latest_source_event_utc`` is tracked for display/debugging only; it never
feeds the status decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from talonx_ingest.intelligence.config import (
    DEFAULT_FRESHNESS,
    FRESHNESS_THRESHOLDS,
    FreshnessThresholds,
)
from talonx_ingest.intelligence.domain import FreshnessStatus, SourceType

if TYPE_CHECKING:  # avoid an import cycle with store.py
    from talonx_ingest.intelligence.store import EventStore


@dataclass(frozen=True)
class FreshnessSnapshot:
    source_type: str
    status: FreshnessStatus
    reason: str
    last_poll_attempt_utc: datetime | None
    last_poll_success_utc: datetime | None
    latest_source_event_utc: datetime | None
    consecutive_failures: int
    age_seconds: float | None  # since last successful poll


def _thresholds_for(source_type: str | SourceType) -> FreshnessThresholds:
    key = source_type.value if isinstance(source_type, SourceType) else str(source_type)
    return FRESHNESS_THRESHOLDS.get(key, DEFAULT_FRESHNESS)


def is_market_day_hours(now: datetime | None = None) -> bool:
    """True during 04:00-20:00 ET on a weekday (pre-market -> after-hours) --
    when EDGAR + market sources are expected to refresh briskly. Reuses the
    existing ingest session classifier (no holiday calendar there, which is
    fine: a holiday merely applies the stricter 'day' threshold)."""
    from talonx_ingest.session import get_session_state

    return get_session_state(now) in ("pre_market", "regular", "after_hours")


def compute_status(
    *,
    last_poll_success_utc: datetime | None,
    consecutive_failures: int,
    now: datetime,
    thresholds: FreshnessThresholds,
    day_hours: bool,
) -> tuple[FreshnessStatus, str, float | None]:
    """Pure status decision. Returns ``(status, reason, age_seconds)``."""
    if consecutive_failures >= thresholds.down_after_failures:
        return FreshnessStatus.DOWN, f"{consecutive_failures}_consecutive_poll_failures", None

    if last_poll_success_utc is None:
        if consecutive_failures > 0:
            return FreshnessStatus.UNKNOWN, "no_successful_poll_yet", None
        return FreshnessStatus.UNKNOWN, "never_polled", None

    if last_poll_success_utc.tzinfo is None:
        last_poll_success_utc = last_poll_success_utc.replace(tzinfo=timezone.utc)
    age = (now - last_poll_success_utc).total_seconds()
    limit = (
        thresholds.stale_after_seconds_day
        if day_hours
        else thresholds.stale_after_seconds_night
    )
    if age > limit:
        return FreshnessStatus.STALE, f"last_success_{int(age)}s_ago_limit_{limit}s", age
    return FreshnessStatus.FRESH, f"last_success_{int(age)}s_ago", age


class SourceFreshnessTracker:
    """Thin persistence wrapper over ``EventStore``'s ``source_freshness``
    table. One row per source; every poll attempt updates it and recomputes
    the status."""

    def __init__(self, store: "EventStore", clock=None) -> None:
        self._store = store
        self._now = clock or (lambda: datetime.now(timezone.utc))

    def record_attempt(
        self,
        source_type: SourceType,
        *,
        success: bool,
        latest_source_event_utc: datetime | None = None,
    ) -> FreshnessSnapshot:
        now = self._now()
        row = self._store._read_freshness_row(source_type.value)
        prev_failures = row["consecutive_failures"] if row else 0
        prev_success = _parse_dt(row["last_poll_success_utc"]) if row else None
        prev_latest_event = _parse_dt(row["latest_source_event_utc"]) if row else None

        consecutive_failures = 0 if success else prev_failures + 1
        last_success = now if success else prev_success
        latest_event = latest_source_event_utc or prev_latest_event

        status, reason, age = compute_status(
            last_poll_success_utc=last_success,
            consecutive_failures=consecutive_failures,
            now=now,
            thresholds=_thresholds_for(source_type),
            day_hours=is_market_day_hours(now),
        )
        self._store._write_freshness_row(
            source_type=source_type.value,
            last_poll_attempt_utc=now,
            last_poll_success_utc=last_success,
            latest_source_event_utc=latest_event,
            consecutive_failures=consecutive_failures,
            status=status.value,
        )
        return FreshnessSnapshot(
            source_type=source_type.value,
            status=status,
            reason=reason,
            last_poll_attempt_utc=now,
            last_poll_success_utc=last_success,
            latest_source_event_utc=latest_event,
            consecutive_failures=consecutive_failures,
            age_seconds=age,
        )

    def snapshot(self, source_type: SourceType) -> FreshnessSnapshot:
        now = self._now()
        row = self._store._read_freshness_row(source_type.value)
        if row is None:
            return FreshnessSnapshot(
                source_type=source_type.value,
                status=FreshnessStatus.UNKNOWN,
                reason="never_polled",
                last_poll_attempt_utc=None,
                last_poll_success_utc=None,
                latest_source_event_utc=None,
                consecutive_failures=0,
                age_seconds=None,
            )
        last_success = _parse_dt(row["last_poll_success_utc"])
        status, reason, age = compute_status(
            last_poll_success_utc=last_success,
            consecutive_failures=row["consecutive_failures"],
            now=now,
            thresholds=_thresholds_for(source_type),
            day_hours=is_market_day_hours(now),
        )
        return FreshnessSnapshot(
            source_type=source_type.value,
            status=status,
            reason=reason,
            last_poll_attempt_utc=_parse_dt(row["last_poll_attempt_utc"]),
            last_poll_success_utc=last_success,
            latest_source_event_utc=_parse_dt(row["latest_source_event_utc"]),
            consecutive_failures=row["consecutive_failures"],
            age_seconds=age,
        )


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
