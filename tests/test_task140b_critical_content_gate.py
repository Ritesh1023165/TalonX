"""
tests/test_task140b_critical_content_gate.py
===============================================
Task 140b -- live defect fix: two real AXON informational pushes (CRITICAL
band, tier CONCISE) were sent whose only "evidence" line restated their
own event-type category ("direct financial obligation 8-K (Item
2.03/2.04)" / "Regulation FD disclosure 8-K (Item 7.01)"), explaining
nothing beyond "this filing type exists". Root cause, traced against the
real production ledger (docs/research/evidence/task140/axon_live_defect/):
``notification_policy.classify_disposition``'s CRITICAL branch had a
SEPARATE, looser fallback -- "no SUBSTANTIVE_REASON_CODES hit? use the
highest-point reason with ANY non-empty description" -- and
EVENT_TYPE_BASE (deliberately excluded from SUBSTANTIVE_REASON_CODES)
always has a non-empty description and typically ties for the highest
point value, so Python's ``max()`` (first-max-wins on a tie) silently
picked it almost every time. Fixed by removing CRITICAL's special case
entirely -- it now runs through the IDENTICAL evidence gate as MEDIUM/HIGH.

This file uses the REAL policy (classify_disposition), REAL significance
engine reason shapes reproduced from the real AXON accession
0001193125-26-391320's own persisted reasons_json (sanitized: no private
chat IDs/credentials, only public SEC filing identifiers), the REAL
renderer (render_concise), and the REAL outbox (enqueue_card,
reclassify_pending_rows) -- never a mocked classifier returning a
pre-decided verdict.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_ingest.intelligence.delivery.notification_policy import (
    DISPOSITION_DIGEST,
    DISPOSITION_IMMEDIATE,
    classify_disposition,
    reclassify_pending_rows,
)
from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
from talonx_ingest.intelligence.delivery.pipeline import enqueue_card
from talonx_ingest.intelligence.delivery.renderer import render_concise
from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.pipeline import build_alert_card
from talonx_ingest.intelligence.significance.domain import (
    InformationSignificance,
    SignificanceBand,
    SignificanceReason,
)
from talonx_ingest.intelligence.significance.store import SignificanceStore
from talonx_ingest.intelligence.store import EventStore
from _significance_helpers import mk_event

UTC = timezone.utc
NOW = datetime(2026, 9, 15, 11, 26, 0, tzinfo=UTC)

# The real AXON accession both live-defect events actually share --
# proven from production text_events (not assumed from timestamps).
_AXON_ACCESSION = "0001193125-26-391320"


def _axon_debt_financing_reasons():
    """Reproduces, verbatim in code/points/description, the REAL
    reasons_json persisted for SEC:0001193125-26-391320:DEBT_FINANCING --
    the exact set that got this CRITICAL card sent with category-only
    "evidence" before this fix."""
    return (
        SignificanceReason(code="EVENT_TYPE_BASE",
                           description="direct financial obligation 8-K (Item 2.03/2.04)",
                           points=2, component="event_type_base"),
        SignificanceReason(code="MULTI_ITEM_8K",
                           description="bundled 8-K carrying 3 distinct material items (1.01, 2.03, 7.01)",
                           points=1, component="material_items"),
        SignificanceReason(code="EVENT_RARE_FOR_FILER",
                           description="this company has not filed a DEBT_FINANCING event in 24 months of tracked history",
                           points=2, component="rarity"),
        SignificanceReason(code="EVENT_CLUSTER",
                           description="4 distinct disclosure types from this company within 7 days",
                           points=1, component="simultaneous_events"),
        SignificanceReason(code="ON_WATCHLIST",
                           description="this company is on your watchlist (user priority, not market significance)",
                           points=1, component="watchlist_priority"),
    )


def _axon_regulation_fd_reasons():
    """Reproduces SEC:0001193125-26-391320:REGULATION_FD's real reasons."""
    return (
        SignificanceReason(code="EVENT_TYPE_BASE",
                           description="Regulation FD disclosure 8-K (Item 7.01)",
                           points=2, component="event_type_base"),
        SignificanceReason(code="MULTI_ITEM_8K",
                           description="bundled 8-K carrying 3 distinct material items (1.01, 2.03, 7.01)",
                           points=1, component="material_items"),
        SignificanceReason(code="EVENT_RARE_FOR_FILER",
                           description="this company has not filed a REGULATION_FD event in 24 months of tracked history",
                           points=2, component="rarity"),
        SignificanceReason(code="EVENT_CLUSTER",
                           description="4 distinct disclosure types from this company within 7 days",
                           points=1, component="simultaneous_events"),
        SignificanceReason(code="ON_WATCHLIST",
                           description="this company is on your watchlist (user priority, not market significance)",
                           points=1, component="watchlist_priority"),
    )


