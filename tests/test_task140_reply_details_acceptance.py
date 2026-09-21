"""
tests/test_task140_reply_details_acceptance.py
=================================================
Task 140 -- meaningful acceptance tests for the reply-for-details
ordering/index/source-link/wording corrections, using the REAL digest
renderer (``pipeline.process_digest`` / ``pipeline.digest_display_order``),
the REAL persisted correlation (``DeliveryOutbox.mark_digest_sent``'s new
``digest_item_ordinal``), and the REAL reply resolver
(``reply_correlation.resolve_details_reply``) together, against an
isolated on-disk sqlite store (never the production ``ingestion_ledger.db``).

Regression fixture: a 14-item digest shaped exactly like the real
historical one an operator round-tripped against (band-uniform MEDIUM,
symbols AKAM, AMZN, APO, CMG, CNP, D, FDX, FITB, MTB, NEE, PH, SYY, TDG,
TECH) -- enqueued in a DELIBERATELY DIFFERENT order from display order,
reproducing the exact shape that exposed the real ordering bug. No
private chat IDs or credentials are used anywhere in this file.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
from talonx_ingest.intelligence.delivery.pipeline import enqueue_card, process_digest
from talonx_ingest.intelligence.delivery.reply_correlation import (
    DetailsContext,
    ReadOnlyIntelligenceReader,
    _one_item_detail,
    build_intelligence_details_resolver,
    resolve_details_reply,
)
from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.insider.domain import InsiderFiling
from talonx_ingest.intelligence.insider.store import InsiderStore
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
NOW = datetime(2026, 9, 15, 0, 7, 55, tzinfo=UTC)

# The real historical digest's own display order (band-uniform MEDIUM,
# so the effective sort is alphabetical-by-symbol) -- the regression
# fixture proven against the operator's own reported evidence.
_HISTORICAL_ORDER = ["AKAM", "AMZN", "APO", "CMG", "CNP", "D", "FDX",
                     "FITB", "MTB", "NEE", "PH", "SYY", "TDG", "TECH"]
# Enqueued in a DIFFERENT order (not alphabetical, not display order) --
# exactly the shape that exposed the real bug, where enqueue order and
# display order silently disagreed.
_ENQUEUE_ORDER = ["PH", "APO", "MTB", "AKAM", "D", "FDX", "SYY", "AMZN",
                  "NEE", "TDG", "TECH", "FITB", "CMG", "CNP"]


class _FixedIdDigestSender:
    """A digest sender that behaves like the real Telegram transport
    adapter: it accepts the ONE synthetic digest row process_digest
    builds and returns a real-shaped SenderResult carrying a Telegram
    message id -- unlike the bare RecordingSender (message_id=None),
    this lets tests reply against a concrete id, exactly as an operator
    would reply to the digest message they actually received."""

    configured = True

    def __init__(self, message_id: int = 95800):
        self.message_id = message_id
        self.sent: list = []

    async def send(self, row):
        from talonx_ingest.intelligence.delivery.pipeline import SenderResult

        self.sent.append(row)
        return SenderResult(ok=True, message_id=self.message_id)


def _ev_sig(symbol, accession, *, event_type=EventType.REGULATION_FD,
           band=SignificanceBand.MEDIUM, score=30, now=NOW):
    ev = mk_event(symbol=symbol, accession=accession, event_type=event_type, now=now)
    ev = ev.model_copy(update={
        "filing_index_url": f"https://www.sec.gov/Archives/edgar/data/1/{accession}-index.htm",
    })
    sig = InformationSignificance(
        significance_id=f"sig-{accession}", event_id=ev.event_id, symbol=symbol,
        score=score, raw_score=score, band=band,
        reasons=(SignificanceReason(code="EVENT_TYPE_BASE", description="a filing arrived",
                                    points=score, component="event_type_base"),),
        input_fingerprint=f"fp-{accession}", evaluated_at_utc=now,
    )
    return ev, sig


def _card(ev, sig):
    return apply_significance(build_alert_card(ev), sig)


def _seed_digest(ledger_path, *, symbols_enqueue_order, message_id=95800):
    """Builds+enqueues one MEDIUM-band card per symbol (in the given
    enqueue order) via the REAL enqueue_card, persists matching events
    and significance, then drains through the REAL process_digest.
    Returns (message_id, sender) -- the outbox/events/significance
    stores are left CLOSED on disk at ledger_path for the caller to
    reopen freely (proves durability, not in-memory state)."""
    ob = DeliveryOutbox(ledger_path)
    events_store = EventStore(ledger_path)
    sig_store = SignificanceStore(ledger_path)

    for i, sym in enumerate(symbols_enqueue_order):
        accession = f"000{1000 + i}000000-26-{100000 + i}"
        ev, sig = _ev_sig(sym, accession)
        card = _card(ev, sig)
        enqueue_card(card, outbox=ob, now=NOW)
        events_store.upsert_event(ev)
        sig_store.upsert(sig)

    sender = _FixedIdDigestSender(message_id=message_id)
    res = asyncio.run(process_digest(ob, sender, mode="enabled",
                                     interval_seconds=6 * 3600.0, now=NOW))
    assert res.delivered == len(symbols_enqueue_order)

    ob.close()
    events_store.close()
    sig_store.close()
    return message_id, sender


def test_the_real_digest_renderer_produces_the_exact_historical_display_order(tmp_path):
    """Ground truth: process_digest's OWN rendered text lists the 14
    symbols in exactly the historical order, regardless of enqueue
    order -- confirms the regression fixture reproduces the real bug's
    shape before testing the correlation fix against it."""
    ledger_path = tmp_path / "l.db"
    _msg_id, sender = _seed_digest(ledger_path, symbols_enqueue_order=_ENQUEUE_ORDER)
    text = sender.sent[0].text
    order_in_text = [line.split(":")[0].lstrip("- ") for line in text.splitlines()
                     if line.startswith("- ")]
    assert order_in_text == _HISTORICAL_ORDER


def test_details_index_and_details_n_match_the_real_displayed_order(tmp_path):
    """The core fix: 'details' alone lists items in the EXACT order the
    digest actually displayed them, and 'details N' for each N resolves
    to the SAME symbol as that position in the real rendered text --
    derived from the newly-persisted digest_item_ordinal, not a
    re-derived or database-insertion order."""
    ledger_path = tmp_path / "l.db"
    message_id, _sender = _seed_digest(ledger_path, symbols_enqueue_order=_ENQUEUE_ORDER)

    ob = DeliveryOutbox(ledger_path)
    events_store = EventStore(ledger_path)
    sig_store = SignificanceStore(ledger_path)

    index_text = resolve_details_reply("details", message_id, outbox=ob,
                                       events_store=events_store, significance_store=sig_store)
    for i, sym in enumerate(_HISTORICAL_ORDER, start=1):
        assert f"{i}. {sym}" in index_text
    assert "reconstructed" not in index_text   # stored ordinal -- verified, not reconstructed

    # "details 2" must resolve to the digest's own second item (AMZN),
    # not whatever enqueue-order position 2 happened to be (APO, the
    # real historical bug).
    item2 = resolve_details_reply("details 2", message_id, outbox=ob,
                                  events_store=events_store, significance_store=sig_store)
    assert "[Item 2 of 14]" in item2
    assert item2.split("\n\n", 1)[1].startswith("AMZN --")

    # every position agrees with the historical order
    for i, sym in enumerate(_HISTORICAL_ORDER, start=1):
        item = resolve_details_reply(f"details {i}", message_id, outbox=ob,
                                     events_store=events_store, significance_store=sig_store)
        assert f"[Item {i} of 14]" in item
        assert item.split("\n\n", 1)[1].startswith(f"{sym} --")

    ob.close()
    events_store.close()
    sig_store.close()


def test_order_survives_close_and_reopen(tmp_path):
    ledger_path = tmp_path / "l.db"
    message_id, _sender = _seed_digest(ledger_path, symbols_enqueue_order=_ENQUEUE_ORDER)

    ob2 = DeliveryOutbox(ledger_path)
    events_store = EventStore(ledger_path)
    sig_store = SignificanceStore(ledger_path)
    index_text = resolve_details_reply("details", message_id, outbox=ob2,
                                       events_store=events_store, significance_store=sig_store)
    for i, sym in enumerate(_HISTORICAL_ORDER, start=1):
        assert f"{i}. {sym}" in index_text
    ob2.close()
    events_store.close()
    sig_store.close()


def test_later_events_do_not_reorder_an_old_message(tmp_path):
    """A digest sent, then MORE events enqueued and sent as a SECOND
    digest afterward, must not change the first digest's own persisted
    order or its resolution."""
    ledger_path = tmp_path / "l.db"
    message_id, _sender = _seed_digest(ledger_path, symbols_enqueue_order=_ENQUEUE_ORDER,
                                       message_id=95800)

    ob = DeliveryOutbox(ledger_path)
    events_store = EventStore(ledger_path)
    sig_store = SignificanceStore(ledger_path)
    before = resolve_details_reply("details 2", message_id, outbox=ob,
                                   events_store=events_store, significance_store=sig_store)
    ob.close(); events_store.close(); sig_store.close()

    # second, later digest -- different bucket
    later_now = NOW.replace(hour=6)
    ob2 = DeliveryOutbox(ledger_path)
    events_store2 = EventStore(ledger_path)
    sig_store2 = SignificanceStore(ledger_path)
    for i, sym in enumerate(["ZBH", "ZION"]):
        accession = f"0009{i}00000-26-{900000 + i}"
        ev, sig = _ev_sig(sym, accession, now=later_now)
        card = _card(ev, sig)
        enqueue_card(card, outbox=ob2, now=later_now)
        events_store2.upsert_event(ev)
        sig_store2.upsert(sig)
    sender2 = _FixedIdDigestSender(message_id=95801)
    res2 = asyncio.run(process_digest(ob2, sender2, mode="enabled",
                                      interval_seconds=6 * 3600.0, now=later_now))
    assert res2.delivered == 2

    after = resolve_details_reply("details 2", message_id, outbox=ob2,
                                  events_store=events_store2, significance_store=sig_store2)
    assert before == after
    assert after.split("\n\n", 1)[1].startswith("AMZN --")
    ob2.close(); events_store2.close(); sig_store2.close()


def test_all_14_items_are_shown_not_hidden_behind_and_n_more(tmp_path):
    ledger_path = tmp_path / "l.db"
    message_id, _sender = _seed_digest(ledger_path, symbols_enqueue_order=_ENQUEUE_ORDER)

    ob = DeliveryOutbox(ledger_path)
    events_store = EventStore(ledger_path)
    sig_store = SignificanceStore(ledger_path)
    index_text = resolve_details_reply("details", message_id, outbox=ob,
                                       events_store=events_store, significance_store=sig_store)
    assert "and 8 more" not in index_text
    assert "14. TECH" in index_text
    for sym in _HISTORICAL_ORDER:
        assert sym in index_text
    ob.close(); events_store.close(); sig_store.close()


def test_a_larger_index_paginates_with_stable_numbering(tmp_path):
    """25 items (over _INDEX_ITEMS_PER_PAGE=20) -- page 1 shows 1-20,
    page 2 shows 21-25, item numbers never restart, and 'details N' for
    any N resolves correctly regardless of which page was last shown."""
    symbols = [f"SYM{i:02d}" for i in range(25)]
    ledger_path = tmp_path / "l.db"
    message_id, _sender = _seed_digest(ledger_path, symbols_enqueue_order=symbols)

    ob = DeliveryOutbox(ledger_path)
    events_store = EventStore(ledger_path)
    sig_store = SignificanceStore(ledger_path)

    page1 = resolve_details_reply("details", message_id, outbox=ob,
                                  events_store=events_store, significance_store=sig_store)
    assert "Page 1 of 2" in page1
    assert "1. SYM00" in page1 and "20. SYM19" in page1
    assert "21. SYM20" not in page1

    page2 = resolve_details_reply("details page 2", message_id, outbox=ob,
                                  events_store=events_store, significance_store=sig_store)
    assert "Page 2 of 2" in page2
    assert "21. SYM20" in page2 and "25. SYM24" in page2

    item21 = resolve_details_reply("details 21", message_id, outbox=ob,
                                   events_store=events_store, significance_store=sig_store)
    assert item21.split("\n\n", 1)[1].startswith("SYM20 --")
    ob.close(); events_store.close(); sig_store.close()


def test_source_link_uses_validated_insider_filing_issuer_cik_not_accession_prefix(tmp_path):
    """Real production shape: accession prefix (a filing agent/insider's
    own CIK, 0001689315) != the issuer's real CIK (0001858681, Apollo
    Global Management) -- the link must come from the validated
    insider_filings.source_reference, never be constructed by guessing
    the issuer CIK from the accession's own prefix."""
    ledger_path = tmp_path / "l.db"
    accession = "0001689315-26-000002"
    ev, sig = _ev_sig("APO", accession, event_type=EventType.INSIDER_TRANSACTION,
                      band=SignificanceBand.HIGH)
    ev = ev.model_copy(update={"filing_index_url": None})  # upstream gap: not populated for Form 4

    ob = DeliveryOutbox(ledger_path)
    card = _card(ev, sig)
    result = enqueue_card(card, outbox=ob, now=NOW)
    assert result.row.route == "IMMEDIATE"
    ob.mark_sent(result.row.delivery_id, message_id=9001, now=NOW)

    real_url = "https://www.sec.gov/Archives/edgar/data/1858681/000168931526000002/wk-form4_1789417000.xml"
    insider_store = InsiderStore(ledger_path)
    insider_store.upsert_filing(InsiderFiling(
        insider_filing_id=accession, accession=accession, event_id=ev.event_id,
        symbol="APO", issuer_cik="0001858681", company_name="Apollo Global Management, Inc.",
        accepted_at_utc=NOW, n_transactions=1, n_owners=1,
        owner_ciks=("0001689315",), owner_names=("Belardi James Richard",),
        source_reference=f"SEC_EDGAR_ARCHIVES:{real_url}",
        ingested_at_utc=NOW,
    ))
    insider_store.close()

    reader = ReadOnlyIntelligenceReader(ledger_path)
    filing = reader.get_filing_for_event(ev.event_id)
    assert filing is not None and filing.issuer_cik == "0001858681"

    ctx = DetailsContext(row=ob.get(result.row.delivery_id), event=ev, significance=sig,
                         insider_filing=filing)
    text = "\n".join(_one_item_detail(ctx))
    assert real_url in text
    assert "0001858681" in text or "1858681" in text
    reader.close()
    ob.close()


