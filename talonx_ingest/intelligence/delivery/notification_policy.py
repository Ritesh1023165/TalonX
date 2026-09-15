"""
talonx_ingest.intelligence.delivery.notification_policy
=========================================================
Task 138 Workstream 2 -- deterministic delivery-disposition policy.
Full rationale, thresholds and representative examples:
``docs/research/NOTIFICATION_POLICY.md``.

A NOTIFICATION policy (what interrupts the operator), not an
economically-validated trading threshold. Reuses only EXISTING,
already-established significance/comparison/insider signals -- it never
invents a new materiality threshold, never touches significance scoring
itself, and never changes which route (``ROUTE_IMMEDIATE``/
``ROUTE_DIGEST``) exists -- it only decides which of the two an
otherwise-HIGH/MEDIUM-band card actually uses, plus a third,
non-delivery outcome (``DASHBOARD_ONLY``: skip the outbox entirely).
"""
from __future__ import annotations

from dataclasses import dataclass

from talonx_ingest.intelligence.domain import SignificanceBand

DISPOSITION_IMMEDIATE = "IMMEDIATE"
DISPOSITION_DIGEST = "DIGEST"
DISPOSITION_DASHBOARD_ONLY = "DASHBOARD_ONLY"

# Reason CODES (SignificanceReason.code, from the significance engine's
# OWN already-computed reasons -- rules.py) that, on their own, represent
# a SPECIFIC, already-thresholded substantive change -- not "a filing of
# this type arrived" or "this issuer is on the watchlist". Each of these
# codes is only ever emitted after crossing a pre-existing, frozen
# threshold defined in significance/config.py (decile/tercile change
# magnitude, risk-keyword delta, XBRL magnitude) -- this module does not
# duplicate or re-derive those comparisons, it only checks whether the
# engine already found one.
SUBSTANTIVE_REASON_CODES = frozenset({
    "SECTION_CHANGE_DECILE",
    "SECTION_CHANGE_TERCILE",
    "WHOLE_DOCUMENT_CHANGE",
    "NEW_MATERIAL_PASSAGES",
    "RISK_TERM_COUNT_ROSE",
    "XBRL_MAGNITUDE",
    "LARGE_OPEN_MARKET_TRANSACTION",
})

# Deliberately NOT substantive on their own (see policy doc §3.4):
# EVENT_TYPE_BASE (form/item number alone), ON_WATCHLIST/WATCHLIST_PINNED
# (watchlist membership alone), MULTI_ITEM_8K (multiple disclosure types
# alone), INSIDER_CLUSTER (fires identically for buy OR sell -- checked
# separately, buy-side only, via the raw cluster list below).
_BUY_CLUSTER_KIND = "MULTIPLE_OPEN_MARKET_BUYERS"


@dataclass(frozen=True)
class DispositionDecision:
    disposition: str          # IMMEDIATE | DIGEST | DASHBOARD_ONLY
    reason: str                # internal, policy-level explanation (audit log) --
                                # NOT the user-facing message text
    evidence_text: str | None = None
    # Task 140 (post-Task-138 stricter requirement): the SPECIFIC,
    # supported fact sentence that justified an IMMEDIATE decision --
    # e.g. "Risk Factors rewrite in the top decile of this filing type's
    # history (change magnitude 34%)" or "3 distinct insiders bought in
    # the open market within 7 days (4 transactions, ~$1,250,000 total)".
    # Populated ONLY from an already-persisted, already-evidenced source
    # (a SignificanceReason.description the engine already computed with
    # real numbers baked in, or the InsiderCluster's own structured
    # fields) -- never invented here. `None` when no such text exists (a
    # DIGEST/DASHBOARD_ONLY verdict, or -- defensively -- a CRITICAL card
    # whose reasons somehow carried no description at all). This is what
    # the renderer and reply-details response must show; `reason` above
    # is deliberately NOT reused for that (see the Task 140 fix note in
    # enrichment.py: reason used to leak into the message as a generic
    # "band with a substantive trigger present: [CODE]" placeholder).


