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
    reason: str                # human-readable, logged verbatim


def _has_buy_cluster(insider_activity) -> bool:
    if insider_activity is None:
        return False
    clusters = getattr(insider_activity, "clusters", None) or ()
    return any(getattr(c, "kind", None) == _BUY_CLUSTER_KIND for c in clusters)


def _substantive_codes_present(reason_codes) -> set[str]:
    return set(reason_codes) & SUBSTANTIVE_REASON_CODES


def classify_disposition(
    *, band: "SignificanceBand | str | None", reason_codes, insider_activity=None,
) -> DispositionDecision:
    """Pure, deterministic. ``reason_codes`` is any iterable of the
    significance engine's own ``SignificanceReason.code`` strings for this
    event (e.g. ``[r.code for r in sig.reasons]``). ``insider_activity``
    is the same object already built for card rendering/significance
    (may be ``None`` for a non-insider event)."""
    band_val = band.value if isinstance(band, SignificanceBand) else band

    if band_val == SignificanceBand.CRITICAL.value:
        return DispositionDecision(
            DISPOSITION_IMMEDIATE,
            "CRITICAL band -- the engine's own structural floor already "
            "requires >=2 substantive scoring families before reaching "
            "CRITICAL, so this policy does not re-derive substantiveness.",
        )
    if band_val == SignificanceBand.LOW.value or band_val is None:
        return DispositionDecision(
            DISPOSITION_DASHBOARD_ONLY,
            f"{band_val or 'no'} band -- no scoring signal worth a digest slot.",
        )

    # MEDIUM / HIGH: require an explicit substantive trigger.
    hits = _substantive_codes_present(reason_codes or ())
    if hits:
        return DispositionDecision(
            DISPOSITION_IMMEDIATE,
            f"{band_val} band with a substantive trigger present: {sorted(hits)}.",
        )
    if _has_buy_cluster(insider_activity):
        return DispositionDecision(
            DISPOSITION_IMMEDIATE,
            f"{band_val} band with a >=2-distinct-insider open-market BUY "
            "cluster present.",
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
                band=sig.band, reason_codes=[r.code for r in sig.reasons],
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
