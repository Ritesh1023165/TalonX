"""
Task 117 output-closure -- D5: intelligence-delivery age/cutoff policy.

The ``intelligence_delivery`` outbox has never drained (9,843 rows, 100% PENDING,
0 ever SENT). Before wiring a drain into the running service, the drain must be
unable to flood Telegram with a historical backlog. These tests pin the
age/cutoff behaviour: on the first real drain every stale PENDING row goes
straight to EXPIRED (terminal, audit-preserving) and NOTHING is sent.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from talonx_ingest.intelligence.delivery.config import CARD_MAX_AGE_SECONDS, ROUTE_IMMEDIATE
from talonx_ingest.intelligence.delivery.outbox import (
    STATE_EXPIRED,
    STATE_PENDING,
    STATE_SENT,
    DeliveryOutbox,
)
from talonx_ingest.intelligence.delivery.pipeline import (
    RecordingSender,
    enqueue_card,
    process_pending,
)
from _delivery_helpers import make_card

UTC = timezone.utc


def _enq(ob, *, symbol, accession, enqueued_at):
    card, _ = make_card(symbol=symbol, accession=accession, on_watchlist=True, now=enqueued_at)
    return enqueue_card(card, outbox=ob, now=enqueued_at).row.delivery_id


def _drain(ob, sender, **kw):
    return asyncio.run(process_pending(ob, sender, **kw))


def test_stale_rows_expire_and_nothing_is_sent(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    old = now - timedelta(days=6)                       # a Sep-4-style backlog row
    did = _enq(ob, symbol="DELL", accession="0001193125-26-386868", enqueued_at=old)
    assert ob.get(did).state == STATE_PENDING

    snd = RecordingSender()
    res = _drain(ob, snd, now=now, enforce_age_cutoff=True)

    assert res.expired == 1 and did in res.expired_ids
    assert res.attempted == 0 and res.delivered == 0
    assert snd.sent == []                               # NOT flooded
    row = ob.get(did)
    assert row.state == STATE_EXPIRED
    assert "stale_card" in (row.suppress_reason or "")
    # audit trail preserved
    kinds = [l["kind"] for l in ob.logs(did)]
    assert "ENQUEUE" in kinds and "EXPIRED" in kinds
    assert "SENT" not in kinds
    ob.close()


def test_fresh_row_still_delivers_alongside_expiring_a_stale_one(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    stale = _enq(ob, symbol="DELL", accession="0001193125-26-386868",
                 enqueued_at=now - timedelta(hours=30))
    fresh = _enq(ob, symbol="ORCL", accession="0001193125-26-387905",
                 enqueued_at=now - timedelta(minutes=20))

    snd = RecordingSender()
    res = _drain(ob, snd, now=now, enforce_age_cutoff=True)

    assert ob.get(stale).state == STATE_EXPIRED
    assert ob.get(fresh).state == STATE_SENT
    assert res.expired == 1 and res.delivered == 1 and len(snd.sent) == 1
    ob.close()


def test_immediate_cutoff_is_six_hours(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    assert CARD_MAX_AGE_SECONDS[ROUTE_IMMEDIATE] == 6 * 3600
    just_ok = _enq(ob, symbol="V", accession="0001403161-26-000118",
                   enqueued_at=now - timedelta(hours=5, minutes=55))
    too_old = _enq(ob, symbol="ADP", accession="0001225208-26-007726",
                   enqueued_at=now - timedelta(hours=6, minutes=5))
    _drain(ob, RecordingSender(), now=now, enforce_age_cutoff=True)
    assert ob.get(just_ok).state == STATE_SENT
    assert ob.get(too_old).state == STATE_EXPIRED
    ob.close()


def test_expire_stale_is_idempotent_and_never_touches_terminal_rows(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    did = _enq(ob, symbol="DELL", accession="0001193125-26-386868",
               enqueued_at=now - timedelta(days=3))
    first = ob.expire_stale(now=now)
    second = ob.expire_stale(now=now)
    assert first == [did] and second == []              # idempotent
    assert ob.get(did).state == STATE_EXPIRED
    ob.close()


def test_default_drain_unchanged_without_opt_in(ledger_path):
    """The pure drain mechanics for existing callers are unaffected: no age
    cutoff unless enforce_age_cutoff=True is passed."""
    ob = DeliveryOutbox(ledger_path)
    now = datetime(2026, 9, 10, 20, 0, 0, tzinfo=UTC)
    did = _enq(ob, symbol="DELL", accession="0001193125-26-386868",
               enqueued_at=now - timedelta(days=30))
    res = _drain(ob, RecordingSender(), now=now)        # no enforce_age_cutoff
    assert res.expired == 0
    assert ob.get(did).state == STATE_SENT
    ob.close()
