"""Task 81 §2 -- reconciliation completeness and entry admission.

Reproduces the three confirmed baseline defects and locks the corrected
contract:

1. Internal AAPL qty 10 vs broker qty 1 must NOT report ``matched``.
2. An untracked broker BUY *order* with empty portfolios must NOT report
   ``matched`` and must block new entries.
3. An individual pending-order refresh failure must durably block new
   entries; a later reconcile that only sees matching position *symbol
   sets* must NOT clear that block, and the block must survive a full
   process restart.

Every test uses an in-memory fake Transport injected into
``AlpacaPaperClient`` -- never the real ``requests`` module. Broker
response shapes are built from Alpaca's documented REST contract
(https://docs.alpaca.markets/reference/getallpositions,
https://docs.alpaca.markets/reference/getallorders), not from the
implementation's own assumptions. Clocks are frozen: every ``reconcile``
call is passed an explicit ``now``. All state is per-test ``tmp_path``.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle

FROZEN_NOW = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("test_task81_reconciliation_admission: a real network call was attempted")

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


class ConfigurableTransport:
    """TEST_FIXTURE_ONLY. Alpaca paper REST simulator with injectable
    fault modes. ``open_orders_body`` / ``positions_body`` default to the
    live simulated lists but can be overridden with a raw object (dict,
    None, str, ...) to model a malformed 200 body. ``failing_order_ids``
    raises a transport error for ``GET /v2/orders/{id}`` -- an individual
    pending-order refresh failure."""

    def __init__(self):
        self.submits = 0
        self.orders: list[dict] = []
        self.positions: list[dict] = []
        self.open_orders_body = _UNSET
        self.positions_body = _UNSET
        self.failing_order_ids: set[str] = set()

    # -- helpers to seed a documented-shape broker state -------------------
    def add_open_order(self, order_id, symbol, qty, side="buy", client_order_id=None, status="new", filled_qty="0"):
        self.orders.append({
            "id": order_id, "client_order_id": client_order_id or order_id,
            "symbol": symbol, "qty": str(qty), "filled_qty": str(filled_qty),
            "side": side, "status": status, "filled_avg_price": None,
            "created_at": "2026-08-28T13:00:00Z", "updated_at": "2026-08-28T13:00:00Z",
        })

    def add_position(self, symbol, qty, side="long", avg_entry_price="100.0"):
        self.positions.append({
            "asset_id": f"asset-{symbol}", "symbol": symbol, "qty": str(qty),
            "side": side, "avg_entry_price": avg_entry_price, "market_value": "0",
        })

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "paper-id", "account_number": "PA123456", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            if self.open_orders_body is not _UNSET:
                return Response(self.open_orders_body)
            return Response([o for o in self.orders if o["status"] not in ("filled", "rejected", "canceled", "expired")])
        if "/v2/orders:by_client_order_id" in url:
            cid = kwargs.get("params", {}).get("client_order_id")
            match = next((o for o in self.orders if o["client_order_id"] == cid), None)
            return Response(match, 200 if match else 404)
        if "/v2/orders/" in url:
            order_id = url.rsplit("/", 1)[-1]
            if order_id in self.failing_order_ids:
                raise RuntimeError("simulated transport failure for GET /v2/orders/{id}")
            match = next((o for o in self.orders if o["id"] == order_id), None)
            return Response(match or {}, 200 if match else 404)
        if url.endswith("/v2/positions"):
            if self.positions_body is not _UNSET:
                return Response(self.positions_body)
            return Response(self.positions)
        return Response({}, 404)

    def post(self, url, **kwargs):
        self.submits += 1
        payload = kwargs.get("json", {})
        order = {
            "id": f"order-{self.submits}", "client_order_id": payload.get("client_order_id", f"order-{self.submits}"),
            "status": "new", "filled_qty": "0", **payload,
        }
        self.orders.append(order)
        return Response(order)

    def delete(self, url, **kwargs):
        return Response([])


_UNSET = object()


def _config(tmp_path, **overrides):
    values = dict(
        key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
        broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
    )
    values.update(overrides)
    return PivConfig(**values)


def _life(tmp_path, *, enabled=("AAPL",), transport=None, state_name="state.json"):
    transport = transport or ConfigurableTransport()
    broker = AlpacaPaperClient(_config(tmp_path), transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode="RESEARCH_SIP")
    life = PaperLifecycle(tmp_path / state_name, broker, bus, PaperEntrySettings.for_test(*enabled))
    life.start_session(True, True)
    return life, transport, bus


def _reload(tmp_path, transport, *, enabled=("AAPL",), state_name="state.json"):
    """Simulate a full process restart: brand-new objects, same state file."""
    broker = AlpacaPaperClient(_config(tmp_path), transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode="RESEARCH_SIP")
    return PaperLifecycle(tmp_path / state_name, broker, bus, PaperEntrySettings.for_test(*enabled))


def _open_internal_position(life, symbol, qty, price=100.0):
    entry = life.order_intent("sig-" + symbol, symbol, "buy", qty, source="STRATEGY")
    # Keep the fake broker consistent: a real Alpaca GET /v2/orders?status=open
    # never returns a filled order (Task 81-R2 §7 -- realistic broker fakes).
    for o in getattr(life.broker.transport, "orders", []):
        if o.get("id") == entry["id"]:
            o.update(status="filled", filled_qty=str(qty), filled_avg_price=str(price))
    life.apply_broker_update(entry["id"], "filled", qty, price, filled_at="2026-08-28T13:30:00Z")
    return entry


# ---------------------------------------------------------------------------
# Defect 1 -- quantity mismatch on the same symbol
# ---------------------------------------------------------------------------

def test_quantity_mismatch_same_symbol_is_not_matched(tmp_path):
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    _open_internal_position(life, "AAPL", 10)
    transport.positions = []
    transport.add_position("AAPL", 1)  # broker only shows 1 share

    result = life.reconcile(now=FROZEN_NOW)

    assert result["matched"] is False, "qty 10 (internal) vs 1 (broker) must not be matched"
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True
    with pytest.raises(PaperGuardError, match="RECONCILIATION_BLOCKS_NEW_ENTRIES|ALREADY_HOLDING"):
        life.order_intent("s2", "MSFT", "buy", 1, source="STRATEGY")


def test_side_mismatch_not_matched(tmp_path):
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    _open_internal_position(life, "AAPL", 5)
    transport.positions = []
    transport.add_position("AAPL", 5, side="short")  # same qty magnitude, wrong side

    result = life.reconcile(now=FROZEN_NOW)

    assert result["matched"] is False
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True


# ---------------------------------------------------------------------------
# Defect 2 -- untracked broker OPEN ORDER, empty portfolios
# ---------------------------------------------------------------------------

def test_untracked_broker_open_order_blocks_admission(tmp_path):
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    # No internal positions, no internal orders. Broker shows an open BUY
    # order this system never submitted.
    transport.add_open_order("broker-xyz", "TSLA", 3, side="buy")

    result = life.reconcile(now=FROZEN_NOW)

    assert result["matched"] is False, "an untracked broker open order is a mismatch"
    assert result.get("untracked_broker_orders")
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True
    with pytest.raises(PaperGuardError, match="RECONCILIATION_BLOCKS_NEW_ENTRIES"):
        life.order_intent("s1", "AAPL", "buy", 1, source="STRATEGY")


def test_tracked_pending_order_is_not_untracked(tmp_path):
    """Positive control: an order this system DID submit (matching
    client_order_id) is reserved and attributable, not flagged untracked."""
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    life.order_intent("s1", "AAPL", "buy", 1, source="STRATEGY")  # pending in fake transport

    result = life.reconcile(now=FROZEN_NOW)

    assert not result.get("untracked_broker_orders")
    # The pending BUY intent is still reserved/attributable after the pass.
    assert life.pending_buy_intent_ids()


# ---------------------------------------------------------------------------
# Defect 3 -- individual pending-order refresh failure must durably block
# ---------------------------------------------------------------------------

def test_single_order_refresh_failure_keeps_block_across_reconcile_and_restart(tmp_path):
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    # An adopted-but-pending internal order whose individual refresh fails.
    entry = life.order_intent("s1", "AAPL", "buy", 1, source="STRATEGY")
    broker_id = entry["id"]
    transport.failing_order_ids.add(broker_id)

    # First reconcile: the per-order refresh raises. Must block.
    result1 = life.reconcile(now=FROZEN_NOW)
    assert result1["matched"] is False
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    # The order's refresh still fails, but position symbol sets happen to
    # line up (both empty). A symbol-set-only reconcile would clear here.
    result2 = life.reconcile(now=FROZEN_NOW)
    assert result2["matched"] is False, "an unresolved order-refresh failure must not clear on symbol-set match"
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    # Full process restart: the durable block must still be in effect.
    life2 = _reload(tmp_path, transport)
    assert life2.state.reconciliation_flags["entry_admission_blocked"] is True
    with pytest.raises(PaperGuardError, match="RECONCILIATION_BLOCKS_NEW_ENTRIES"):
        life2.order_intent("s2", "MSFT", "buy", 1, source="STRATEGY")

    # Once the refresh succeeds and everything is consistent, the block clears.
    transport.failing_order_ids.discard(broker_id)
    for o in transport.orders:
        if o["id"] == broker_id:
            o["status"] = "filled"
            o["filled_qty"] = "1"
            o["filled_avg_price"] = "100.0"
            o["filled_at"] = "2026-08-28T14:00:00Z"
    transport.positions = []
    transport.add_position("AAPL", 1)
    result3 = life2.reconcile(now=FROZEN_NOW)
    assert result3["matched"] is True
    assert life2.state.reconciliation_flags["entry_admission_blocked"] is False


# ---------------------------------------------------------------------------
# Response completeness / shape
# ---------------------------------------------------------------------------

def test_malformed_positions_response_blocks(tmp_path):
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    transport.positions_body = {"message": "internal error"}  # a 200 with a dict, not a list

    result = life.reconcile(now=FROZEN_NOW)

    assert result["matched"] is False
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True
    assert "INCOMPLETE" in life.state.reconciliation_flags.get("status", "") or \
        life.state.reconciliation_flags.get("status") == "RECONCILIATION_ERROR"


def test_non_list_orders_response_blocks(tmp_path):
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    transport.open_orders_body = None  # a 200 with null

    result = life.reconcile(now=FROZEN_NOW)

    assert result["matched"] is False
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True


def test_position_with_unparseable_qty_blocks(tmp_path):
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    _open_internal_position(life, "AAPL", 1)
    transport.positions = [{"symbol": "AAPL", "side": "long", "qty": "not-a-number"}]

    result = life.reconcile(now=FROZEN_NOW)

    assert result["matched"] is False
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True


# ---------------------------------------------------------------------------
# Clearing only after a complete, consistent pass
# ---------------------------------------------------------------------------

def test_block_clears_only_after_complete_consistent_pass(tmp_path):
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    _open_internal_position(life, "AAPL", 4)
    transport.positions = []
    transport.add_position("AAPL", 2)  # mismatch

    life.reconcile(now=FROZEN_NOW)
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    # Broker now reports the correct quantity -> consistent + complete.
    transport.positions = []
    transport.add_position("AAPL", 4)
    result = life.reconcile(now=FROZEN_NOW)
    assert result["matched"] is True
    assert life.state.reconciliation_flags["entry_admission_blocked"] is False


def test_uncertain_submission_prevents_clear(tmp_path):
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    # Force a submit failure so the intent is SUBMIT_FAILED_UNCERTAIN.
    original_post = transport.post

    def _boom(url, **kwargs):
        raise RuntimeError("submit connection reset")

    transport.post = _boom
    with pytest.raises(RuntimeError):
        life.order_intent("s1", "AAPL", "buy", 1, source="STRATEGY")
    transport.post = original_post

    assert any(i.get("status") == "SUBMIT_FAILED_UNCERTAIN" for i in life.state.intents.values())

    # Portfolios are empty on both sides, but an unresolved submission means
    # the reconcile is not consistent/complete -- must not clear.
    result = life.reconcile(now=FROZEN_NOW)
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True
    assert result["matched"] is False


# ---------------------------------------------------------------------------
# Protective exits / EOD are never gated by the entry block
# ---------------------------------------------------------------------------

def test_block_does_not_suppress_sell(tmp_path):
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    _open_internal_position(life, "AAPL", 3)
    transport.positions = []
    transport.add_position("AAPL", 99)  # mismatch -> entry block

    life.reconcile(now=FROZEN_NOW)
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    # A protective SELL sized to verified internal remaining holdings still
    # goes through -- the block is BUY_TO_OPEN-only.
    before = transport.submits
    life.order_intent("exit-1", "AAPL", "sell", 3, source="STRATEGY")
    assert transport.submits == before + 1


def test_entry_block_does_not_disable_eod_cleanup(tmp_path):
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    _open_internal_position(life, "AAPL", 2)
    transport.positions = []
    transport.add_position("AAPL", 5)  # mismatch -> entry block

    life.reconcile(now=FROZEN_NOW)
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    out = life.eod_flatten()  # must not raise / must not be disabled by the block
    assert life.state.session_enabled is False
    assert all(p["status"] == "CLOSED" for p in life.state.positions.values())
    assert isinstance(out, dict)


def test_sell_sizing_unknown_exposure_fails_visibly(tmp_path):
    """Unknown exposure must not produce a blind oversell: a second sell for
    more than the verified remaining holdings (after a still-pending sell)
    is rejected before it can reach the broker."""
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    _open_internal_position(life, "AAPL", 3)
    life.order_intent("exit-a", "AAPL", "sell", 2, source="STRATEGY")  # pending, unresolved
    with pytest.raises(PaperGuardError, match="OVERSIZED_OR_DUPLICATE_SELL"):
        life.order_intent("exit-b", "AAPL", "sell", 3, source="STRATEGY")


# ---------------------------------------------------------------------------
# Verified pending order stays reserved through a clearing pass
# ---------------------------------------------------------------------------

def test_verified_pending_order_stays_reserved_after_clear(tmp_path):
    transport = ConfigurableTransport()
    life, transport, _ = _life(tmp_path, transport=transport)
    entry = life.order_intent("s1", "AAPL", "buy", 1, source="STRATEGY")
    # Broker confirms exactly this order is open (same client_order_id).
    reserved_before = set(life.pending_buy_intent_ids())
    result = life.reconcile(now=FROZEN_NOW)
    assert not result.get("untracked_broker_orders")
    assert set(life.pending_buy_intent_ids()) == reserved_before
    # A same-symbol retry is still blocked by the reserved pending entry.
    with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
        life.order_intent("s2", "AAPL", "buy", 1, source="STRATEGY")
