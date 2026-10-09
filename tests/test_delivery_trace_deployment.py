"""Delivery tracing wired into the promotion send path (2026-10-09): the real TelegramClient's internal retries are
observed, instrumentation failure never causes an extra send or a retry, routing/content/dedup are unchanged, no
historical trace is fabricated. Synthetic Telegram doubles only -- nothing is sent."""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from talonx_opportunity import delivery_trace as T

UTC = timezone.utc


class FakeBot:
    """Stands in for telegram.Bot inside the REAL TelegramClient.send loop."""
    script: list = []
    sent: list = []

    def __init__(self, token):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send_message(self, chat_id, text, parse_mode, disable_web_page_preview):
        step = FakeBot.script.pop(0)
        if isinstance(step, Exception):
            raise step
        FakeBot.sent.append(text)
        return SimpleNamespace(message_id=step, date=datetime.now(UTC).replace(microsecond=0),
                               chat=SimpleNamespace(id=-1001))


def real_client(monkeypatch, script):
    import talonx_dispatch.telegram_client as TC
    from talonx_dispatch.config import DispatchConfig
    FakeBot.script, FakeBot.sent = list(script), []
    monkeypatch.setattr(TC, "Bot", FakeBot)

    async def no_sleep(s):
        return None
    monkeypatch.setattr(TC.asyncio, "sleep", no_sleep)
    return TC.TelegramClient(config=DispatchConfig(telegram_bot_token="t", telegram_chat_id="c",
                                                   telegram_max_retries=3))


def test_wrapper_observes_the_real_clients_internal_timeout_retry(tmp_path, monkeypatch):
    from telegram.error import TimedOut
    client = real_client(monkeypatch, [TimedOut(), 501])
    store = T.TraceStore(tmp_path / "t.db")
    msg = asyncio.run(T.TracedTransport(client, store).send("alert-1", parse_mode=None))
    assert msg.message_id == 501 and FakeBot.sent == ["alert-1"]
    row = store.con.execute("SELECT outcome, network_retries, rate_limit_retries, trace_state, message_id "
                            "FROM traces").fetchone()
    assert row == ("API_ACCEPTED", 1, 0, "TRACE_OK", 501)          # the hidden retry is SEEN, not assumed absent


def test_rate_limit_and_definite_errors_are_counted_but_not_called_network(tmp_path, monkeypatch):
    from telegram.error import RetryAfter, TelegramError
    # NB: telegram.error.BadRequest subclasses NetworkError, so the real client logs it as a NETWORK retry (and the
    # study treats it as ambiguous) -- the counter reports the client's own classification; a plain TelegramError is
    # the client's "definite" branch.
    client = real_client(monkeypatch, [RetryAfter(1), TelegramError("x"), 7])
    store = T.TraceStore(tmp_path / "t.db")
    asyncio.run(T.TracedTransport(client, store).send("alert-2"))
    assert store.con.execute("SELECT network_retries, rate_limit_retries, definite_error_retries FROM traces"
                             ).fetchone() == (0, 1, 1)


def test_trace_store_failure_after_success_causes_no_extra_send_and_no_retry(tmp_path, monkeypatch):
    client = real_client(monkeypatch, [9])

    class BrokenStore:
        def add(self, row):
            raise sqlite3.OperationalError("disk full")
    msg = asyncio.run(T.TracedTransport(client, BrokenStore()).send("alert-3"))
    assert msg.message_id == 9 and FakeBot.sent == ["alert-3"]        # exactly one send, success returned


def test_failed_send_is_traced_and_reraised_unchanged(tmp_path, monkeypatch):
    from telegram.error import Forbidden
    client = real_client(monkeypatch, [Forbidden("blocked")])
    store = T.TraceStore(tmp_path / "t.db")
    with pytest.raises(Exception):
        asyncio.run(T.TracedTransport(client, store).send("alert-4"))
    assert store.con.execute("SELECT outcome FROM traces").fetchone() == ("SEND_FAILED",)


