"""Task 81-R2 §3 -- real orphan recovery through production code only.

An orphan ORDER_INTENT (a crash strictly between persisting the intent and
calling submit_order -> a persisted intent with NO recorded broker order)
must stay blocked until resolved by production paths:

- reconcile() promotes it to SUBMIT_FAILED_UNCERTAIN;
- _resolve_uncertain_submissions discovers it by its stable
  client_order_id and adopts it ONLY on an exact match, applying the real
  status (pending / partial / filled / terminal);
- operator_resolve_uncertain_submission resolves an independently-verified
  non-submission, with explicit confirmation + an audit reason, refusing
  wrong-state / ambiguous / unsupported resolutions;
- no blind resubmission, no count-based "never existed"; restart-safe;
  idempotent.

State seeding is used only for setup; every resolution invokes production
methods. Deterministic clocks; per-test tmp_path; in-memory Alpaca fake;
no network.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle, stable_id

BASE = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)


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
        self.by_client_id: dict[str, object] = {}   # client_order_id -> order dict | 404 | Exception

    _TERMINAL = {"filled", "canceled", "rejected", "expired", "done_for_day"}

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "paper-id", "account_number": "PA123456", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            return Response([o for o in self.orders if o["status"] not in self._TERMINAL])
        if "/v2/orders:by_client_order_id" in url:
            cid = kwargs.get("params", {}).get("client_order_id")
            if cid in self.by_client_id:
                v = self.by_client_id[cid]
                if isinstance(v, Exception):
                    raise v
                if v == 404:
                    return Response({}, 404)
                return Response(v)
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
             "filled_qty": "0", "filled_avg_price": None, "status": "new",
             "created_at": "2026-08-28T13:00:00Z", "updated_at": "2026-08-28T13:00:00Z"}
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


def _reload(cfg, fake):
    broker = AlpacaPaperClient(cfg, fake)
    broker.verify_paper_identity()
    bus = EventBus(cfg.state_dir / "piv_events.jsonl", feed_mode=cfg.feed_mode)
    return PaperLifecycle(cfg.state_dir / "lifecycle_state.json", broker, bus,
                          PaperEntrySettings.for_test("AAPL", "MSFT"))


def _seed_orphan(life, symbol="AAPL", qty=2.0, *, sig="orphan-sig"):
    """Setup only: a persisted ORDER_INTENT with NO recorded broker order."""
    intent_id = stable_id("intent", sig, symbol, "buy", qty)
    life.state.intents[intent_id] = {
        "signal_id": sig,
        "payload": {"symbol": symbol, "side": "buy", "qty": str(qty), "type": "market",
                    "time_in_force": "day", "client_order_id": intent_id},
        "status": "ORDER_INTENT", "source": "STRATEGY",
        "reference_price": 100.0, "stop_price": 95.0, "target_price": 110.0,
        "signal_timestamp": "2026-08-28T13:20:00Z",
    }
    life._save()
    return intent_id


def _found_order(intent_id, symbol, qty, *, status="new", filled_qty=0, price=None, at="2026-08-28T13:25:00Z"):
    return {"id": f"broker-{intent_id[:8]}", "client_order_id": intent_id, "symbol": symbol,
            "side": "buy", "qty": str(qty), "filled_qty": str(filled_qty),
            "filled_avg_price": (str(price) if price is not None else None), "status": status,
            "created_at": "2026-08-28T13:20:00Z", "updated_at": at, "filled_at": at}


# ---------------------------------------------------------------------------
# R3.1 -- promoted and blocked until resolved through production code
# ---------------------------------------------------------------------------

def test_orphan_order_intent_promoted_and_blocked_until_resolved(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    intent_id = _seed_orphan(life)
    fake.by_client_id[intent_id] = 404          # broker has no such order (yet)

    r = life.reconcile(now=BASE)
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"   # promoted by production code
    assert life.state.intents[intent_id].get("promoted_from_orphan_order_intent_at")
    assert intent_id in r["unresolved_submissions"]
    assert r["matched"] is False
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True

    # A same-symbol retry is blocked by the pending/uncertain guard.
    with pytest.raises(PaperGuardError, match="PENDING_ENTRY_EXISTS"):
        life.order_intent("retry", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)


def test_orphan_never_auto_resolves_on_absence(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    intent_id = _seed_orphan(life)
    fake.by_client_id[intent_id] = 404
    for i in range(1, 6):
        life.reconcile(now=BASE + timedelta(hours=i))
        assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN", f"auto-resolved at {i}"
        assert life.state.reconciliation_flags["entry_admission_blocked"] is True
    assert fake.submits == 0                      # never a blind resubmission


# ---------------------------------------------------------------------------
# R3.2 -- discovery + adoption only on exact match
# ---------------------------------------------------------------------------

def test_orphan_discovered_and_adopted_only_on_exact_match(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    intent_id = _seed_orphan(life, qty=2.0)
    # The order DID reach the broker after all -- discoverable by client id.
    fake.by_client_id[intent_id] = _found_order(intent_id, "AAPL", 2, status="new")

    life.reconcile(now=BASE)

    intent = life.state.intents[intent_id]
    assert intent["status"] == "SUBMITTED"        # adopted, not re-submitted
    broker_id = f"broker-{intent_id[:8]}"
    assert broker_id in life.state.orders and life.state.orders[broker_id]["intent_id"] == intent_id
    assert fake.submits == 0


def test_orphan_unrelated_response_not_adopted(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    intent_id = _seed_orphan(life, qty=2.0)
    # A response for a DIFFERENT symbol/qty -- must be rejected, not adopted.
    fake.by_client_id[intent_id] = _found_order(intent_id, "MSFT", 9, status="new")

    life.reconcile(now=BASE)

    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"   # still unresolved
    assert not any(o.get("intent_id") == intent_id for o in life.state.orders.values())
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True


@pytest.mark.parametrize("status,filled_qty,price,expect_open,expect_remaining", [
    ("new", 0, None, False, None),
    ("partially_filled", 1, 100.0, True, 1.0),
    ("filled", 2, 100.0, True, 2.0),
    ("rejected", 0, None, False, None),
])
def test_orphan_recovery_matrix(tmp_path, status, filled_qty, price, expect_open, expect_remaining):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    intent_id = _seed_orphan(life, qty=2.0)
    fake.by_client_id[intent_id] = _found_order(intent_id, "AAPL", 2, status=status,
                                                filled_qty=filled_qty, price=price)
    life.reconcile(now=BASE)

    pos = life._open_position_for("AAPL")
    if expect_open:
        assert pos is not None
        assert pos["remaining_quantity"] == pytest.approx(expect_remaining)
        assert pos["stop_price"] == 95.0 and pos["target_price"] == 110.0     # exit plan recovered
        assert pos["first_fill_observed_at"] is not None                      # fill timing recovered
    else:
        assert pos is None
    if status == "rejected":
        broker_id = f"broker-{intent_id[:8]}"
        assert life.state.orders[broker_id]["status"] == "rejected"


# ---------------------------------------------------------------------------
# R3.4 -- production operator resolution
# ---------------------------------------------------------------------------

def test_operator_resolution_requires_confirmation_and_audits(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    intent_id = _seed_orphan(life)
    fake.by_client_id[intent_id] = 404
    life.reconcile(now=BASE)                     # promotes to SUBMIT_FAILED_UNCERTAIN

    with pytest.raises(PaperGuardError, match="requires explicit confirmation"):
        life.operator_resolve_uncertain_submission(intent_id, operator_confirmation=False)
    assert life.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"

    life.operator_resolve_uncertain_submission(
        intent_id, operator_confirmation=True, operator_note="verified via Alpaca dashboard: never submitted",
    )
    intent = life.state.intents[intent_id]
    assert intent["status"] == "SUBMIT_FAILED_CONFIRMED_NOT_SUBMITTED"
    assert intent["resolution_source"] == "OPERATOR"
    assert "never submitted" in intent["operator_resolution_note"]
    assert intent["operator_resolved_at"]

    # Now a clean reconcile clears the block; a genuinely new signal proceeds.
    r = life.reconcile(now=BASE + timedelta(hours=1))
    assert r["matched"] is True
    assert life.state.reconciliation_flags["entry_admission_blocked"] is False
    ok = life.order_intent("fresh", "AAPL", "buy", 2, source="STRATEGY", reference_price=100.0)
    assert ok["id"]


def test_operator_resolution_refuses_wrong_state(tmp_path):
    fake = AlpacaFake()
    life = _life(_cfg(tmp_path), fake)
    # A normal, SUBMITTED order (not uncertain) cannot be operator-resolved.
    entry = life.order_intent("s1", "AAPL", "buy", 1, source="STRATEGY", reference_price=100.0)
    entry_intent = life.state.orders[entry["id"]]["intent_id"]
    with pytest.raises(PaperGuardError, match="not SUBMIT_FAILED_UNCERTAIN"):
        life.operator_resolve_uncertain_submission(entry_intent, operator_confirmation=True)
    # Unknown intent id -> refused.
    with pytest.raises(PaperGuardError, match="no such intent"):
        life.operator_resolve_uncertain_submission("does-not-exist", operator_confirmation=True)
    # Double resolution -> refused (applies exactly once).
    orphan = _seed_orphan(life, symbol="MSFT")
    fake.by_client_id[orphan] = 404
    life.reconcile(now=BASE)
    life.operator_resolve_uncertain_submission(orphan, operator_confirmation=True, operator_note="verified")
    with pytest.raises(PaperGuardError, match="not SUBMIT_FAILED_UNCERTAIN"):
        life.operator_resolve_uncertain_submission(orphan, operator_confirmation=True)


# ---------------------------------------------------------------------------
# R3.5 -- restart-safe + idempotent
# ---------------------------------------------------------------------------

def test_orphan_recovery_idempotent_and_restart_safe(tmp_path):
    fake = AlpacaFake()
    cfg = _cfg(tmp_path)
    life = _life(cfg, fake)
    intent_id = _seed_orphan(life)
    fake.by_client_id[intent_id] = 404

    life.reconcile(now=BASE)
    life.reconcile(now=BASE + timedelta(hours=1))          # idempotent -- still one uncertain intent
    assert [i for i in life.state.intents.values() if i["status"] == "SUBMIT_FAILED_UNCERTAIN"] != []
    assert fake.submits == 0

    # Full restart: the promoted-uncertain intent and the durable block survive.
    life2 = _reload(cfg, fake)
    assert life2.state.intents[intent_id]["status"] == "SUBMIT_FAILED_UNCERTAIN"
    assert life2.state.reconciliation_flags["entry_admission_blocked"] is True
    r = life2.reconcile(now=BASE + timedelta(hours=2))
    assert r["matched"] is False

    # Later the broker reveals the order genuinely filled -> adopted once.
    fake.by_client_id[intent_id] = _found_order(intent_id, "AAPL", 2, status="filled", filled_qty=2, price=100.0)
    life2.reconcile(now=BASE + timedelta(hours=3))
    assert life2._open_position_for("AAPL") is not None
    assert fake.submits == 0
    # A second reconcile does not double-adopt.
    pos_before = dict(next(p for p in life2.state.positions.values() if p["symbol"] == "AAPL"))
    life2.reconcile(now=BASE + timedelta(hours=4))
    assert dict(next(p for p in life2.state.positions.values() if p["symbol"] == "AAPL")) == pos_before
