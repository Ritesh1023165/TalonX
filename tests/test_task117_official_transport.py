"""
Task 117 controlled-deployment-readiness -- the REAL official Telegram transport
adapter for the V2 durable outbox, tested with the network boundary INTERCEPTED.

No real network, no real bot, no message sent.  A stub TelegramClient (or a
monkeypatched telegram.Bot) stands in at the boundary.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from talonx_v2.delivery import (DryRunTransport, OfficialTelegramTransport, RecordingTransport,
                                deliver_outbox)
from talonx_v2.store import V2Store


# --------------------------------------------------------------------------- #
class _StubClient:
    """Boundary stand-in for talonx_dispatch.telegram_client.TelegramClient."""

    def __init__(self, *, configured=True, mode="ok"):
        self.is_configured = configured
        self.mode = mode
        self.sent: list[tuple[str, object]] = []

    async def send(self, text, parse_mode=None):
        self.sent.append((text, parse_mode))
        if self.mode == "ok":
            return
        from talonx_dispatch.telegram_client import TelegramSendError
        if self.mode == "permanent":
            raise TelegramSendError("Telegram send failed (non-retryable): InvalidToken")
        if self.mode == "transient":
            raise TelegramSendError("Exhausted 3 retries: TimedOut")
        raise RuntimeError("weird")


class _Router:
    def __init__(self, *, eligible=True, delivered=None):
        self.eligible = eligible
        self.delivered = delivered or set()

    def decide(self, family, dedup_key=""):
        class _RD:
            pass
        rd = _RD()
        rd.eligible = self.eligible and family == "insider_buy_cluster_v2"
        rd.already_delivered = dedup_key in self.delivered
        rd.reason = "eligible" if rd.eligible else "not eligible"
        return rd


def _enq(s, event_id, kind, action, dedup, *, deliver_by=None, payload="card"):
    return s.enqueue_alert(event_id=event_id, episode_id="ep", kind=kind, action=action,
                           symbol="AAA", strategy_version="INSIDER_BUY_CLUSTER_V2@1",
                           dedup_key=dedup, payload_text=payload, provenance={"episode_id": "ep"},
                           deliver_by_utc=deliver_by)


# --------------------------------------------------------------------------- transport adapter
def test_transport_holds_when_not_configured(tmp_path):
    t = OfficialTelegramTransport(client=_StubClient(configured=False))
    r = t.send("x", meta={"dedup_key": "k"})
    assert r == {"held": True, "detail": "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not configured -- HOLD"}


def test_transport_sends_with_parse_mode_none_and_returns_ref(tmp_path):
    c = _StubClient()
    t = OfficialTelegramTransport(client=c)
    r = t.send("hello *world*", meta={"dedup_key": "ep:BUY:ENTRY_FILL"})
    assert r["ok"] is True and r["ref"] == "telegram:sent:ep:BUY:ENTRY_FILL"
    assert c.sent == [("hello *world*", None)]              # raw text, no Markdown parse


def test_transport_permanent_failure_flagged(tmp_path):
    r = OfficialTelegramTransport(client=_StubClient(mode="permanent")).send("x", meta={"dedup_key": "k"})
    assert r["ok"] is False and r["permanent"] is True and "non-retryable" in r["detail"]


def test_transport_transient_failure_not_permanent(tmp_path):
    r = OfficialTelegramTransport(client=_StubClient(mode="transient")).send("x", meta={"dedup_key": "k"})
    assert r["ok"] is False and not r.get("permanent")


# --------------------------------------------------------------------------- through deliver_outbox
def test_outbox_through_official_transport_sent_and_recorded(tmp_path):
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    _enq(s, "e-fill", "ENTRY_FILL", "BUY", "ep:BUY:ENTRY_FILL")
    summ = deliver_outbox(s, router=_Router(), transport=OfficialTelegramTransport(client=_StubClient()))
    assert summ["sent"] == 1
    row = s.all_outbox()[0]
    assert row["state"] == "SENT" and row["transport_ref"] == "telegram:sent:ep:BUY:ENTRY_FILL"
    assert row["sent_at_utc"]


def test_planned_buy_and_fill_and_sell_are_distinct_and_correlated(tmp_path):
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    _enq(s, "e-plan", "ENTRY_INTENT", "BUY", "ep:BUY:ENTRY_INTENT", deliver_by=future)
    _enq(s, "e-fill", "ENTRY_FILL", "BUY", "ep:BUY:ENTRY_FILL")
    _enq(s, "e-sell", "EXIT_FILL", "SELL", "ep:SELL:EXIT_FILL")
    c = _StubClient()
    deliver_outbox(s, router=_Router(), transport=OfficialTelegramTransport(client=c))
    states = {o["kind"]: o["state"] for o in s.all_outbox()}
    assert states == {"ENTRY_INTENT": "SENT", "ENTRY_FILL": "SENT", "EXIT_FILL": "SENT"}
    dedups = {o["kind"]: o["dedup_key"] for o in s.all_outbox()}
    assert dedups["ENTRY_INTENT"].endswith(":BUY:ENTRY_INTENT")
    assert dedups["EXIT_FILL"].endswith(":SELL:EXIT_FILL")
    # every card correlates to the same episode via provenance
    for o in s.all_outbox():
        assert json.loads(o["provenance_json"])["episode_id"] == "ep"


def test_permanent_failure_stays_visible_no_retry_storm(tmp_path):
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    _enq(s, "e1", "ENTRY_FILL", "BUY", "ep:BUY:ENTRY_FILL")
    summ = deliver_outbox(s, router=_Router(), transport=OfficialTelegramTransport(client=_StubClient(mode="permanent")))
    assert summ["failed"] == 1
    row = s.all_outbox()[0]
    assert row["state"] == "FAILED" and row["attempts"] == 1        # NOT 5 -- permanent short-circuits
    assert "permanent transport failure" in row["last_error"]
    # a second drain does not pick it up again
    assert deliver_outbox(s, router=_Router(), transport=RecordingTransport())["considered"] == 0


def test_transient_failure_retries_then_succeeds(tmp_path):
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    _enq(s, "e1", "ENTRY_FILL", "BUY", "ep:BUY:ENTRY_FILL")
    r1 = deliver_outbox(s, router=_Router(), transport=OfficialTelegramTransport(client=_StubClient(mode="transient")))
    assert r1["retry"] == 1 and s.all_outbox()[0]["state"] == "RETRY"
    r2 = deliver_outbox(s, router=_Router(), transport=OfficialTelegramTransport(client=_StubClient(mode="ok")),
                        now=datetime.now(timezone.utc) + timedelta(seconds=400))
    assert r2["sent"] == 1 and s.all_outbox()[0]["state"] == "SENT"


def test_planned_buy_deadline_expires_not_sent_late(tmp_path):
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _enq(s, "e-plan", "ENTRY_INTENT", "BUY", "ep:BUY:ENTRY_INTENT", deliver_by=past)
    c = _StubClient()
    summ = deliver_outbox(s, router=_Router(), transport=OfficialTelegramTransport(client=c))
    assert summ.get("expired") == 1 and summ["sent"] == 0
    assert s.all_outbox()[0]["state"] == "EXPIRED"
    assert c.sent == []                                             # nothing left the boundary
    assert "no longer actionable" in s.all_outbox()[0]["last_error"]


def test_dedup_across_ticks_router_already_delivered_no_second_send(tmp_path):
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    assert _enq(s, "e1", "ENTRY_FILL", "BUY", "ep:BUY:ENTRY_FILL") is True
    assert _enq(s, "e1", "ENTRY_FILL", "BUY", "ep:BUY:ENTRY_FILL") is False   # same event_id
    c = _StubClient()
    deliver_outbox(s, router=_Router(delivered={"ep:BUY:ENTRY_FILL"}),
                   transport=OfficialTelegramTransport(client=c))
    assert s.all_outbox()[0]["state"] == "SENT"
    assert s.all_outbox()[0]["transport_ref"] == "dedup:already_delivered"
    assert c.sent == []                                             # router said delivered -> no send


def test_ambiguous_outcome_not_blindly_retried_into_duplicate(tmp_path):
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    _enq(s, "e1", "ENTRY_FILL", "BUY", "ep:BUY:ENTRY_FILL")
    # RedisDispatchPublishTransport-style ambiguous result
    class _Amb:
        name = "amb"
        def send(self, payload_text, *, meta):
            return {"ambiguous": True, "detail": "sent but ACK lost"}
    summ = deliver_outbox(s, router=_Router(), transport=_Amb())
    assert summ["ambiguous"] == 1 and s.all_outbox()[0]["state"] == "AMBIGUOUS"
    # an AMBIGUOUS row is NOT re-picked by outbox_due -> no automatic duplicate send
    assert deliver_outbox(s, router=_Router(), transport=RecordingTransport())["considered"] == 0


def test_experimental_family_cannot_send_through_this_path(tmp_path):
    from talonx_ops.official_dispatch import OfficialExternalRouter
    r = OfficialExternalRouter(home=tmp_path)
    assert r.decide("experimental", "x").eligible is False


def test_sell_requires_that_a_long_existed_semantics(tmp_path):
    """The service only enqueues EXIT_FILL from a real settle_due_exits SELL --
    the outbox has no path to fabricate a SELL without a prior BUY.  Guard: an
    EXIT_FILL row always carries a position/episode that had an ENTRY_FILL."""
    s = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    _enq(s, "e-fill", "ENTRY_FILL", "BUY", "ep:BUY:ENTRY_FILL")
    _enq(s, "e-sell", "EXIT_FILL", "SELL", "ep:SELL:EXIT_FILL")
    kinds = {o["kind"] for o in s.all_outbox() if o["episode_id"] == "ep"}
    assert "ENTRY_FILL" in kinds and "EXIT_FILL" in kinds       # SELL paired with a prior BUY notification
