"""Task 87B FC_01 -- durable decision-bearing alert delivery.

Proves: persist-before-deliver, no loss on Redis outage, automatic retry
after recovery, restart-safe pending work, end-to-end idempotency (no
duplicate user-facing alert), ambiguous-ack safety, and that transport
durability does NOT change alert policy (a muted `hold_quality` stays
muted). TEST_FIXTURE_ONLY -- no real sockets.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_core.alert_outbox import (
    KIND_LONG_TERM,
    AlertOutbox,
    make_outbox_id,
)
from talonx_core.config import CoreConfig
from talonx_core.consumer import DecisionEngine
from talonx_core.state import TickerCorrelator
from talonx_core.store import TickerStateStore


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _signal_payload(direction: str = "bullish") -> dict:
    return {
        "ticker": "AAPL", "signal_type": "rsi_oversold_volume_surge", "direction": direction,
        "message": "RSI oversold with volume surge", "price": 200.0,
        "bar_timestamp": "2026-08-07T12:00:00Z",
    }


def _report_payload(verdict: str = "bullish", confidence: float = 0.9) -> dict:
    return {
        "ticker": "AAPL", "triggering_signal": _signal_payload(), "verdict": verdict,
        "confidence": confidence, "summary": "Fundamentals support the move.",
        "key_findings": [], "risk_factors": [], "citations": [], "model_used": "gemini-flash-latest",
        "generated_at": "2026-08-07T12:00:30Z", "published_at": "2026-08-07T12:00:30Z",
    }


def _message(channel: str, payload: dict) -> dict:
    return {"channel": channel.encode(), "data": json.dumps(payload)}


class FlakyRedis:
    """Async publish that can be toggled between success and hard failure."""

    def __init__(self) -> None:
        self.up = True
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel, payload):
        if not self.up:
            raise ConnectionError("Redis unavailable (simulated)")
        self.published.append((channel, payload))
        return 1

    async def incrby(self, *a, **k):
        return 1

    async def expire(self, *a, **k):
        return True


async def _drive_to_alert(engine: DecisionEngine) -> None:
    await engine._handle_message(_message(engine.config.signals_channel, _signal_payload("bullish")))
    await engine._handle_message(_message(engine.config.reports_channel, _report_payload("bullish", 0.9)))


# --------------------------------------------------------------------------
# AlertOutbox unit behaviour
# --------------------------------------------------------------------------
def test_outbox_id_is_stable_and_deterministic():
    a = make_outbox_id(ticker="AAPL", trading_date="2026-08-31", kind="intraday",
                       action="confirmed_bullish", correlated_at="2026-08-31T14:00:00+00:00")
    b = make_outbox_id(ticker="AAPL", trading_date="2026-08-31", kind="intraday",
                       action="confirmed_bullish", correlated_at="2026-08-31T14:00:00+00:00")
    c = make_outbox_id(ticker="AAPL", trading_date="2026-08-31", kind="intraday",
                       action="confirmed_bullish", correlated_at="2026-08-31T15:00:00+00:00")
    assert a == b and a != c and len(a) == 32


@pytest.mark.asyncio
async def test_enqueue_persists_pending_before_any_publish(tmp_path):
    path = tmp_path / "outbox.json"
    ob = AlertOutbox(path, publish=AsyncMock(return_value=True))
    ob.enqueue(outbox_id="x1", channel="c", payload="p", kind="intraday", ticker="AAPL", action="a")
    # File on disk shows PENDING *before* flush was ever called.
    on_disk = json.loads(path.read_text())
    assert on_disk["x1"]["status"] == "PENDING"
    assert ob.pending_depth() == 1


@pytest.mark.asyncio
async def test_redis_unavailable_keeps_alert_pending_no_loss(tmp_path):
    async def always_fail(_c, _p):
        return False

    ob = AlertOutbox(tmp_path / "outbox.json", publish=always_fail, backoff_base_seconds=0.0, backoff_max_seconds=0.0)
    ob.enqueue(outbox_id="x1", channel="c", payload="p", kind="intraday", ticker="AAPL", action="a")
    out = await ob.flush()
    assert out["attempted"] == 1 and out["delivered"] == 0
    assert ob.records["x1"]["status"] == "RETRY"
    assert ob.pending_depth() == 1  # still owed -- nothing lost


@pytest.mark.asyncio
async def test_retry_after_recovery_delivers_once(tmp_path):
    flaky = FlakyRedis()
    flaky.up = False

    async def pub(c, p):
        try:
            await flaky.publish(c, p)
            return True
        except ConnectionError:
            return False

    ob = AlertOutbox(tmp_path / "outbox.json", publish=pub, backoff_base_seconds=0.0, backoff_max_seconds=0.0)
    ob.enqueue(outbox_id="x1", channel="c", payload="p", kind="intraday", ticker="AAPL", action="a")
    await ob.flush()
    assert ob.records["x1"]["status"] == "RETRY"
    flaky.up = True
    out = await ob.flush()
    assert out["delivered"] == 1
    assert ob.records["x1"]["status"] == "SENT"
    assert len(flaky.published) == 1  # delivered exactly once
    # A further flush is a clean no-op -- never re-sends a SENT record.
    await ob.flush()
    assert len(flaky.published) == 1


@pytest.mark.asyncio
async def test_pending_work_survives_process_restart(tmp_path):
    path = tmp_path / "outbox.json"
    async def fail(_c, _p):
        return False
    ob1 = AlertOutbox(path, publish=fail, backoff_base_seconds=0.0, backoff_max_seconds=0.0)
    ob1.enqueue(outbox_id="x1", channel="c", payload="p", kind="intraday", ticker="AAPL", action="a")
    await ob1.flush()
    assert ob1.records["x1"]["status"] == "RETRY"

    # "restart": brand-new instance, same file, Redis now healthy.
    delivered: list = []
    async def ok(c, p):
        delivered.append((c, p))
        return True
    ob2 = AlertOutbox(path, publish=ok, backoff_base_seconds=0.0, backoff_max_seconds=0.0)
    assert ob2.pending_depth() == 1  # reloaded the pending record
    await ob2.flush()
    assert delivered == [("c", "p")]
    assert ob2.records["x1"]["status"] == "SENT"


@pytest.mark.asyncio
async def test_ambiguous_ack_then_restart_dedups_downstream(tmp_path):
    """Publish may have landed but the local SENT write is lost. On restart
    the still-PENDING record is re-published under the SAME outbox_id -- a
    downstream idempotency check (see the Dispatch test below) collapses it."""
    path = tmp_path / "outbox.json"
    sent_wire: list = []
    async def ok(c, p):
        sent_wire.append((c, p))
        return True
    ob1 = AlertOutbox(path, publish=ok)
    ob1.enqueue(outbox_id="x1", channel="c", payload="p", kind="intraday", ticker="AAPL", action="a")
    await ob1.flush()  # wire got it
    assert len(sent_wire) == 1
    # Simulate the SENT persistence never reaching disk: rewrite the file
    # back to the pre-flush PENDING state.
    ob1.records["x1"]["status"] = "PENDING"
    ob1.records["x1"]["sent_at"] = None
    path.write_text(json.dumps(ob1.records))

    ob2 = AlertOutbox(path, publish=ok)  # restart
    await ob2.flush()
    assert len(sent_wire) == 2  # re-sent on the wire (at-least-once)
    # both wire messages carry the SAME idempotency id -> downstream dedups
    assert sent_wire[0] == sent_wire[1]


@pytest.mark.asyncio
async def test_bounded_retries_then_permanently_failed_but_visible(tmp_path):
    async def fail(_c, _p):
        return False
    ob = AlertOutbox(tmp_path / "outbox.json", publish=fail, backoff_base_seconds=0.0, backoff_max_seconds=0.0)
    ob.records  # noqa
    rec = ob.enqueue(outbox_id="x1", channel="c", payload="p", kind="intraday", ticker="AAPL", action="a")
    rec["max_attempts"] = 3
    for _ in range(5):
        await ob.flush()
    assert ob.records["x1"]["status"] == "FAILED"
    assert ob.stats()["failed_permanently"] == 1
    assert ob.stats()["status_failed"] == 1  # still in the ledger, never silently dropped


# --------------------------------------------------------------------------
# DecisionEngine integration
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_normal_path_enqueues_publishes_and_marks_sent(tmp_path):
    flaky = FlakyRedis()
    engine = DecisionEngine(
        config=CoreConfig(alert_outbox_path=str(tmp_path / "ob.json")),
        store=TickerStateStore(tmp_path / "core.db"),
    )
    engine._client = flaky
    await _drive_to_alert(engine)
    assert len(flaky.published) == 1
    assert engine.alert_outbox.pending_depth() == 0
    ids = list(engine.alert_outbox.records)
    assert engine.alert_outbox.records[ids[0]]["status"] == "SENT"
    # payload carried the outbox_id so Dispatch can dedup
    _, wire_payload = flaky.published[0]
    assert json.loads(wire_payload)["outbox_id"] == ids[0]


@pytest.mark.asyncio
async def test_core_publish_failure_leaves_recoverable_pending_then_delivers(tmp_path):
    flaky = FlakyRedis()
    flaky.up = False
    engine = DecisionEngine(
        config=CoreConfig(
            alert_outbox_path=str(tmp_path / "ob.json"),
            alert_outbox_backoff_base_seconds=0.0, alert_outbox_backoff_max_seconds=0.0,
        ),
        store=TickerStateStore(tmp_path / "core.db"),
    )
    engine._client = flaky
    await _drive_to_alert(engine)
    # Nothing on the wire, but the obligation is durably recorded.
    assert flaky.published == []
    assert engine.alert_outbox.pending_depth() == 1
    # Redis recovers; the message-loop flush re-publishes.
    flaky.up = True
    await engine._flush_alert_outbox()
    assert len(flaky.published) == 1
    assert engine.alert_outbox.pending_depth() == 0


@pytest.mark.asyncio
async def test_core_restart_recovers_pending_alert(tmp_path):
    ob_path = str(tmp_path / "ob.json")
    db_path = tmp_path / "core.db"
    flaky = FlakyRedis()
    flaky.up = False
    engine1 = DecisionEngine(
        config=CoreConfig(alert_outbox_path=ob_path, alert_outbox_backoff_base_seconds=0.0,
                          alert_outbox_backoff_max_seconds=0.0),
        store=TickerStateStore(db_path),
    )
    engine1._client = flaky
    await _drive_to_alert(engine1)
    assert engine1.alert_outbox.pending_depth() == 1

    # New process: fresh engine, same outbox file, Redis healthy.
    flaky2 = FlakyRedis()
    engine2 = DecisionEngine(
        config=CoreConfig(alert_outbox_path=ob_path, alert_outbox_backoff_base_seconds=0.0,
                          alert_outbox_backoff_max_seconds=0.0),
        store=TickerStateStore(tmp_path / "core2.db"),
    )
    engine2._client = flaky2
    assert engine2.alert_outbox.pending_depth() == 1
    await engine2._flush_alert_outbox()
    assert len(flaky2.published) == 1


# --------------------------------------------------------------------------
# End-to-end idempotency at Dispatch
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_processes_duplicate_outbox_id_once(tmp_path):
    from talonx_dispatch.config import DispatchConfig
    from talonx_dispatch.consumer import DispatchAgent
    from talonx_dispatch.store import AuditStore
    from talonx_watchlist.store import TickerWatchlistStore

    store = AuditStore(tmp_path / "audit.db")
    wl = TickerWatchlistStore(tmp_path / "watchlist.db")
    agent = DispatchAgent(config=DispatchConfig(), store=store, telegram_client=AsyncMock(), watchlist_store=wl)
    agent._client = AsyncMock()
    agent._maybe_send_telegram = AsyncMock()

    payload = {
        "ticker": "AAPL", "action": "confirmed_bullish", "severity": "critical",
        "rationale": "r", "quant_direction": "bullish", "research_verdict": "bullish",
        "research_confidence": 0.9,
        "triggering_signal": {"ticker": "AAPL", "signal_type": "x", "direction": "bullish",
                              "message": "m", "price": 1.0, "bar_timestamp": "2026-08-31T14:00:00Z"},
        "research_summary": "s", "key_findings": [], "risk_factors": [], "model_used": "m",
        "signal_received_at": "2026-08-31T14:00:00Z", "report_received_at": "2026-08-31T14:00:00Z",
        "correlated_at": "2026-08-31T14:00:00Z", "published_at": "2026-08-31T14:00:00Z",
        "outbox_id": "dup-1",
    }
    msg = {"channel": agent.config.alerts_channel.encode(), "data": json.dumps(payload)}
    await agent._handle_message(msg)
    await agent._handle_message(msg)  # at-least-once redelivery

    rows = store._conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert rows == 1  # recorded exactly once
    assert agent._maybe_send_telegram.await_count == 1  # pushed exactly once
    store.close()


@pytest.mark.asyncio
async def test_mcd_style_muted_hold_quality_still_durable_but_policy_unchanged(tmp_path):
    """The 2026-08-31 MCD case: a long-term `hold_quality` alert. It must be
    durably delivered (outbox SENT, Dispatch records it) AND remain muted
    from Telegram -- transport durability changes reliability, never policy.
    """
    from talonx_dispatch.config import DispatchConfig
    from talonx_dispatch.consumer import DispatchAgent
    from talonx_dispatch.store import AuditStore
    from talonx_watchlist.store import TickerWatchlistStore

    store = AuditStore(tmp_path / "audit.db")
    wl = TickerWatchlistStore(tmp_path / "watchlist.db")
    agent = DispatchAgent(config=DispatchConfig(), store=store, telegram_client=AsyncMock(), watchlist_store=wl)
    agent._client = AsyncMock()

    lt_payload = {
        "ticker": "MCD", "action": "hold_quality", "severity": "info", "rationale": "r",
        "summary": "s", "quality_score": 9, "moat_rating": "wide", "market_price": 265.0,
        "intrinsic_fair_value": 280.0, "margin_of_safety_pct": 0.057,
        "capital_allocation_assessment": "ok", "key_findings": [], "risk_factors": [],
        "model_used": "gemini", "correlated_at": "2026-08-31T14:00:00Z",
        "published_at": "2026-08-31T14:00:00Z",
        "outbox_id": make_outbox_id(ticker="MCD", trading_date="2026-08-31", kind=KIND_LONG_TERM,
                                    action="hold_quality", correlated_at="2026-08-31T14:00:00+00:00"),
    }
    await agent._handle_long_term_alert(lt_payload)

    lt_rows = store._conn.execute("SELECT COUNT(*) FROM long_term_alerts").fetchone()[0]
    assert lt_rows == 1  # durably recorded by Dispatch
    # hold_quality is an action-muted class -> no Telegram send attempted.
    assert agent.telegram_client.send.await_count == 0
    store.close()
