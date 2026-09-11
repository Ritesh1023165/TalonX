"""Task 81 §6 (E4) -- negative controls for the critical safety guards.

For each guard, the forbidden outcome is deliberately injected (the guard's
effect is manually undone) and the test proves the forbidden outcome then
occurs -- demonstrating that the guard is load-bearing and that the
corresponding positive regression test in the other Task 81 files would
genuinely fail if the guard regressed.

Each test asserts BOTH sides: guard active -> safe; guard bypassed -> the
forbidden outcome is observable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.session_identity import (
    SessionRecoveryRequired, assess_session_recovery, build_session_identity, resolve_session_identity,
)

FROZEN_NOW = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)


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
    life = PaperLifecycle(cfg.state_dir / "lifecycle_state.json", broker, bus, PaperEntrySettings.for_test("AAPL", "MSFT"))
    life.start_session(True, True)
    return life


# ---------------------------------------------------------------------------
# Guard 1 (§2): reconcile() entry-admission block on a quantity mismatch
# ---------------------------------------------------------------------------

def test_reconciliation_block_is_load_bearing(tmp_path):
    cfg = _cfg(tmp_path)
    transport = Transport()
    life = _life(cfg, transport)
    entry = life.order_intent("s1", "AAPL", "buy", 10, source="STRATEGY")
    life.apply_broker_update(entry["id"], "filled", 10, 100.0, filled_at="2026-08-28T13:30:00Z")
    transport.positions = [{"symbol": "AAPL", "qty": "1", "side": "long"}]   # 10 internal vs 1 broker

    # Guard active: the mismatch blocks a new (different-symbol) entry.
    life.reconcile(now=FROZEN_NOW)
    assert life.state.reconciliation_flags["entry_admission_blocked"] is True
    with pytest.raises(PaperGuardError, match="RECONCILIATION_BLOCKS_NEW_ENTRIES"):
        life.order_intent("s2", "MSFT", "buy", 1, source="STRATEGY")

    # Inject the forbidden outcome: clear the block flag (what a symbol-set-
    # only reconcile() would wrongly have done). The unsafe entry now goes
    # through -- proving the flag is the thing that stops it.
    flags = dict(life.state.reconciliation_flags)
    flags["entry_admission_blocked"] = False
    life.state.reconciliation_flags = flags
    life._save()
    before = transport.submits
    life.order_intent("s3", "MSFT", "buy", 1, source="STRATEGY")
    assert transport.submits == before + 1   # forbidden outcome: entry admitted during an unreconciled mismatch


# ---------------------------------------------------------------------------
# Guard 2 (§3): cumulative filled_qty monotonic clamp in apply_broker_update
# ---------------------------------------------------------------------------

def test_cumulative_fill_clamp_is_load_bearing(tmp_path):
    cfg = _cfg(tmp_path)
    life = _life(cfg, Transport())
    entry = life.order_intent("s1", "AAPL", "buy", 10, source="STRATEGY")
    life.apply_broker_update(entry["id"], "partially_filled", 6, 100.0, filled_at="2026-08-28T13:30:00Z")

    # Guard active: a delayed older cumulative (3) does not rewind the stored 6.
    life.apply_broker_update(entry["id"], "partially_filled", 3, 99.0, filled_at="2026-08-28T13:29:00Z")
    assert life.state.orders[entry["id"]]["filled_qty"] == 6
    assert life._open_position_for("AAPL")["remaining_quantity"] == 6

    # Inject the forbidden outcome: manually rewind the stored filled_qty
    # (what an unclamped apply_broker_update would have persisted). The next
    # genuine cumulative update (10) then computes an inflated increment.
    life.state.orders[entry["id"]]["filled_qty"] = 3.0
    life._save()
    life.apply_broker_update(entry["id"], "filled", 10, 100.0, filled_at="2026-08-28T13:31:00Z")
    pos = life._open_position_for("AAPL")
    # 10 - 3 (rewound) = 7 increment added to prior remaining 6 -> 13, i.e.
    # MORE than was ever entered. This is the accounting corruption the
    # clamp prevents.
    assert pos["remaining_quantity"] > 10


# ---------------------------------------------------------------------------
# Guard 3 (§3): SessionRecoveryRequired on changed bindings + unresolved
# ---------------------------------------------------------------------------

def test_recovery_required_raise_is_load_bearing(tmp_path):
    from unittest.mock import patch
    cfg = _cfg(tmp_path)
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        ident = build_session_identity(cfg, now=FROZEN_NOW)
    (cfg.state_dir / "session_identity.json").write_text(__import__("json").dumps(ident.to_dict()), encoding="utf-8")
    transport = Transport()
    life = _life(cfg, transport)
    e = life.order_intent("s1", "AAPL", "buy", 2, source="STRATEGY")
    life.apply_broker_update(e["id"], "filled", 2, 100.0, filled_at="2026-08-28T13:30:00Z")

    changed = _cfg(tmp_path, universe=("AAPL", "MSFT", "NVDA"))

    # Guard active: resolve raises rather than minting a replacement.
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        with pytest.raises(SessionRecoveryRequired):
            resolve_session_identity(changed, now=FROZEN_NOW + timedelta(minutes=5))

    # Inject the forbidden outcome: swallow the assessment and mint fresh
    # anyway. The prior session's open exposure is now orphaned under a new,
    # unrelated session_id while it remains unresolved.
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        assessment = assess_session_recovery(changed, now=FROZEN_NOW + timedelta(minutes=5))
    assert assessment.mode == "RECOVERY_REQUIRED"           # the assessment DID flag it
    fresh = build_session_identity(changed, now=FROZEN_NOW + timedelta(minutes=5))
    assert fresh.session_id != ident.session_id             # forbidden: a replacement session while exposure is open
    assert life._open_position_for("AAPL") is not None      # the orphaned exposure still exists
