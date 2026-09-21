"""
talonx_ingest.intelligence.significance.rules
============================================
One pure function per scoring component family. Each returns a
``(SignificanceComponent, list[SignificanceReason])`` pair. No I/O, no
clock except the ``now`` explicitly passed to :func:`recency`, no store
access — the engine gathers inputs and calls these.

Every non-zero rule hit becomes exactly one ``SignificanceReason`` whose
``points`` sum (with any synthetic cap reason) equals the component's
capped ``points``. Descriptions are deterministic, factual and
language-safe (no direction, no outcome claim).
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.significance.config import (
    COMPONENT_CAPS,
    DECILE_CHANGE_THRESHOLDS,
    EVENT_TYPE_BASE_DEFAULT,
    EVENT_TYPE_BASE_POINTS,
    FILING_CHANGE_DECILE_POINTS,
    FILING_CHANGE_SECTION_KEYS,
    FILING_CHANGE_TERCILE_POINTS,
    FILING_CHANGE_WHOLE_DOC_POINTS,
    HIGH_BASE_RAW_ITEMS,
    INSIDER_CLUSTER_POINTS,
    INSIDER_LARGE_TRANSACTION_POINTS,
    INSIDER_LARGE_TRANSACTION_USD,
    MULTI_ITEM_MIN_COUNT,
    MULTI_ITEM_POINTS,
    NEGATIVE_RISK_KEYWORD_DELTA_THRESHOLD,
    NEW_MATERIAL_PASSAGES_POINTS,
    NON_MATERIAL_ITEMS,
    QUALITY_COMPARISON_FLAGS,
    QUALITY_EVENT_FLAGS,
    QUALITY_INSIDER_FLAGS,
    QUALITY_PENALTY_FLOOR,
    QUALITY_PENALTY_PER_ISSUE,
    RECENCY_FRESH_SECONDS,
    RECENCY_HORIZON_SECONDS,
    RECENCY_POINTS,
    RISK_LANGUAGE_POINTS,
    SIMULTANEOUS_MIN_DISTINCT_TYPES,
    SIMULTANEOUS_POINTS,
    TERCILE_CHANGE_THRESHOLDS,
    WATCHLIST_PINNED_POINTS,
    WATCHLIST_POINTS,
    XBRL_DECILE_ABS_RELATIVE_DELTA,
    XBRL_DECILE_POINTS,
    XBRL_MAGNITUDE_FIELDS,
    XBRL_TERCILE_ABS_RELATIVE_DELTA,
    XBRL_TERCILE_POINTS,
)
from talonx_ingest.intelligence.significance.domain import (
    SignificanceComponent,
    SignificanceReason,
)

# ---------------------------------------------------------------------------
# labels (deterministic, factual — no adjective implying an outcome)
# ---------------------------------------------------------------------------
_EVENT_TYPE_LABEL: dict[EventType, str] = {
    EventType.EARNINGS_RESULTS: "results-of-operations 8-K (Item 2.02)",
    EventType.MATERIAL_AGREEMENT: "material definitive agreement 8-K (Item 1.01)",
    EventType.AGREEMENT_TERMINATED: "material agreement termination 8-K (Item 1.02)",
    EventType.ACQUISITION_DISPOSITION: "asset acquisition or disposition 8-K (Item 2.01)",
    EventType.DEBT_FINANCING: "direct financial obligation 8-K (Item 2.03/2.04)",
    EventType.RESTRUCTURING: "exit or disposal costs 8-K (Item 2.05)",
    EventType.MATERIAL_IMPAIRMENT: "material impairment 8-K (Item 2.06)",
    EventType.DELISTING_NOTICE: "delisting / listing-transfer 8-K (Item 3.01)",
    EventType.EXECUTIVE_CHANGE: "director/officer change 8-K (Item 5.02)",
    EventType.REGULATION_FD: "Regulation FD disclosure 8-K (Item 7.01)",
    EventType.OTHER_MATERIAL_EVENT: "other-events 8-K (Item 8.01)",
    EventType.UNREGISTERED_EQUITY_SALE: "unregistered equity sale 8-K (Item 3.02)",
    EventType.SHAREHOLDER_VOTE_RESULT: "shareholder-vote-results 8-K (Item 5.07)",
    EventType.CHARTER_BYLAW_AMENDMENT: "charter/bylaw amendment 8-K (Item 5.03)",
    EventType.QUARTERLY_FILING: "Form 10-Q quarterly report",
    EventType.ANNUAL_FILING: "Form 10-K annual report",
    EventType.INSIDER_TRANSACTION: "insider ownership filing (Form 3/4/5)",
    EventType.FILING_AMENDMENT: "amendment to a prior filing",
    EventType.UNCLASSIFIED_8K: "8-K (items not individually classified)",
    EventType.UNSUPPORTED_FORM: "filing outside the current coverage set",
    EventType.EARNINGS_EXPECTED: "expected earnings date (unconfirmed)",
}
_SECTION_LABEL = {
    "risk_factors": "Risk Factors",
    "mdna": "MD&A",
    "liquidity": "Liquidity & Capital Resources",
    "whole_document": "whole document",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _finalize(
    code: str,
    substantive: bool,
    hits: list[tuple[str, str, int, str | None]],
    *,
    detail: str = "",
) -> tuple[SignificanceComponent, list[SignificanceReason]]:
    """``hits`` is a list of (reason_code, description, points, evidence_ref).
    Applies the frozen per-category cap (and, for the quality penalty, the
    negative floor), emitting a synthetic cap/floor reason so the reason
    points always sum to the component points."""
    raw = sum(p for _, _, p, _ in hits)
    cap = COMPONENT_CAPS.get(code)
    floor = QUALITY_PENALTY_FLOOR if code == "quality_penalty" else None

    points = raw
    synthetic: tuple[str, str, int, str | None] | None = None
    if cap is not None and raw > cap:
        points = cap
        synthetic = (
            f"{code.upper()}_CONTRIBUTION_CAPPED",
            f"{code.replace('_', ' ')} contribution limited to the frozen category cap ({cap})",
            cap - raw,
            None,
        )
    elif floor is not None and raw < floor:
        points = floor
        synthetic = (
            "QUALITY_PENALTY_FLOORED",
            f"data-quality penalty limited to the frozen floor ({floor})",
            floor - raw,
            None,
        )

    all_hits = list(hits) + ([synthetic] if synthetic else [])
    reasons = [
        SignificanceReason(
            code=rc, description=desc, points=pts, component=code, evidence_ref=ref
        )
        for rc, desc, pts, ref in all_hits
    ]
    comp = SignificanceComponent(
        code=code,
        points=points,
        raw_points=raw,
        substantive=substantive,
        detail=detail or (reasons[0].description if reasons else ""),
    )
    return comp, reasons


def _empty(code: str, substantive: bool, detail: str = "") -> tuple[
    SignificanceComponent, list[SignificanceReason]
]:
    return (
        SignificanceComponent(
            code=code, points=0, raw_points=0, substantive=substantive, detail=detail
        ),
        [],
    )


# ---------------------------------------------------------------------------
# Phase 4 — event-type base significance
# ---------------------------------------------------------------------------
def event_type_base(
    event, *, has_open_market_insider: bool = False
) -> tuple[SignificanceComponent, list[SignificanceReason]]:
    et = event.event_type
    base = EVENT_TYPE_BASE_POINTS.get(et, EVENT_TYPE_BASE_DEFAULT)
    label = _EVENT_TYPE_LABEL.get(et, et.value)

    # an insider parent event only scores when real open-market P/S activity
    # is attached (a grant-only / tax-only Form 4 is routine).
    if et is EventType.INSIDER_TRANSACTION and not has_open_market_insider:
        return _empty(
            "event_type_base",
            substantive=True,
            detail="insider ownership filing with no open-market transaction",
        )

    hits: list[tuple[str, str, int, str | None]] = []
    if base > 0:
        hits.append(("EVENT_TYPE_BASE", f"{label}", base, event.accession))

    # raw item codes that lift the base to +3 (rare / structural), incl.
    # item 1.05 (material cybersecurity incident) which the 96A map omits.
    raw_high = sorted(set(event.filing_items or ()) & HIGH_BASE_RAW_ITEMS)
    for code in raw_high:
        if base < 3:
            bump = 3 - base
            base = 3
            note = (
                "material cybersecurity incident (Item 1.05)"
                if code == "1.05"
                else f"rare structural 8-K item ({code})"
            )
            hits.append(("HIGH_BASE_RAW_ITEM", note, bump, event.accession))
            break

    # a restatement/correction of a periodic or earnings filing is worth a
    # look on top of the base.
    if event.is_amendment and et in (
        EventType.QUARTERLY_FILING,
        EventType.ANNUAL_FILING,
        EventType.EARNINGS_RESULTS,
    ):
        hits.append(
            ("AMENDS_PRIOR_FILING", "amends a previously filed report", 1, event.accession)
        )

    if not hits:
        return _empty("event_type_base", substantive=True, detail=label)
    return _finalize("event_type_base", True, hits, detail=label)


# ---------------------------------------------------------------------------
# Phase 5 — multi-item filing contribution
# ---------------------------------------------------------------------------
def material_items(event) -> tuple[SignificanceComponent, list[SignificanceReason]]:
    material = [c for c in (event.filing_items or ()) if c not in NON_MATERIAL_ITEMS]
    n = len(set(material))
    if n < MULTI_ITEM_MIN_COUNT:
        return _empty(
            "material_items", substantive=True, detail=f"{n} material 8-K item(s)"
        )
    return _finalize(
        "material_items",
        True,
        [
            (
                "MULTI_ITEM_8K",
                f"bundled 8-K carrying {n} distinct material items ({', '.join(sorted(set(material)))})",
                MULTI_ITEM_POINTS,
                event.accession,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Phase 6 — filing-change magnitude + Phase (risk language)
# ---------------------------------------------------------------------------
def _section_map(what_changed: dict) -> dict:
    return what_changed.get("sections", {}) or {}


def filing_change(
    what_changed: dict | None, *, comparison_id: str | None = None
) -> tuple[SignificanceComponent, list[SignificanceReason]]:
    if not what_changed:
        return _empty("filing_change", substantive=True, detail="no filing comparison available")

    hits: list[tuple[str, str, int, str | None]] = []
    sections = _section_map(what_changed)
    for key in FILING_CHANGE_SECTION_KEYS:
        sc = sections.get(key)
        if not sc or sc.get("diff_ratio") is None or sc.get("status") != "FOUND":
            continue
        dr = float(sc["diff_ratio"])
        label = _SECTION_LABEL[key]
        if dr >= DECILE_CHANGE_THRESHOLDS[key]:
            hits.append(
                (
                    "SECTION_CHANGE_DECILE",
                    f"{label} rewrite in the top decile of this filing type's history "
                    f"(change magnitude {dr:.0%})",
                    FILING_CHANGE_DECILE_POINTS,
                    comparison_id,
                )
            )
        elif dr >= TERCILE_CHANGE_THRESHOLDS[key]:
            hits.append(
                (
                    "SECTION_CHANGE_TERCILE",
                    f"{label} changed above the frozen material threshold "
                    f"(change magnitude {dr:.0%})",
                    FILING_CHANGE_TERCILE_POINTS,
                    comparison_id,
                )
            )

    whole = what_changed.get("whole_document")
    if whole and whole.get("diff_ratio") is not None:
        wdr = float(whole["diff_ratio"])
        if wdr >= DECILE_CHANGE_THRESHOLDS["whole_document"]:
            hits.append(
                (
                    "WHOLE_DOCUMENT_CHANGE",
                    f"whole-document rewrite in the top decile of history "
                    f"(change magnitude {wdr:.0%})",
                    FILING_CHANGE_WHOLE_DOC_POINTS,
                    comparison_id,
                )
            )

    new_passages = [
        f
        for f in (what_changed.get("notable_changes") or [])
        if f.get("kind") == "new_material_passages"
    ]
    if new_passages:
        cnt = int(new_passages[0].get("value", 0))
        hits.append(
            (
                "NEW_MATERIAL_PASSAGES",
                f"{cnt} new multi-sentence passage(s) inserted into Risk Factors / MD&A",
                NEW_MATERIAL_PASSAGES_POINTS,
                comparison_id,
            )
        )

    if not hits:
        return _empty("filing_change", substantive=True, detail="filing changes below thresholds")
    return _finalize("filing_change", True, hits)


def risk_language(
    what_changed: dict | None, *, comparison_id: str | None = None
) -> tuple[SignificanceComponent, list[SignificanceReason]]:
    if not what_changed:
        return _empty("risk_language", substantive=True)
    by_cat = (what_changed.get("keywords") or {}).get("by_category") or {}
    neg = by_cat.get("negative_risk")
    if not neg or neg.get("total_delta") is None:
        return _empty("risk_language", substantive=True)
    delta = int(neg["total_delta"])
    if delta < NEGATIVE_RISK_KEYWORD_DELTA_THRESHOLD:
        return _empty(
            "risk_language",
            substantive=True,
            detail=f"risk-term lexicon count change {delta:+d} (below threshold)",
        )
    terms = ", ".join(neg.get("terms_increased", [])[:5])
    return _finalize(
        "risk_language",
        True,
        [
            (
                "RISK_TERM_COUNT_ROSE",
                f"count of frozen risk-term lexicon entries rose by {delta} "
                f"vs the prior filing" + (f" (e.g. {terms})" if terms else ""),
                RISK_LANGUAGE_POINTS,
                comparison_id,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Phase 7 — XBRL fundamental magnitude (absolute value only)
# ---------------------------------------------------------------------------
def xbrl_magnitude(
    what_changed: dict | None, *, comparison_id: str | None = None
) -> tuple[SignificanceComponent, list[SignificanceReason]]:
    if not what_changed:
        return _empty("xbrl_magnitude", substantive=True)
    rows = [
        x
        for x in (what_changed.get("xbrl") or [])
        if x.get("field") in XBRL_MAGNITUDE_FIELDS
        and x.get("status") == "FOUND"
        and x.get("relative_delta") is not None
    ]
    best = None
    for x in rows:
        mag = abs(float(x["relative_delta"]))
        if best is None or mag > best[0]:
            best = (mag, x)
    if best is None:
        return _empty("xbrl_magnitude", substantive=True)

    mag, x = best
    field = x["field"]
    comp = x.get("comparison", "YOY")
    if mag >= XBRL_DECILE_ABS_RELATIVE_DELTA:
        pts, tier = XBRL_DECILE_POINTS, "very large"
    elif mag >= XBRL_TERCILE_ABS_RELATIVE_DELTA:
        pts, tier = XBRL_TERCILE_POINTS, "large"
    else:
        return _empty(
            "xbrl_magnitude",
            substantive=True,
            detail=f"reported {field} {comp} change {mag:.0%} (below threshold)",
        )
    return _finalize(
        "xbrl_magnitude",
        True,
        [
            (
                "XBRL_MAGNITUDE",
                f"{tier} reported {field.replace('_', ' ')} {comp} change "
                f"(magnitude {mag:.0%}; size only, not direction)",
                pts,
                comparison_id,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Phase 8 — insider activity
# ---------------------------------------------------------------------------
def insider_activity(
    activity,
) -> tuple[SignificanceComponent, list[SignificanceReason]]:
    if activity is None:
        return _empty("insider_activity", substantive=True, detail="no insider activity")

    hits: list[tuple[str, str, int, str | None]] = []

    largest = 0.0
    largest_id = None
    for agg in activity.open_market_aggregates:
        v = agg.largest_single_transaction_value
        if v is not None and abs(v) > largest:
            largest = abs(v)
            largest_id = agg.largest_single_transaction_id
    if largest >= INSIDER_LARGE_TRANSACTION_USD:
        hits.append(
            (
                "LARGE_OPEN_MARKET_TRANSACTION",
                f"an open-market insider transaction of about ${largest:,.0f} was reported",
                INSIDER_LARGE_TRANSACTION_POINTS,
                largest_id,
            )
        )

    for c in activity.clusters:
        n = c.distinct_owners
        side = "buyers" if c.kind == "MULTIPLE_OPEN_MARKET_BUYERS" else "sellers"
        hits.append(
            (
                "INSIDER_CLUSTER",
                f"{n} distinct insiders reported open-market {side} within "
                f"{c.window_calendar_days} days",
                INSIDER_CLUSTER_POINTS,
                None,
            )
        )
        break  # at most one cluster contribution (cap handles the rest)

    if not hits:
        return _empty(
            "insider_activity", substantive=True, detail="insider activity below thresholds"
        )
    return _finalize("insider_activity", True, hits)


# ---------------------------------------------------------------------------
# Phase 9 — event rarity (RarityResult -> component)
# ---------------------------------------------------------------------------
def rarity_component(
    rarity_result,
) -> tuple[SignificanceComponent, list[SignificanceReason]]:
    if rarity_result is None or rarity_result.points <= 0:
        return _empty(
            "rarity",
            substantive=True,
            detail=(rarity_result.detail if rarity_result else "rarity not assessed"),
        )
    return _finalize(
        "rarity",
        True,
        [
            (
                f"EVENT_{rarity_result.code}_FOR_FILER",
                rarity_result.detail,
                rarity_result.points,
                "event_store:rarity_count",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Phase 10 — recency
# ---------------------------------------------------------------------------
def recency(
    event, *, now: datetime
) -> tuple[SignificanceComponent, list[SignificanceReason]]:
    ts = event.accepted_at_utc
    if ts is None:
        return _empty("recency", substantive=False, detail="no acceptance timestamp")
    ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    age = (now - ts).total_seconds()
    if age < 0:
        age = 0.0
    if age < RECENCY_FRESH_SECONDS:
        return _finalize(
            "recency",
            False,
            [
                (
                    "RECENT_ARRIVAL",
                    "filing was accepted within the last 2 hours",
                    RECENCY_POINTS,
                    None,
                )
            ],
            detail="FRESH",
        )
    state = "RECENT" if age < RECENCY_HORIZON_SECONDS else "AGED"
    return _empty(
        "recency",
        substantive=False,
        detail=f"{state} (accepted {int(age // 3600)}h ago)",
    )


# ---------------------------------------------------------------------------
# Phase 11 — watchlist relevance
# ---------------------------------------------------------------------------
def watchlist_priority(
    *, on_watchlist: bool, pinned: bool
) -> tuple[SignificanceComponent, list[SignificanceReason]]:
    if pinned:
        return _finalize(
            "watchlist_priority",
            False,
            [
                (
                    "WATCHLIST_PINNED",
                    "this company is pinned on your watchlist (user priority, not market significance)",
                    WATCHLIST_PINNED_POINTS,
                    None,
                )
            ],
        )
    if on_watchlist:
        return _finalize(
            "watchlist_priority",
            False,
            [
                (
                    "ON_WATCHLIST",
                    "this company is on your watchlist (user priority, not market significance)",
                    WATCHLIST_POINTS,
                    None,
                )
            ],
        )
    return _empty("watchlist_priority", substantive=False, detail="not on watchlist")


# ---------------------------------------------------------------------------
# Phase — simultaneous events
# ---------------------------------------------------------------------------
def simultaneous_events(
    *, distinct_type_count: int, window_days: int
) -> tuple[SignificanceComponent, list[SignificanceReason]]:
    if distinct_type_count < SIMULTANEOUS_MIN_DISTINCT_TYPES:
        return _empty(
            "simultaneous_events",
            substantive=True,
            detail=f"{distinct_type_count} distinct event type(s) in {window_days}d",
        )
    return _finalize(
        "simultaneous_events",
        True,
        [
            (
                "EVENT_CLUSTER",
                f"{distinct_type_count} distinct disclosure types from this company within "
                f"{window_days} days",
                SIMULTANEOUS_POINTS,
                "event_store:simultaneous_count",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Phase 12 — data-quality penalty
# ---------------------------------------------------------------------------
def quality_penalty(
    *,
    event,
    comparison=None,
    activity=None,
    source_status: str | None = None,
) -> tuple[SignificanceComponent, list[SignificanceReason]]:
    hits: list[tuple[str, str, int, str | None]] = []

    ev_flags = sorted(set(event.data_quality_flags or ()) & QUALITY_EVENT_FLAGS)
    for f in ev_flags:
        hits.append(
            (
                "EVENT_DATA_INCOMPLETE",
                f"event evidence is incomplete ({f})",
                QUALITY_PENALTY_PER_ISSUE,
                event.accession,
            )
        )

    if comparison is not None:
        cmp_flags = set(comparison.data_quality_flags or ()) & QUALITY_COMPARISON_FLAGS
        if cmp_flags:
            hits.append(
                (
                    "FILING_COMPARISON_INCOMPLETE",
                    "filing comparison evidence is incomplete ("
                    + ", ".join(sorted(cmp_flags))
                    + ")",
                    QUALITY_PENALTY_PER_ISSUE,
                    getattr(comparison, "comparison_id", None),
                )
            )

    if activity is not None:
        ins_flags = set(activity.data_quality_flags or ()) & QUALITY_INSIDER_FLAGS
        if ins_flags:
            hits.append(
                (
                    "INSIDER_DATA_INCOMPLETE",
                    "insider evidence is incomplete ("
                    + ", ".join(sorted(ins_flags))
                    + ")",
                    QUALITY_PENALTY_PER_ISSUE,
                    None,
                )
            )

    if source_status in ("STALE", "DOWN"):
        hits.append(
            (
                "SOURCE_NOT_FRESH",
                f"the SEC source feed was {source_status.lower()} at evaluation time",
                QUALITY_PENALTY_PER_ISSUE,
                None,
            )
        )

    if not hits:
        return _empty("quality_penalty", substantive=False, detail="evidence complete")
    return _finalize("quality_penalty", False, hits)
