"""
talonx_ingest.intelligence.significance.rarity
=============================================
Deterministic, metadata-only event rarity for a filer
(``INFORMATION_SIGNIFICANCE_SPEC.md`` row 2).

"How unusual is a disclosure of this type for this company?" — computed
purely from **event-store metadata** (counts of prior same-type events for
the same symbol). No forward return, no price, no outcome. A coarse band
(``COMMON`` / ``UNCOMMON`` / ``RARE``) plus the point contribution.

Tiny-denominator guard: if the store holds no event for the symbol older
than ``RARITY_MIN_HISTORY_MONTHS`` before the reference instant, rarity is
scored 0 with an ``INSUFFICIENT_HISTORY`` code — a company TalonX only
started tracking last week is not "rare", just unobserved.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.significance.config import (
    RARITY_ABSENT_MONTHS_RARE,
    RARITY_ABSENT_MONTHS_UNCOMMON,
    RARITY_MIN_HISTORY_MONTHS,
    RARITY_RARE_POINTS,
    RARITY_UNCOMMON_POINTS,
)

_DAYS_PER_MONTH = 30.4375


@dataclass(frozen=True)
class RarityResult:
    code: str          # RARE | UNCOMMON | COMMON | INSUFFICIENT_HISTORY
    points: int
    detail: str
    lookback_count_12mo: int
    lookback_count_24mo: int
    earliest_symbol_event_utc: datetime | None


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def event_rarity(
    event_store,
    *,
    symbol: str,
    event_type: EventType,
    as_of: datetime,
    exclude_event_id: str | None = None,
) -> RarityResult:
    """Rarity of ``event_type`` for ``symbol`` as of ``as_of`` (causal —
    only events already accepted by then are counted)."""
    as_of = _as_utc(as_of)
    since_12 = as_of - timedelta(days=RARITY_ABSENT_MONTHS_UNCOMMON * _DAYS_PER_MONTH)
    since_24 = as_of - timedelta(days=RARITY_ABSENT_MONTHS_RARE * _DAYS_PER_MONTH)
    min_hist_cut = as_of - timedelta(days=RARITY_MIN_HISTORY_MONTHS * _DAYS_PER_MONTH)

    prior = [
        e
        for e in event_store.query_events(
            symbol=symbol, event_type=event_type, until=as_of, newest_first=False
        )
        if e.event_id != exclude_event_id and e.accepted_at_utc is not None
    ]
    n12 = sum(1 for e in prior if _as_utc(e.accepted_at_utc) >= since_12)
    n24 = sum(1 for e in prior if _as_utc(e.accepted_at_utc) >= since_24)

    all_for_symbol = event_store.query_events(
        symbol=symbol, until=as_of, newest_first=False, limit=1
    )
    earliest = (
        _as_utc(all_for_symbol[0].accepted_at_utc)
        if all_for_symbol and all_for_symbol[0].accepted_at_utc
        else None
    )

    if earliest is None or earliest > min_hist_cut:
        return RarityResult(
            code="INSUFFICIENT_HISTORY",
            points=0,
            detail=(
                "not enough tracked history for this company to assess how unusual "
                "this filing type is"
            ),
            lookback_count_12mo=n12,
            lookback_count_24mo=n24,
            earliest_symbol_event_utc=earliest,
        )

    if n24 == 0:
        return RarityResult(
            code="RARE",
            points=RARITY_RARE_POINTS,
            detail=f"this company has not filed a {event_type.value} event in 24 months of tracked history",
            lookback_count_12mo=n12,
            lookback_count_24mo=n24,
            earliest_symbol_event_utc=earliest,
        )
    if n12 == 0:
        return RarityResult(
            code="UNCOMMON",
            points=RARITY_UNCOMMON_POINTS,
            detail=f"this company has not filed a {event_type.value} event in the last 12 months",
            lookback_count_12mo=n12,
            lookback_count_24mo=n24,
            earliest_symbol_event_utc=earliest,
        )
    return RarityResult(
        code="COMMON",
        points=0,
        detail=f"this company filed {n12} {event_type.value} event(s) in the last 12 months",
        lookback_count_12mo=n12,
        lookback_count_24mo=n24,
        earliest_symbol_event_utc=earliest,
    )
