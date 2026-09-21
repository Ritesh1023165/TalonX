"""Task 81-R1 §2 -- genuine late BUY-fill recovery.

Reproduces and fixes: a BUY for 2 shares partially fills 1; a protective
SELL closes that 1 (position CLOSED, remaining 0); then the still-
outstanding BUY completes its remaining share. Pre-fix, the order records
2 purchased shares while the position stays CLOSED with zero tracked
holdings -- the newly acquired share is silently discarded.

Required: distinguish that genuine positive cumulative-fill delta from a
duplicate/stale update, account for the new share WITHOUT resurrecting the
sold quantity, restore protective monitoring, preserve prior exits / P&L /
intent linkage / the triggered-exit latch, survive restart on both sides
of the late fill, stay idempotent on repeats, and fail visibly on
contradiction.

Frozen clocks (broker `filled_at` supplied explicitly); per-test tmp_path;
in-memory fake transport; no network.
"""
from __future__ import annotations

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle

FA = "2026-08-28T13:30:00Z"


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    import requests

    def _blocked(*a, **k):
        raise AssertionError("test_task81_r1_late_fill_recovery: real network call attempted")

    monkeypatch.setattr(requests, "request", _blocked, raising=True)
    monkeypatch.setattr(requests.sessions.Session, "request", _blocked, raising=True)


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Transport:
    def __init__(self):
        self.submits = 0
        self.orders: list[dict] = []
        self.positions: list[dict] = []

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "paper-id", "account_number": "PA123456", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            return Response([o for o in self.orders if o["status"] not in ("filled", "rejected", "canceled", "expired")])
        if "/v2/orders/" in url:
            oid = url.rsplit("/", 1)[-1]
            m = next((o for o in self.orders if o["id"] == oid), None)
            return Response(m or {}, 200 if m else 404)
        if url.endswith("/v2/positions"):
            return Response(self.positions)
        return Response({}, 404)

    def post(self, url, **kwargs):
        self.submits += 1
        p = kwargs.get("json", {})
        o = {"id": f"order-{self.submits}", "client_order_id": p.get("client_order_id", f"order-{self.submits}"),
             "status": "new", "filled_qty": "0", **p}
        self.orders.append(o)
        return Response(o)

    def delete(self, url, **kwargs):
        return Response([])


def _cfg(tmp_path, **o):
    v = dict(key_id="k", secret_key="s", paper_trading=True, real_capital=False,
             broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
             universe=("AAPL", "MSFT"), feed_mode="IEX_PAPER_PIV")
    v.update(o)
    return PivConfig(**v)


def _life(cfg, transport):
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(cfg.state_dir / "piv_events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(cfg.state_dir / "lifecycle_state.json", broker, bus,
                          PaperEntrySettings.for_test("AAPL", "MSFT"))
    life.start_session(True, True)
    return life


def _reload(cfg, transport):
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(cfg.state_dir / "piv_events.jsonl", feed_mode=cfg.feed_mode)
    return PaperLifecycle(cfg.state_dir / "lifecycle_state.json", broker, bus,
                          PaperEntrySettings.for_test("AAPL", "MSFT"))


def _run_sequence(life, *, latch=True, sell_price=96.0):
    """BUY 2 -> 1 fills -> protective SELL closes it -> BUY completes."""
    buy = life.order_intent("buy1", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0,
                            stop_price=95.0, target_price=110.0)
    life.apply_broker_update(buy["id"], "partially_filled", 1, 100.0, filled_at=FA)
    if latch:
        life.mark_exit_triggered("AAPL", "STOP_HIT")
    sell = life.order_intent("sell1", "AAPL", "sell", 1, source="STRATEGY", reference_price=95.0)
    life.apply_broker_update(sell["id"], "filled", 1, sell_price, filled_at="2026-08-28T13:40:00Z")
    return buy, sell


# ---------------------------------------------------------------------------
# Pre-fix reproduction (documents the defect precisely)
# ---------------------------------------------------------------------------

def test_reproduce_late_fill_leaves_order_2_position_closed_zero(tmp_path):
    """Pre-fix behaviour lived here as an xfail-style repro; post-fix this
    asserts the CORRECTED outcome so it doubles as the regression."""
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    buy, _sell = _run_sequence(life)
    pos_id = next(iter(life.state.positions))
    assert life.state.positions[pos_id]["status"] == "CLOSED"

    life.apply_broker_update(buy["id"], "filled", 2, 100.5, filled_at="2026-08-28T13:50:00Z")

    order = life.state.orders[buy["id"]]
    pos = life.state.positions[pos_id]
    # The order truthfully records both shares...
    assert order["filled_qty"] == 2 and order["status"] == "filled"
    # ...and the newly acquired share is NOW tracked (pre-fix it was not).
    assert pos["status"] == "OPEN"
    assert pos["remaining_quantity"] == pytest.approx(1)
    assert life._open_position_for("AAPL") is not None


