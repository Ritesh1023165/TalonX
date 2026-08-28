"""Task 81-R2 §2 -- complete order-identity + state reconciliation.

Two more false passes reproduced, plus the coherent-contract lock:

1. An internally FILLED order that the broker still reports open/unfilled
   while position quantities agree -> pre-fix matched=True.
2. A known broker id carrying the WRONG client_order_id -> pre-fix
   matched=True.

Also: no eventual-consistency exemption for `filled`; position agreement
never overrides order disagreement; both directions validated (every
internally outstanding order needs a verified current disposition); the
durable BUY block is held over transient inconsistent snapshots and clears
only on a complete + consistent pass; one coherent validation contract
across every reconcile entry path.

Deterministic clocks (explicit now / filled_at); per-test tmp_path;
in-memory Alpaca fake built to the documented REST contract; no network.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle

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
    """In-memory Alpaca paper simulator (documented Order/Position shapes).
    `orders` is the authoritative order store; open_orders() filters it by
    non-terminal status exactly like GET /v2/orders?status=open, unless
    `open_orders_body` overrides it for a fault-injection test."""

    def __init__(self):
        self.submits = 0
        self.orders: list[dict] = []
        self.positions: list[dict] = []
        self.open_orders_body = _UNSET
        self.get_order_overrides: dict[str, object] = {}   # id -> dict | Exception | 404

    _TERMINAL = {"filled", "canceled", "rejected", "expired", "done_for_day"}

    def _order(self, oid):
        return next((o for o in self.orders if o["id"] == oid), None)

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "paper-id", "account_number": "PA123456", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            if self.open_orders_body is not _UNSET:
                return Response(self.open_orders_body)
            return Response([o for o in self.orders if o["status"] not in self._TERMINAL])
        if "/v2/orders:by_client_order_id" in url:
            cid = kwargs.get("params", {}).get("client_order_id")
            m = next((o for o in self.orders if o["client_order_id"] == cid), None)
            return Response(m, 200 if m else 404)
        if "/v2/orders/" in url:
            oid = url.rsplit("/", 1)[-1]
            if oid in self.get_order_overrides:
                ov = self.get_order_overrides[oid]
                if isinstance(ov, Exception):
                    raise ov
                if ov == 404:
                    return Response({}, 404)
                return Response(ov)
            m = self._order(oid)
            return Response(m or {}, 200 if m else 404)
        if url.endswith("/v2/positions"):
            return Response(self.positions)
        return Response({}, 404)

    def post(self, url, **kwargs):
        self.submits += 1
        p = kwargs.get("json", {})
        o = {"id": f"order-{self.submits}", "client_order_id": p.get("client_order_id", f"order-{self.submits}"),
             "symbol": p.get("symbol"), "side": p.get("side"), "qty": str(p.get("qty")),
             "filled_qty": "0", "filled_avg_price": None, "status": "new",
             "created_at": "2026-08-28T13:00:00Z", "updated_at": "2026-08-28T13:00:00Z"}
        self.orders.append(o)
        return Response(o)

    def delete(self, url, **kwargs):
        return Response([])

    # -- test helpers: keep the fake broker + lifecycle consistent --------
    def sync_fill(self, life, oid, cum_qty, price, *, status="filled", at=FA):
        o = self._order(oid)
        o["status"] = status
        o["filled_qty"] = str(cum_qty)
        o["filled_avg_price"] = str(price)
        o["updated_at"] = at
        life.apply_broker_update(oid, status, cum_qty, price, filled_at=at)

    def add_position(self, symbol, qty, side="long", avg="100.0"):
        self.positions.append({"asset_id": f"a-{symbol}", "symbol": symbol, "qty": str(qty),
                               "side": side, "avg_entry_price": avg, "market_value": "0"})


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


def _reload(cfg, fake):
    broker = AlpacaPaperClient(cfg, fake)
    broker.verify_paper_identity()
    bus = EventBus(cfg.state_dir / "piv_events.jsonl", feed_mode=cfg.feed_mode)
    return PaperLifecycle(cfg.state_dir / "lifecycle_state.json", broker, bus,
                          PaperEntrySettings.for_test("AAPL", "MSFT"))


def _order_row(oid, cid, symbol, side, qty, *, filled_qty="0", status="new", price=None):
    return {"id": oid, "client_order_id": cid, "symbol": symbol, "side": side, "qty": str(qty),
            "filled_qty": str(filled_qty), "filled_avg_price": price, "status": status,
            "created_at": "2026-08-28T13:00:00Z", "updated_at": "2026-08-28T13:00:00Z"}


# ---------------------------------------------------------------------------
# R2a.1 -- internally filled, broker still open, positions agree
# ---------------------------------------------------------------------------

def test_reproduce_filled_order_reported_open_false_pass(tmp_path):
    """Post-fix this asserts the CORRECTED verdict (doubles as regression)."""
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    entry = life.order_intent("s1", "AAPL", "buy", 3, source="STRATEGY", reference_price=100.0)
    fake.sync_fill(life, entry["id"], 3, 100.0)                # order + lifecycle both filled
    # Broker position agrees...
    fake.add_position("AAPL", 3)
    # ...but the broker's open-orders response STILL lists the (filled) order.
    fake.open_orders_body = [_order_row(entry["id"], entry["client_order_id"], "AAPL", "buy", 3, filled_qty="3", status="new")]

    result = life.reconcile(now=NOW)

    assert result["matched"] is False, "a filled order the broker reports open is a contradiction"
    assert result["contradictory_broker_orders"]
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True


def test_internally_filled_order_still_open_at_broker_is_contradiction(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    entry = life.order_intent("s1", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)
    fake.sync_fill(life, entry["id"], 2, 100.0)
    fake.add_position("AAPL", 2)
    fake.open_orders_body = [_order_row(entry["id"], entry["client_order_id"], "AAPL", "buy", 2, filled_qty="2", status="partially_filled")]
    r = life.reconcile(now=NOW)
    assert r["matched"] is False and r["contradictory_broker_orders"]
    # No eventual-consistency exemption -- even repeated passes stay blocked
    # while the contradiction persists.
    r2 = life.reconcile(now=NOW)
    assert r2["matched"] is False
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True


def test_no_eventual_consistency_exemption_for_filled(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    entry = life.order_intent("s1", "AAPL", "buy", 1, source="STRATEGY", reference_price=100.0)
    fake.sync_fill(life, entry["id"], 1, 100.0)
    fake.add_position("AAPL", 1)
    fake.open_orders_body = [_order_row(entry["id"], entry["client_order_id"], "AAPL", "buy", 1, filled_qty="1", status="filled")]
    r = life.reconcile(now=NOW)
    assert r["matched"] is False


# ---------------------------------------------------------------------------
# R2a.2 -- known id, wrong client_order_id
# ---------------------------------------------------------------------------

def test_reproduce_wrong_client_order_id_false_pass(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    entry = life.order_intent("s1", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)
    # Broker lists our order id but with a FOREIGN client_order_id.
    fake.open_orders_body = [_order_row(entry["id"], "FOREIGN-xyz", "AAPL", "buy", 2)]

    result = life.reconcile(now=NOW)

    assert result["matched"] is False, "our id + a foreign client_order_id is a contradiction"
    assert result["contradictory_broker_orders"]


def test_id_with_wrong_client_order_id_is_contradiction(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    entry = life.order_intent("s1", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)
    fake.open_orders_body = [_order_row(entry["id"], "not-ours", "AAPL", "buy", 2)]
    r = life.reconcile(now=NOW)
    assert r["matched"] is False and r["contradictory_broker_orders"]
    with pytest.raises(PaperGuardError, match="RECONCILIATION_BLOCKS_NEW_ENTRIES"):
        life.order_intent("s2", "MSFT", "buy", 1, source="STRATEGY", reference_price=100.0)


# ---------------------------------------------------------------------------
# R2a.3 / R2a.4 -- full field consistency; ambiguity / conflict / malformed
# ---------------------------------------------------------------------------

def test_full_field_consistency_required_for_ok(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    entry = life.order_intent("s1", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)
    # Genuine, fully-consistent open order -> OK (no contradiction/untracked).
    fake.open_orders_body = [_order_row(entry["id"], entry["client_order_id"], "AAPL", "buy", 2, filled_qty="0", status="new")]
    r = life.reconcile(now=NOW)
    assert not r["contradictory_broker_orders"] and not r["untracked_broker_orders"]
    # The pending BUY intent still blocks a same-symbol retry (unchanged).
    with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
        life.order_intent("s1b", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)


@pytest.mark.parametrize("mutate,label", [
    (lambda row: row.update(side="sell"), "wrong_side"),
    (lambda row: row.update(qty="9"), "wrong_requested_qty"),
    (lambda row: row.update(symbol="MSFT"), "wrong_symbol"),
    (lambda row: row.update(filled_qty="99"), "impossible_filled_qty"),
    (lambda row: row.pop("client_order_id"), "missing_client_id"),
    (lambda row: row.update(qty="not-a-number"), "malformed_qty"),
])
def test_missing_intent_ambiguous_conflicting_malformed_never_ok(tmp_path, mutate, label):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    entry = life.order_intent("s1", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)
    row = _order_row(entry["id"], entry["client_order_id"], "AAPL", "buy", 2)
    mutate(row)
    fake.open_orders_body = [row]
    r = life.reconcile(now=NOW)
    assert r["matched"] is False, f"{label} must never be an accepted match"
    assert r["contradictory_broker_orders"] or r["untracked_broker_orders"] or r["incomplete_read"]


def test_conflicting_ids_map_to_different_intents_is_contradiction(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    a = life.order_intent("sA", "AAPL", "buy", 1, source="STRATEGY", reference_price=100.0)
    b = life.order_intent("sB", "MSFT", "buy", 1, source="STRATEGY", reference_price=100.0)
    # broker id == A's order id, but client_order_id == B's intent id
    fake.open_orders_body = [_order_row(a["id"], b["client_order_id"], "AAPL", "buy", 1)]
    r = life.reconcile(now=NOW)
    assert r["matched"] is False and r["contradictory_broker_orders"]


# ---------------------------------------------------------------------------
# R2a.6 -- position agreement does not override order disagreement
# ---------------------------------------------------------------------------

def test_position_agreement_does_not_override_order_disagreement(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    entry = life.order_intent("s1", "AAPL", "buy", 3, source="STRATEGY", reference_price=100.0)
    fake.sync_fill(life, entry["id"], 3, 100.0)
    fake.add_position("AAPL", 3)                       # positions agree exactly
    fake.open_orders_body = [_order_row("stranger-1", "stranger-1", "NVDA", "buy", 5)]   # an untracked order
    r = life.reconcile(now=NOW)
    assert r["matched"] is False
    assert r["untracked_broker_orders"]


# ---------------------------------------------------------------------------
# R2a.7 -- reverse direction: internal outstanding order absent from broker list
# ---------------------------------------------------------------------------

def test_reproduce_internal_order_missing_from_broker_list_false_pass(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    entry = life.order_intent("s1", "AAPL", "buy", 1, source="STRATEGY", reference_price=100.0)
    # get_order still says it's live (non-terminal) ...
    fake.get_order_overrides[entry["id"]] = _order_row(entry["id"], entry["client_order_id"], "AAPL", "buy", 1, status="new")
    # ... but the broker's open-orders LIST omits it entirely.
    fake.open_orders_body = []

    result = life.reconcile(now=NOW)

    assert result["matched"] is False, "an internally-outstanding order absent from the broker list is unresolved"
    assert result.get("orders_missing_from_broker_list") or result["contradictory_broker_orders"]


def test_internal_outstanding_order_absent_from_broker_list_is_unresolved(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    entry = life.order_intent("s1", "AAPL", "buy", 1, source="STRATEGY", reference_price=100.0)
    fake.get_order_overrides[entry["id"]] = _order_row(entry["id"], entry["client_order_id"], "AAPL", "buy", 1, status="accepted")
    fake.open_orders_body = []
    r = life.reconcile(now=NOW)
    assert r["matched"] is False
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True
    # Once the broker list includes it, the pass is consistent again.
    fake.open_orders_body = [_order_row(entry["id"], entry["client_order_id"], "AAPL", "buy", 1, status="accepted")]
    r2 = life.reconcile(now=NOW)
    assert not r2.get("orders_missing_from_broker_list")


# ---------------------------------------------------------------------------
# R2a.8 -- block persistence over transient snapshots; restart-safe
# ---------------------------------------------------------------------------

def test_block_persists_over_transient_snapshot_and_clears_on_clean_pass(tmp_path):
    fake = AlpacaFake()
    cfg = _cfg(tmp_path)
    life = _life(cfg, fake)
    entry = life.order_intent("s1", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)
    fake.open_orders_body = [_order_row(entry["id"], "FOREIGN", "AAPL", "buy", 2)]   # inconsistent snapshot
    life.reconcile(now=NOW)
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    # A second, still-inconsistent snapshot: retryable, still not clean.
    life.reconcile(now=NOW)
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    # A genuinely consistent snapshot clears it.
    fake.open_orders_body = [_order_row(entry["id"], entry["client_order_id"], "AAPL", "buy", 2)]
    # (a lone consistent pending order + its own intent still block via
    #  PENDING_ENTRY_EXISTS, but the reconciliation-level block clears)
    r = life.reconcile(now=NOW)
    assert r["matched"] is True
    assert life.state.reconciliation_flags["entry_admission_blocked"] is False


def test_block_survives_restart(tmp_path):
    fake = AlpacaFake()
    cfg = _cfg(tmp_path)
    life = _life(cfg, fake)
    entry = life.order_intent("s1", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)
    fake.open_orders_body = [_order_row(entry["id"], "FOREIGN", "AAPL", "buy", 2)]
    life.reconcile(now=NOW)
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    life2 = _reload(cfg, fake)
    assert life2.state.reconciliation_flags["entry_admission_blocked"] is True
    with pytest.raises(PaperGuardError, match="RECONCILIATION_BLOCKS_NEW_ENTRIES"):
        life2.order_intent("s2", "MSFT", "buy", 1, source="STRATEGY", reference_price=100.0)
