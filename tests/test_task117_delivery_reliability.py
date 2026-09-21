"""
Task 117 overnight closure -- delivery reliability:
1A invalid modes fail closed (before expiry / DB mutation / network)
1B interrupted sends -> durable IN_FLIGHT claim -> restart / competing drainer
   recovers to AMBIGUOUS, never blind-retried
1C accurate state incl. transport message id; disabled holds; simulate no SENT;
   permanent vs transient distinguishable
1D decisions use the actual send time
1E unexpected delivery errors are visible and do not silently pass as healthy
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from talonx_ingest.intelligence.delivery.outbox import (
    STATE_AMBIGUOUS, STATE_IN_FLIGHT, STATE_PENDING, STATE_SENT, DeliveryOutbox,
)
from talonx_ingest.intelligence.delivery.pipeline import (
    InvalidDeliveryMode, SenderResult, _SendCancelled, enqueue_card, process_pending,
)
from _delivery_helpers import make_card

UTC = timezone.utc
NOW = datetime(2026, 9, 11, 13, 0, 0, tzinfo=UTC)


def _enq(ob, *, symbol="ORCL", accession="0001193125-26-000001", enqueued_at=NOW):
    c, _ = make_card(symbol=symbol, accession=accession, on_watchlist=True, now=enqueued_at)
    return enqueue_card(c, outbox=ob, now=enqueued_at).row.delivery_id


class _Sender:
    def __init__(self, *, configured=True, result=None, raises=None, record_time=False):
        self.configured = configured
        self._result = result or SenderResult(ok=True, message_id=4242)
        self._raises = raises
        self.calls = []
        self.record_time = record_time

    async def send(self, row):
        self.calls.append((row.delivery_id, datetime.now(UTC)))
        if self._raises is not None:
            raise self._raises
        return self._result


# --------------------------------------------------------------------------- 1A
def test_invalid_mode_fails_closed_before_any_mutation(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    did = _enq(ob, enqueued_at=NOW - timedelta(days=30))       # would expire if reached
    snd = _Sender()
    with pytest.raises(InvalidDeliveryMode):
        asyncio.run(process_pending(ob, snd, mode="ENABLED ", enforce_age_cutoff=True))
    with pytest.raises(InvalidDeliveryMode):
        asyncio.run(process_pending(ob, snd, mode="on"))
    assert ob.get(did).state == STATE_PENDING                  # not expired, not sent
    assert snd.calls == []
    ob.close()


# --------------------------------------------------------------------------- 1B
def test_claim_is_persisted_before_the_network(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    did = _enq(ob)
    seen = {}

    class _Peek:
        configured = True
        async def send(self, row):
            # at this point the row MUST already be IN_FLIGHT (committed) --
            # observed through the SAME connection is fine; the point is the
            # state transition + commit happened before send() ran.
            cur = ob.get(row.delivery_id)
            seen["state"] = cur.state
            seen["attempt_id"] = cur.attempt_id
            return SenderResult(ok=True, message_id=7)

    asyncio.run(process_pending(ob, _Peek(), mode="enabled", now=NOW))
    assert seen["state"] == STATE_IN_FLIGHT and seen["attempt_id"]
    # and the IN_FLIGHT log line precedes the SENT log line
    kinds = [l["kind"] for l in ob.logs(did)]
    assert kinds.index("IN_FLIGHT") < kinds.index("SENT")
    assert ob.get(did).state == STATE_SENT
    assert ob.get(did).transport_message_id == "7"
    ob.close()


def test_competing_drainer_cannot_send_a_claimed_row(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    did = _enq(ob)
    ob.claim_for_send(did, "other-drainer", now=NOW)           # someone else holds it
    snd = _Sender()
    r = asyncio.run(process_pending(ob, snd, mode="enabled", now=NOW,
                                    stale_in_flight_seconds=9999))
    assert snd.calls == []                                     # we did not send it
    assert r.attempted == 0
    assert ob.get(did).state == STATE_IN_FLIGHT
    ob.close()


def test_restart_recovers_a_stale_in_flight_row_to_ambiguous(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    did = _enq(ob)
    # simulate a drainer that died mid-send 5 minutes ago
    ob.claim_for_send(did, "dead-drainer", now=NOW - timedelta(minutes=5))
    snd = _Sender()
    r = asyncio.run(process_pending(ob, snd, mode="enabled", now=NOW,
                                    stale_in_flight_seconds=90))
    assert ob.get(did).state == STATE_AMBIGUOUS
    assert did in r.ambiguous_ids
    assert snd.calls == []                                     # NOT blind re-sent
    # a second cycle also does not touch it
    r2 = asyncio.run(process_pending(ob, snd, mode="enabled", now=NOW + timedelta(minutes=1)))
    assert ob.get(did).state == STATE_AMBIGUOUS and r2.attempted == 0
    ob.close()


def test_cancellation_mid_send_marks_ambiguous_and_propagates(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    did = _enq(ob)
    snd = _Sender(raises=_SendCancelled())
    with pytest.raises(_SendCancelled):
        asyncio.run(process_pending(ob, snd, mode="enabled", now=NOW))
    assert ob.get(did).state == STATE_AMBIGUOUS
    ob.close()


def test_lower_layer_does_not_blind_retry_an_ambiguous_timeout():
    """TelegramClient.send(retry_ambiguous=False) raises immediately on a
    post-request timeout instead of retrying."""
    from talonx_dispatch.telegram_client import TelegramClient, TelegramAmbiguousError
    from telegram.error import TimedOut

    calls = {"n": 0}

    class _Bot:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def send_message(self, **k):
            calls["n"] += 1
            raise TimedOut("read timed out")

    import talonx_dispatch.telegram_client as tc
    orig_bot = tc.Bot
    orig_isconf = tc.TelegramClient.is_configured
    tc.Bot = _Bot
    tc.TelegramClient.is_configured = property(lambda self: True)
    try:
        cli = TelegramClient()
        object.__setattr__(cli.config, "telegram_bot_token", "x")
        object.__setattr__(cli.config, "telegram_chat_id", "y")
        with pytest.raises(TelegramAmbiguousError):
            asyncio.run(cli.send("hi", retry_ambiguous=False))
        assert calls["n"] == 1                                 # NOT retried
    finally:
        tc.Bot = orig_bot
        tc.TelegramClient.is_configured = orig_isconf


# --------------------------------------------------------------------------- 1C
def test_sent_records_message_id_disabled_holds_simulate_no_sent(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    did = _enq(ob)
    # disabled -> held, PENDING
    r = asyncio.run(process_pending(ob, _Sender(), mode="disabled", now=NOW))
    assert r.held == 1 and ob.get(did).state == STATE_PENDING
    # simulate -> no SENT, outbox untouched
    r = asyncio.run(process_pending(ob, _Sender(), mode="simulate", now=NOW))
    assert r.simulated == 1 and ob.get(did).state == STATE_PENDING
    # enabled -> SENT + message id
    r = asyncio.run(process_pending(ob, _Sender(result=SenderResult(ok=True, message_id=999)),
                                    mode="enabled", now=NOW))
    assert r.delivered == 1 and ob.get(did).state == STATE_SENT
    assert ob.get(did).transport_message_id == "999"
    assert r.message_ids[did] == "999"
    ob.close()


def test_permanent_vs_transient_stay_distinguishable(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    p = _enq(ob, symbol="AAPL", accession="0000320193-26-000001")
    t = _enq(ob, symbol="MSFT", accession="0000789019-26-000002")
    assert p != t

    class _PerRow:
        configured = True
        async def send(self, row):
            if row.delivery_id == p:
                return SenderResult(ok=False, permanent=True, error="InvalidToken")
            return SenderResult(ok=False, error="transient blip")

    asyncio.run(process_pending(ob, _PerRow(), mode="enabled", now=NOW))
    assert ob.get(p).state == "FAILED"
    tr = ob.get(t)
    assert tr.state == STATE_PENDING and tr.attempts == 1 and tr.next_retry_at_utc is not None
    ob.close()


# --------------------------------------------------------------------------- 1D
def test_decision_uses_the_actual_send_time(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    did = _enq(ob)
    snd = _Sender()
    asyncio.run(process_pending(ob, snd, mode="enabled"))       # no `now` -> real now
    sent_at = ob.get(did).sent_at_utc
    assert sent_at is not None
    assert abs((datetime.now(UTC) - sent_at).total_seconds()) < 30
    ob.close()


# --------------------------------------------------------------------------- 1E
def test_unexpected_sender_error_is_visible_not_swallowed(ledger_path):
    ob = DeliveryOutbox(ledger_path)
    did = _enq(ob)
    snd = _Sender(raises=RuntimeError("boom"))
    r = asyncio.run(process_pending(ob, snd, mode="enabled", now=NOW))
    assert r.errors and "boom" in r.errors[0]
    assert ob.get(did).state == STATE_AMBIGUOUS               # not SENT, not blind-retried
    assert r.ambiguous >= 1
    ob.close()
