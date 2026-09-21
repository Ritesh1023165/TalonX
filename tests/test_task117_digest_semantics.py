"""
Task 117 -- DIGEST route is AGGREGATED into one scheduled message, not sent
per-row. Restart in the same window does not re-send.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.delivery.outbox import (
    STATE_PENDING, STATE_SENT, DeliveryOutbox,
)
from talonx_ingest.intelligence.delivery.pipeline import (
    SenderResult, enqueue_card, process_digest,
)
from _delivery_helpers import make_card

UTC = timezone.utc
NOW = datetime(2026, 9, 11, 13, 0, 0, tzinfo=UTC)
INTERVAL = 6 * 3600.0


class _Sender:
    def __init__(self, *, configured=True, result=None):
        self.configured = configured
        self._result = result or SenderResult(ok=True, message_id=555)
        self.sent = []

    async def send(self, row):
        self.sent.append(getattr(row, "text", ""))
        return self._result


def _enq_digest(ob, sym, acc, *, at):
    # MEDIUM-band insider tx -> DIGEST route
    c, _ = make_card(symbol=sym, event_type=EventType.INSIDER_TRANSACTION,
                     accession=acc, on_watchlist=False, now=at)
    r = enqueue_card(c, outbox=ob, now=at).row
    assert r.route == "DIGEST"
    return r.delivery_id


def test_multiple_digest_rows_become_one_message(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    ids = [
        _enq_digest(ob, "TSLA", "0001104659-26-000001", at=NOW - timedelta(minutes=30)),
        _enq_digest(ob, "AAPL", "0000320193-26-000002", at=NOW - timedelta(minutes=20)),
        _enq_digest(ob, "MSFT", "0000789019-26-000003", at=NOW - timedelta(minutes=10)),
    ]
    snd = _Sender()
    r = asyncio.run(process_digest(ob, snd, mode="enabled", interval_seconds=INTERVAL, now=NOW))
    assert len(snd.sent) == 1                       # ONE message, not three
    assert r.delivered == 3                         # all 3 rows marked delivered
    for did in ids:
        row = ob.get(did)
        assert row.state == STATE_SENT
        assert row.transport_message_id.startswith("digest:")
    assert all(s in snd.sent[0] for s in ("TSLA", "AAPL", "MSFT"))
    ob.close()


def test_not_due_holds_digest_rows_pending(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    did = _enq_digest(ob, "TSLA", "0001104659-26-000001", at=NOW - timedelta(minutes=5))
    snd = _Sender()
    # first run at NOW -> due (no prior bucket) -> sends
    asyncio.run(process_digest(ob, snd, mode="enabled", interval_seconds=INTERVAL, now=NOW))
    assert ob.get(did).state == STATE_SENT
    # a new row arrives 1h later -- still the SAME 6h window -> NOT due
    did2 = _enq_digest(ob, "AAPL", "0000320193-26-000002", at=NOW + timedelta(hours=1))
    r = asyncio.run(process_digest(ob, snd, mode="enabled", interval_seconds=INTERVAL,
                                   now=NOW + timedelta(hours=1)))
    assert r.held == 1 and r.held_reason == "digest_not_due"
    assert ob.get(did2).state == STATE_PENDING and len(snd.sent) == 1
    # next window -> due again
    r2 = asyncio.run(process_digest(ob, snd, mode="enabled", interval_seconds=INTERVAL,
                                    now=NOW + timedelta(hours=7)))
    assert ob.get(did2).state == STATE_SENT and len(snd.sent) == 2
    ob.close()


def test_restart_in_same_window_does_not_resend(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    _enq_digest(ob, "TSLA", "0001104659-26-000001", at=NOW - timedelta(minutes=5))
    snd = _Sender()
    asyncio.run(process_digest(ob, snd, mode="enabled", interval_seconds=INTERVAL, now=NOW))
    assert len(snd.sent) == 1
    ob.close()

    # "restart": fresh outbox on the same file, same window
    ob2 = DeliveryOutbox(ledger_path)
    snd2 = _Sender()
    r = asyncio.run(process_digest(ob2, snd2, mode="enabled", interval_seconds=INTERVAL,
                                   now=NOW + timedelta(minutes=10)))
    assert snd2.sent == []                          # not re-sent in the same bucket
    ob2.close()


def test_disabled_holds_and_simulate_does_not_send(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    did = _enq_digest(ob, "TSLA", "0001104659-26-000001", at=NOW - timedelta(minutes=5))
    snd = _Sender()
    r = asyncio.run(process_digest(ob, snd, mode="disabled", interval_seconds=INTERVAL, now=NOW))
    assert r.held == 1 and ob.get(did).state == STATE_PENDING and snd.sent == []
    r = asyncio.run(process_digest(ob, snd, mode="simulate", interval_seconds=INTERVAL, now=NOW))
    assert r.simulated == 1 and ob.get(did).state == STATE_PENDING and snd.sent == []
    ob.close()


def test_stale_digest_row_expires_and_is_not_in_the_message(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    fresh = _enq_digest(ob, "TSLA", "0001104659-26-000001", at=NOW - timedelta(hours=2))
    stale = _enq_digest(ob, "AAPL", "0000320193-26-000002", at=NOW - timedelta(days=3))
    snd = _Sender()
    r = asyncio.run(process_digest(ob, snd, mode="enabled", interval_seconds=INTERVAL, now=NOW,
                                   enforce_age_cutoff=True))
    assert ob.get(stale).state == "EXPIRED"
    assert ob.get(fresh).state == STATE_SENT
    assert "AAPL" not in snd.sent[0] and "TSLA" in snd.sent[0]
    ob.close()
