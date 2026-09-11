"""Task 81-R1 §3 -- reconciliation completeness (two remaining false passes).

A. An internally CANCELLED (terminal) order still appears in the broker's
   open-order response. Pre-fix, its historically-known id causes the
   reconcile pass to accept it as tracked/consistent -> false MATCHED.
B. An orphan `ORDER_INTENT` (persisted intent, no recorded broker order --
   a crash between persisting the intent and calling submit_order) is
   excluded from unresolved submissions -> a later pass wrongly clears the
   entry-admission block.

Also locks: a broker open order is matched to its exact durable intent
only when broker/client id, symbol, side, quantity AND a compatible
(non-terminal) internal lifecycle state all agree.

Frozen `now`; per-test tmp_path; in-memory fake transport; no network.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle, stable_id

NOW = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)


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


def _reload(cfg, transport):
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(cfg.state_dir / "piv_events.jsonl", feed_mode=cfg.feed_mode)
    return PaperLifecycle(cfg.state_dir / "lifecycle_state.json", broker, bus,
                          PaperEntrySettings.for_test("AAPL", "MSFT"))


# ---------------------------------------------------------------------------
# Defect A -- cancelled order the broker still reports open
# ---------------------------------------------------------------------------

def test_cancelled_order_reported_open_is_contradiction_and_blocks(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    buy = life.order_intent("b1", "AAPL", "buy", 1, source="STRATEGY", reference_price=100.0)
    bid = buy["id"]
    # We cancelled it internally...
    life.apply_broker_update(bid, "canceled", 0, None)
    assert life.state.orders[bid]["status"] == "canceled"
    # ...but the broker's open-orders response still lists it (stale / the
    # cancel did not actually take at the broker).
    transport.open_orders_body = [{
        "id": bid, "client_order_id": bid, "symbol": "AAPL", "side": "buy",
        "qty": "1", "filled_qty": "0", "status": "new", "filled_avg_price": None,
    }]

    result = life.reconcile(now=NOW)

    assert result["matched"] is False, "a cancelled order still open at the broker is a contradiction"
    assert result.get("contradictory_broker_orders")
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True
    with pytest.raises(PaperGuardError, match="RECONCILIATION_BLOCKS_NEW_ENTRIES"):
        life.order_intent("b2", "MSFT", "buy", 1, source="STRATEGY", reference_price=100.0)


def test_broker_order_matched_only_with_consistent_symbol_side_qty(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    buy = life.order_intent("b1", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)
    bid = buy["id"]
    cid = buy["client_order_id"]   # the REAL client_order_id we sent (== intent id)
    # Broker reports our id back, but with a WRONG quantity -- not a valid match.
    transport.open_orders_body = [{
        "id": bid, "client_order_id": cid, "symbol": "AAPL", "side": "buy",
        "qty": "9", "filled_qty": "0", "status": "new", "filled_avg_price": None,
    }]
    result = life.reconcile(now=NOW)
    assert result["matched"] is False
    assert result.get("contradictory_broker_orders")

    # Consistent id + client id + symbol + side + qty + non-terminal internal state -> OK.
    transport.open_orders_body = [{
        "id": bid, "client_order_id": cid, "symbol": "AAPL", "side": "buy",
        "qty": "2", "filled_qty": "0", "status": "new", "filled_avg_price": None,
    }]
    result2 = life.reconcile(now=NOW)
    assert not result2.get("contradictory_broker_orders")
    assert not result2.get("untracked_broker_orders")


# ---------------------------------------------------------------------------
# Defect B -- orphan ORDER_INTENT
# ---------------------------------------------------------------------------

def _make_orphan_intent(life, symbol="AAPL", qty=1.0):
    """Reproduce a crash strictly between persisting the intent and calling
    submit_order: an ORDER_INTENT-status intent with NO recorded order."""
    intent_id = stable_id("intent", "orphan-sig", symbol, "buy", qty)
    life.state.intents[intent_id] = {
        "signal_id": "orphan-sig",
        "payload": {"symbol": symbol, "side": "buy", "qty": str(qty), "type": "market",
                    "time_in_force": "day", "client_order_id": intent_id},
        "status": "ORDER_INTENT", "source": "STRATEGY", "reference_price": 100.0,
    }
    life._save()
    return intent_id


def test_orphan_order_intent_is_unresolved_and_blocks_clear(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    intent_id = _make_orphan_intent(life)

    # Broker shows nothing; portfolios empty on both sides. A symbol-set /
    # SUBMIT_FAILED_UNCERTAIN-only reconcile would call this a clean pass.
    result = life.reconcile(now=NOW)

    assert result["matched"] is False
    assert result["complete"] is False
    assert intent_id in result.get("orphan_intents", [])
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    # Restart: the orphan and the durable block both survive.
    life2 = _reload(cfg, transport)
    assert life2.state.reconciliation_flags["entry_admission_blocked"] is True
    r2 = life2.reconcile(now=NOW)
    assert intent_id in r2.get("orphan_intents", [])
    assert r2["matched"] is False


def test_orphan_intent_clears_only_after_documented_operator_resolution(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    intent_id = _make_orphan_intent(life)
    life.reconcile(now=NOW)   # Task 81-R2 §3: promotes the orphan to SUBMIT_FAILED_UNCERTAIN
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    # Resolved ONLY through the production operator method (independently
    # verified non-submission) -- no direct status editing.
    life.operator_resolve_uncertain_submission(
        intent_id, operator_confirmation=True, operator_note="verified never submitted via Alpaca dashboard",
    )

    result = life.reconcile(now=NOW)
    assert intent_id not in result.get("orphan_intents", [])
    assert result["matched"] is True
    assert life.state.reconciliation_flags["entry_admission_blocked"] is False


# ---------------------------------------------------------------------------
# Regression: existing completeness guarantees still hold
# ---------------------------------------------------------------------------

def test_malformed_order_row_does_not_clear(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    transport.open_orders_body = "not-a-list"
    result = life.reconcile(now=NOW)
    assert result["matched"] is False
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True


def test_block_persists_and_clears_only_on_clean_pass(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    intent_id = _make_orphan_intent(life)
    life.reconcile(now=NOW)
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True
    life.operator_resolve_uncertain_submission(
        intent_id, operator_confirmation=True, operator_note="verified never submitted",
    )
    life.reconcile(now=NOW)
    assert life.state.reconciliation_flags["entry_admission_blocked"] is False
