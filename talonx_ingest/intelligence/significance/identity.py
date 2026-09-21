"""
talonx_ingest.intelligence.significance.identity
===============================================
Deterministic, restart-stable identity + input fingerprint for a
significance evaluation.

``significance_id = "SIG:{event_id}:{ruleset_version}"``
    Same event + same ruleset -> same id (safe upsert). A ``RULESET_VERSION``
    bump changes the id, so an old score and a re-computed one are both
    addressable and neither silently overwrites the other.

``input_fingerprint``
    sha256 over the *substantive* inputs to the evaluation — event identity
    + classification, the filing-comparison content, the insider-activity
    content, and the watchlist flags. It deliberately EXCLUDES ``now`` (and
    therefore the recency contribution): recency changes every minute and
    must not, by itself, force a re-evaluation. ``recompute.needs_recompute``
    fires on a fingerprint change (new comparison, new insider transaction,
    watchlist change) or a ruleset change.
"""
from __future__ import annotations

from talonx_ingest.intelligence.identity import source_hash
from talonx_ingest.intelligence.significance.config import RULESET_VERSION


def significance_id(event_id: str, *, ruleset_version: str = RULESET_VERSION) -> str:
    return f"SIG:{event_id}:{ruleset_version}"


def _event_part(event) -> str:
    if event is None:
        return "event=NONE"
    return "|".join(
        [
            "event",
            str(event.event_id),
            str(getattr(event.event_type, "value", event.event_type)),
            str(event.form_type or ""),
            ",".join(event.filing_items or ()),
            (event.accepted_at_utc.isoformat() if event.accepted_at_utc else ""),
            str(event.source_hash or ""),
            ",".join(sorted(event.data_quality_flags or ())),
            "AMEND" if event.is_amendment else "ORIG",
        ]
    )


def _comparison_part(comparison) -> str:
    if comparison is None:
        return "comparison=NONE"
    w = comparison.whole_document_change
    secs = "&".join(
        f"{s.section_type.value}:{s.status.value}:{'' if s.diff_ratio is None else round(s.diff_ratio, 6)}"
        for s in comparison.section_changes
    )
    xbrl = "&".join(
        f"{x.field}:{x.comparison.value}:{'' if x.relative_delta is None else round(x.relative_delta, 6)}:{x.status}"
        for x in comparison.xbrl_changes
    )
    kw = "&".join(
        f"{s.category.value}:{s.total_delta}" for s in comparison.keyword_category_summaries
    )
    return "|".join(
        [
            "comparison",
            str(comparison.comparison_id),
            str(comparison.current_document_hash or ""),
            str(comparison.prior_document_hash or ""),
            ("" if w is None else f"whole:{round(w.diff_ratio, 6)}:{int(w.exceeds_material_threshold)}"),
            secs,
            xbrl,
            kw,
            str(len(comparison.new_passages)),
            ",".join(sorted(comparison.data_quality_flags or ())),
        ]
    )


def _insider_part(activity) -> str:
    if activity is None:
        return "insider=NONE"
    aggs = "&".join(
        f"{a.window_calendar_days}:{a.transaction_count}:{'' if a.largest_single_transaction_value is None else round(a.largest_single_transaction_value, 2)}"
        f":{a.distinct_purchasers}:{a.distinct_sellers}"
        for a in activity.open_market_aggregates
    )
    clusters = "&".join(f"{c.kind}:{c.distinct_owners}" for c in activity.clusters)
    txn_ids = ",".join(sorted(t.transaction_id for t in activity.transactions))
    return "|".join(
        [
            "insider",
            activity.symbol,
            activity.as_of_date.isoformat(),
            aggs,
            clusters,
            txn_ids,
            ",".join(sorted(activity.data_quality_flags or ())),
        ]
    )


def _watchlist_part(*, on_watchlist: bool, pinned: bool) -> str:
    return f"watchlist:{int(bool(on_watchlist))}:{int(bool(pinned))}"


def _context_part(*, simultaneous_types: int, rarity_code: str, source_status: str) -> str:
    return f"context:sim={int(simultaneous_types)}:rarity={rarity_code}:src={source_status}"


def input_fingerprint(
    *,
    event,
    comparison=None,
    insider_activity=None,
    on_watchlist: bool = False,
    pinned: bool = False,
    simultaneous_types: int = 0,
    rarity_code: str = "NA",
    source_status: str = "NA",
    ruleset_version: str = RULESET_VERSION,
) -> str:
    """Deterministic sha256 of every input that can change the score, with
    the sole, deliberate exception of wall-clock ``now`` (recency)."""
    return source_hash(
        "significance_input_fingerprint@v1",
        ruleset_version,
        _event_part(event),
        _comparison_part(comparison),
        _insider_part(insider_activity),
        _watchlist_part(on_watchlist=on_watchlist, pinned=pinned),
        _context_part(
            simultaneous_types=simultaneous_types,
            rarity_code=rarity_code,
            source_status=source_status,
        ),
    )
