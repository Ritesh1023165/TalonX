"""
tests/test_task138_reply_correlation.py
========================================
Task 138 Workstream 3 -- isolated coverage for
``talonx_ingest.intelligence.delivery.reply_correlation``: reply-for-
details correlation, deterministic (no external LLM), against
persisted evidence only. Every fixture DB is a REAL sqlite file on disk
(not in-memory) so the mode=ro production-wiring path
(``ReadOnlyIntelligenceReader`` / ``build_intelligence_details_resolver``)
can be exercised exactly as ``run_talonx.py`` uses it.

NOTE on scope: chat-identity authorization is enforced upstream, in
``talonx_dispatch.telegram_listener._handle_update``, before any
resolver (including this module's) ever runs -- so it is out of scope
for THIS file and is not re-tested here.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from talonx_ingest.intelligence.delivery.reply_correlation import (
    DetailsContext,
    ReadOnlyIntelligenceReader,
    _requested_index,
    build_details_response,
    build_intelligence_details_resolver,
    find_delivery_rows_for_message,
    is_details_request,
    resolve_details_reply,
)
from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.significance.domain import (
    InformationSignificance,
    SignificanceBand,
    SignificanceReason,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 15, 16, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------
# is_details_request / _requested_index -- pure text parsing
# ---------------------------------------------------------------------

@pytest.mark.parametrize("text", ["details", "Details", "DETAILS", "detail", "info",
                                  "details.", "details!", '"details"', "details 2",
                                  "details 1", "  details  "])
def test_is_details_request_recognizes_trigger_words(text):
    assert is_details_request(text) is True


@pytest.mark.parametrize("text", [None, "", "thanks", "ok", "what", "detailsx",
                                  "give me details please"])
def test_is_details_request_rejects_non_triggers(text):
    assert is_details_request(text) is False


def test_requested_index_parses_indexed_followup():
    assert _requested_index("details 2") == 2
    assert _requested_index("details") is None
    assert _requested_index("details foo") is None
    assert _requested_index("details 2 3") is None


# ---------------------------------------------------------------------
# shared fixture builders
# ---------------------------------------------------------------------

def _mk_event_and_sig(*, symbol, accession, event_type, now=NOW, text_body=None):
    from _significance_helpers import mk_event

    ev = mk_event(symbol=symbol, accession=accession, event_type=event_type, now=now)
    ev = ev.model_copy(update={
        "filing_index_url": f"https://www.sec.gov/Archives/edgar/data/1/{accession}-index.htm",
    })
    sig = InformationSignificance(
        significance_id=f"sig-{accession}", event_id=ev.event_id, symbol=symbol,
        score=40, raw_score=40, band=SignificanceBand.HIGH,
        reasons=(SignificanceReason(code="EVENT_TYPE_BASE", description="8-K item filed",
                                    points=40, component="event_type_base"),),
        input_fingerprint=f"fp-{accession}", evaluated_at_utc=now,
    )
    return ev, sig


def _mk_card_for(ev, sig):
    from talonx_ingest.intelligence.pipeline import build_alert_card
    from talonx_ingest.intelligence.significance.alert_integration import apply_significance

    return apply_significance(build_alert_card(ev), sig)


@pytest.fixture()
def ledger_path(tmp_path):
    return tmp_path / "ingestion_ledger.db"


# ---------------------------------------------------------------------
# find_delivery_rows_for_message -- single-card vs digest transport ids
# ---------------------------------------------------------------------

def test_find_delivery_rows_bare_id_matches_single_card_send(ledger_path):
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
    from talonx_ingest.intelligence.delivery.pipeline import enqueue_card

    ob = DeliveryOutbox(ledger_path)
    ev, sig = _mk_event_and_sig(symbol="LULU", accession="0001397187-26-000129",
                                event_type=EventType.CHARTER_BYLAW_AMENDMENT)
    card = _mk_card_for(ev, sig)
    result = enqueue_card(card, outbox=ob, now=NOW)
    ob.mark_sent(result.row.delivery_id, message_id=945, now=NOW)

    rows = find_delivery_rows_for_message(ob, 945)
    assert len(rows) == 1
    assert rows[0].delivery_id == result.row.delivery_id
    assert rows[0].event_id == ev.event_id

    assert find_delivery_rows_for_message(ob, 999999) == []
    ob.close()


def test_find_delivery_rows_digest_suffix_matches_every_constituent_row(ledger_path):
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
    from talonx_ingest.intelligence.delivery.pipeline import enqueue_card

    ob = DeliveryOutbox(ledger_path)
    ids = []
    for i, sym in enumerate(("DXCM", "PSA", "AXON")):
        ev, sig = _mk_event_and_sig(symbol=sym, accession=f"0000{i}00000-26-000100",
                                    event_type=EventType.REGULATION_FD)
        card = _mk_card_for(ev, sig)
        result = enqueue_card(card, outbox=ob, now=NOW)
        ids.append(result.row.delivery_id)
    ob.claim_digest_batch(ids, "digest-2026-09-15", now=NOW)
    ob.mark_digest_sent(ids, "digest-2026-09-15", message_id=1001, now=NOW)

    rows = find_delivery_rows_for_message(ob, 1001)
    assert len(rows) == 3
    assert {r.symbol for r in rows} == {"DXCM", "PSA", "AXON"}
    # a bare (non-digest) message id must NOT accidentally match a digest row
    assert find_delivery_rows_for_message(ob, "2026") == []
    ob.close()


# ---------------------------------------------------------------------
# build_details_response
# ---------------------------------------------------------------------

def test_build_details_response_empty_contexts_is_truthful_unavailable():
    text = build_details_response([])
    assert "predates durable reply correlation" in text
    assert "won't guess" in text


class _FakeRow:
    """A minimal stand-in for a real DeliveryRow -- only the attributes
    ``_one_item_detail`` actually reads."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_build_details_response_single_item_has_facts_link_and_limitations():
    ev, sig = _mk_event_and_sig(symbol="LULU", accession="0001397187-26-000129",
                                event_type=EventType.CHARTER_BYLAW_AMENDMENT)
    row = _FakeRow(
        delivery_id="deliv-abc12345", symbol="LULU", route="IMMEDIATE",
        text="<b>LULU</b> -- charter amendment. <a href=\"https://x\">link</a>",
        enqueued_at_utc=NOW, sent_at_utc=NOW,
    )
    ctx = DetailsContext(row=row, event=ev, significance=sig)
    text = build_details_response([ctx])

    assert ev.accession in text
    assert ev.filing_index_url in text
    assert "8-K item filed" in text and "EVENT_TYPE_BASE" in text
    assert "<b>" not in text and "<a href" not in text     # HTML stripped
    assert "LULU -- charter amendment. link" in text        # entities/tags removed, wording kept
    assert "Data limitations" in text


