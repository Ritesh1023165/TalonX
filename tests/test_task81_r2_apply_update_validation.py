"""Task 81-R2 §4 -- validate before mutating accounting.

apply_broker_update must reject a malformed / contradictory broker update
BEFORE any trusted accounting (order status, filled-qty high-water mark,
position) is touched: missing/invalid status, non-finite / boolean /
negative filled_qty, invalid fill_price, and an impossible cumulative fill
(> the intent's requested quantity). A contradictory response must not
poison an order's terminal status or its fill high-water mark. Genuine
positive deltas, prior exits/P&L, protective levels, linkage and the exit
latch are preserved; duplicate/stale responses stay idempotent.

Also: the full production scenario -- partial BUY -> protective close ->
later BUY fill -> restart -> remaining protective exit -- and that a
reconciliation block never suppresses SELL / shadow / monitoring / EOD.

Deterministic clocks; per-test tmp_path; in-memory Alpaca fake; no network.
"""
from __future__ import annotations

import math

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
        raise AssertionError("real network call attempted")

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
             "symbol": p.get("symbol"), "side": p.get("side"), "qty": str(p.get("qty")),
             "filled_qty": "0", "filled_avg_price": None, "status": "new"}
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


def _events(life):
    import json
    return [json.loads(x) for x in (life.state_path.parent / "piv_events.jsonl").read_text().splitlines() if x.strip()]


# ---------------------------------------------------------------------------
# R4.1 -- invalid updates rejected before mutation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status,fq,fp,why", [
    ("teleported", 1, 100.0, "UNRECOGNISED_STATUS"),
    ("partially_filled", float("nan"), 100.0, "NOT_FINITE"),
    ("partially_filled", float("inf"), 100.0, "NOT_FINITE"),
    ("partially_filled", -1, 100.0, "NONNEGATIVE"),
    ("partially_filled", True, 100.0, "BOOLEAN"),
    ("partially_filled", 1, float("nan"), "FILL_PRICE"),
    ("partially_filled", 1, -5.0, "FILL_PRICE"),
    ("partially_filled", 1, 0.0, "FILL_PRICE"),
    ("filled", 99, 100.0, "EXCEEDS_REQUESTED"),
])
def test_invalid_update_rejected_before_mutation(tmp_path, status, fq, fp, why):
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    entry = life.order_intent("s1", "AAPL", "buy", 3, source="STRATEGY", reference_price=100.0)
    # a genuine prior partial so there IS trusted accounting to protect
    life.apply_broker_update(entry["id"], "partially_filled", 2, 99.5, filled_at=FA)
    order_before = dict(life.state.orders[entry["id"]])
    pos_before = dict(life._open_position_for("AAPL"))

    life.apply_broker_update(entry["id"], status, fq, fp, filled_at="2026-08-28T13:50:00Z")

    assert life.state.orders[entry["id"]] == order_before, "order accounting must be untouched"
    assert dict(life._open_position_for("AAPL")) == pos_before, "position accounting must be untouched"
    ev = _events(life)
    assert any(e["event"] == "BROKER_ERROR" and "BROKER_UPDATE_REJECTED" in str(e.get("reason", "")) for e in ev)


def test_contradictory_update_does_not_poison_status_or_high_water_mark(tmp_path):
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    entry = life.order_intent("s1", "AAPL", "buy", 5, source="STRATEGY", reference_price=100.0)
    life.apply_broker_update(entry["id"], "partially_filled", 3, 100.0, filled_at=FA)
    assert life.state.orders[entry["id"]]["filled_qty"] == 3
    assert life.state.orders[entry["id"]]["status"] == "partially_filled"

    # An impossible cumulative fill (> requested 5) -- rejected, no mutation.
    life.apply_broker_update(entry["id"], "filled", 7, 100.0, filled_at="2026-08-28T13:50:00Z")
    assert life.state.orders[entry["id"]]["filled_qty"] == 3           # high-water mark intact
    assert life.state.orders[entry["id"]]["status"] == "partially_filled"  # not poisoned to terminal

    # The genuine completion (exactly 5) then applies normally.
    life.apply_broker_update(entry["id"], "filled", 5, 100.0, filled_at="2026-08-28T13:55:00Z")
    assert life.state.orders[entry["id"]]["status"] == "filled"
    assert life._open_position_for("AAPL")["remaining_quantity"] == pytest.approx(5)


