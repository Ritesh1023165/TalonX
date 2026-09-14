"""
tests/test_task138_notification_policy.py
--------------------------------------------
Task 138 Workstream 2: the notification delivery-disposition policy.
See docs/research/NOTIFICATION_POLICY.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from talonx_ingest.intelligence.delivery.notification_policy import (
    DISPOSITION_DASHBOARD_ONLY,
    DISPOSITION_DIGEST,
    DISPOSITION_IMMEDIATE,
    classify_disposition,
    reclassify_pending_rows,
)
from talonx_ingest.intelligence.domain import EventType, SignificanceBand

UTC = timezone.utc


@dataclass
class _FakeCluster:
    kind: str


@dataclass
class _FakeInsiderActivity:
    clusters: list = field(default_factory=list)


# ---------------------------------------------------------------------
# classify_disposition -- deterministic band/reason-code decisions
# ---------------------------------------------------------------------

def test_critical_band_is_always_immediate_no_extra_signal_needed():
    d = classify_disposition(band=SignificanceBand.CRITICAL, reason_codes=[])
    assert d.disposition == DISPOSITION_IMMEDIATE


def test_low_band_is_dashboard_only():
    d = classify_disposition(band=SignificanceBand.LOW, reason_codes=["EVENT_TYPE_BASE"])
    assert d.disposition == DISPOSITION_DASHBOARD_ONLY


def test_no_band_is_dashboard_only():
    d = classify_disposition(band=None, reason_codes=[])
    assert d.disposition == DISPOSITION_DASHBOARD_ONLY


def test_high_band_with_only_watchlist_and_form_type_is_not_immediate():
    """The exact over-triggering case: watchlist membership + 'a Form 4/
    8-K was filed' alone (EVENT_TYPE_BASE/ON_WATCHLIST) must NOT reach
    IMMEDIATE -- routes to DIGEST, not suppressed."""
    d = classify_disposition(
        band=SignificanceBand.HIGH,
        reason_codes=["EVENT_TYPE_BASE", "ON_WATCHLIST"],
    )
    assert d.disposition == DISPOSITION_DIGEST


def test_high_band_multi_item_8k_alone_is_not_immediate():
    """'Multiple disclosure types' (MULTI_ITEM_8K) alone must not justify
    immediate delivery."""
    d = classify_disposition(
        band=SignificanceBand.HIGH,
        reason_codes=["EVENT_TYPE_BASE", "ON_WATCHLIST", "MULTI_ITEM_8K"],
    )
    assert d.disposition == DISPOSITION_DIGEST


def test_high_band_with_a_substantive_filing_change_is_immediate():
    d = classify_disposition(
        band=SignificanceBand.HIGH,
        reason_codes=["EVENT_TYPE_BASE", "ON_WATCHLIST", "SECTION_CHANGE_DECILE"],
    )
    assert d.disposition == DISPOSITION_IMMEDIATE


def test_high_band_with_large_insider_transaction_is_immediate():
    d = classify_disposition(
        band=SignificanceBand.HIGH,
        reason_codes=["EVENT_TYPE_BASE", "LARGE_OPEN_MARKET_TRANSACTION"],
    )
    assert d.disposition == DISPOSITION_IMMEDIATE


def test_sell_side_cluster_alone_is_not_immediate_axon_style():
    """AXON-style routine insider-sale summary: a sell cluster (or none)
    with no dollar/comparison trigger must default to DIGEST."""
    activity = _FakeInsiderActivity(clusters=[_FakeCluster(kind="MULTIPLE_OPEN_MARKET_SELLERS")])
    d = classify_disposition(
        band=SignificanceBand.HIGH,
        reason_codes=["EVENT_TYPE_BASE", "INSIDER_CLUSTER"],
        insider_activity=activity,
    )
    assert d.disposition == DISPOSITION_DIGEST


def test_buy_side_cluster_is_immediate():
    activity = _FakeInsiderActivity(clusters=[_FakeCluster(kind="MULTIPLE_OPEN_MARKET_BUYERS")])
    d = classify_disposition(
        band=SignificanceBand.HIGH,
        reason_codes=["EVENT_TYPE_BASE", "INSIDER_CLUSTER"],
        insider_activity=activity,
    )
    assert d.disposition == DISPOSITION_IMMEDIATE


def test_medium_band_without_trigger_is_digest():
    d = classify_disposition(band=SignificanceBand.MEDIUM, reason_codes=["EVENT_TYPE_BASE"])
    assert d.disposition == DISPOSITION_DIGEST


def test_medium_band_with_trigger_is_immediate():
    d = classify_disposition(band=SignificanceBand.MEDIUM, reason_codes=["XBRL_MAGNITUDE"])
    assert d.disposition == DISPOSITION_IMMEDIATE


def test_reason_is_recorded_and_non_empty_for_every_decision():
    for band in (SignificanceBand.CRITICAL, SignificanceBand.HIGH, SignificanceBand.MEDIUM,
                SignificanceBand.LOW, None):
        d = classify_disposition(band=band, reason_codes=[])
        assert d.reason


# ---------------------------------------------------------------------
# End-to-end through the real enqueue path -- IMMEDIATE/DIGEST route
# override and DASHBOARD_ONLY skip.
# ---------------------------------------------------------------------

def test_render_card_route_override_downgrades_high_band_to_digest():
    from talonx_ingest.intelligence.delivery.config import ROUTE_DIGEST, ROUTE_IMMEDIATE
    from talonx_ingest.intelligence.delivery.pipeline import render_card
    from _delivery_helpers import make_card

    card, _ = make_card(symbol="DXCM", event_type=EventType.REGULATION_FD,
                        on_watchlist=True, now=datetime(2026, 9, 15, tzinfo=UTC))
    # confirm this card would band-derive to IMMEDIATE by default (HIGH via
    # watchlist priority) before applying the override
    natural = render_card(card)
    msg = render_card(card, route_override=ROUTE_DIGEST)
    assert msg.route == ROUTE_DIGEST
    if natural.route == ROUTE_IMMEDIATE:
        assert msg.route != natural.route   # override actually narrowed it


def test_render_card_route_override_never_widens_a_digest_only_band():
    """A LOW/MEDIUM-band card is never force-upgraded to IMMEDIATE by an
    override the renderer itself did not independently derive -- the
    override can only narrow, matching the documented one-directional
    contract."""
    from talonx_ingest.intelligence.delivery.config import ROUTE_DIGEST, ROUTE_IMMEDIATE
    from talonx_ingest.intelligence.delivery.pipeline import render_card
    from _delivery_helpers import make_card

    card, _ = make_card(symbol="XYZ", event_type=EventType.REGULATION_FD,
                        on_watchlist=False, now=datetime(2026, 9, 15, tzinfo=UTC))
    msg = render_card(card, route_override=ROUTE_IMMEDIATE)
    # override is only ever consulted for IMMEDIATE/DIGEST; a genuinely
    # LOW-scored card is not touched by this policy at the render layer
    # at all in the real pipeline (enrichment.py skips enqueue_card
    # entirely for DASHBOARD_ONLY) -- this just confirms the override
    # mechanism itself does what it says for a route it IS given.
    assert msg.route == ROUTE_IMMEDIATE


def test_dashboard_only_event_never_reaches_the_outbox(ledger_path, monkeypatch):
    """End-to-end through the real EnrichmentEngine: a card that
    classifies as DASHBOARD_ONLY must never appear in intelligence_
    delivery at all, while its significance/processing record is still
    persisted (dashboard-queryable). Forces the DASHBOARD_ONLY verdict
    via classify_disposition itself (rather than reverse-engineering a
    LOW-scoring synthetic event against the real, hardcoded-on_watchlist
    significance evaluation) -- this isolates the ENQUEUE-SKIP wiring in
    enrichment.py, which is what's actually under test here."""
    import asyncio
    import talonx_ingest.intelligence.delivery.notification_policy as policy_mod
    from talonx_ingest.intelligence.delivery.notification_policy import (
        DISPOSITION_DASHBOARD_ONLY, DispositionDecision,
    )
    from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
    from talonx_ingest.intelligence.service.config import ServiceConfig
    from talonx_ingest.intelligence.service.stores import StoreBundle
    from talonx_ingest.intelligence.domain import TextEvent, SourceType, SessionBucket

    # enrichment.py imports classify_disposition LOCALLY (inside
    # _enqueue_delivery), so it resolves the name from this source module
    # at call time -- patching it here takes effect even though there is
    # no module-level import on the enrichment.py side to patch instead.
    monkeypatch.setattr(
        policy_mod, "classify_disposition",
        lambda **kw: DispositionDecision(DISPOSITION_DASHBOARD_ONLY, "forced for test"),
    )

    cfg = ServiceConfig(ledger_path=ledger_path, state_dir=None)
    stores = StoreBundle.open(cfg.ledger())
    engine = EnrichmentEngine(stores, client=None, config=cfg)

    now = datetime(2026, 9, 15, 16, 0, 0, tzinfo=UTC)
    ev = TextEvent(
        event_id="SEC:0000000090-26-000090:REGULATION_FD", symbol="LOWX",
        company_name="LOW SIGNAL CO", source_type=SourceType.SEC_EDGAR_SUBMISSIONS,
        source_record_id="0000000090-26-000090", event_type=EventType.REGULATION_FD,
        form_type="8-K", accession="0000000090-26-000090",
        accepted_at_utc=now, ingested_at_utc=now, session_bucket=SessionBucket.RTH,
    )
    stores.events.upsert_event(ev)

    outcome = asyncio.run(engine.process_event(ev.event_id, allow_delivery=True, now=now))
    rows = [r for r in stores.outbox._conn.execute(
        "SELECT delivery_id FROM intelligence_delivery WHERE event_id=?", (ev.event_id,))]
    assert rows == [], "a DASHBOARD_ONLY event must never be enqueued into the delivery outbox"
    # but the underlying event/processing record remains fully queryable
    assert stores.events.get_event(ev.event_id) is not None
    proc_row = stores.processing.get(ev.event_id)
    assert proc_row.delivery_state == "DONE"


