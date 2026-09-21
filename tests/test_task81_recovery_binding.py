"""Task 81 §3 -- recovery, session binding, and cumulative-fill idempotency.

- Same-session restart under unchanged verified bindings preserves the
  session identity, pending plans, budgets and exit obligations.
- Changed runtime/config/feed bindings, a corrupt identity, or incomplete
  EOD state must NOT silently mint a replacement session while exposure or
  submissions remain unresolved -- recovery context is preserved, new
  entries are blocked, and the required operator action is reported.
- A fresh session is permitted only through a defined, verified transition
  (exposure resolved + EOD complete).
- Exact order-to-intent pending-plan recovery; ambiguity fails visibly.
- Cumulative fills are idempotent: repeated / delayed / older updates must
  not resurrect sold quantity, erase the exit latch, or corrupt accounting.
- End-to-end: partial entry -> partial exit -> later entry fill -> restart
  -> remaining exit, including a reconciliation failure.

Clocks are frozen (explicit ``now``); every state dir is per-test
``tmp_path``; the broker is an in-memory fake.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from talonx_piv.broker import AlpacaPaperClient, PaperGuardError
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.session_identity import (
    FRESH_SESSION_CLEAN, RECOVERY_REQUIRED, RESUME_SAME_SESSION, SessionRecoveryRequired,
    assess_session_recovery, build_session_identity, compute_config_hash,
    resolve_session_identity, write_session_recovery_marker,
)

FROZEN_NOW = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
TODAY_ET = "2026-08-28"


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("test_task81_recovery_binding: a real network call was attempted")

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
    """Minimal in-memory Alpaca paper simulator (documented shapes)."""

    def __init__(self):
        self.submits = 0
        self.orders: list[dict] = []
        self.positions: list[dict] = []
        self.get_order_raises = False

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "paper-id", "account_number": "PA123456", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            return Response([o for o in self.orders if o["status"] not in ("filled", "rejected", "canceled", "expired")])
        if "/v2/orders/" in url:
            if self.get_order_raises:
                raise RuntimeError("simulated broker read failure")
            oid = url.rsplit("/", 1)[-1]
            match = next((o for o in self.orders if o["id"] == oid), None)
            return Response(match or {}, 200 if match else 404)
        if url.endswith("/v2/positions"):
            return Response(self.positions)
        return Response({}, 404)

    def post(self, url, **kwargs):
        self.submits += 1
        payload = kwargs.get("json", {})
        order = {"id": f"order-{self.submits}", "client_order_id": payload.get("client_order_id", f"order-{self.submits}"),
                 "status": "new", "filled_qty": "0", **payload}
        self.orders.append(order)
        return Response(order)

    def delete(self, url, **kwargs):
        return Response([])


def _config(tmp_path, **overrides):
    values = dict(
        key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
        broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
        universe=("AAPL", "MSFT"), feed_mode="IEX_PAPER_PIV",
    )
    values.update(overrides)
    return PivConfig(**values)


def _life(cfg, transport, *, enabled=("AAPL", "MSFT")):
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(cfg.state_dir / "piv_events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(cfg.state_dir / "lifecycle_state.json", broker, bus, PaperEntrySettings.for_test(*enabled))
    return life, bus


def _seed_identity(cfg, *, runtime_sha="sha-old"):
    from unittest.mock import patch
    with patch("talonx_piv.session_identity.runtime_sha", return_value=runtime_sha):
        ident = build_session_identity(cfg, now=FROZEN_NOW)
    (cfg.state_dir / "session_identity.json").write_text(json.dumps(ident.to_dict()), encoding="utf-8")
    return ident


# ---------------------------------------------------------------------------
# B1 -- same-session restart under unchanged verified bindings
# ---------------------------------------------------------------------------

def test_same_session_restart_preserves_everything(tmp_path):
    from unittest.mock import patch
    cfg = _config(tmp_path)
    ident = _seed_identity(cfg)

    transport = Transport()
    life, _ = _life(cfg, transport)
    life.start_session(True, True)
    entry = life.order_intent("s1", "AAPL", "buy", 3, source="STRATEGY", stop_price=95.0, target_price=110.0)
    life.apply_broker_update(entry["id"], "filled", 3, 100.0, filled_at="2026-08-28T13:30:00Z")
    life.mark_exit_triggered("AAPL", "STOP_HIT")
    life.state.experimental_budgets["exp-1"] = {"entries_used": 1, "notional_used": 300.0}
    life._save()

    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        assessment = assess_session_recovery(cfg, now=FROZEN_NOW + timedelta(minutes=5))
    assert assessment.mode == RESUME_SAME_SESSION
    assert assessment.identity.session_id == ident.session_id

    # Full restart: brand-new objects, same state file.
    life2, _ = _life(cfg, Transport())
    pos = life2._open_position_for("AAPL")
    assert pos is not None and pos["remaining_quantity"] == 3
    assert pos["triggered_exit_reason"] == "STOP_HIT"          # exit obligation preserved
    assert life2.state.experimental_budgets["exp-1"] == {"entries_used": 1, "notional_used": 300.0}


# ---------------------------------------------------------------------------
# B2 -- changed bindings / corrupt identity / incomplete EOD + unresolved
#       exposure must NOT silently replace the session
# ---------------------------------------------------------------------------

def _seed_live_session_with_open_position(tmp_path, cfg):
    _seed_identity(cfg)
    transport = Transport()
    life, _ = _life(cfg, transport)
    life.start_session(True, True)
    entry = life.order_intent("s1", "AAPL", "buy", 2, source="STRATEGY", stop_price=95.0, target_price=110.0)
    life.apply_broker_update(entry["id"], "filled", 2, 100.0, filled_at="2026-08-28T13:30:00Z")
    return life


def test_changed_config_binding_with_open_exposure_blocks_and_reports(tmp_path):
    from unittest.mock import patch
    cfg = _config(tmp_path)
    _seed_live_session_with_open_position(tmp_path, cfg)
    changed = _config(tmp_path, universe=("AAPL", "MSFT", "NVDA"))  # config_hash changes

    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        with pytest.raises(SessionRecoveryRequired) as ei:
            resolve_session_identity(changed, now=FROZEN_NOW + timedelta(minutes=5))
    assert any("BINDINGS_CHANGED" in r for r in ei.value.reasons)
    assert any(r.startswith("OPEN_POSITION:AAPL") for r in ei.value.reasons)
    assert "eod" in ei.value.required_action
    assert ei.value.preserved_identity["trading_date_et"] == TODAY_ET

    write_session_recovery_marker(cfg.state_dir, ei.value, command="start", now=FROZEN_NOW)
    marker = json.loads((cfg.state_dir / "session_recovery_required.json").read_text())
    assert marker["command"] == "start" and marker["reasons"] == list(ei.value.reasons)
    # session_identity.json is NOT overwritten.
    saved = json.loads((cfg.state_dir / "session_identity.json").read_text())
    assert saved["config_hash"] == compute_config_hash(cfg)


def test_changed_feed_mode_binding_blocks(tmp_path):
    from unittest.mock import patch
    cfg = _config(tmp_path)
    _seed_live_session_with_open_position(tmp_path, cfg)
    changed = _config(tmp_path, feed_mode="RESEARCH_SIP")
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        with pytest.raises(SessionRecoveryRequired) as ei:
            resolve_session_identity(changed, now=FROZEN_NOW + timedelta(minutes=5))
    assert any("feed_mode" in r for r in ei.value.reasons)


def test_corrupt_identity_with_outstanding_order_blocks_not_silently_replaced(tmp_path):
    cfg = _config(tmp_path)
    _seed_identity(cfg)
    transport = Transport()
    life, _ = _life(cfg, transport)
    life.start_session(True, True)
    life.order_intent("s1", "AAPL", "buy", 1, source="STRATEGY")  # pending, non-terminal order
    (cfg.state_dir / "session_identity.json").write_text("{ this is not json", encoding="utf-8")

    with pytest.raises(SessionRecoveryRequired) as ei:
        resolve_session_identity(cfg, now=FROZEN_NOW + timedelta(minutes=5))
    assert "SESSION_IDENTITY_CORRUPT" in ei.value.reasons
    assert any(r.startswith("OUTSTANDING_ORDER") for r in ei.value.reasons)


@pytest.mark.parametrize("eod_status", ["PENDING", "INCONCLUSIVE", "FAILED"])
def test_incomplete_eod_with_exposure_blocks(tmp_path, eod_status):
    cfg = _config(tmp_path)
    _seed_live_session_with_open_position(tmp_path, cfg)
    (cfg.state_dir / "eod_state.json").write_text(
        json.dumps({"trading_date_et": TODAY_ET, "status": eod_status, "session_id": "x"}), encoding="utf-8",
    )
    with pytest.raises(SessionRecoveryRequired) as ei:
        resolve_session_identity(cfg, now=FROZEN_NOW + timedelta(minutes=5))
    assert any("EOD_NOT_COMPLETE" in r for r in ei.value.reasons)


def test_changed_binding_without_exposure_and_eod_passed_is_clean_fresh(tmp_path):
    from unittest.mock import patch
    cfg = _config(tmp_path)
    _seed_identity(cfg)
    # A prior session that is flat and EOD-complete.
    (cfg.state_dir / "lifecycle_state.json").write_text(
        json.dumps({"session_enabled": False, "kill_switch": False, "positions": {}, "orders": {}, "intents": {}}),
        encoding="utf-8",
    )
    (cfg.state_dir / "eod_state.json").write_text(
        json.dumps({"trading_date_et": TODAY_ET, "status": "PASSED"}), encoding="utf-8",
    )
    changed = _config(tmp_path, universe=("AAPL", "MSFT", "NVDA"))
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        assessment = assess_session_recovery(changed, now=FROZEN_NOW + timedelta(minutes=5))
    assert assessment.mode == FRESH_SESSION_CLEAN
    ident = resolve_session_identity(changed, now=FROZEN_NOW + timedelta(minutes=5))
    assert ident.config_hash == compute_config_hash(changed)


# ---------------------------------------------------------------------------
# B3 -- fresh session only through a defined, verified transition
# ---------------------------------------------------------------------------

def test_fresh_session_requires_defined_transition(tmp_path):
    from unittest.mock import patch
    cfg = _config(tmp_path)
    _seed_live_session_with_open_position(tmp_path, cfg)

    # While exposure is unresolved -> blocked, even on the SAME bindings if
    # the session is no longer live (e.g. crashed mid-session, not EOD'd).
    state = json.loads((cfg.state_dir / "lifecycle_state.json").read_text())
    state["session_enabled"] = False
    (cfg.state_dir / "lifecycle_state.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(SessionRecoveryRequired):
        resolve_session_identity(cfg, now=FROZEN_NOW + timedelta(minutes=5))

    # The defined transition: exposure resolved (position closed) + session
    # not live -> a fresh identity is minted cleanly.
    state = json.loads((cfg.state_dir / "lifecycle_state.json").read_text())
    for p in state["positions"].values():
        p["status"] = "CLOSED"
        p["remaining_quantity"] = 0
    state["orders"] = {}
    (cfg.state_dir / "lifecycle_state.json").write_text(json.dumps(state), encoding="utf-8")
    with patch("talonx_piv.session_identity.runtime_sha", return_value="sha-old"):
        assessment = assess_session_recovery(cfg, now=FROZEN_NOW + timedelta(minutes=6))
    assert assessment.mode == FRESH_SESSION_CLEAN


# ---------------------------------------------------------------------------
# B4 -- exact order-to-intent pending-plan recovery; ambiguity fails visibly
# ---------------------------------------------------------------------------

def test_exact_pending_plan_recovery_and_ambiguity(tmp_path):
    cfg = _config(tmp_path)
    _seed_identity(cfg)
    transport = Transport()
    life, _ = _life(cfg, transport)
    life.start_session(True, True)

    # An older same-symbol intent that reached a terminal (rejected) state.
    old = life.order_intent("old-sig", "AAPL", "buy", 1, source="STRATEGY")
    life.apply_broker_update(old["id"], "rejected", 0, None)
    # A newer, genuinely-outstanding entry order.
    new = life.order_intent("new-sig", "AAPL", "buy", 2, source="STRATEGY")

    pending = life.pending_buy_intent_ids()
    assert len(pending) == 1
    assert life.state.orders[new["id"]]["intent_id"] in pending
    assert life.state.orders[old["id"]]["intent_id"] not in pending  # older terminal plan not restored


# ---------------------------------------------------------------------------
# B5 -- cumulative fill idempotency matrix
# ---------------------------------------------------------------------------

def _open_life(tmp_path):
    cfg = _config(tmp_path)
    _seed_identity(cfg)
    life, _ = _life(cfg, Transport())
    life.start_session(True, True)
    return life


def test_repeated_identical_fill_update_is_idempotent(tmp_path):
    life = _open_life(tmp_path)
    entry = life.order_intent("s1", "AAPL", "buy", 5, source="STRATEGY")
    life.apply_broker_update(entry["id"], "filled", 5, 100.0, filled_at="2026-08-28T13:30:00Z")
    pos_id = next(iter(life.state.positions))
    snapshot = dict(life.state.positions[pos_id])
    # Same terminal update replayed twice more.
    life.apply_broker_update(entry["id"], "filled", 5, 100.0, filled_at="2026-08-28T13:30:00Z")
    life.apply_broker_update(entry["id"], "filled", 5, 100.0, filled_at="2026-08-28T13:30:00Z")
    assert life.state.positions[pos_id] == snapshot
    assert life.state.orders[entry["id"]]["filled_qty"] == 5


def test_older_smaller_cumulative_update_does_not_rewind_or_double_count(tmp_path):
    life = _open_life(tmp_path)
    entry = life.order_intent("s1", "AAPL", "buy", 10, source="STRATEGY")
    life.apply_broker_update(entry["id"], "partially_filled", 6, 100.0, filled_at="2026-08-28T13:30:00Z")
    # A DELAYED, older cumulative report (only 3 filled) arrives late.
    life.apply_broker_update(entry["id"], "partially_filled", 3, 99.0, filled_at="2026-08-28T13:29:00Z")
    pos = life._open_position_for("AAPL")
    assert pos["remaining_quantity"] == 6            # not rewound to 3, not inflated
    assert life.state.orders[entry["id"]]["filled_qty"] == 6
    # The genuine completion then applies its true increment (10 - 6 = 4).
    life.apply_broker_update(entry["id"], "filled", 10, 100.0, filled_at="2026-08-28T13:31:00Z")
    pos = life._open_position_for("AAPL")
    assert pos["remaining_quantity"] == 10           # never 3+... double counted


def test_delayed_fill_after_close_does_not_resurrect_or_erase_latch(tmp_path):
    life = _open_life(tmp_path)
    entry = life.order_intent("s1", "AAPL", "buy", 3, source="STRATEGY", stop_price=95.0)
    life.apply_broker_update(entry["id"], "filled", 3, 100.0, filled_at="2026-08-28T13:30:00Z")
    life.mark_exit_triggered("AAPL", "STOP_HIT")
    exit_ = life.order_intent("x1", "AAPL", "sell", 3, source="STRATEGY")
    life.apply_broker_update(exit_["id"], "filled", 3, 96.0, filled_at="2026-08-28T14:00:00Z")
    pos_id = next(pid for pid, p in life.state.positions.items() if p["symbol"] == "AAPL")
    assert life.state.positions[pos_id]["status"] == "CLOSED"
    closed_snapshot = dict(life.state.positions[pos_id])

    # A stale, duplicated terminal callback for the ENTRY order arrives now.
    life.apply_broker_update(entry["id"], "filled", 3, 100.0, filled_at="2026-08-28T13:30:00Z")
    assert life.state.positions[pos_id] == closed_snapshot          # not resurrected
    assert life._open_position_for("AAPL") is None
    assert life.state.positions[pos_id]["triggered_exit_reason"] == "STOP_HIT"  # latch intact
    assert life.state.positions[pos_id]["gross_pnl"] == pytest.approx(3 * (96.0 - 100.0))


def test_terminal_status_cannot_regress_to_non_terminal(tmp_path):
    life = _open_life(tmp_path)
    entry = life.order_intent("s1", "AAPL", "buy", 4, source="STRATEGY")
    life.apply_broker_update(entry["id"], "filled", 4, 100.0, filled_at="2026-08-28T13:30:00Z")
    life.apply_broker_update(entry["id"], "new", 0, None)   # nonsensical regression
    assert life.state.orders[entry["id"]]["status"] == "filled"
    assert life.state.orders[entry["id"]]["filled_qty"] == 4


# ---------------------------------------------------------------------------
# B6 -- partial entry -> partial exit -> later entry fill -> restart ->
#       remaining exit, including a reconciliation failure
# ---------------------------------------------------------------------------

def test_partial_entry_partial_exit_later_fill_restart_remaining_exit(tmp_path):
    cfg = _config(tmp_path)
    _seed_identity(cfg)
    transport = Transport()
    life, _ = _life(cfg, transport)
    life.start_session(True, True)

    entry = life.order_intent("e1", "AAPL", "buy", 10, source="STRATEGY", stop_price=95.0, target_price=115.0)
    life.apply_broker_update(entry["id"], "partially_filled", 4, 100.0, filled_at="2026-08-28T13:30:00Z")
    # Partial protective exit -- smaller than what is held, position stays OPEN.
    ex1 = life.order_intent("x1", "AAPL", "sell", 3, source="STRATEGY")
    life.apply_broker_update(ex1["id"], "filled", 3, 101.0, filled_at="2026-08-28T13:40:00Z")
    pos = life._open_position_for("AAPL")
    assert pos["status"] == "OPEN" and pos["remaining_quantity"] == pytest.approx(1)

    # Later, the rest of the ENTRY fills (cumulative 10).
    life.apply_broker_update(entry["id"], "filled", 10, 100.2, filled_at="2026-08-28T13:50:00Z")
    pos = life._open_position_for("AAPL")
    assert pos is not None
    assert pos["remaining_quantity"] == pytest.approx(7)   # prior remaining 1 + new increment 6
    assert pos["exit_quantity"] == pytest.approx(3)

    # -- Full process restart --
    life2, _ = _life(cfg, transport)
    pos = life2._open_position_for("AAPL")
    assert pos is not None and pos["remaining_quantity"] == pytest.approx(7)

    # A reconciliation failure right after restart durably blocks NEW entries
    # but never the protective exit of the verified remaining holdings.
    transport.positions = [{"symbol": "AAPL", "qty": "999", "side": "long"}]  # contradictory qty
    res = life2.reconcile(now=FROZEN_NOW)
    assert res["matched"] is False
    assert life2.state.reconciliation_flags["entry_admission_blocked"] is True
    with pytest.raises(PaperGuardError, match="RECONCILIATION_BLOCKS_NEW_ENTRIES"):
        life2.order_intent("e3", "MSFT", "buy", 1, source="STRATEGY")

    # The remaining protective exit still proceeds, sized to verified holdings.
    ex2 = life2.order_intent("x2", "AAPL", "sell", 7, source="STRATEGY")
    life2.apply_broker_update(ex2["id"], "filled", 7, 96.0, filled_at="2026-08-28T14:10:00Z")
    pos_id = next(pid for pid, p in life2.state.positions.items() if p["symbol"] == "AAPL")
    assert life2.state.positions[pos_id]["status"] == "CLOSED"
    assert life2.state.positions[pos_id]["remaining_quantity"] == pytest.approx(0)
    assert life2.state.positions[pos_id]["exit_quantity"] == pytest.approx(10)
