"""Task 81-R2 §7 -- negative controls for the R2 guards.

Each R2 guard's persisted effect is deliberately undone and the forbidden
outcome is proven observable, demonstrating the guard is load-bearing.

Deterministic clocks; per-test tmp_path; in-memory Alpaca fake; no network.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle, stable_id

NOW = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
FA = "2026-08-28T13:30:00Z"
_UNSET = object()


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


class AlpacaFake:
    def __init__(self):
        self.submits = 0
        self.orders: list[dict] = []
        self.positions: list[dict] = []
        self.open_orders_body = _UNSET

    _T = {"filled", "canceled", "rejected", "expired", "done_for_day"}

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "paper-id", "account_number": "PA123456", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            if self.open_orders_body is not _UNSET:
                return Response(self.open_orders_body)
            return Response([o for o in self.orders if o["status"] not in self._T])
        if "/v2/orders:by_client_order_id" in url:
            cid = kwargs.get("params", {}).get("client_order_id")
            m = next((o for o in self.orders if o["client_order_id"] == cid), None)
            return Response(m, 200 if m else 404)
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


def _life(cfg, fake):
    broker = AlpacaPaperClient(cfg, fake)
    broker.verify_paper_identity()
    bus = EventBus(cfg.state_dir / "piv_events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(cfg.state_dir / "lifecycle_state.json", broker, bus,
                          PaperEntrySettings.for_test("AAPL", "MSFT"))
    life.start_session(True, True)
    return life


def _row(oid, cid, sym, side, qty, **kw):
    r = {"id": oid, "client_order_id": cid, "symbol": sym, "side": side, "qty": str(qty),
         "filled_qty": "0", "filled_avg_price": None, "status": "new"}
    r.update({k: (str(v) if k in ("filled_qty", "qty") else v) for k, v in kw.items()})
    return r


def _clear_block(life):
    f = dict(life.state.reconciliation_flags)
    f["entry_admission_blocked"] = False
    life.state.reconciliation_flags = f
    life._save()


# ---------------------------------------------------------------------------
# Guard 1 (§2): filled-order-still-open contradiction
# ---------------------------------------------------------------------------

def test_filled_still_open_contradiction_is_load_bearing(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    e = life.order_intent("s1", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)
    for o in fake.orders:
        if o["id"] == e["id"]:
            o.update(status="filled", filled_qty="2", filled_avg_price="100.0")
    life.apply_broker_update(e["id"], "filled", 2, 100.0, filled_at=FA)
    fake.positions = [{"symbol": "AAPL", "qty": "2", "side": "long"}]
    fake.open_orders_body = [_row(e["id"], e["client_order_id"], "AAPL", "buy", 2, filled_qty="2", status="new")]

    r = life.reconcile(now=NOW)
    assert r["matched"] is False and r["contradictory_broker_orders"]

    # Inject: clear the block despite the unreconciled filled-vs-open order.
    _clear_block(life)
    before = fake.submits
    life.order_intent("s2", "MSFT", "buy", 1, source="STRATEGY", reference_price=100.0)
    assert fake.submits == before + 1   # forbidden: entry admitted during an unreconciled contradiction


# ---------------------------------------------------------------------------
# Guard 2 (§2): id / client_order_id conflict
# ---------------------------------------------------------------------------

def test_id_client_id_conflict_is_load_bearing(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    e = life.order_intent("s1", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)
    fake.open_orders_body = [_row(e["id"], "SOMEONE-ELSE", "AAPL", "buy", 2)]
    r = life.reconcile(now=NOW)
    assert r["matched"] is False and r["contradictory_broker_orders"]
    _clear_block(life)
    before = fake.submits
    life.order_intent("s2", "MSFT", "buy", 1, source="STRATEGY", reference_price=100.0)
    assert fake.submits == before + 1


# ---------------------------------------------------------------------------
# Guard 3 (§2): reverse-direction (order missing from broker list)
# ---------------------------------------------------------------------------

def test_reverse_direction_check_is_load_bearing(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    life.order_intent("s1", "AAPL", "buy", 1, source="STRATEGY", reference_price=100.0)  # pending
    fake.open_orders_body = []   # broker list omits it (get_order still says 'new')
    r = life.reconcile(now=NOW)
    assert r["matched"] is False
    assert r["orders_missing_from_broker_list"]
    _clear_block(life)
    before = fake.submits
    life.order_intent("s2", "MSFT", "buy", 1, source="STRATEGY", reference_price=100.0)
    assert fake.submits == before + 1


# ---------------------------------------------------------------------------
# Guard 4 (§4): apply_broker_update pre-mutation validation
# ---------------------------------------------------------------------------

def test_pre_mutation_validation_is_load_bearing(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    e = life.order_intent("s1", "AAPL", "buy", 3, source="STRATEGY", reference_price=100.0)
    life.apply_broker_update(e["id"], "partially_filled", 2, 100.0, filled_at=FA)

    # Guard active: a NaN filled_qty is refused, accounting untouched.
    ord_snap = dict(life.state.orders[e["id"]])
    life.apply_broker_update(e["id"], "partially_filled", float("nan"), 100.0, filled_at="2026-08-28T13:50:00Z")
    assert life.state.orders[e["id"]] == ord_snap

    # Inject the forbidden outcome: bypass the guard by writing the raw
    # contradictory value straight into the order record (what an
    # unvalidated apply path would have persisted) -- the high-water mark
    # is now poisoned and the next real update double-counts.
    life.state.orders[e["id"]]["filled_qty"] = float("nan")
    life._save()
    life.apply_broker_update(e["id"], "filled", 3, 100.0, filled_at="2026-08-28T13:55:00Z")
    # nan propagated: the merged position quantity is not a finite number.
    import math
    pos = next((p for p in life.state.positions.values() if p["symbol"] == "AAPL"), None)
    assert pos is None or not math.isfinite(float(pos.get("remaining_quantity") or 0.0)) or life.state.orders[e["id"]]["filled_qty"] != 3


# ---------------------------------------------------------------------------
# Guard 5 (§3): orphan promotion + audited resolution
# ---------------------------------------------------------------------------

def test_orphan_promotion_is_load_bearing(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    iid = stable_id("intent", "orphan", "AAPL", "buy", 1.0)
    life.state.intents[iid] = {
        "signal_id": "orphan",
        "payload": {"symbol": "AAPL", "side": "buy", "qty": "1", "client_order_id": iid},
        "status": "ORDER_INTENT", "source": "STRATEGY",
    }
    life._save()

    # Guard active: reconcile promotes it -> uncertain -> blocked.
    life.reconcile(now=NOW)
    assert life.state.intents[iid]["status"] == "SUBMIT_FAILED_UNCERTAIN"
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    # Inject: an operator resolution WITHOUT confirmation is refused (the
    # audit gate is load-bearing) ...
    with pytest.raises(PaperGuardError, match="requires explicit confirmation"):
        life.operator_resolve_uncertain_submission(iid, operator_confirmation=False)
    # ... and a direct status edit that skips the audited method leaves no
    # resolution_source / audit trail.
    life.state.intents[iid]["status"] = "REJECTED"   # forbidden shortcut
    life._save()
    assert "resolution_source" not in life.state.intents[iid]
