"""
Package 1 -- Settlement Integrity & Unresolved Obligations.

Isolated regressions, real temporary SQLite files (never mocks the
ledger itself), no network dependency. These reproduce two defects an
earlier audit identified in ``talonx_v2.paper``/``talonx_v2.store`` and
in the V2 reporting/reconciliation paths that read the same ledger:

  A. ``paper.close_position`` performs its state transition via a
     conditional SQL UPDATE (``WHERE status='OPEN'``) but never checks
     whether that UPDATE actually matched a row before unconditionally
     crediting cash, appending a trade, and resetting cooldown -- so a
     second call against a stale snapshot of an already-closed position
     duplicates all three economic effects.
  B. ``EXIT_UNRESOLVED`` positions are invisible to several OPEN-only
     lookups (``n_open()``, ``position_for_symbol()``) and to the V2
     reporting/reconciliation paths (``talonx_ops.paper_performance``,
     ``talonx_ops.prospective.close``), which can under-count capacity,
     admit a second position in the same security, report a fabricated
     "COMPLETE" cash-only equity, and produce a fabricated cash-loss
     reconciliation mismatch -- all purely because the unresolved
     position's cost basis is omitted from those calculations.

Run once against the unmodified baseline (evidence: which assertions
fail and why), then again after the minimum Package 1 fix (evidence:
all pass). Neither pass is skipped or deleted -- this file is the
regression suite going forward.
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from talonx_v2 import paper
from talonx_v2.config import V2Config
from talonx_v2.schemas import V2Action, V2Decision, V2Direction
from talonx_v2.store import V2Store


def _decision(episode_id="ep1", symbol="AAA"):
    return V2Decision(signal_id=f"sig-{episode_id}", episode_id=episode_id, symbol=symbol,
                      direction=V2Direction.BULLISH, action=V2Action.BUY,
                      official_eligible=False, rationale="test",
                      eligible_entry_session=date(2026, 9, 8))


def _entered(tmp_path, *, cash=300_000.0, symbol="AAA", episode_id="ep1", db_name="v.db"):
    store = V2Store(str(tmp_path / db_name), starting_cash=cash)
    cfg = V2Config(starting_cash_usd=cash, per_position_allocation_usd=10_000.0)
    outcome = paper.enter_position(store, _decision(episode_id, symbol), entry_price=100.0,
                                   entry_session=date(2026, 9, 8), config=cfg)
    assert outcome.entered, outcome.reason
    pos = store.all_positions()[0]
    return store, cfg, pos


# ===================================================================== #
# A. Duplicate settlement
# ===================================================================== #

def test_sequential_duplicate_close_same_stale_snapshot(tmp_path):
    """Two calls to close_position() with the SAME stale in-memory
    position dict (as would happen if two overlapping callers each read
    the position while it was still OPEN) must credit cash and record a
    SELL exactly ONCE, not twice."""
    store, cfg, pos = _entered(tmp_path)
    cash_after_entry = store.cash()

    out1 = paper.close_position(store, pos, exit_price=105.0,
                                exit_session=date(2026, 9, 22), config=cfg)
    out2 = paper.close_position(store, pos, exit_price=105.0,
                                exit_session=date(2026, 9, 22), config=cfg)

    fresh = V2Store(str(tmp_path / "v.db"))
    proceeds = pos["shares"] * 105.0
    assert fresh.cash() == pytest.approx(cash_after_entry + proceeds), (
        "cash was credited more than once for the same position close")
    assert [t["action"] for t in fresh.trades()] == ["BUY", "SELL"], (
        "a duplicate SELL trade record was appended")
    assert fresh.all_positions()[0]["status"] == "CLOSED"


def test_concurrent_duplicate_close_two_independent_connections(tmp_path):
    """Two INDEPENDENT V2Store connections (as two separate processes/
    threads would have), each holding its own stale snapshot of the same
    OPEN position, both call close_position() at the same time. SQLite's
    write lock serializes the two transactions, but that alone does not
    protect against duplicate economic effects unless the second call's
    own state-transition eligibility is actually checked."""
    store, cfg, pos = _entered(tmp_path)
    cash_after_entry = store.cash()
    path = str(tmp_path / "v.db")

    store_a = V2Store(path)
    store_b = V2Store(path)
    pos_a = store_a.all_positions()[0]
    pos_b = store_b.all_positions()[0]

    errors: list[BaseException] = []

    def _close(s, p):
        try:
            paper.close_position(s, p, exit_price=105.0,
                                 exit_session=date(2026, 9, 22), config=cfg)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=_close, args=(store_a, pos_a))
    t2 = threading.Thread(target=_close, args=(store_b, pos_b))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"unexpected exception(s) from concurrent close: {errors}"

    fresh = V2Store(path)
    proceeds = pos["shares"] * 105.0
    assert fresh.cash() == pytest.approx(cash_after_entry + proceeds), (
        "concurrent duplicate close credited cash more than once")
    assert [t["action"] for t in fresh.trades()] == ["BUY", "SELL"], (
        "concurrent duplicate close appended more than one SELL trade")
    assert fresh.all_positions()[0]["status"] == "CLOSED"


def test_duplicate_close_does_not_reset_cooldown_twice(tmp_path):
    store, cfg, pos = _entered(tmp_path)
    paper.close_position(store, pos, exit_price=105.0, exit_session=date(2026, 9, 22), config=cfg)
    cooldown_after_first = V2Store(str(tmp_path / "v.db")).cooldown_until("AAA")

    # a later, stale-snapshot duplicate close attempt with a DIFFERENT
    # (later) exit_session must not silently move the cooldown forward --
    # the second call is not a genuine settlement at all.
    paper.close_position(store, pos, exit_price=105.0, exit_session=date(2026, 9, 24), config=cfg)
    fresh = V2Store(str(tmp_path / "v.db"))
    assert fresh.cooldown_until("AAA") == cooldown_after_first, (
        "a duplicate close call moved the re-entry cooldown forward")


def test_close_position_returns_a_no_op_outcome_for_an_already_closed_position(tmp_path):
    """The caller must be able to distinguish "I actually settled this"
    from "this was already settled" so it never generates a second exit
    notification for the same economic event."""
    store, cfg, pos = _entered(tmp_path)
    out1 = paper.close_position(store, pos, exit_price=105.0,
                                exit_session=date(2026, 9, 22), config=cfg)
    out2 = paper.close_position(store, pos, exit_price=105.0,
                                exit_session=date(2026, 9, 22), config=cfg)
    assert out1.settled is True
    assert out2.settled is False


def test_close_position_failure_midway_rolls_back_completely(tmp_path, monkeypatch):
    """Reaffirms the existing atomicity guarantee (this project's own
    test_task131_atomic_transactions.py) specifically for this task's
    evidence bundle: a crash between the state transition and the
    trade-record write leaves nothing committed."""
    store, cfg, pos = _entered(tmp_path)
    cash_before = store.cash()

    def _boom(*a, **k):
        raise RuntimeError("simulated crash mid-settlement")
    monkeypatch.setattr(store, "append_trade", _boom)

    with pytest.raises(RuntimeError):
        paper.close_position(store, pos, exit_price=105.0, exit_session=date(2026, 9, 22), config=cfg)

    fresh = V2Store(str(tmp_path / "v.db"))
    assert fresh.all_positions()[0]["status"] == "OPEN", "position was left CLOSED despite the failure"
    assert fresh.cash() == cash_before, "cash was credited despite the failure"
    assert [t["action"] for t in fresh.trades()] == ["BUY"], "a partial SELL trade record survived"
    assert fresh.cooldown_until("AAA") is None, "cooldown was set despite the failure"


# ===================================================================== #
# B. Unresolved obligations
# ===================================================================== #

def test_unresolved_position_retains_one_occupied_slot(tmp_path):
    store, cfg, pos = _entered(tmp_path)
    store.mark_exit_unresolved(pos["position_id"], detail="no bar found")
    assert store.n_open() == 1, (
        "an EXIT_UNRESOLVED position must still occupy one capacity slot")


def test_unresolved_position_retains_its_invested_cost_on_the_row(tmp_path):
    store, cfg, pos = _entered(tmp_path)
    store.mark_exit_unresolved(pos["position_id"], detail="no bar found")
    row = store.all_positions()[0]
    assert row["status"] == "EXIT_UNRESOLVED"
    assert row["position_cost"] == pos["position_cost"]


def test_mark_unresolved_credits_no_proceeds(tmp_path):
    store, cfg, pos = _entered(tmp_path)
    cash_before = store.cash()
    store.mark_exit_unresolved(pos["position_id"], detail="no bar found")
    assert store.cash() == cash_before, (
        "marking a position EXIT_UNRESOLVED must never credit a fabricated sale")


def test_unresolved_position_blocks_a_second_open_in_the_same_symbol(tmp_path):
    store, cfg, pos = _entered(tmp_path, symbol="AAA", episode_id="ep1")
    store.mark_exit_unresolved(pos["position_id"], detail="no bar found")

    outcome = paper.enter_position(store, _decision(episode_id="ep2", symbol="AAA"),
                                   entry_price=50.0, entry_session=date(2026, 9, 9), config=cfg)
    assert outcome.entered is False, (
        "an OPEN-only symbol lookup silently permitted a second position "
        "in a symbol that already has an unresolved obligation"
    )
    assert outcome.reason == "SYMBOL_ALREADY_OPEN"


def test_normal_open_still_permits_entry_after_a_genuine_close(tmp_path):
    """Sanity check: the fix must not block a legitimate re-entry after
    an ordinary (non-unresolved) close and cooldown elapses."""
    store, cfg, pos = _entered(tmp_path, symbol="AAA", episode_id="ep1")
    paper.close_position(store, pos, exit_price=105.0, exit_session=date(2026, 9, 22), config=cfg)
    # well past the frozen 5-session cooldown
    outcome = paper.enter_position(store, _decision(episode_id="ep2", symbol="AAA"),
                                   entry_price=50.0, entry_session=date(2026, 10, 15), config=cfg)
    assert outcome.entered is True, outcome.reason


def test_unresolved_position_never_produces_complete_cash_only_equity(tmp_path):
    from talonx_ops import paper_performance

    store, cfg, pos = _entered(tmp_path)
    store.mark_exit_unresolved(pos["position_id"], detail="no bar found")

    snap = paper_performance._v2_snapshot(
        Path(store.path), now=datetime(2026, 9, 22, tzinfo=timezone.utc),
        session_date="2026-09-22", price_source_db=None)

    assert snap["equity"]["status"] != "COMPLETE", (
        "equity was reported COMPLETE while an EXIT_UNRESOLVED position's "
        "value is entirely unknown"
    )


def test_reconciliation_does_not_fabricate_a_cash_loss_for_unresolved(tmp_path, monkeypatch):
    import talonx_ops.prospective.close as close_mod

    store, cfg, pos = _entered(tmp_path, cash=300_000.0)
    store.mark_exit_unresolved(pos["position_id"], detail="no bar found")

    monkeypatch.setattr(close_mod, "V2_DB_PATH", str(tmp_path / "v.db"))
    monkeypatch.setattr(close_mod, "CAMPAIGN_STARTING_CASH", 300_000.0)

    rec, asserts, findings = close_mod._v2_reconcile()
    assert asserts["cash_plus_open_cost_reconciles"] == "PASS", (
        f"reconciliation fabricated a mismatch purely because the "
        f"EXIT_UNRESOLVED position's cost was omitted: {findings}"
    )


def test_restart_preserves_unresolved_capacity_and_symbol_block(tmp_path):
    store, cfg, pos = _entered(tmp_path)
    store.mark_exit_unresolved(pos["position_id"], detail="no bar found")

    # simulate a restart: a brand-new V2Store instance against the same file
    restarted = V2Store(str(tmp_path / "v.db"))
    assert restarted.n_open() == 1
    outcome = paper.enter_position(restarted, _decision(episode_id="ep2", symbol="AAA"),
                                   entry_price=50.0, entry_session=date(2026, 9, 9), config=cfg)
    assert outcome.entered is False
    assert outcome.reason == "SYMBOL_ALREADY_OPEN"


def test_normal_open_and_closed_counts_unaffected_by_the_fix(tmp_path):
    """Sanity check across OPEN and CLOSED in one ledger (EXIT_UNRESOLVED
    is covered separately above)."""
    store, cfg, pos1 = _entered(tmp_path, symbol="AAA", episode_id="ep1")
    paper.enter_position(store, _decision(episode_id="ep2", symbol="BBB"),
                         entry_price=50.0, entry_session=date(2026, 9, 8), config=cfg)
    pos2 = [p for p in store.all_positions() if p["symbol"] == "BBB"][0]

    paper.close_position(store, pos2, exit_price=55.0, exit_session=date(2026, 9, 22), config=cfg)

    fresh = V2Store(str(tmp_path / "v.db"))
    statuses = sorted(p["status"] for p in fresh.all_positions())
    assert statuses == ["CLOSED", "OPEN"]
    assert fresh.n_open() == 1