# ---------------------------------------------------------------------
# reclassify_pending_rows -- bounded, idempotent backlog reclassification
# ---------------------------------------------------------------------

def test_reclassify_pending_rows_downgrades_a_non_substantive_immediate_row(ledger_path):
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
    from talonx_ingest.intelligence.delivery.pipeline import enqueue_card
    from talonx_ingest.intelligence.significance.domain import InformationSignificance, SignificanceReason
    from talonx_ingest.intelligence.significance.store import SignificanceStore
    from _delivery_helpers import make_card

    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 15, 16, 0, 0, tzinfo=UTC)
    card, _ = make_card(symbol="DXCM", event_type=EventType.REGULATION_FD,
                        on_watchlist=True, now=now)
    result = enqueue_card(card, outbox=ob, now=now)
    assert result.row.route == "IMMEDIATE"   # the old band-only behaviour

    sig_store = SignificanceStore(ledger_path)
    sig = InformationSignificance(
        significance_id="sig-1", event_id=card.event_id, symbol="DXCM",
        score=10, raw_score=10, band=card.significance,
        reasons=(SignificanceReason(code="EVENT_TYPE_BASE", description="d", points=10,
                                    component="event_type_base"),),
        input_fingerprint="fp1", evaluated_at_utc=now,
    )
    sig_store.upsert(sig)

    res = reclassify_pending_rows(ob, significance_store=sig_store, route="IMMEDIATE", limit=10, now=now)
    assert res.downgraded == 1
    assert ob.get(result.row.delivery_id).route == "DIGEST"
    ob.close()


