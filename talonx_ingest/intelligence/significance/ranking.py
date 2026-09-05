"""
talonx_ingest.intelligence.significance.ranking
=============================================
Deterministic watchlist / event ranking on top of the stored
``InformationSignificance`` rows (``WATCHLIST_RANKING_SPEC.md``).

Ranks by **information significance** — "which of my names has something
worth looking at right now" — never by expected return. Every ordering is
fully deterministic; ties break on stable keys, never on a price move.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from talonx_ingest.intelligence.domain import EventType, SignificanceBand
from talonx_ingest.intelligence.significance.config import (
    RULESET_VERSION,
    SIMULTANEOUS_WINDOW_DAYS,
    _BAND_ORDER,
)
from talonx_ingest.intelligence.significance.domain import InformationSignificance

_BAND_MIN_ORDER = _BAND_ORDER


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class RankedEvent:
    significance: InformationSignificance
    event_type: EventType | None
    accepted_at_utc: datetime | None

    @property
    def symbol(self) -> str:
        return self.significance.symbol

    @property
    def band(self) -> SignificanceBand:
        return self.significance.band

    @property
    def score(self) -> int:
        return self.significance.score

    @property
    def why(self) -> tuple[str, ...]:
        return self.significance.reason_strings()


@dataclass
class RankedSymbol:
    symbol: str
    band: SignificanceBand
    score: int
    distinct_event_types: int
    latest_event_utc: datetime | None
    pinned: bool
    top_event: RankedEvent | None
    events: list[RankedEvent] = field(default_factory=list)

    @property
    def why(self) -> tuple[str, ...]:
        return self.top_event.why if self.top_event else ()


def _min_band_ok(band: SignificanceBand, minimum: SignificanceBand | None) -> bool:
    if minimum is None:
        return True
    return _BAND_MIN_ORDER[band] >= _BAND_MIN_ORDER[minimum]


def rank_events(
    store,
    *,
    symbols: list[str] | set[str] | None = None,
    min_band: SignificanceBand | None = None,
    event_type: EventType | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    ruleset_version: str = RULESET_VERSION,
    limit: int | None = None,
    event_lookup=None,
) -> list[RankedEvent]:
    """Latest significant events, ranked. Tie-breakers (all deterministic):
    ``score`` desc, then ``accepted_at_utc`` desc, then ``event_id`` asc.

    ``event_lookup`` (optional): ``event_id -> TextEvent`` (or object with
    ``event_type`` / ``accepted_at_utc``), used to enrich the row and to
    honour ``event_type`` / ``since`` / ``until`` filters against the event's
    own acceptance time rather than the evaluation time.
    """
    rows = store.query(ruleset_version=ruleset_version, limit=None)
    sym_filter = {s.upper() for s in symbols} if symbols else None

    out: list[RankedEvent] = []
    for sig in rows:
        if sym_filter is not None and sig.symbol not in sym_filter:
            continue
        if not _min_band_ok(sig.band, min_band):
            continue
        et = None
        accepted = None
        if event_lookup is not None:
            ev = event_lookup(sig.event_id)
            if ev is not None:
                et = getattr(ev, "event_type", None)
                accepted = _as_utc(getattr(ev, "accepted_at_utc", None))
        if event_type is not None and et is not None and et is not event_type:
            continue
        ref_time = accepted or _as_utc(sig.evaluated_at_utc)
        if since is not None and ref_time is not None and ref_time < _as_utc(since):
            continue
        if until is not None and ref_time is not None and ref_time > _as_utc(until):
            continue
        out.append(RankedEvent(significance=sig, event_type=et, accepted_at_utc=accepted))

    out.sort(
        key=lambda r: (
            -r.significance.score,
            -( (r.accepted_at_utc or _as_utc(r.significance.evaluated_at_utc)
                or datetime.min.replace(tzinfo=timezone.utc)).timestamp() ),
            r.significance.event_id,
        )
    )
    return out[:limit] if limit is not None else out


def rank_watchlist_symbols(
    store,
    *,
    watchlist: list[str] | set[str],
    pinned: set[str] | None = None,
    trailing_days: int = SIMULTANEOUS_WINDOW_DAYS,
    now: datetime | None = None,
    ruleset_version: str = RULESET_VERSION,
    event_lookup=None,
) -> list[RankedSymbol]:
    """One row per watchlist symbol, ranked by the maximum event score in
    the trailing window. Tie-breakers: band, then distinct ``event_type``
    count, then latest-event recency, then pinned-first, then symbol.

    A symbol with no event in the window is still returned (a "quiet" row)
    with ``band = LOW`` and ``score = 0``, sorted after the active rows.
    """
    now = _as_utc(now) or datetime.now(timezone.utc)
    pinned = {s.upper() for s in (pinned or set())}
    cutoff = now - timedelta(days=trailing_days)

    all_events = rank_events(
        store, ruleset_version=ruleset_version, event_lookup=event_lookup
    )
    by_symbol: dict[str, list[RankedEvent]] = {}
    for re_ in all_events:
        ref = re_.accepted_at_utc or _as_utc(re_.significance.evaluated_at_utc)
        if ref is None or ref < cutoff or ref > now:
            continue
        by_symbol.setdefault(re_.symbol, []).append(re_)

    rows: list[RankedSymbol] = []
    for sym in sorted({s.upper() for s in watchlist}):
        evs = sorted(
            by_symbol.get(sym, []),
            key=lambda r: (
                -r.significance.score,
                -((r.accepted_at_utc or _as_utc(r.significance.evaluated_at_utc)
                   or datetime.min.replace(tzinfo=timezone.utc)).timestamp()),
                r.significance.event_id,
            ),
        )
        if evs:
            top = evs[0]
            distinct_types = len({e.event_type for e in evs if e.event_type is not None})
            latest = max(
                (e.accepted_at_utc or _as_utc(e.significance.evaluated_at_utc) for e in evs),
                default=None,
            )
            rows.append(
                RankedSymbol(
                    symbol=sym,
                    band=top.band,
                    score=top.score,
                    distinct_event_types=distinct_types,
                    latest_event_utc=latest,
                    pinned=sym in pinned,
                    top_event=top,
                    events=evs,
                )
            )
        else:
            rows.append(
                RankedSymbol(
                    symbol=sym,
                    band=SignificanceBand.LOW,
                    score=0,
                    distinct_event_types=0,
                    latest_event_utc=None,
                    pinned=sym in pinned,
                    top_event=None,
                    events=[],
                )
            )

    def _key(r: RankedSymbol):
        return (
            0 if r.events else 1,                       # active rows first
            -r.score,
            -_BAND_MIN_ORDER[r.band],
            -r.distinct_event_types,
            -((r.latest_event_utc or datetime.min.replace(tzinfo=timezone.utc)).timestamp()),
            0 if r.pinned else 1,
            r.symbol,
        )

    rows.sort(key=_key)
    return rows