def test_build_details_response_missing_event_is_reported_not_guessed():
    row = _FakeRow(delivery_id="deliv-xyz", symbol="ACME", route="DIGEST",
                   text="plain text", enqueued_at_utc=NOW, sent_at_utc=NOW)
    ctx = DetailsContext(row=row, event=None, significance=None)
    text = build_details_response([ctx])
    assert "Source event record unavailable" in text
    assert "no persisted significance reasons found" in text


def test_build_details_response_multi_event_gives_indexed_summary_by_default():
    contexts = []
    for i, sym in enumerate(("DXCM", "PSA", "AXON")):
        ev, sig = _mk_event_and_sig(symbol=sym, accession=f"0000{i}00000-26-000100",
                                    event_type=EventType.REGULATION_FD)
        row = _FakeRow(delivery_id=f"deliv-{i}", symbol=sym, route="DIGEST",
                       text="t", enqueued_at_utc=NOW, sent_at_utc=NOW)
        contexts.append(DetailsContext(row=row, event=ev, significance=sig))

    text = build_details_response(contexts)
    assert "covered 3 event(s)" in text
    for i, sym in enumerate(("DXCM", "PSA", "AXON"), start=1):
        assert f"{i}. {sym}" in text
    assert 'Reply "details N"' in text


def test_build_details_response_indexed_followup_returns_one_item():
    contexts = []
    for i, sym in enumerate(("DXCM", "PSA", "AXON")):
        ev, sig = _mk_event_and_sig(symbol=sym, accession=f"0000{i}00000-26-000100",
                                    event_type=EventType.REGULATION_FD)
        row = _FakeRow(delivery_id=f"deliv-{i}", symbol=sym, route="DIGEST",
                       text="t", enqueued_at_utc=NOW, sent_at_utc=NOW)
        contexts.append(DetailsContext(row=row, event=ev, significance=sig))

    text = build_details_response(contexts, requested_index=2)
    assert "[Item 2 of 3]" in text
    assert "PSA" in text
    assert "0000100000-26-000100" in text  # PSA's accession, not DXCM's/AXON's