# ---------------------------------------------------------------------
# 1. Both real AXON cards must now fail immediate eligibility
# ---------------------------------------------------------------------
def test_axon_debt_financing_no_longer_qualifies_immediate():
    decision = classify_disposition(band=SignificanceBand.CRITICAL,
                                    reasons=_axon_debt_financing_reasons())
    assert decision.disposition != DISPOSITION_IMMEDIATE
    assert decision.disposition == DISPOSITION_DIGEST
    assert decision.evidence_text is None


def test_axon_regulation_fd_no_longer_qualifies_immediate():
    decision = classify_disposition(band=SignificanceBand.CRITICAL,
                                    reasons=_axon_regulation_fd_reasons())
    assert decision.disposition != DISPOSITION_IMMEDIATE
    assert decision.disposition == DISPOSITION_DIGEST
    assert decision.evidence_text is None


# ---------------------------------------------------------------------
# 2. A category-only CRITICAL card cannot bypass via ANY reason shape
# ---------------------------------------------------------------------
def test_critical_band_category_only_reasons_cannot_reach_immediate():
    """Generalizes beyond the exact AXON shape: ANY CRITICAL-band event
    whose reasons are all non-substantive (category/watchlist/multi-item/
    rarity/clustering-count) must route to DIGEST, never IMMEDIATE --
    regardless of how many points they sum to or their description
    length."""
    reasons = (
        SignificanceReason(code="EVENT_TYPE_BASE", description="a filing of this type was made",
                           points=3, component="event_type_base"),
        SignificanceReason(code="WATCHLIST_PINNED", description="this ticker is pinned",
                           points=3, component="watchlist_priority"),
        SignificanceReason(code="EVENT_UNCOMMON_FOR_FILER",
                           description="this event type is uncommon for this filer historically",
                           points=2, component="rarity"),
    )
    decision = classify_disposition(band=SignificanceBand.CRITICAL, reasons=reasons)
    assert decision.disposition == DISPOSITION_DIGEST
    assert decision.evidence_text is None


def test_nonempty_generic_reason_description_is_insufficient_regardless_of_length():
    """A long, verbose, entirely nonempty description attached to a
    non-substantive code must still not qualify -- length/non-emptiness
    alone is not the bar (the exact has_content-boolean trap this task
    explicitly forbids reintroducing)."""
    reasons = (
        SignificanceReason(
            code="EVENT_TYPE_BASE",
            description=("this is a long, detailed, entirely non-empty description of the "
                        "filing category that nonetheless says nothing about what was "
                        "actually disclosed beyond the fact that a filing of this type exists"),
            points=5, component="event_type_base"),
    )
    decision = classify_disposition(band=SignificanceBand.CRITICAL, reasons=reasons)
    assert decision.disposition == DISPOSITION_DIGEST
    assert decision.evidence_text is None


# ---------------------------------------------------------------------
# 3. Existing PENDING generic rows cannot escape the corrected policy
# ---------------------------------------------------------------------
def test_reclassify_pending_rows_downgrades_a_critical_category_only_pending_row(tmp_path):
    """A row enqueued under the OLD (buggy) policy -- IMMEDIATE/CONCISE,
    CRITICAL band, category-only evidence -- sitting PENDING (never sent)
    -- must be caught and downgraded to DIGEST by the bounded, idempotent
    reclassify_pending_rows pass, exactly like the pre-existing HIGH/
    MEDIUM reclassification path already proven in Task 140."""
    ledger = tmp_path / "l.db"
    ob = DeliveryOutbox(ledger)
    sig_store = SignificanceStore(ledger)
    events_store = EventStore(ledger)

    accession = "0001193125-26-391320"
    ev = mk_event(symbol="AXON", accession=accession,
                 event_type=EventType.DEBT_FINANCING, now=NOW)
    events_store.upsert_event(ev)
    sig = InformationSignificance(
        significance_id=f"sig-{accession}-debt", event_id=ev.event_id, symbol="AXON",
        score=7, raw_score=7, band=SignificanceBand.CRITICAL,
        reasons=_axon_debt_financing_reasons(),
        input_fingerprint="fp-axon-debt", evaluated_at_utc=NOW,
    )
    sig_store.upsert(sig)

    card = build_alert_card(ev)
    from talonx_ingest.intelligence.significance.alert_integration import apply_significance
    card = apply_significance(card, sig)

    # Simulate the OLD buggy enqueue: IMMEDIATE route, CONCISE tier, using
    # the (bug-era) category-only evidence text a pre-fix classify_
    # disposition would have produced.
    result = enqueue_card(card, outbox=ob, now=NOW, route_override="IMMEDIATE",
                          tier="CONCISE", disposition_reason="direct financial obligation 8-K (Item 2.03/2.04)")
    row_before = ob.get(result.row.delivery_id)
    assert row_before.route == "IMMEDIATE"
    assert row_before.state == "PENDING"

    res = reclassify_pending_rows(ob, significance_store=sig_store, route="IMMEDIATE", now=NOW)
    assert result.row.delivery_id in res.downgraded_ids

    row_after = ob.get(result.row.delivery_id)
    assert row_after.route == "DIGEST"
    assert row_after.state == "PENDING"          # never deleted/replayed, just reclassified
    ob.close(); sig_store.close(); events_store.close()