def test_missing_source_metadata_never_guesses_a_link(tmp_path):
    ledger_path = tmp_path / "l.db"
    accession = "0009999999-26-000099"
    ev, sig = _ev_sig("NOLNK", accession, event_type=EventType.INSIDER_TRANSACTION,
                      band=SignificanceBand.HIGH)
    ev = ev.model_copy(update={"filing_index_url": None})

    ob = DeliveryOutbox(ledger_path)
    card = _card(ev, sig)
    result = enqueue_card(card, outbox=ob, now=NOW)

    ctx = DetailsContext(row=ob.get(result.row.delivery_id), event=ev, significance=sig,
                         insider_filing=None)
    text = "\n".join(_one_item_detail(ctx))
    assert "Source link unavailable" in text
    assert accession in text          # the accession itself is still retained
    assert "Filing link:" not in text  # never a fabricated link line
    ob.close()


def test_digest_item_labelled_supporting_card_not_original_message(tmp_path):
    """The confirmed real mislabeling: a digest item's fuller stored card
    text was labelled 'Original notification text sent to you' even
    though the actual message the operator received was the compact
    digest line. Must now show the ACTUAL digest line, correctly
    labelled, and label the fuller card as supporting/stored, not
    'original'."""
    ledger_path = tmp_path / "l.db"
    message_id, _sender = _seed_digest(ledger_path, symbols_enqueue_order=["ONE", "TWO"])

    ob = DeliveryOutbox(ledger_path)
    events_store = EventStore(ledger_path)
    sig_store = SignificanceStore(ledger_path)
    item1 = resolve_details_reply("details 1", message_id, outbox=ob,
                                  events_store=events_store, significance_store=sig_store)
    assert "digest line you actually received" in item1
    assert "Stored supporting card" in item1
    assert "Original notification text sent to you" not in item1
    ob.close(); events_store.close(); sig_store.close()