def test_build_details_response_out_of_range_index_gives_bounded_guidance():
    contexts = []
    for i, sym in enumerate(("DXCM", "PSA")):
        ev, sig = _mk_event_and_sig(symbol=sym, accession=f"0000{i}00000-26-000100",
                                    event_type=EventType.REGULATION_FD)
        row = _FakeRow(delivery_id=f"deliv-{i}", symbol=sym, route="DIGEST",
                       text="t", enqueued_at_utc=NOW, sent_at_utc=NOW)
        contexts.append(DetailsContext(row=row, event=ev, significance=sig))

    text = build_details_response(contexts, requested_index=99)
    assert "referenced 2 event(s)" in text
    assert "details 1" in text and "details 2" in text


def test_build_details_response_truncates_to_the_safe_reply_cap():
    ev, sig = _mk_event_and_sig(symbol="LULU", accession="0001397187-26-000129",
                                event_type=EventType.CHARTER_BYLAW_AMENDMENT)
    row = _FakeRow(delivery_id="deliv-huge", symbol="LULU", route="IMMEDIATE",
                   text="X" * 10000, enqueued_at_utc=NOW, sent_at_utc=NOW)
    ctx = DetailsContext(row=row, event=ev, significance=sig)
    text = build_details_response([ctx])
    assert len(text) <= 3500


# ---------------------------------------------------------------------
# resolve_details_reply -- the outbox/events_store/significance_store
# entry point used directly by make_telegram_message_resolver
# ---------------------------------------------------------------------

class _FakeEventsStore:
    def __init__(self, events_by_id, *, raise_on_get=False):
        self._events = events_by_id
        self._raise = raise_on_get

    def get_event(self, event_id):
        if self._raise:
            raise RuntimeError("simulated store failure")
        return self._events.get(event_id)


class _FakeSignificanceStore:
    def __init__(self, sig_by_event_id, *, raise_on_get=False):
        self._sigs = sig_by_event_id
        self._raise = raise_on_get

    def get_for_event(self, event_id):
        if self._raise:
            raise RuntimeError("simulated store failure")
        return self._sigs.get(event_id)


def test_resolve_details_reply_non_details_text_falls_through(ledger_path):
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox

    ob = DeliveryOutbox(ledger_path)
    result = resolve_details_reply("thanks", 945, outbox=ob, events_store=_FakeEventsStore({}),
                                   significance_store=_FakeSignificanceStore({}))
    assert result is None
    ob.close()


def test_resolve_details_reply_no_reply_target_asks_to_reply_directly(ledger_path):
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox

    ob = DeliveryOutbox(ledger_path)
    result = resolve_details_reply("details", None, outbox=ob, events_store=_FakeEventsStore({}),
                                   significance_store=_FakeSignificanceStore({}))
    assert result is not None and "Reply \"details\" directly" in result
    ob.close()


def test_resolve_details_reply_unmapped_old_message_is_truthfully_unavailable(ledger_path):
    """An old message predating durable correlation -- no delivery row will
    ever match. Must NOT guess; must say so explicitly."""
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox

    ob = DeliveryOutbox(ledger_path)
    result = resolve_details_reply("details", 123456, outbox=ob, events_store=_FakeEventsStore({}),
                                   significance_store=_FakeSignificanceStore({}))
    assert "predates durable reply correlation" in result
    ob.close()


def test_resolve_details_reply_full_roundtrip_matches_real_event_and_significance(ledger_path):
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
    from talonx_ingest.intelligence.delivery.pipeline import enqueue_card

    ob = DeliveryOutbox(ledger_path)
    ev, sig = _mk_event_and_sig(symbol="LULU", accession="0001397187-26-000129",
                                event_type=EventType.CHARTER_BYLAW_AMENDMENT)
    card = _mk_card_for(ev, sig)
    result = enqueue_card(card, outbox=ob, now=NOW)
    ob.mark_sent(result.row.delivery_id, message_id=945, now=NOW)

    events_store = _FakeEventsStore({ev.event_id: ev})
    sig_store = _FakeSignificanceStore({ev.event_id: sig})
    text = resolve_details_reply("details", 945, outbox=ob, events_store=events_store,
                                 significance_store=sig_store)
    assert ev.accession in text
    assert "EVENT_TYPE_BASE" in text
    ob.close()


def test_resolve_details_reply_survives_store_lookup_failures(ledger_path):
    """A downstream store raising must degrade to 'data unavailable', not
    crash the resolver / the poller."""
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
    from talonx_ingest.intelligence.delivery.pipeline import enqueue_card

    ob = DeliveryOutbox(ledger_path)
    ev, sig = _mk_event_and_sig(symbol="LULU", accession="0001397187-26-000129",
                                event_type=EventType.CHARTER_BYLAW_AMENDMENT)
    card = _mk_card_for(ev, sig)
    result = enqueue_card(card, outbox=ob, now=NOW)
    ob.mark_sent(result.row.delivery_id, message_id=945, now=NOW)

    text = resolve_details_reply(
        "details", 945, outbox=ob,
        events_store=_FakeEventsStore({}, raise_on_get=True),
        significance_store=_FakeSignificanceStore({}, raise_on_get=True),
    )
    assert "Source event record unavailable" in text
    assert "no persisted significance reasons found" in text
    ob.close()


