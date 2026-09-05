"""
tests/test_delivery_outbox.py
-----------------------------
Task 96F -- durable outbox: additive schema, persist-before-send,
idempotent enqueue, retry accounting, priority ordering, restart safety.
"""
from __future__ import annotations

import sqlite3

import pytest

from talonx_ingest.intelligence.delivery.identity import delivery_id
from talonx_ingest.intelligence.delivery.outbox import (
    STATE_FAILED,
    STATE_PENDING,
    STATE_SENT,
    DeliveryOutbox,
)
from talonx_ingest.intelligence.delivery.renderer import render_compact
from _delivery_helpers import make_card, mk_comparison, mk_event
from talonx_ingest.intelligence.domain import EventType


def _msg(**kw):
    card, wc = make_card(**kw)
    return render_compact(card, what_changed=wc), card


def test_schema_is_additive(ledger_path):
    conn = sqlite3.connect(ledger_path)
    conn.execute("CREATE TABLE ingested_filings (accession TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO ingested_filings VALUES ('x')")
    conn.commit()
    conn.close()

    ob = DeliveryOutbox(ledger_path)
    m, card = _msg()
    ob.enqueue(m, delivery_id=delivery_id(card.alert_id))
    ob.close()

    conn = sqlite3.connect(ledger_path)
    assert conn.execute("SELECT COUNT(*) FROM ingested_filings").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM intelligence_delivery").fetchone()[0] == 1
    conn.close()


def test_enqueue_is_idempotent_on_delivery_id(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    m, card = _msg()
    did = delivery_id(card.alert_id)
    r1 = ob.enqueue(m, delivery_id=did)
    r2 = ob.enqueue(m, delivery_id=did)
    assert r1.created and not r2.created
    assert r2.disposition == "SUPPRESSED"
    assert len(ob.query()) == 1
    ob.close()


def test_persist_before_send_row_is_pending(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    m, card = _msg()
    did = delivery_id(card.alert_id)
    ob.enqueue(m, delivery_id=did)
    assert ob.get(did).state == STATE_PENDING
    ob.mark_sent(did)
    assert ob.get(did).state == STATE_SENT
    # a second mark_sent is a no-op (guarded on state = PENDING)
    ob.mark_sent(did)
    assert ob.get(did).state == STATE_SENT
    ob.close()


def test_retry_then_fail_terminal(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    m, card = _msg()
    did = delivery_id(card.alert_id)
    ob.enqueue(m, delivery_id=did)
    for i in range(4):
        st = ob.mark_failed(did, f"boom {i}")
        assert st == STATE_PENDING
    st = ob.mark_failed(did, "final")
    assert st == STATE_FAILED
    assert ob.get(did).attempts == 5
    ob.close()


def test_permanent_failure_is_immediately_terminal(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    m, card = _msg()
    did = delivery_id(card.alert_id)
    ob.enqueue(m, delivery_id=did)
    assert ob.mark_failed(did, "InvalidToken (non-retryable)", permanent=True) == STATE_FAILED
    ob.close()


def test_pending_orders_critical_first(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    ev = mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=())
    hi, hcard = _msg(
        event_type=EventType.ANNUAL_FILING, form_type="10-K", items=(), symbol="HII",
        comparison=mk_comparison(event=ev, rf_diff=0.7, mdna_diff=0.4, revenue_rel_delta=0.6),
        pinned=True,
    )
    lo, lcard = _msg(
        event_type=EventType.SHAREHOLDER_VOTE_RESULT, items=("5.07",), symbol="LOW", age_hours=100,
    )
    ob.enqueue(lo, delivery_id=delivery_id(lcard.alert_id))
    ob.enqueue(hi, delivery_id=delivery_id(hcard.alert_id))
    order = [r.symbol for r in ob.pending()]
    assert order.index("HII") < order.index("LOW")
    ob.close()


def test_restart_safe_state_survives_reopen(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    m, card = _msg()
    did = delivery_id(card.alert_id)
    ob.enqueue(m, delivery_id=did)
    ob.mark_failed(did, "transient")
    ob.close()

    ob2 = DeliveryOutbox(ledger_path)          # "restart"
    row = ob2.get(did)
    assert row.state == STATE_PENDING and row.attempts == 1
    assert len(ob2.pending()) == 1             # still deliverable
    ob2.close()


def test_log_records_lifecycle(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    m, card = _msg()
    did = delivery_id(card.alert_id)
    ob.enqueue(m, delivery_id=did)
    ob.mark_failed(did, "x")
    ob.mark_sent(did)
    kinds = [r["kind"] for r in ob.logs(did)]
    assert kinds == ["ENQUEUE", "RETRY", "SENT"]
    ob.close()