def test_reclassify_never_touches_sent_rows(tmp_path):
    """A row already SENT (the real AXON cards' own terminal state) must
    never be modified by reclassify_pending_rows -- it only ever selects
    PENDING rows (outbox.pending's own query), matching the explicit
    'do not replay or modify SENT/AMBIGUOUS rows' requirement."""
    ledger = tmp_path / "l.db"
    ob = DeliveryOutbox(ledger)
    sig_store = SignificanceStore(ledger)

    accession = "0001193125-26-391320"
    ev = mk_event(symbol="AXON", accession=accession,
                 event_type=EventType.DEBT_FINANCING, now=NOW)
    sig = InformationSignificance(
        significance_id=f"sig-{accession}-debt2", event_id=ev.event_id, symbol="AXON",
        score=7, raw_score=7, band=SignificanceBand.CRITICAL,
        reasons=_axon_debt_financing_reasons(),
        input_fingerprint="fp-axon-debt2", evaluated_at_utc=NOW,
    )
    sig_store.upsert(sig)
    card = build_alert_card(ev)
    from talonx_ingest.intelligence.significance.alert_integration import apply_significance
    card = apply_significance(card, sig)
    result = enqueue_card(card, outbox=ob, now=NOW, route_override="IMMEDIATE",
                          tier="CONCISE", disposition_reason="direct financial obligation 8-K (Item 2.03/2.04)")
    ob.mark_sent(result.row.delivery_id, message_id=973, now=NOW)
    text_before = ob.get(result.row.delivery_id).text

    res = reclassify_pending_rows(ob, significance_store=sig_store, route="IMMEDIATE", now=NOW)
    assert res.scanned == 0            # outbox.pending() finds nothing -- already SENT
    row_after = ob.get(result.row.delivery_id)
    assert row_after.state == "SENT"
    assert row_after.route == "IMMEDIATE"       # untouched
    assert row_after.text == text_before        # byte-identical, never replayed
    ob.close(); sig_store.close()


# ---------------------------------------------------------------------
# 4. Positive fixture: a genuinely supported CRITICAL event still sends
# ---------------------------------------------------------------------
def test_critical_band_with_genuine_substantive_reason_still_sends_one_useful_message():
    """The fix must not simply block all CRITICAL informational alerts --
    a CRITICAL card carrying a REAL SUBSTANTIVE_REASON_CODES hit (here:
    the same XBRL_MAGNITUDE shape rules.py actually computes) sends
    exactly as before, with its qualifying fact in the actual payload."""
    reasons = (
        SignificanceReason(code="EVENT_TYPE_BASE", description="quarterly report (10-Q)",
                           points=1, component="event_type_base"),
        SignificanceReason(code="XBRL_MAGNITUDE",
                           description="very large reported revenue YOY change (magnitude 42%; size only, not direction)",
                           points=3, component="xbrl_magnitude"),
        SignificanceReason(code="EVENT_CLUSTER", description="3 distinct disclosure types within 7 days",
                           points=1, component="simultaneous_events"),
        SignificanceReason(code="ON_WATCHLIST", description="this company is on your watchlist",
                           points=1, component="watchlist_priority"),
    )
    decision = classify_disposition(band=SignificanceBand.CRITICAL, reasons=reasons)
    assert decision.disposition == DISPOSITION_IMMEDIATE
    assert decision.evidence_text is not None
    assert "revenue" in decision.evidence_text and "42%" in decision.evidence_text

    ev = mk_event(symbol="POSV", accession="0009999999-26-000001",
                 event_type=EventType.QUARTERLY_FILING, now=NOW)
    sig = InformationSignificance(
        significance_id="sig-posv", event_id=ev.event_id, symbol="POSV",
        score=6, raw_score=6, band=SignificanceBand.CRITICAL, reasons=reasons,
        input_fingerprint="fp-posv", evaluated_at_utc=NOW,
    )
    from talonx_ingest.intelligence.significance.alert_integration import apply_significance
    card = apply_significance(build_alert_card(ev), sig)

    msg = render_concise(card, disposition_reason=decision.evidence_text, now=NOW)
    assert "revenue" in msg.text and "42%" in msg.text
    assert "quarterly report" in msg.text.lower() or "10-Q" in msg.text  # category still in the header line
    # the header category line and the fact line must be DIFFERENT --
    # never the same text repeated (the exact original bug shape)
    body_lines = msg.text.split("\n")
    assert body_lines[0] != body_lines[1]