def test_resolve_details_reply_indexed_followup_on_a_digest(ledger_path):
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
    from talonx_ingest.intelligence.delivery.pipeline import enqueue_card

    ob = DeliveryOutbox(ledger_path)
    events = {}
    sigs = {}
    ids = []
    for i, sym in enumerate(("DXCM", "PSA", "AXON")):
        ev, sig = _mk_event_and_sig(symbol=sym, accession=f"0000{i}00000-26-000100",
                                    event_type=EventType.REGULATION_FD)
        card = _mk_card_for(ev, sig)
        result = enqueue_card(card, outbox=ob, now=NOW)
        ids.append(result.row.delivery_id)
        events[ev.event_id] = ev
        sigs[ev.event_id] = sig
    ob.claim_digest_batch(ids, "digest-2026-09-15", now=NOW)
    ob.mark_digest_sent(ids, "digest-2026-09-15", message_id=1001, now=NOW)

    events_store = _FakeEventsStore(events)
    sig_store = _FakeSignificanceStore(sigs)

    summary = resolve_details_reply("details", 1001, outbox=ob, events_store=events_store,
                                    significance_store=sig_store)
    assert "covered 3 event(s)" in summary

    item2 = resolve_details_reply("details 2", 1001, outbox=ob, events_store=events_store,
                                  significance_store=sig_store)
    assert "[Item 2 of 3]" in item2 and "PSA" in item2

    ob.close()


# ---------------------------------------------------------------------
# Production wiring: ReadOnlyIntelligenceReader / build_intelligence_
# details_resolver against a REAL on-disk sqlite file, mode=ro
# ---------------------------------------------------------------------

def _populate_real_ledger(path, *, symbol="LULU", accession="0001397187-26-000129",
                          event_type=EventType.CHARTER_BYLAW_AMENDMENT, message_id=945):
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
    from talonx_ingest.intelligence.delivery.pipeline import enqueue_card
    from talonx_ingest.intelligence.significance.store import SignificanceStore
    from talonx_ingest.intelligence.store import EventStore

    ev, sig = _mk_event_and_sig(symbol=symbol, accession=accession, event_type=event_type)
    card = _mk_card_for(ev, sig)

    events_store = EventStore(path)
    events_store.upsert_event(ev)
    events_store.close()

    sig_store = SignificanceStore(path)
    sig_store.upsert(sig)
    sig_store.close()

    ob = DeliveryOutbox(path)
    result = enqueue_card(card, outbox=ob, now=NOW)
    ob.mark_sent(result.row.delivery_id, message_id=message_id, now=NOW)
    ob.close()
    return ev, sig, result.row.delivery_id


class _FakeReplyToMessage:
    def __init__(self, message_id):
        self.message_id = message_id


class _FakeTelegramMessage:
    """Stands in for a real python-telegram-bot Message -- only the
    attributes ``message_resolver``/``make_telegram_message_resolver``
    actually read."""

    def __init__(self, text, reply_to_message_id=None):
        self.text = text
        self.reply_to_message = (
            _FakeReplyToMessage(reply_to_message_id) if reply_to_message_id is not None else None
        )


def test_read_only_reader_reads_a_real_on_disk_ledger(ledger_path):
    ev, sig, delivery_id = _populate_real_ledger(ledger_path)

    reader = ReadOnlyIntelligenceReader(ledger_path)
    rows = reader.find_delivery_rows_for_message(945)
    assert len(rows) == 1 and rows[0].delivery_id == delivery_id

    got_ev = reader.get_event(ev.event_id)
    assert got_ev is not None and got_ev.accession == ev.accession

    got_sig = reader.get_significance(ev.event_id)
    assert got_sig is not None and got_sig.reasons and got_sig.reasons[0].code == "EVENT_TYPE_BASE"
    reader.close()


def test_build_intelligence_details_resolver_end_to_end_real_message(ledger_path):
    ev, sig, delivery_id = _populate_real_ledger(ledger_path)

    reader, resolver = build_intelligence_details_resolver(db_path=ledger_path)
    assert reader is not None and resolver is not None

    msg = _FakeTelegramMessage("details", reply_to_message_id=945)
    text = resolver(msg)
    assert ev.accession in text
    assert ev.filing_index_url in text
    assert "EVENT_TYPE_BASE" in text
    reader.close()