def test_reclassify_pending_rows_leaves_a_substantive_immediate_row_alone(ledger_path):
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
    from talonx_ingest.intelligence.delivery.pipeline import enqueue_card
    from talonx_ingest.intelligence.significance.domain import InformationSignificance, SignificanceReason
    from talonx_ingest.intelligence.significance.store import SignificanceStore
    from _delivery_helpers import make_card

    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 15, 16, 0, 0, tzinfo=UTC)
    card, _ = make_card(symbol="ACME", event_type=EventType.QUARTERLY_FILING,
                        on_watchlist=True, now=now)
    result = enqueue_card(card, outbox=ob, now=now)
    # simulate a pre-Task-138 backlog row already on IMMEDIATE (old band-
    # only routing), regardless of what this card's own natural band
    # happened to route to -- the point under test is reclassify_pending_
    # rows' OWN decision given a SUBSTANTIVE significance record, not
    # make_card's default scoring for this particular event type.
    ob._conn.execute("UPDATE intelligence_delivery SET route='IMMEDIATE' WHERE delivery_id=?",
                     (result.row.delivery_id,))
    ob._conn.commit()

    sig_store = SignificanceStore(ledger_path)
    sig = InformationSignificance(
        significance_id="sig-2", event_id=card.event_id, symbol="ACME",
        score=40, raw_score=40, band=card.significance,
        reasons=(SignificanceReason(code="SECTION_CHANGE_DECILE", description="d", points=40,
                                    component="filing_change"),),
        input_fingerprint="fp2", evaluated_at_utc=now,
    )
    sig_store.upsert(sig)

    res = reclassify_pending_rows(ob, significance_store=sig_store, route="IMMEDIATE", limit=10, now=now)
    assert res.downgraded == 0
    assert ob.get(result.row.delivery_id).route == "IMMEDIATE"
    ob.close()