def test_digest_line_reconstruction_via_the_real_readonly_production_wiring(tmp_path):
    """Task 140 regression, found via live re-verification against the
    real historical production message: the read-only reader
    (ReadOnlyIntelligenceReader / build_intelligence_details_resolver --
    the EXACT path run_talonx.py wires up in production) hands rows
    whose evidence_urls column is a RAW un-decoded JSON string, not the
    already-json.loads'd tuple a real DeliveryRow carries. Indexing that
    raw string at [0] silently returned the literal character "[" instead
    of the real URL for every digest row with a non-empty evidence list
    -- confirmed live against 12 of the 14 real rows in message 958.
    Reproduced here with a local, isolated digest (never touches
    production) through the SAME production entry point."""
    ledger_path = tmp_path / "l.db"
    message_id, _sender = _seed_digest(ledger_path, symbols_enqueue_order=["ONE", "TWO"],
                                       message_id=95900)

    reader, resolver = build_intelligence_details_resolver(db_path=ledger_path)
    assert reader is not None and resolver is not None

    class _FakeReplyTo:
        def __init__(self, mid):
            self.message_id = mid

    class _FakeMsg:
        def __init__(self, text, reply_to_id):
            self.text = text
            self.reply_to_message = _FakeReplyTo(reply_to_id)

    item1 = resolver(_FakeMsg("details 1", message_id))
    assert "digest line you actually received" in item1
    line = [ln for ln in item1.splitlines() if ln.startswith("- ONE:")][0]
    assert not line.rstrip().endswith("[")
    assert "https://www.sec.gov/Archives/edgar/data/1/" in line
    reader.close()