def test_build_intelligence_details_resolver_non_details_message_returns_none(ledger_path):
    _populate_real_ledger(ledger_path)
    reader, resolver = build_intelligence_details_resolver(db_path=ledger_path)
    assert resolver(_FakeTelegramMessage("good morning")) is None
    reader.close()


def test_build_intelligence_details_resolver_no_reply_target(ledger_path):
    _populate_real_ledger(ledger_path)
    reader, resolver = build_intelligence_details_resolver(db_path=ledger_path)
    text = resolver(_FakeTelegramMessage("details", reply_to_message_id=None))
    assert "Reply \"details\" directly" in text
    reader.close()


def test_build_intelligence_details_resolver_unmapped_old_message(ledger_path):
    _populate_real_ledger(ledger_path)
    reader, resolver = build_intelligence_details_resolver(db_path=ledger_path)
    text = resolver(_FakeTelegramMessage("details", reply_to_message_id=42))
    assert "predates durable reply correlation" in text
    reader.close()


def test_build_intelligence_details_resolver_missing_db_fails_gracefully(tmp_path):
    """Mirrors the Experimental resolver's own contract: a missing/
    unreadable db must return (None, None) via on_error, never raise
    into run_talonx.py's startup path."""
    missing = tmp_path / "does_not_exist" / "ingestion_ledger.db"
    errors = []
    reader, resolver = build_intelligence_details_resolver(
        db_path=missing, on_error=lambda exc: errors.append(exc)
    )
    assert reader is None and resolver is None
    assert len(errors) == 1


def test_resolver_is_idempotent_across_repeated_calls_same_update(ledger_path):
    """A duplicate inbound Telegram update (same message replayed) must
    resolve to the identical answer, with no mutation of persisted state
    -- this module holds no in-memory-only state to desync."""
    ev, sig, delivery_id = _populate_real_ledger(ledger_path)
    reader, resolver = build_intelligence_details_resolver(db_path=ledger_path)
    msg = _FakeTelegramMessage("details", reply_to_message_id=945)
    first = resolver(msg)
    second = resolver(msg)
    assert first == second
    reader.close()


def test_reader_survives_a_simulated_listener_restart(ledger_path):
    """Correlation must survive a listener restart -- i.e. depend only on
    the durable on-disk table, never an in-memory dictionary. Simulated
    by closing the resolver's reader entirely and building a brand-new
    one (as run_talonx.py would on process restart) against the SAME
    file, then confirming the same message id still resolves."""
    ev, sig, delivery_id = _populate_real_ledger(ledger_path)

    reader1, resolver1 = build_intelligence_details_resolver(db_path=ledger_path)
    before = resolver1(_FakeTelegramMessage("details", reply_to_message_id=945))
    reader1.close()

    reader2, resolver2 = build_intelligence_details_resolver(db_path=ledger_path)
    after = resolver2(_FakeTelegramMessage("details", reply_to_message_id=945))
    reader2.close()

    assert before == after
    assert ev.accession in after


def test_reader_handles_a_concurrent_writer_mid_session(ledger_path, tmp_path):
    """A card enqueued+sent AFTER the reader/resolver was already built
    must still resolve on the NEXT call (mode=ro sees committed writes
    from the live WAL-mode writer -- no restart required for new data,
    matching how the real Intelligence poller keeps writing while the
    listener process reads)."""
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
    from talonx_ingest.intelligence.delivery.pipeline import enqueue_card
    from talonx_ingest.intelligence.significance.store import SignificanceStore
    from talonx_ingest.intelligence.store import EventStore

    # touch the file into existence first (mode=ro requires it to exist)
    _populate_real_ledger(ledger_path, symbol="LULU", accession="0001397187-26-000129",
                          message_id=945)
    reader, resolver = build_intelligence_details_resolver(db_path=ledger_path)

    ev2, sig2 = _mk_event_and_sig(symbol="AXON", accession="0009999999-26-000200",
                                  event_type=EventType.REGULATION_FD)
    card2 = _mk_card_for(ev2, sig2)
    EventStore(ledger_path).upsert_event(ev2)
    SignificanceStore(ledger_path).upsert(sig2)
    ob = DeliveryOutbox(ledger_path)
    r2 = enqueue_card(card2, outbox=ob, now=NOW)
    ob.mark_sent(r2.row.delivery_id, message_id=2002, now=NOW)
    ob.close()

    text = resolver(_FakeTelegramMessage("details", reply_to_message_id=2002))
    assert ev2.accession in text
    reader.close()