# ---------------------------------------------------------------------------
# Corrected behaviour
# ---------------------------------------------------------------------------

def test_late_fill_completion_reopens_monitoring_without_resurrecting_sold_qty(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    buy, _ = _run_sequence(life)
    pos_id = next(iter(life.state.positions))

    life.apply_broker_update(buy["id"], "filled", 2, 100.5, filled_at="2026-08-28T13:50:00Z")

    pos = life.state.positions[pos_id]
    assert pos["status"] == "OPEN"
    assert pos["quantity"] == pytest.approx(2)          # total ever acquired
    assert pos["remaining_quantity"] == pytest.approx(1)  # only the newly-arrived share
    assert pos["exit_quantity"] == pytest.approx(1)     # the already-sold share NOT resurrected
    assert pos["quantity"] == pytest.approx(pos["exit_quantity"] + pos["remaining_quantity"])
    assert life.state.open_position_by_symbol["AAPL"] == pos_id   # protective monitoring restored
    # A re-open event is emitted so downstream monitoring/rehydration sees it.
    import json
    ev = [json.loads(x) for x in (cfg.state_dir / "piv_events.jsonl").read_text().splitlines() if x.strip()]
    assert any(e["event"] == "POSITION_OPENED" and "REOPEN" in str(e.get("status", "")) for e in ev)


def test_reopen_preserves_exit_accounting_and_latch(tmp_path):
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    buy, _ = _run_sequence(life, latch=True, sell_price=96.0)
    pos_id = next(iter(life.state.positions))
    closed_pnl = life.state.positions[pos_id]["gross_pnl"]
    assert closed_pnl == pytest.approx(1 * (96.0 - 100.0))   # -4 from the exit

    life.apply_broker_update(buy["id"], "filled", 2, 100.5, filled_at="2026-08-28T13:50:00Z")
    pos = life.state.positions[pos_id]
    assert pos["triggered_exit_reason"] == "STOP_HIT"        # latch preserved
    assert pos["gross_pnl"] == pytest.approx(closed_pnl)     # realised exit P&L untouched
    assert pos["stop_price"] == 95.0 and pos["target_price"] == 110.0   # exit plan intact
    intent_id = life.state.orders[buy["id"]]["intent_id"]
    assert pos_id == __import__("talonx_piv.lifecycle", fromlist=["stable_id"]).stable_id("position", intent_id, "AAPL")


def test_duplicate_and_stale_updates_are_idempotent(tmp_path):
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    buy, _ = _run_sequence(life)
    pos_id = next(iter(life.state.positions))
    life.apply_broker_update(buy["id"], "filled", 2, 100.5, filled_at="2026-08-28T13:50:00Z")
    snap = dict(life.state.positions[pos_id])

    # Exact terminal repeat -> no-op.
    life.apply_broker_update(buy["id"], "filled", 2, 100.5, filled_at="2026-08-28T13:50:00Z")
    assert life.state.positions[pos_id] == snap
    # Stale smaller cumulative on a now-terminal order -> no-op (+ diagnostic).
    life.apply_broker_update(buy["id"], "partially_filled", 1, 100.0, filled_at=FA)
    assert life.state.positions[pos_id] == snap


def test_terminal_order_refill_is_noop(tmp_path):
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    buy = life.order_intent("buy1", "AAPL", "buy", 3, source="STRATEGY", reference_price=100.0, stop_price=95.0)
    life.apply_broker_update(buy["id"], "filled", 3, 100.0, filled_at=FA)          # terminal
    sell = life.order_intent("sell1", "AAPL", "sell", 3, source="STRATEGY")
    life.apply_broker_update(sell["id"], "filled", 3, 105.0, filled_at="2026-08-28T14:00:00Z")
    pos_id = next(iter(life.state.positions))
    snap = dict(life.state.positions[pos_id])
    life.apply_broker_update(buy["id"], "filled", 3, 100.0, filled_at=FA)          # duplicate terminal
    assert life.state.positions[pos_id] == snap


def test_contradictory_overfill_fails_visibly(tmp_path):
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    buy, _ = _run_sequence(life)
    pos_id = next(iter(life.state.positions))
    before = dict(life.state.positions[pos_id])

    # Broker reports MORE filled than the intent ever requested (2).
    life.apply_broker_update(buy["id"], "filled", 5, 100.5, filled_at="2026-08-28T13:50:00Z")

    import json
    ev = [json.loads(x) for x in (cfg.state_dir / "piv_events.jsonl").read_text().splitlines() if x.strip()]
    assert any(e["event"] == "BROKER_ERROR" and "EXCEEDS_REQUESTED" in str(e.get("reason", "")) for e in ev)
    # Verified exposure is NOT silently discarded: position unchanged, still CLOSED with its true exit accounting.
    assert life.state.positions[pos_id]["exit_quantity"] == before["exit_quantity"]
    assert life.state.positions[pos_id]["status"] == "CLOSED"


def test_restart_before_and_after_late_fill(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    buy, _ = _run_sequence(life)
    pos_id = next(iter(life.state.positions))

    # Restart BEFORE the late fill: CLOSED position survives.
    life2 = _reload(cfg, transport)
    assert life2.state.positions[pos_id]["status"] == "CLOSED"
    assert life2._open_position_for("AAPL") is None

    # Late fill applied on the reloaded instance.
    life2.apply_broker_update(buy["id"], "filled", 2, 100.5, filled_at="2026-08-28T13:50:00Z")
    assert life2._open_position_for("AAPL") is not None

    # Restart AFTER the late fill: re-opened position survives with correct sizing.
    life3 = _reload(cfg, transport)
    pos = life3._open_position_for("AAPL")
    assert pos is not None
    assert pos["remaining_quantity"] == pytest.approx(1)
    assert pos["exit_quantity"] == pytest.approx(1)
    assert pos["triggered_exit_reason"] == "STOP_HIT"


def test_partial_exit_then_late_fill(tmp_path):
    """Entry 4, 2 fill, partial sell 1 (position OPEN remaining 1), then the
    entry completes to 4 -- remaining becomes 1 + (4-2) = 3, exit_quantity 1."""
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    buy = life.order_intent("b", "AAPL", "buy", 4, source="STRATEGY", reference_price=100.0, stop_price=95.0)
    life.apply_broker_update(buy["id"], "partially_filled", 2, 100.0, filled_at=FA)
    sell = life.order_intent("s", "AAPL", "sell", 1, source="STRATEGY")
    life.apply_broker_update(sell["id"], "filled", 1, 101.0, filled_at="2026-08-28T13:40:00Z")
    pos = life._open_position_for("AAPL")
    assert pos["status"] == "OPEN" and pos["remaining_quantity"] == pytest.approx(1)

    life.apply_broker_update(buy["id"], "filled", 4, 100.2, filled_at="2026-08-28T13:50:00Z")
    pos = life._open_position_for("AAPL")
    assert pos["remaining_quantity"] == pytest.approx(3)   # 1 held + 2 new
    assert pos["exit_quantity"] == pytest.approx(1)
    assert pos["quantity"] == pytest.approx(4)


def test_cancellation_race_then_late_fill(tmp_path):
    """The BUY is 'canceled' locally after its partial while a fill for the
    remaining share is already in flight. A canceled (terminal) order must
    not be re-mutated by the late fill -- it fails visibly, not silently."""
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    buy, _ = _run_sequence(life)
    pos_id = next(iter(life.state.positions))
    life.apply_broker_update(buy["id"], "canceled", 1, 100.0, filled_at="2026-08-28T13:45:00Z")
    snap = dict(life.state.positions[pos_id])
    life.apply_broker_update(buy["id"], "filled", 2, 100.5, filled_at="2026-08-28T13:50:00Z")
    import json
    ev = [json.loads(x) for x in (cfg.state_dir / "piv_events.jsonl").read_text().splitlines() if x.strip()]
    assert any(e["event"] == "BROKER_ERROR" and "STALE_OR_CONTRADICTORY" in str(e.get("reason", "")) for e in ev)
    assert life.state.positions[pos_id] == snap


def test_out_of_order_updates(tmp_path):
    """The completion (cumulative 2) arrives BEFORE a straggling re-report
    of the earlier partial (cumulative 1). The straggler must not rewind."""
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    buy, _ = _run_sequence(life)
    pos_id = next(iter(life.state.positions))
    life.apply_broker_update(buy["id"], "filled", 2, 100.5, filled_at="2026-08-28T13:50:00Z")
    life.apply_broker_update(buy["id"], "partially_filled", 1, 100.0, filled_at=FA)  # straggler
    pos = life.state.positions[pos_id]
    assert pos["remaining_quantity"] == pytest.approx(1)
    assert pos["exit_quantity"] == pytest.approx(1)
    assert life.state.orders[buy["id"]]["filled_qty"] == 2
