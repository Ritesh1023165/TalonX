"""
talonx_ingest.intelligence.significance.engine
=============================================
``evaluate_significance`` — the deterministic composer.

Pure: given the same inputs and the same ``now`` it returns the same
``InformationSignificance`` every time. It gathers each component
(``rules.py``), sums the capped contributions into an integer score,
maps the score to a band via the FROZEN thresholds, then applies the
CRITICAL / HIGH structural floors (``CRITICAL_BAND_POLICY.md``) and the
data-quality band cap. Every point is carried by a named reason; the
reason points always sum to the final score.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_ingest.intelligence.comparison.whatchanged import build_what_changed
from talonx_ingest.intelligence.domain import SignificanceBand, utc_now
from talonx_ingest.intelligence.significance import rules
from talonx_ingest.intelligence.significance.config import (
    CRITICAL_MIN_SUBSTANTIVE_FAMILIES,
    CRITICAL_MIN_SUBSTANTIVE_POINTS,
    HIGH_MIN_SUBSTANTIVE_POINTS,
    NON_SUBSTANTIVE_ONLY_BAND,
    QUALITY_BAND_CAP_TRIGGERS,
    QUALITY_COMPARISON_FLAGS,
    RULESET_VERSION,
    SCORE_FLOOR,
    SCORE_TOTAL_CAP,
    SIMULTANEOUS_WINDOW_DAYS,
    band_for_score,
    min_band,
)
from talonx_ingest.intelligence.significance.domain import (
    InformationSignificance,
    SignificanceReason,
)
from talonx_ingest.intelligence.significance.identity import (
    input_fingerprint,
    significance_id,
)

_COMPARISON_QUALITY = frozenset(QUALITY_COMPARISON_FLAGS)


def _has_open_market_insider(activity) -> bool:
    if activity is None:
        return False
    if any(a.transaction_count > 0 for a in activity.open_market_aggregates):
        return True
    return any(t.is_open_market_discretionary for t in activity.transactions)


def evaluate_significance(
    event,
    *,
    comparison=None,
    insider_activity=None,
    rarity_result=None,
    on_watchlist: bool = False,
    pinned: bool = False,
    simultaneous_type_count: int = 0,
    source_status: str | None = None,
    now: datetime | None = None,
    ruleset_version: str = RULESET_VERSION,
) -> InformationSignificance:
    now = now or utc_now()
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    what_changed = build_what_changed(comparison) if comparison is not None else None
    hom_insider = _has_open_market_insider(insider_activity)
    cmp_id = getattr(comparison, "comparison_id", None)

    ordered = [
        rules.event_type_base(event, has_open_market_insider=hom_insider),
        rules.material_items(event),
        rules.filing_change(what_changed, comparison_id=cmp_id),
        rules.risk_language(what_changed, comparison_id=cmp_id),
        rules.xbrl_magnitude(what_changed, comparison_id=cmp_id),
        rules.insider_activity(insider_activity),
        rules.rarity_component(rarity_result),
        rules.simultaneous_events(
            distinct_type_count=simultaneous_type_count,
            window_days=SIMULTANEOUS_WINDOW_DAYS,
        ),
        rules.recency(event, now=now),
        rules.watchlist_priority(on_watchlist=on_watchlist, pinned=pinned),
        rules.quality_penalty(
            event=event,
            comparison=comparison,
            activity=insider_activity,
            source_status=source_status,
        ),
    ]
    components = [c for c, _ in ordered]
    reasons: list[SignificanceReason] = []
    for _, rs in ordered:
        reasons.extend(rs)

    raw_score = sum(c.points for c in components)
    score = max(SCORE_FLOOR, min(SCORE_TOTAL_CAP, raw_score))
    if score != raw_score:
        delta = score - raw_score
        code = "SCORE_CAPPED" if delta < 0 else "SCORE_FLOORED"
        reasons.append(
            SignificanceReason(
                code=code,
                description=(
                    f"total significance score {'limited to' if delta < 0 else 'raised to'} "
                    f"the frozen {'cap' if delta < 0 else 'floor'} "
                    f"({SCORE_TOTAL_CAP if delta < 0 else SCORE_FLOOR})"
                ),
                points=delta,
                component="score_total",
                evidence_ref=None,
            )
        )

    substantive_points = sum(
        c.points for c in components if c.substantive and c.points > 0
    )
    substantive_families = sum(
        1 for c in components if c.substantive and c.points > 0
    )

    band = band_for_score(score)
    caps: list[str] = []

    if band is SignificanceBand.CRITICAL and not (
        substantive_points >= CRITICAL_MIN_SUBSTANTIVE_POINTS
        and substantive_families >= CRITICAL_MIN_SUBSTANTIVE_FAMILIES
    ):
        band = SignificanceBand.HIGH
        caps.append(
            f"CRITICAL held to HIGH: needs >= {CRITICAL_MIN_SUBSTANTIVE_POINTS} substantive "
            f"points across >= {CRITICAL_MIN_SUBSTANTIVE_FAMILIES} families "
            f"(had {substantive_points} / {substantive_families})"
        )

    if band is SignificanceBand.HIGH and substantive_points < HIGH_MIN_SUBSTANTIVE_POINTS:
        band = SignificanceBand.MEDIUM
        caps.append(
            f"HIGH held to MEDIUM: needs >= {HIGH_MIN_SUBSTANTIVE_POINTS} substantive points "
            f"(had {substantive_points})"
        )

    if substantive_points <= 0:
        capped = min_band(band, NON_SUBSTANTIVE_ONLY_BAND)
        if capped is not band:
            caps.append(
                "band held to LOW: no substantive evidence "
                "(recency / watchlist priority only)"
            )
            band = capped

    triggers = set()
    if "missing_acceptance_timestamp" in (event.data_quality_flags or ()):
        triggers.add("missing_acceptance_timestamp")
    if source_status == "DOWN":
        triggers.add("source_down")
    if triggers & QUALITY_BAND_CAP_TRIGGERS:
        capped = min_band(band, SignificanceBand.MEDIUM)
        if capped is not band:
            caps.append(
                "band held to MEDIUM by a data-quality trigger ("
                + ", ".join(sorted(triggers & QUALITY_BAND_CAP_TRIGGERS))
                + ")"
            )
            band = capped

    # output quality flags: the actually-contributing issues
    qflags: set[str] = set()
    qflags |= set(event.data_quality_flags or ()) & rules.QUALITY_EVENT_FLAGS
    if comparison is not None:
        qflags |= set(comparison.data_quality_flags or ()) & _COMPARISON_QUALITY
    if insider_activity is not None:
        qflags |= set(insider_activity.data_quality_flags or ()) & rules.QUALITY_INSIDER_FLAGS
    if source_status in ("STALE", "DOWN"):
        qflags.add(f"source_{source_status.lower()}")
    if rarity_result is not None and rarity_result.code == "INSUFFICIENT_HISTORY":
        qflags.add("rarity_insufficient_history")

    inputs_present = ["event"]
    if comparison is not None:
        inputs_present.append("comparison")
    if insider_activity is not None:
        inputs_present.append("insider")
    if on_watchlist or pinned:
        inputs_present.append("watchlist")

    fp = input_fingerprint(
        event=event,
        comparison=comparison,
        insider_activity=insider_activity,
        on_watchlist=on_watchlist,
        pinned=pinned,
        simultaneous_types=simultaneous_type_count,
        rarity_code=(rarity_result.code if rarity_result is not None else "NA"),
        source_status=source_status or "NA",
        ruleset_version=ruleset_version,
    )

    return InformationSignificance(
        significance_id=significance_id(event.event_id, ruleset_version=ruleset_version),
        ruleset_version=ruleset_version,
        event_id=event.event_id,
        symbol=event.symbol,
        score=score,
        band=band,
        raw_score=raw_score,
        reasons=tuple(reasons),
        components=tuple(components),
        substantive_points=substantive_points,
        substantive_families=substantive_families,
        data_quality_flags=tuple(sorted(qflags)),
        inputs_present=tuple(inputs_present),
        band_caps_applied=tuple(caps),
        input_fingerprint=fp,
        evaluated_at_utc=now,
    )