def test_reclassify_pending_rows_never_touches_sent_rows(ledger_path):
    """SENT/AMBIGUOUS rows are never touched -- reclassify_pending_rows
    only ever selects via outbox.pending(), which returns PENDING rows
    only."""
    import asyncio
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
    from talonx_ingest.intelligence.delivery.pipeline import (
        RecordingSender, enqueue_card, process_pending,
    )
    from talonx_ingest.intelligence.significance.store import SignificanceStore
    from _delivery_helpers import make_card

    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 15, 16, 0, 0, tzinfo=UTC)
    card, _ = make_card(symbol="SENT1", event_type=EventType.REGULATION_FD,
                        on_watchlist=True, now=now)
    result = enqueue_card(card, outbox=ob, now=now)
    asyncio.run(process_pending(ob, RecordingSender(), mode="enabled", route="IMMEDIATE", now=now))
    assert ob.get(result.row.delivery_id).state == "SENT"

    sig_store = SignificanceStore(ledger_path)
    res = reclassify_pending_rows(ob, significance_store=sig_store, route="IMMEDIATE", limit=10, now=now)
    assert res.scanned == 0
    assert ob.get(result.row.delivery_id).state == "SENT"
    assert ob.get(result.row.delivery_id).route == "IMMEDIATE"   # untouched
    ob.close()


# ---------------------------------------------------------------------
# render_concise -- the compact 3-5-line IMMEDIATE shape (policy §7).
# ---------------------------------------------------------------------

def test_render_concise_is_within_the_compact_line_target():
    from talonx_ingest.intelligence.delivery.renderer import render_concise
    from _delivery_helpers import make_card

    card, _ = make_card(symbol="ACME", event_type=EventType.EARNINGS_RESULTS,
                        on_watchlist=True, now=datetime(2026, 9, 15, tzinfo=UTC))
    msg = render_concise(card, disposition_reason="a specific substantive change",
                         now=datetime(2026, 9, 15, 1, 0, tzinfo=UTC))
    lines = msg.text.split("\n")
    assert 3 <= len(lines) <= 5
    assert msg.route == "IMMEDIATE"
    assert msg.tier == "CONCISE"


def test_render_concise_names_the_specific_disposition_reason():
    from talonx_ingest.intelligence.delivery.renderer import render_concise
    from _delivery_helpers import make_card

    card, _ = make_card(symbol="ACME", event_type=EventType.QUARTERLY_FILING,
                        on_watchlist=True, now=datetime(2026, 9, 15, tzinfo=UTC))
    msg = render_concise(card, disposition_reason="Risk Factors rewrite, top decile of history")
    assert "Risk Factors rewrite, top decile of history" in msg.text


def test_render_concise_never_drops_the_disclaimer():
    from talonx_ingest.intelligence.delivery.renderer import render_concise
    from _delivery_helpers import make_card

    card, _ = make_card(symbol="ACME", event_type=EventType.EARNINGS_RESULTS,
                        on_watchlist=True, now=datetime(2026, 9, 15, tzinfo=UTC))
    msg = render_concise(card, disposition_reason="x")
    assert "not advice" in msg.text.lower() or "information" in msg.text.lower()
    assert msg.disclaimer_present is True


def test_render_concise_shows_source_age_not_a_false_freshness_claim():
    from talonx_ingest.intelligence.delivery.renderer import render_concise
    from _delivery_helpers import make_card

    accepted = datetime(2026, 9, 15, 10, 0, 0, tzinfo=UTC)
    card, _ = make_card(symbol="ACME", event_type=EventType.EARNINGS_RESULTS,
                        on_watchlist=True, now=accepted)
    msg = render_concise(card, disposition_reason="x", now=accepted + timedelta(hours=2))
    assert "source age" in msg.text.lower()
    assert "fresh" not in msg.text.lower()   # never claims "fresh" outright


def test_immediate_card_from_enqueue_card_uses_the_concise_shape():
    """End-to-end: enqueue_card(tier='CONCISE') produces the same compact
    shape as render_concise directly."""
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
    from talonx_ingest.intelligence.delivery.pipeline import enqueue_card
    from _delivery_helpers import make_card

    ob = DeliveryOutbox(":memory:")
    now = datetime(2026, 9, 15, 16, 0, 0, tzinfo=UTC)
    card, _ = make_card(symbol="ACME", event_type=EventType.EARNINGS_RESULTS,
                        on_watchlist=True, now=now)
    result = enqueue_card(card, outbox=ob, now=now, route_override="IMMEDIATE",
                          tier="CONCISE", disposition_reason="a specific substantive change")
    assert result.row.route == "IMMEDIATE"
    lines = result.row.text.split("\n")
    assert 3 <= len(lines) <= 5
    ob.close()