def _promoter_signal(tmp_path, monkeypatch, client):
    from talonx_opportunity import promotion as P
    from tests.test_opportunity_promotion import Clock, T as tt, _NoData, seed
    from tests.test_promotion_signal_pause import PAUSE, pause
    pause(tmp_path, {**PAUSE, "paused": False, "delivery_mode": "RESEARCH_REVIEW",
                     "delivery_boundary_utc": tt(14).isoformat()})
    import talonx_ops.notify as N
    monkeypatch.setattr(N, "telegram_client_for", lambda dest: client)
    monkeypatch.setattr(N, "resolve_destination_config", lambda dest: SimpleNamespace(enabled=True, reason="t"))
    import talonx_ops.notify.worker as W
    monkeypatch.setattr(W, "resolve_destination_config", lambda dest: SimpleNamespace(enabled=True, reason="t"))
    monkeypatch.setattr(W, "telegram_client_for", lambda dest: client)  # the worker's own default resolution

    class FixedNow(datetime):
        @classmethod
        def now(cls, tz=None):
            return tt(15).astimezone(tz) if tz else tt(15)
    monkeypatch.setattr(W, "datetime", FixedNow)                     # the worker's deadline clock = fixture time
    seed(tmp_path, [])
    pr = P.Promoter(root=tmp_path, clock=Clock(tt(15)), data=_NoData(), mode=P.PAPER_SIGNAL)
    seed(tmp_path, [dict(sym="AAA", at=tt(15))])
    return P, pr


def test_promotion_send_path_uses_the_traced_wrapper_with_unchanged_content(tmp_path, monkeypatch):
    sent = []

    class Client:
        is_configured = True

        async def send(self, text, parse_mode=None, **kw):
            sent.append((text, parse_mode))
            return SimpleNamespace(message_id=11, date=datetime.now(UTC).replace(microsecond=0),
                                   chat=SimpleNamespace(id=-77))
    P, pr = _promoter_signal(tmp_path, monkeypatch, Client())
    pr.tick()
    ob = sqlite3.connect(P.signal_outbox_path(tmp_path))
    payload, state = ob.execute("SELECT payload_text, state FROM ops_notification_outbox").fetchone()
    assert state == "SENT" and sent == [(payload, None)]             # same text, same parse mode, one send
    tr = sqlite3.connect(P.trace_path(tmp_path))
    (h, mid, ref) = tr.execute("SELECT payload_sha256, message_id, chat_ref FROM traces").fetchone()
    assert h == T.payload_hash(payload) and mid == 11 and ref != "-77" and len(ref) == 12
    look = T.make_trace_lookup(P.signal_outbox_path(tmp_path), P.trace_path(tmp_path))
    ev = ob.execute("SELECT event_id FROM ops_notification_outbox").fetchone()[0]
    assert look(ev)["trace_state"] == "TRACE_OK" and look(ev)["hidden_retries"] == 0


def test_tracing_setup_failure_falls_back_to_the_unchanged_default_path(tmp_path, monkeypatch):
    sent = []

    class Client:
        is_configured = True

        async def send(self, text, parse_mode=None, **kw):
            sent.append(text)
            return None
    P, pr = _promoter_signal(tmp_path, monkeypatch, Client())
    import talonx_opportunity.delivery_trace as D
    monkeypatch.setattr(D, "TraceStore", lambda path: (_ for _ in ()).throw(OSError("no disk")))
    pr.tick()
    assert len(sent) == 1 and not P.trace_path(tmp_path).exists()


def test_historical_sends_have_no_trace_and_lookup_never_fabricates(tmp_path):
    ob = sqlite3.connect(tmp_path / "o.db")
    ob.execute("CREATE TABLE ops_notification_outbox (event_id TEXT, payload_text TEXT)")
    ob.execute("INSERT INTO ops_notification_outbox VALUES ('OLD', 'sent before tracing existed')")
    ob.commit()
    T.TraceStore(tmp_path / "t.db")
    assert T.make_trace_lookup(tmp_path / "o.db", tmp_path / "t.db")("OLD") is None   # TRACE_MISSING
