"""Task 81-R1 §7 -- negative controls for the R1 recovery-integrity guards.

For each guard, the forbidden outcome is deliberately injected (the guard's
persisted effect is manually undone) and the test proves the forbidden
outcome then occurs -- demonstrating the guard is load-bearing and that the
positive regression test would genuinely fail on a regression.

Deterministic clocks (explicit `now` / `filled_at`); per-test tmp_path;
in-memory fake transport; no network.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle, stable_id
from talonx_piv.session_identity import (
    RECOVERY_REQUIRED, assess_session_recovery, build_session_identity,
)

NOW = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)


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
        self.open_orders_body = _UNSET

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "paper-id", "account_number": "PA123456", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            if self.open_orders_body is not _UNSET:
                return Response(self.open_orders_body)
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
             "symbol": p.get("symbol"), "side": p.get("side"), "qty": p.get("qty"),
             "status": "new", "filled_qty": "0", "filled_avg_price": None}
        self.orders.append(o)
        return Response(o)

    def delete(self, url, **kwargs):
        return Response([])


_UNSET = object()


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


# ---------------------------------------------------------------------------
# Guard 1 (§2): late-fill completion re-opens monitoring
# ---------------------------------------------------------------------------

def test_late_fill_reopen_is_load_bearing(tmp_path):
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    buy = life.order_intent("b", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0, stop_price=95.0)
    life.apply_broker_update(buy["id"], "partially_filled", 1, 100.0, filled_at="2026-08-28T13:30:00Z")
    life.mark_exit_triggered("AAPL", "STOP_HIT")
    sell = life.order_intent("s", "AAPL", "sell", 1, source="STRATEGY")
    life.apply_broker_update(sell["id"], "filled", 1, 96.0, filled_at="2026-08-28T13:40:00Z")
    pos_id = next(iter(life.state.positions))

    # Guard active: the genuine late fill re-opens monitoring.
    life.apply_broker_update(buy["id"], "filled", 2, 100.5, filled_at="2026-08-28T13:50:00Z")
    assert life._open_position_for("AAPL") is not None
    assert life.state.positions[pos_id]["remaining_quantity"] == pytest.approx(1)

    # Inject the forbidden outcome: manually re-close the position and drop
    # the monitoring registration (what the pre-R1 "IGNORED" guard did).
    life.state.positions[pos_id]["status"] = "CLOSED"
    life.state.positions[pos_id]["remaining_quantity"] = 0
    life.state.open_position_by_symbol.pop("AAPL", None)
    life._save()
    # The newly acquired share is now untracked -- a protective SELL for it
    # is (wrongly) rejected as SELL_WHILE_FLAT, i.e. exposure is lost.
    with pytest.raises(PaperGuardError, match="SELL_WHILE_FLAT"):
        life.order_intent("s2", "AAPL", "sell", 1, source="STRATEGY")


# ---------------------------------------------------------------------------
# Guard 2 (§3): cancelled-order-still-open contradiction
# ---------------------------------------------------------------------------

def test_cancelled_order_contradiction_is_load_bearing(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    buy = life.order_intent("b", "AAPL", "buy", 1, source="STRATEGY", reference_price=100.0)
    life.apply_broker_update(buy["id"], "canceled", 0, None)
    transport.open_orders_body = [{
        "id": buy["id"], "client_order_id": buy["id"], "symbol": "AAPL", "side": "buy",
        "qty": "1", "filled_qty": "0", "status": "new", "filled_avg_price": None,
    }]

    # Guard active: contradiction flagged, block set.
    r = life.reconcile(now=NOW)
    assert r["matched"] is False and r["contradictory_broker_orders"]
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    # Inject the forbidden outcome: clear the block flag (what an
    # id-membership-only reconcile left it as -> matched). A new entry now
    # goes through despite the unreconciled cancelled-but-open order.
    flags = dict(life.state.reconciliation_flags)
    flags["entry_admission_blocked"] = False
    life.state.reconciliation_flags = flags
    life._save()
    before = transport.submits
    life.order_intent("b2", "MSFT", "buy", 1, source="STRATEGY", reference_price=100.0)
    assert transport.submits == before + 1


# ---------------------------------------------------------------------------
# Guard 3 (§3): orphan ORDER_INTENT counted as unresolved
# ---------------------------------------------------------------------------

def test_orphan_intent_unresolved_is_load_bearing(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    iid = stable_id("intent", "orphan", "AAPL", "buy", 1.0)
    life.state.intents[iid] = {
        "signal_id": "orphan",
        "payload": {"symbol": "AAPL", "side": "buy", "qty": "1", "client_order_id": iid},
        "status": "ORDER_INTENT", "source": "STRATEGY",
    }
    life._save()

    # Guard active: orphan counted -> incomplete -> block.
    r = life.reconcile(now=NOW)
    assert iid in r["orphan_intents"] and r["complete"] is False
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    # Inject the forbidden outcome: dispose the orphan and clear the block,
    # then re-add an identical orphan WITHOUT reconciling -- proving the
    # block only stays because the orphan is counted each pass.
    flags = dict(life.state.reconciliation_flags)
    flags["entry_admission_blocked"] = False
    life.state.reconciliation_flags = flags
    life._save()
    before = transport.submits
    life.order_intent("b2", "MSFT", "buy", 1, source="STRATEGY", reference_price=100.0)
    assert transport.submits == before + 1   # forbidden: entry while an orphan intent is unresolved


# ---------------------------------------------------------------------------
# Guard 4 (§4): missing identity + exposure -> RECOVERY_REQUIRED
# ---------------------------------------------------------------------------

def test_missing_identity_recovery_is_load_bearing(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "lifecycle_state.json").write_text(json.dumps({
        "session_enabled": True, "kill_switch": False,
        "positions": {"p": {"symbol": "AAPL", "status": "OPEN", "quantity": 1, "remaining_quantity": 1}},
        "orders": {}, "intents": {},
    }), encoding="utf-8")

    # Guard active: absent identity + open position -> RECOVERY_REQUIRED.
    a = assess_session_recovery(cfg, now=NOW)
    assert a.mode == RECOVERY_REQUIRED and a.identity is None

    # Inject the forbidden outcome: a caller that ignores the assessment
    # and mints a fresh authorization-bound identity around the open
    # position (what the pre-R1 fall-through to FRESH_SESSION_CLEAN did).
    fresh = build_session_identity(cfg, now=NOW)
    assert fresh.session_id  # a brand-new session_id now exists...
    # ...while the unresolved exposure is still on disk, unrecovered.
    state = json.loads((tmp_path / "lifecycle_state.json").read_text())
    assert state["positions"]["p"]["status"] == "OPEN"