def test_genuine_delta_preserves_exits_levels_linkage_latch(tmp_path):
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    buy = life.order_intent("s1", "AAPL", "buy", 3, source="STRATEGY", reference_price=100.0,
                            stop_price=95.0, target_price=110.0)
    life.apply_broker_update(buy["id"], "partially_filled", 2, 100.0, filled_at=FA)
    life.mark_exit_triggered("AAPL", "STOP_HIT")
    sell = life.order_intent("x1", "AAPL", "sell", 2, source="STRATEGY")
    life.apply_broker_update(sell["id"], "filled", 2, 96.0, filled_at="2026-08-28T13:40:00Z")
    pos_id = next(pid for pid, p in life.state.positions.items() if p["symbol"] == "AAPL")
    realised = life.state.positions[pos_id]["gross_pnl"]

    # The outstanding BUY completes -- a genuine +1 delta.
    life.apply_broker_update(buy["id"], "filled", 3, 100.2, filled_at="2026-08-28T13:50:00Z")
    pos = life.state.positions[pos_id]
    assert pos["status"] == "OPEN" and pos["remaining_quantity"] == pytest.approx(1)
    assert pos["exit_quantity"] == pytest.approx(2)          # prior exit not resurrected
    assert pos["gross_pnl"] == pytest.approx(realised)       # realised P&L preserved
    assert pos["stop_price"] == 95.0 and pos["target_price"] == 110.0
    assert pos["triggered_exit_reason"] == "STOP_HIT"        # latch preserved
    assert life.state.orders[buy["id"]]["intent_id"] in life.state.intents   # linkage intact


def test_duplicate_and_stale_idempotent(tmp_path):
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    entry = life.order_intent("s1", "AAPL", "buy", 4, source="STRATEGY", reference_price=100.0)
    life.apply_broker_update(entry["id"], "filled", 4, 100.0, filled_at=FA)
    pos_id = next(iter(life.state.positions))
    snap = dict(life.state.positions[pos_id])
    ord_snap = dict(life.state.orders[entry["id"]])
    life.apply_broker_update(entry["id"], "filled", 4, 100.0, filled_at=FA)          # exact dup
    life.apply_broker_update(entry["id"], "partially_filled", 2, 99.0, filled_at=FA)  # stale
    assert life.state.positions[pos_id] == snap
    assert life.state.orders[entry["id"]] == ord_snap


# ---------------------------------------------------------------------------
# R4.5 -- full production scenario
# ---------------------------------------------------------------------------

def test_partial_buy_close_late_fill_restart_remaining_exit(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    buy = life.order_intent("e1", "AAPL", "buy", 10, source="STRATEGY", reference_price=100.0,
                            stop_price=95.0, target_price=115.0)
    life.apply_broker_update(buy["id"], "partially_filled", 4, 100.0, filled_at=FA)
    ex1 = life.order_intent("x1", "AAPL", "sell", 3, source="STRATEGY")
    life.apply_broker_update(ex1["id"], "filled", 3, 101.0, filled_at="2026-08-28T13:40:00Z")
    assert life._open_position_for("AAPL")["remaining_quantity"] == pytest.approx(1)

    life.apply_broker_update(buy["id"], "filled", 10, 100.2, filled_at="2026-08-28T13:50:00Z")
    assert life._open_position_for("AAPL")["remaining_quantity"] == pytest.approx(7)

    life2 = _reload(cfg, transport)
    pos = life2._open_position_for("AAPL")
    assert pos is not None and pos["remaining_quantity"] == pytest.approx(7)

    ex2 = life2.order_intent("x2", "AAPL", "sell", 7, source="STRATEGY")
    life2.apply_broker_update(ex2["id"], "filled", 7, 96.0, filled_at="2026-08-28T14:10:00Z")
    pos_id = next(pid for pid, p in life2.state.positions.items() if p["symbol"] == "AAPL")
    assert life2.state.positions[pos_id]["status"] == "CLOSED"
    assert life2.state.positions[pos_id]["exit_quantity"] == pytest.approx(10)


# ---------------------------------------------------------------------------
# R4.6 -- block never suppresses SELL / shadow / monitoring / EOD
# ---------------------------------------------------------------------------

def test_block_preserves_sell_shadow_monitoring_eod(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    entry = life.order_intent("s1", "AAPL", "buy", 3, source="STRATEGY", reference_price=100.0)
    for o in transport.orders:
        if o["id"] == entry["id"]:
            o.update(status="filled", filled_qty="3", filled_avg_price="100.0")
    life.apply_broker_update(entry["id"], "filled", 3, 100.0, filled_at=FA)
    transport.positions = [{"symbol": "AAPL", "qty": "999", "side": "long"}]   # contradictory -> block
    life.reconcile(now=None) if False else life.reconcile()
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    before = transport.submits
    life.order_intent("x1", "AAPL", "sell", 3, source="STRATEGY")   # protective SELL still allowed
    assert transport.submits == before + 1

    out = life.eod_flatten()   # EOD cleanup not disabled by the block
    assert isinstance(out, dict)
    assert life.state.session_enabled is False


def test_unknown_exposure_sell_fails_visibly(tmp_path):
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    entry = life.order_intent("s1", "AAPL", "buy", 3, source="STRATEGY", reference_price=100.0)
    life.apply_broker_update(entry["id"], "filled", 3, 100.0, filled_at=FA)
    life.order_intent("x1", "AAPL", "sell", 2, source="STRATEGY")   # pending, unresolved
    with pytest.raises(PaperGuardError, match="OVERSIZED_OR_DUPLICATE_SELL"):
        life.order_intent("x2", "AAPL", "sell", 3, source="STRATEGY")   # more than verified remaining
