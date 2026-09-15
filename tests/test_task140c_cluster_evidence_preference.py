"""
tests/test_task140c_cluster_evidence_preference.py
=====================================================
Task 140c -- bounded alert-usefulness acceptance review found a real,
demonstrated content-quality defect: two real PENDING DD insider cards
(accession-distinct, both genuine 2-distinct-seller/30-day clusters)
would have sent with evidence_text = "an open-market insider transaction
of about $X was reported" -- LARGE_OPEN_MARKET_TRANSACTION's own
description, which never states purchase/sale direction -- even though a
richer, already-computed cluster fact (which DOES state direction,
distinct-owner count and window) was sitting right next to it in the
same persisted reasons list. `classify_disposition` picked the
direction-less dollar-only reason simply because it iterated the
SUBSTANTIVE_REASON_CODES hit first, never checking whether a cluster
also existed for the same event.

Fixed: when LARGE_OPEN_MARKET_TRANSACTION is the ONLY reason making an
event eligible AND a real insider cluster (buy or sell) also exists,
the cluster's own text is preferred -- never widening ELIGIBILITY
(buy-cluster-only eligibility, `_has_buy_cluster`, is untouched), only
improving WHICH already-qualifying fact is shown. `_cluster_evidence_
text` also gained a real direction check (was hardcoded "bought").

This file uses the REAL `classify_disposition`/`render_concise`/
`reclassify_pending_rows` -- never a mocked classifier -- and reproduces
the exact real DD reasons_json/cluster shape (sanitized: no private
chat IDs/credentials, only public SEC filing identifiers).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

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
from talonx_ingest.intelligence.significance.alert_integration import apply_significance
from talonx_ingest.intelligence.significance.domain import (
    InformationSignificance,
    SignificanceBand,
    SignificanceReason,
)
from talonx_ingest.intelligence.significance.store import SignificanceStore
from talonx_ingest.intelligence.store import EventStore
from _significance_helpers import mk_event

UTC = timezone.utc
NOW = datetime(2026, 9, 15, 12, 31, 0, tzinfo=UTC)


def _cluster(kind, *, distinct_owners=2, window=30, transaction_count=2, total_value=3_026_466.0):
    return SimpleNamespace(kind=kind, distinct_owners=distinct_owners,
                           window_calendar_days=window, transaction_count=transaction_count,
                           total_value=total_value)


def _insider_activity(clusters):
    return SimpleNamespace(clusters=tuple(clusters))


def _dd_reasons(dollar=3_026_466):
    """Reproduces, verbatim in code/points/description, the real
    reasons_json persisted for the real PENDING DD event
    SEC:0001628280-25-054484:INSIDER_TRANSACTION."""
    return (
        SignificanceReason(code="EVENT_TYPE_BASE", description="insider ownership filing (Form 3/4/5)",
                           points=1, component="event_type_base"),
        SignificanceReason(code="LARGE_OPEN_MARKET_TRANSACTION",
                           description=f"an open-market insider transaction of about ${dollar:,.0f} was reported",
                           points=1, component="insider_activity"),
        SignificanceReason(code="INSIDER_CLUSTER",
                           description="2 distinct insiders reported open-market sellers within 30 days",
                           points=2, component="insider_activity"),
        SignificanceReason(code="ON_WATCHLIST",
                           description="this company is on your watchlist (user priority, not market significance)",
                           points=1, component="watchlist_priority"),
    )


# ---------------------------------------------------------------------
# 1. The exact real DD defect -- cluster text preferred over bare dollar
# ---------------------------------------------------------------------
def test_dd_sell_cluster_prefers_direction_stating_cluster_text_over_bare_dollar():
    activity = _insider_activity([_cluster("MULTIPLE_OPEN_MARKET_SELLERS")])
    decision = classify_disposition(band=SignificanceBand.HIGH, reasons=_dd_reasons(),
                                    insider_activity=activity)
    assert decision.disposition == DISPOSITION_IMMEDIATE
    assert decision.evidence_text is not None
    assert "sold" in decision.evidence_text
    assert "2 distinct insiders" in decision.evidence_text
    assert "within 30 days" in decision.evidence_text
    assert "3,026,466" in decision.evidence_text          # the dollar fact is NOT lost, just enriched
    # the bare, direction-less original text must NOT be the final evidence
    assert decision.evidence_text != "an open-market insider transaction of about $3,026,466 was reported"


def test_buy_side_co_occurrence_says_bought_not_sold():
    activity = _insider_activity([_cluster("MULTIPLE_OPEN_MARKET_BUYERS")])
    reasons = (
        SignificanceReason(code="LARGE_OPEN_MARKET_TRANSACTION",
                           description="an open-market insider transaction of about $900,000 was reported",
                           points=1, component="insider_activity"),
    )
    decision = classify_disposition(band=SignificanceBand.HIGH, reasons=reasons,
                                    insider_activity=activity)
    assert decision.disposition == DISPOSITION_IMMEDIATE
    assert "bought" in decision.evidence_text
    assert "sold" not in decision.evidence_text


# ---------------------------------------------------------------------
# 2. Regression: no cluster present -> unchanged bare-dollar behavior
# ---------------------------------------------------------------------
def test_large_transaction_alone_with_no_cluster_is_unchanged():
    reasons = (
        SignificanceReason(code="LARGE_OPEN_MARKET_TRANSACTION",
                           description="an open-market insider transaction of about $500,000 was reported",
                           points=1, component="insider_activity"),
    )
    decision = classify_disposition(band=SignificanceBand.HIGH, reasons=reasons, insider_activity=None)
    assert decision.disposition == DISPOSITION_IMMEDIATE
    assert decision.evidence_text == "an open-market insider transaction of about $500,000 was reported"


def test_large_transaction_with_insider_activity_but_no_clusters_is_unchanged():
    activity = _insider_activity([])
    reasons = (
        SignificanceReason(code="LARGE_OPEN_MARKET_TRANSACTION",
                           description="an open-market insider transaction of about $500,000 was reported",
                           points=1, component="insider_activity"),
    )
    decision = classify_disposition(band=SignificanceBand.HIGH, reasons=reasons, insider_activity=activity)
    assert decision.evidence_text == "an open-market insider transaction of about $500,000 was reported"


# ---------------------------------------------------------------------
# 3. A genuinely different substantive code is never overridden
# ---------------------------------------------------------------------
def test_filing_change_code_is_never_overridden_by_an_unrelated_cluster():
    activity = _insider_activity([_cluster("MULTIPLE_OPEN_MARKET_SELLERS")])
    reasons = (
        SignificanceReason(code="SECTION_CHANGE_DECILE",
                           description="Risk Factors rewrite in the top decile of this filing type's history (change magnitude 71%)",
                           points=3, component="filing_change"),
    )
    decision = classify_disposition(band=SignificanceBand.CRITICAL, reasons=reasons,
                                    insider_activity=activity)
    assert decision.evidence_text == ("Risk Factors rewrite in the top decile of this filing "
                                      "type's history (change magnitude 71%)")


# ---------------------------------------------------------------------
# 4. Eligibility is NOT widened -- a sell-cluster-only event (no other
#    hit) still does not qualify on its own.
# ---------------------------------------------------------------------
def test_sell_cluster_alone_still_does_not_grant_eligibility():
    activity = _insider_activity([_cluster("MULTIPLE_OPEN_MARKET_SELLERS")])
    reasons = (
        SignificanceReason(code="EVENT_TYPE_BASE", description="insider ownership filing (Form 3/4/5)",
                           points=1, component="event_type_base"),
        SignificanceReason(code="INSIDER_CLUSTER",
                           description="2 distinct insiders reported open-market sellers within 30 days",
                           points=2, component="insider_activity"),
        SignificanceReason(code="ON_WATCHLIST", description="this company is on your watchlist",
                           points=1, component="watchlist_priority"),
    )
    decision = classify_disposition(band=SignificanceBand.HIGH, reasons=reasons, insider_activity=activity)
    assert decision.disposition == DISPOSITION_DIGEST
    assert decision.evidence_text is None


# ---------------------------------------------------------------------
# 5. Real render_concise output actually contains the corrected fact
# ---------------------------------------------------------------------
def test_render_concise_shows_the_corrected_direction_stating_evidence():
    ev = mk_event(symbol="DD", accession="0001628280-25-054484",
                 event_type=EventType.INSIDER_TRANSACTION, now=NOW)
    sig = InformationSignificance(
        significance_id="sig-dd", event_id=ev.event_id, symbol="DD",
        score=5, raw_score=5, band=SignificanceBand.HIGH, reasons=_dd_reasons(),
        input_fingerprint="fp-dd", evaluated_at_utc=NOW,
    )
    card = apply_significance(build_alert_card(ev), sig)
    activity = _insider_activity([_cluster("MULTIPLE_OPEN_MARKET_SELLERS")])
    decision = classify_disposition(band=sig.band, reasons=sig.reasons, insider_activity=activity)
    msg = render_concise(card, disposition_reason=decision.evidence_text, now=NOW)
    assert "sold" in msg.text
    assert "2 distinct insiders" in msg.text
    assert "an open-market insider transaction of about $3,026,466 was reported" not in msg.text


# ---------------------------------------------------------------------
# 6. Existing PENDING rows get their stored TEXT corrected, not just route
# ---------------------------------------------------------------------
def test_reclassify_pending_rows_refreshes_stale_evidence_text_in_place(tmp_path):
    """The real DD scenario end-to-end: a PENDING CONCISE/IMMEDIATE row
    enqueued under the OLD (bare-dollar) evidence selection must have its
    stored text corrected in place by reclassify_pending_rows once
    events_store is supplied -- route/state/attempts untouched."""
    from talonx_ingest.intelligence.insider.domain import (
        InsiderActivity, InsiderCluster, RollingOpenMarketAggregate,
    )
    from talonx_ingest.intelligence.insider.store import InsiderStore

    ledger = tmp_path / "l.db"
    ob = DeliveryOutbox(ledger)
    sig_store = SignificanceStore(ledger)
    events_store = EventStore(ledger)
    insider_store = InsiderStore(ledger)

    accession = "0001628280-25-054484"
    ev = mk_event(symbol="DD", accession=accession,
                 event_type=EventType.INSIDER_TRANSACTION, now=NOW)
    events_store.upsert_event(ev)
    sig = InformationSignificance(
        significance_id="sig-dd-pending", event_id=ev.event_id, symbol="DD",
        score=5, raw_score=5, band=SignificanceBand.HIGH, reasons=_dd_reasons(),
        input_fingerprint="fp-dd-pending", evaluated_at_utc=NOW,
    )
    sig_store.upsert(sig)
    card = apply_significance(build_alert_card(ev), sig)

    # Simulate the OLD (pre-fix) enqueue: the bare-dollar evidence text a
    # pre-fix classify_disposition would have produced.
    old_text_reason = "an open-market insider transaction of about $3,026,466 was reported"
    result = enqueue_card(card, outbox=ob, now=NOW, route_override="IMMEDIATE",
                          tier="CONCISE", disposition_reason=old_text_reason)
    row_before = ob.get(result.row.delivery_id)
    assert "sold" not in row_before.text
    assert old_text_reason in row_before.text

    # Real InsiderStore-backed cluster so build_insider_activity (called
    # internally by reclassify_pending_rows) finds the real sell cluster.
    _seed_dd_sell_cluster(insider_store, symbol="DD", now=NOW)

    res = reclassify_pending_rows(ob, significance_store=sig_store, insider_store=insider_store,
                                  events_store=events_store, route="IMMEDIATE", now=NOW)
    assert result.row.delivery_id in res.content_refreshed_ids
    assert result.row.delivery_id not in res.downgraded_ids

    row_after = ob.get(result.row.delivery_id)
    assert row_after.route == "IMMEDIATE"       # eligibility unchanged
    assert row_after.state == "PENDING"         # never replayed/sent
    assert "sold" in row_after.text
    assert "2 distinct insiders" in row_after.text
    ob.close(); sig_store.close(); events_store.close(); insider_store.close()


def _seed_dd_sell_cluster(insider_store, *, symbol, now):
    """Minimal real InsiderStore-backed transactions producing a genuine
    2-distinct-seller/30-day cluster build_insider_activity will detect,
    via the real detect_clusters()/aggregate machinery -- not a stub."""
    from talonx_ingest.intelligence.insider.domain import (
        AcquiredDisposed, InsiderRole, InsiderTransaction, OwnershipNature, TransactionClass,
    )

    for i, owner in enumerate(("0001111111", "0002222222")):
        insider_store.upsert_transaction(InsiderTransaction(
            transaction_id=f"tx-dd-sell-{i}",
            accession="0001628280-25-054484",
            issuer_cik="0000030554",
            symbol=symbol,
            company_name="DD Inc.",
            classification=TransactionClass.OPEN_MARKET_SALE,
            transaction_code="S",
            transaction_shares=1000.0,
            price_per_share=100.0,
            transaction_value=100_000.0 + i,
            transaction_date=now.date(),
            owner_cik=owner,
            owner_role=InsiderRole.OFFICER,
            owner_roles=(InsiderRole.OFFICER,),
            is_officer=True,
            acquired_disposed=AcquiredDisposed.DISPOSED,
            ownership_nature=OwnershipNature.DIRECT,
            signed_open_market_shares=-1000.0,
        ))


def test_reclassify_pending_rows_without_events_store_preserves_old_text_only_behavior(tmp_path):
    """Backward compatibility: an existing caller that does NOT pass
    events_store (e.g. any pre-Task-140c call site) gets EXACTLY the
    prior route-only reclassification behavior -- text is never touched."""
    ledger = tmp_path / "l.db"
    ob = DeliveryOutbox(ledger)
    sig_store = SignificanceStore(ledger)

    ev = mk_event(symbol="DD", accession="0001628280-25-054484",
                 event_type=EventType.INSIDER_TRANSACTION, now=NOW)
    sig = InformationSignificance(
        significance_id="sig-dd-compat", event_id=ev.event_id, symbol="DD",
        score=5, raw_score=5, band=SignificanceBand.HIGH, reasons=_dd_reasons(),
        input_fingerprint="fp-dd-compat", evaluated_at_utc=NOW,
    )
    sig_store.upsert(sig)
    card = apply_significance(build_alert_card(ev), sig)
    old_text_reason = "an open-market insider transaction of about $3,026,466 was reported"
    result = enqueue_card(card, outbox=ob, now=NOW, route_override="IMMEDIATE",
                          tier="CONCISE", disposition_reason=old_text_reason)
    text_before = ob.get(result.row.delivery_id).text

    res = reclassify_pending_rows(ob, significance_store=sig_store, route="IMMEDIATE", now=NOW)
    assert res.content_refreshed == 0
    text_after = ob.get(result.row.delivery_id).text
    assert text_after == text_before
    ob.close(); sig_store.close()