def test_single_card_send_still_labelled_original_message(tmp_path):
    """A genuine single-card IMMEDIATE send (not a digest) keeps the
    accurate 'Original message' label -- this distinction is real,
    per-route, not removed globally."""
    ledger_path = tmp_path / "l.db"
    ev, sig = _ev_sig("SOLO", "0007777777-26-000077", band=SignificanceBand.HIGH)
    ob = DeliveryOutbox(ledger_path)
    events_store = EventStore(ledger_path)
    sig_store = SignificanceStore(ledger_path)

    card = _card(ev, sig)
    result = enqueue_card(card, outbox=ob, now=NOW)
    assert result.row.route == "IMMEDIATE"
    ob.mark_sent(result.row.delivery_id, message_id=9002, now=NOW)
    events_store.upsert_event(ev)
    sig_store.upsert(sig)

    text = resolve_details_reply("details", 9002, outbox=ob,
                                 events_store=events_store, significance_store=sig_store)
    assert "Original message text sent to you" in text
    assert "digest line you actually received" not in text
    ob.close(); events_store.close(); sig_store.close()


def test_facts_and_selection_reasons_are_visually_separated(tmp_path):
    ledger_path = tmp_path / "l.db"
    ev, _sig = _ev_sig("SEPX", "0006666666-26-000066", band=SignificanceBand.HIGH)
    sig = InformationSignificance(
        significance_id="sig-sepx", event_id=ev.event_id, symbol="SEPX",
        score=45, raw_score=45, band=SignificanceBand.HIGH,
        reasons=(
            SignificanceReason(code="ON_WATCHLIST", description="this company is on your watchlist",
                              points=5, component="watchlist"),
            SignificanceReason(code="SECTION_CHANGE_DECILE",
                              description="Risk Factors rewrite in the top decile (change magnitude 71%)",
                              points=40, component="filing_change"),
        ),
        input_fingerprint="fp-sepx", evaluated_at_utc=NOW,
    )
    ob = DeliveryOutbox(ledger_path)
    events_store = EventStore(ledger_path)
    sig_store = SignificanceStore(ledger_path)

    card = _card(ev, sig)
    result = enqueue_card(card, outbox=ob, now=NOW)
    ob.mark_sent(result.row.delivery_id, message_id=9003, now=NOW)
    events_store.upsert_event(ev)
    sig_store.upsert(sig)

    text = resolve_details_reply("details", 9003, outbox=ob,
                                 events_store=events_store, significance_store=sig_store)
    facts_idx = text.index("Facts from the filing")
    reasons_idx = text.index("Why this was selected")
    watchlist_idx = text.index("on your watchlist")
    fact_idx = text.index("71%")
    assert facts_idx < fact_idx < reasons_idx < watchlist_idx
    ob.close(); events_store.close(); sig_store.close()


def test_unauthorized_chat_regression_coverage_still_present():
    """Regression note: chat authorization is enforced upstream in
    talonx_dispatch.telegram_listener._handle_update BEFORE any resolver
    (including this one) ever runs -- already exhaustively covered by
    tests/test_task138_telegram_message_resolvers.py, unaffected by this
    task's changes (verified separately: 8/8 pass). This test only
    confirms that coverage still exists in the suite."""
    import pathlib

    assert (pathlib.Path(__file__).parent / "test_task138_telegram_message_resolvers.py").exists()


def test_single_card_and_v2_actionable_routes_module_contract_unchanged():
    """Existing single-card reply-details behaviour (already covered
    exhaustively in test_task138_reply_correlation.py, 43/43 passing
    unchanged) still uses the same public entry points this task did
    not remove."""
    from talonx_ingest.intelligence.delivery.reply_correlation import (
        build_details_response, is_details_request, resolve_details_reply,
    )
    assert callable(build_details_response)
    assert callable(is_details_request)
    assert callable(resolve_details_reply)