def _has_buy_cluster(insider_activity):
    """Returns the matching InsiderCluster object (not just a bool) so
    its own real fields (distinct_owners, window_calendar_days,
    transaction_count, total_value) can build genuine evidence text --
    never a bare presence check alone."""
    if insider_activity is None:
        return None
    clusters = getattr(insider_activity, "clusters", None) or ()
    for c in clusters:
        if getattr(c, "kind", None) == _BUY_CLUSTER_KIND:
            return c
    return None


def _cluster_evidence_text(cluster) -> str:
    n = cluster.distinct_owners
    window = cluster.window_calendar_days
    txns = getattr(cluster, "transaction_count", 0) or 0
    total = getattr(cluster, "total_value", None)
    detail = f"{n} distinct insiders bought in the open market within {window} days"
    extra = []
    if txns:
        extra.append(f"{txns} transaction{'s' if txns != 1 else ''}")
    if total:
        extra.append(f"~${total:,.0f} total")
    if extra:
        detail += f" ({', '.join(extra)})"
    return detail


def _substantive_evidence(reasons) -> tuple[set, str | None]:
    """``reasons`` is an iterable of the significance engine's own
    ``SignificanceReason`` objects (NOT bare code strings -- Task 140:
    checking the code alone, without validating its own supporting
    description field is genuinely populated, is exactly the
    reason-code-only bypass this closes). Returns (hit_codes,
    evidence_text) -- evidence_text is the FIRST substantive reason's own
    ``description`` (already a real, specific, already-computed fact
    sentence -- see rules.py's ``filing_change``/``insider_activity``),
    or ``None`` if a substantive code is present but its own description
    is empty/whitespace (a genuine content-gate failure, not assumed
    impossible)."""
    reasons = list(reasons or ())
    hits = {r.code for r in reasons if getattr(r, "code", None) in SUBSTANTIVE_REASON_CODES}
    if not hits:
        return hits, None
    for r in reasons:
        if r.code in hits and (r.description or "").strip():
            return hits, r.description
    return hits, None    # codes present but no genuine supporting text -- fails the content gate


def classify_disposition(
    *, band: "SignificanceBand | str | None", reasons=(), insider_activity=None,
) -> DispositionDecision:
    """Pure, deterministic. ``reasons`` is an iterable of the
    significance engine's own ``SignificanceReason`` objects for this
    event (e.g. ``sig.reasons``) -- Task 140: the FULL objects, not bare
    code strings, because eligibility now requires validating each
    reason's own supporting ``description`` text is genuinely populated,
    not merely that its code is a recognized substantive one.
    ``insider_activity`` is the same object already built for card
    rendering/significance (may be ``None`` for a non-insider event)."""
    band_val = band.value if isinstance(band, SignificanceBand) else band
    reasons = list(reasons or ())

    if band_val == SignificanceBand.CRITICAL.value:
        # The engine's own structural floor (>=2 substantive families,
        # >=5 substantive points) already gates CRITICAL strictly -- this
        # policy does not re-derive that. But the MESSAGE must still show
        # real evidence, not a bare band label: prefer the highest-point
        # reason with a genuine description among the ones that already
        # crossed a substantive threshold in this event's own scoring.
        _, ev = _substantive_evidence(reasons)
        if ev is None and reasons:
            # CRITICAL's floor can also be reached by insider-cluster/
            # dollar-magnitude reasons outside SUBSTANTIVE_REASON_CODES's
            # filing-change subset -- fall back to the highest-point
            # reason with ANY real description, still never inventing text.
            with_desc = [r for r in reasons if (r.description or "").strip()]
            if with_desc:
                ev = max(with_desc, key=lambda r: r.points).description
        return DispositionDecision(
            DISPOSITION_IMMEDIATE,
            "CRITICAL band -- the engine's own structural floor already "
            "requires >=2 substantive scoring families before reaching "
            "CRITICAL, so this policy does not re-derive substantiveness.",
            evidence_text=ev,
        )
    if band_val == SignificanceBand.LOW.value or band_val is None:
        return DispositionDecision(
            DISPOSITION_DASHBOARD_ONLY,
            f"{band_val or 'no'} band -- no scoring signal worth a digest slot.",
        )

    # MEDIUM / HIGH: require an explicit substantive trigger AND its own
    # genuine, already-computed supporting fact text -- Task 140: a
    # recognized code with no real description behind it does NOT
    # qualify (falls through to DIGEST, content-gated, not suppressed).
    hits, evidence = _substantive_evidence(reasons)
    if hits and evidence:
        return DispositionDecision(
            DISPOSITION_IMMEDIATE,
            f"{band_val} band with a substantive, evidenced trigger present: {sorted(hits)}.",
            evidence_text=evidence,
        )
    cluster = _has_buy_cluster(insider_activity)
    if cluster is not None:
        return DispositionDecision(
            DISPOSITION_IMMEDIATE,
            f"{band_val} band with a >=2-distinct-insider open-market BUY "
            "cluster present.",
            evidence_text=_cluster_evidence_text(cluster),
        )
    if hits and not evidence:
        return DispositionDecision(
            DISPOSITION_DIGEST,
            f"{band_val} band: substantive code(s) {sorted(hits)} present but no "
            "genuine supporting description found on the reason itself -- content "
            "gate not satisfied, routed to DIGEST rather than trusting the code alone.",
        )
    return DispositionDecision(
        DISPOSITION_DIGEST,
        f"{band_val} band but no substantive trigger present (routed to DIGEST, "
        "not suppressed -- band/watchlist/item-number/multi-item/sell-cluster "
        "alone do not justify an immediate interruption).",
    )