# ---------------------------------------------------------------------
# 5. Missing evidence -> honest non-send, never fabricated
# ---------------------------------------------------------------------
def test_critical_band_missing_evidence_is_an_honest_non_send_not_a_fabrication():
    decision = classify_disposition(band=SignificanceBand.CRITICAL, reasons=())
    assert decision.disposition == DISPOSITION_DIGEST
    assert decision.evidence_text is None
    assert "no substantive trigger" in decision.reason


# ---------------------------------------------------------------------
# 6. Same-accession: distinct substantive explanation per send when both
#    independently qualify (no cross-event consolidation exists to
#    reuse -- verified: see docs/research/evidence/task140/axon_live_
#    defect/consolidation_inspection.md -- so the required fallback is
#    that each send stands on its own distinct, genuine evidence).
# ---------------------------------------------------------------------
def test_same_accession_events_that_each_independently_qualify_get_distinct_evidence():
    same_accession = "0001999999-26-000555"
    reasons_a = (
        SignificanceReason(code="EVENT_TYPE_BASE", description="material definitive agreement 8-K (Item 1.01)",
                           points=2, component="event_type_base"),
        SignificanceReason(code="XBRL_MAGNITUDE",
                           description="very large reported total debt change (magnitude 55%; size only, not direction)",
                           points=3, component="xbrl_magnitude"),
    )
    reasons_b = (
        SignificanceReason(code="EVENT_TYPE_BASE", description="Regulation FD disclosure 8-K (Item 7.01)",
                           points=2, component="event_type_base"),
        SignificanceReason(code="SECTION_CHANGE_DECILE",
                           description="Risk Factors rewrite in the top decile of this filing type's history (change magnitude 71%)",
                           points=3, component="filing_change"),
    )
    dec_a = classify_disposition(band=SignificanceBand.CRITICAL, reasons=reasons_a)
    dec_b = classify_disposition(band=SignificanceBand.CRITICAL, reasons=reasons_b)
    assert dec_a.disposition == DISPOSITION_IMMEDIATE
    assert dec_b.disposition == DISPOSITION_IMMEDIATE
    assert dec_a.evidence_text != dec_b.evidence_text
    assert "total debt" in dec_a.evidence_text
    assert "Risk Factors" in dec_b.evidence_text
    # both events share an accession only incidentally -- this module
    # never reads/compares accession at all (confirmed: classify_
    # disposition's own signature takes no accession/event_id argument),
    # so it structurally cannot combine or delay one waiting on the other.


# ---------------------------------------------------------------------
# 7. Freshness wording -- the new label is precise, the old one is gone
# ---------------------------------------------------------------------
def test_freshness_wording_no_longer_implies_the_known_source_timestamp_is_in_doubt():
    from talonx_ingest.intelligence.domain import FreshnessStatus

    ev = mk_event(symbol="AXON", accession=_AXON_ACCESSION,
                 event_type=EventType.DEBT_FINANCING, now=NOW)
    ev = ev.model_copy(update={"freshness": FreshnessStatus.UNKNOWN})
    reasons = (
        SignificanceReason(code="XBRL_MAGNITUDE",
                           description="very large reported total debt change (magnitude 60%; size only, not direction)",
                           points=3, component="xbrl_magnitude"),
    )
    sig = InformationSignificance(
        significance_id="sig-axon-fresh", event_id=ev.event_id, symbol="AXON",
        score=3, raw_score=3, band=SignificanceBand.HIGH, reasons=reasons,
        input_fingerprint="fp-axon-fresh", evaluated_at_utc=NOW,
    )
    from talonx_ingest.intelligence.significance.alert_integration import apply_significance
    card = apply_significance(build_alert_card(ev), sig)
    decision = classify_disposition(band=sig.band, reasons=sig.reasons)
    msg = render_concise(card, disposition_reason=decision.evidence_text, now=NOW)

    assert "Source freshness unknown at emit time" not in msg.text
    assert "Ingestion feed-poll currency not tracked" in msg.text
    assert "exact and unaffected" in msg.text
    # the exact accepted-at timestamp/age is still shown, unaffected
    assert "Source:" in msg.text and "source age:" in msg.text


# ---------------------------------------------------------------------
# 8. Digest-OFF / V2 unaffected -- structural, no code in this module
#    touches either
# ---------------------------------------------------------------------
def test_classify_disposition_never_touches_digest_toggle_or_v2():
    import inspect

    src = inspect.getsource(classify_disposition)
    assert "deliver_digest_enabled" not in src
    assert "talonx_v2" not in src
    assert "TALONX_INTEL_DELIVER_DIGEST_ENABLED" not in src
