"""
talonx_ingest.intelligence.significance.pipeline
==============================================
Thin orchestration: gather the deterministic evidence for one event from
the 96A / 96C / 96D stores, evaluate its significance, and (optionally)
persist it.

No delivery, no rendering, no quant, no network. Every input is read-only
metadata already in ``ingestion_ledger.db``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from talonx_ingest.intelligence.domain import EventType, utc_now
from talonx_ingest.intelligence.significance.config import (
    RULESET_VERSION,
    SIMULTANEOUS_WINDOW_DAYS,
)
from talonx_ingest.intelligence.significance.domain import InformationSignificance
from talonx_ingest.intelligence.significance.engine import evaluate_significance
from talonx_ingest.intelligence.significance.identity import significance_id
from talonx_ingest.intelligence.significance.rarity import event_rarity
from talonx_ingest.intelligence.significance.recompute import needs_recompute

_PERIODIC = (EventType.QUARTERLY_FILING, EventType.ANNUAL_FILING)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def simultaneous_event_types(
    event_store,
    *,
    symbol: str,
    as_of: datetime,
    window_days: int = SIMULTANEOUS_WINDOW_DAYS,
) -> int:
    """Count of DISTINCT ``event_type`` values for ``symbol`` with an
    acceptance time in ``[as_of - window_days, as_of]`` (backward-looking
    only — causal)."""
    as_of = _as_utc(as_of)
    if as_of is None:
        return 0
    since = as_of - timedelta(days=window_days)
    evs = event_store.query_events(symbol=symbol, since=since, until=as_of)
    return len({e.event_type for e in evs})


@dataclass
class SignificanceEvalResult:
    significance: InformationSignificance
    recompute_reason: str
    persisted: bool
    was_new: bool


def evaluate_event(
    event,
    *,
    event_store,
    comparison_store=None,
    insider_store=None,
    insider_activity=None,
    on_watchlist: bool = False,
    pinned: bool = False,
    source_status: str | None = None,
    now: datetime | None = None,
    ruleset_version: str = RULESET_VERSION,
    store=None,
    force: bool = False,
) -> SignificanceEvalResult:
    """Evaluate one ``TextEvent`` end-to-end.

    * pulls the filing comparison for a periodic event from ``comparison_store``;
    * builds/accepts an ``InsiderActivity`` for an insider event;
    * computes rarity + simultaneous-event context from ``event_store``;
    * if ``store`` is given, checks ``needs_recompute`` and upserts.
    """
    now = _as_utc(now) or utc_now()
    as_of = _as_utc(event.accepted_at_utc) or now

    comparison = None
    if comparison_store is not None and event.event_type in _PERIODIC:
        comparison = comparison_store.get_comparison_for_current_event(event.event_id)

    if (
        insider_activity is None
        and insider_store is not None
        and event.event_type is EventType.INSIDER_TRANSACTION
    ):
        insider_activity = _insider_activity_for_filing(insider_store, event, as_of)

    rarity_result = event_rarity(
        event_store,
        symbol=event.symbol,
        event_type=event.event_type,
        as_of=as_of,
        exclude_event_id=event.event_id,
    )
    sim = simultaneous_event_types(event_store, symbol=event.symbol, as_of=as_of)

    sig = evaluate_significance(
        event,
        comparison=comparison,
        insider_activity=insider_activity,
        rarity_result=rarity_result,
        on_watchlist=on_watchlist,
        pinned=pinned,
        simultaneous_type_count=sim,
        source_status=source_status,
        now=now,
        ruleset_version=ruleset_version,
    )

    recompute_reason = "not persisted"
    persisted = False
    was_new = False
    if store is not None:
        existing = store.get_for_event(event.event_id, ruleset_version=ruleset_version)
        decision = needs_recompute(
            existing, new_fingerprint=sig.input_fingerprint, ruleset_version=ruleset_version
        )
        recompute_reason = decision.reason
        if decision.needed or force:
            was_new = store.upsert(sig)
            persisted = True
        else:
            sig = existing  # keep the stored one; nothing substantive changed

    return SignificanceEvalResult(
        significance=sig,
        recompute_reason=recompute_reason,
        persisted=persisted,
        was_new=was_new,
    )


def _insider_activity_for_filing(insider_store, event, as_of):
    """Build an ``InsiderActivity`` for the issuer of one Form 3/4/5 parent
    event, using only transactions knowable as of ``as_of`` (the 96D
    pipeline helper handles the causal cutoff)."""
    from talonx_ingest.intelligence.insider.pipeline import (
        build_insider_activity as _build,
    )

    as_of_date = as_of.date() if hasattr(as_of, "date") else as_of
    activity = _build(insider_store, event.symbol, as_of_date=as_of_date, now=as_of)
    if not activity.transactions and not activity.latest_filings:
        return None
    return activity