# ---------------------------------------------------------------------
# Bounded, idempotent reclassification of the EXISTING PENDING backlog
# (policy doc §9) -- run once at cutover, safe to re-run.
# ---------------------------------------------------------------------
@dataclass
class ReclassifyResult:
    scanned: int = 0
    downgraded: int = 0
    downgraded_ids: list = None       # type: ignore[assignment]
    errors: list = None               # type: ignore[assignment]

    def __post_init__(self):
        if self.downgraded_ids is None:
            self.downgraded_ids = []
        if self.errors is None:
            self.errors = []


def reclassify_pending_rows(
    outbox, *, significance_store, insider_store=None, route: str = "IMMEDIATE",
    limit: int = 500, now=None,
) -> ReclassifyResult:
    """Bounded: inspects at most ``limit`` PENDING rows on ``route``
    (default IMMEDIATE), oldest-enqueued first, reusing ``outbox.pending``
    (the SAME selection query the send path uses -- no separate/unbounded
    scan). For each, re-fetches its already-persisted significance record
    and re-classifies; a row whose new verdict is DIGEST has its `route`
    column updated in place (logged). SENT/AMBIGUOUS rows are never
    touched (``outbox.pending`` only ever returns PENDING rows); nothing
    is deleted or replayed. Safe to call repeatedly -- a row already
    reclassified to DIGEST is simply skipped on a later call (its route
    is no longer IMMEDIATE)."""
    from talonx_ingest.intelligence.insider.pipeline import build_insider_activity

    res = ReclassifyResult()
    rows = outbox.pending(route=route, now=now, limit=limit)
    res.scanned = len(rows)
    for row in rows:
        try:
            sig = significance_store.get_for_event(row.event_id)
            if sig is None:
                continue  # no persisted significance to re-derive from -- leave as-is
            insider_activity = None
            if insider_store is not None:
                try:
                    insider_activity = build_insider_activity(insider_store, row.symbol)
                except Exception:  # noqa: BLE001
                    insider_activity = None
            decision = classify_disposition(
                band=sig.band, reasons=sig.reasons,
                insider_activity=insider_activity,
            )
            if decision.disposition == DISPOSITION_DIGEST:
                outbox._conn.execute(
                    "UPDATE intelligence_delivery SET route=? WHERE delivery_id=? AND state='PENDING'",
                    ("DIGEST", row.delivery_id),
                )
                outbox._conn.commit()
                outbox._log(row.delivery_id, "ROUTE_RECLASSIFIED",
                            f"IMMEDIATE -> DIGEST: {decision.reason}")
                res.downgraded += 1
                res.downgraded_ids.append(row.delivery_id)
        except Exception as exc:  # noqa: BLE001
            res.errors.append(f"{row.delivery_id}: {exc!r}")
    return res
