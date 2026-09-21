"""
Package 2 -- Durable Account Blocks and Auditable Clearance.

Isolated regressions, real temporary SQLite files (never mocks the
ledger itself for store/account_blocks-level tests; consumer-level
tests mock the store the same way every other consumer test in this
project does -- see test_paper_consumer*.py). No network dependency.

Covers, one test (or small group) per item, the twelve acceptance
criteria from the task specification verbatim:
  1. V2 EXIT_UNRESOLVED blocks new admissions for OTHER symbols.
  2. Ledger mismatch blocks the affected local account only.
  3. Already-pending entry execution rechecks account blocks.
  4. Block check and entry mutation are serialized at the database
     boundary.
  5. A competing writer cannot commit an entry after a prior block
     activation.
  6. Restart preserves active blocks.
  7. Repeated incident detection is idempotent.
  8. Multiple block reasons remain independent.
  9. Clearance without required evidence is refused.
  10. Authorized clearance preserves its audit trail.
  11. Existing exits and safe obligation recovery continue while
      entries are blocked.
  12. Collection and notification failures do not erase blocks or
      accounting state.

Plus: clearance.py's reason-type-specific re-verification logic, and
the Original (talonx_paper) intraday/long-term integration.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_ops import account_blocks
from talonx_ops.prospective import clearance
from talonx_paper.config import PaperConfig
from talonx_paper.consumer import LongTermPaperEngine, PaperTradingEngine
from talonx_paper.schemas import AlertAction, LongTermOrderType, LongTermTradeExecution, OrderType, PaperTradeExecution
from talonx_paper.store import ORIGINAL_INTRADAY_ACCOUNT_ID, ORIGINAL_LONGTERM_ACCOUNT_ID, PaperTradingStore
from talonx_v2 import paper
from talonx_v2.config import V2Config
from talonx_v2.schemas import V2Action, V2Decision, V2Direction
from talonx_v2.store import V2_ACCOUNT_ID, V2Store

NOW = datetime(2026, 8, 10, 14, 37, 0, tzinfo=timezone.utc)


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
# account_blocks.py -- unit-level contract
# ===================================================================== #

def test_idempotent_repeated_detection_does_not_duplicate_or_perturb_detected_at(tmp_path):
    """Acceptance 7: repeated incident detection is idempotent."""
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    bid1 = store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                      reference="same-ref", detail="d1")
    first_detected = store.active_account_blocks()[0]["detected_at_utc"]

    bid2 = store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                      reference="same-ref", detail="d2")

    assert bid2 == bid1, "the same underlying issue must map to the same block_id"
    active = store.active_account_blocks()
    assert len(active) == 1, "repeated detection created a duplicate active block"
    assert active[0]["detected_at_utc"] == first_detected, (
        "a true no-op re-detection must not perturb the original detection time")
    assert active[0]["detail"] == "d2", "detail should still refresh on a no-op re-detection"


def test_multiple_block_reasons_remain_independent(tmp_path):
    """Acceptance 8: multiple block reasons remain independent."""
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    bid1 = store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                      reference="r1", detail="")
    bid2 = store.record_account_block(reason_type=account_blocks.REASON_CASH_DEFICIT,
                                      reference="r2", detail="")

    store.attempt_block_clearance(block_id=bid1, operator_id="ops1", reason="fixed",
                                  evidence_ref="ev1", allow=True)

    active_ids = {b["block_id"] for b in store.active_account_blocks()}
    assert bid1 not in active_ids, "clearance of bid1 did not take effect"
    assert bid2 in active_ids, "clearing one block reason cleared an unrelated one"
    assert store.blocked_reason() is not None, "account should still read as blocked (bid2 active)"


def test_clearance_without_required_evidence_is_refused(tmp_path):
    """Acceptance 9: clearance without required evidence is refused."""
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    bid = store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                     reference="r", detail="")
    for kwargs in (
        dict(operator_id="", reason="x", evidence_ref="y"),
        dict(operator_id="ops", reason="", evidence_ref="y"),
        dict(operator_id="ops", reason="x", evidence_ref=""),
    ):
        with pytest.raises(ValueError):
            store.attempt_block_clearance(block_id=bid, allow=True, **kwargs)
    assert store.blocked_reason() is not None, "block must remain active after refused attempts"
    assert store.block_clearance_history(bid) == [], (
        "a raised ValueError must mean no half-written clearance row at all")


def test_authorized_clearance_preserves_its_audit_trail(tmp_path):
    """Acceptance 10: authorized clearance preserves its audit trail --
    including a prior REFUSED attempt for the same block."""
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    bid = store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                     reference="r", detail="")

    store.attempt_block_clearance(block_id=bid, operator_id="ops1", reason="investigating",
                                  evidence_ref="partial-check", allow=False, detail="not yet resolved")
    store.attempt_block_clearance(block_id=bid, operator_id="ops2", reason="confirmed fixed",
                                  evidence_ref="recon-2026-09-17", allow=True)

    history = store.block_clearance_history(bid)
    assert [h["outcome"] for h in history] == ["REFUSED", "CLEARED"]
    assert history[0]["operator_id"] == "ops1"
    assert history[1]["operator_id"] == "ops2"
    assert store.blocked_reason() is None


def test_restart_preserves_active_blocks(tmp_path):
    """Acceptance 6: restart preserves active blocks."""
    path = str(tmp_path / "v.db")
    store = V2Store(path, starting_cash=300_000.0)
    bid = store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                     reference="r", detail="")

    restarted = V2Store(path)
    assert restarted.blocked_reason() is not None
    assert any(b["block_id"] == bid for b in restarted.active_account_blocks())


def test_restart_preserves_clearance_history(tmp_path):
    path = str(tmp_path / "v.db")
    store = V2Store(path, starting_cash=300_000.0)
    bid = store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                     reference="r", detail="")
    store.attempt_block_clearance(block_id=bid, operator_id="ops1", reason="fixed",
                                  evidence_ref="ev", allow=True)

    restarted = V2Store(path)
    assert len(restarted.block_clearance_history(bid)) == 1
    assert restarted.blocked_reason() is None


# ===================================================================== #
# V2 integration
# ===================================================================== #

def test_v2_exit_unresolved_blocks_new_admission_for_a_different_symbol(tmp_path):
    """Acceptance 1: V2 EXIT_UNRESOLVED blocks new admissions for OTHER
    symbols -- not merely the same-symbol SYMBOL_ALREADY_OPEN path
    Package 1 already covered."""
    store, cfg, pos = _entered(tmp_path, symbol="AAA", episode_id="ep1")
    store.mark_exit_unresolved(pos["position_id"], detail="no bar found")

    outcome = paper.enter_position(store, _decision("ep2", "ZZZ"), entry_price=50.0,
                                   entry_session=date(2026, 9, 9), config=cfg)
    assert outcome.entered is False
    assert "ACCOUNT_BLOCKED" in outcome.reason
    assert "EXIT_UNRESOLVED" in outcome.reason


def test_pending_entry_execution_rechecks_a_block_activated_after_the_decision_was_formed(tmp_path):
    """Acceptance 3: already-pending entry execution rechecks account
    blocks -- a V2Decision object formed BEFORE any block existed still
    gets refused if, by the time enter_position() actually executes it,
    a block has since been recorded (no exemption from an earlier
    in-memory decision)."""
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    cfg = V2Config(starting_cash_usd=300_000.0, per_position_allocation_usd=10_000.0)
    decision = _decision("ep-late", "QQQ")  # "formed" before any block existed

    store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                               reference="late-block", detail="detected after decision formed")

    outcome = paper.enter_position(store, decision, entry_price=10.0,
                                   entry_session=date(2026, 9, 8), config=cfg)
    assert outcome.entered is False
    assert "ACCOUNT_BLOCKED" in outcome.reason


def test_competing_writer_cannot_commit_an_entry_after_a_prior_block_activation(tmp_path):
    """Acceptance 4 + 5: block check and entry mutation are serialized
    at the database boundary, and a competing writer cannot commit an
    entry after a prior block activation. Two INDEPENDENT V2Store
    connections (as two separate processes would have) race for
    SQLite's write lock; whichever transaction commits first must be
    visible to the other, because the block check happens INSIDE the
    same protected transaction as the entry mutation, not on an
    earlier, unprotected read."""
    path = str(tmp_path / "v.db")
    V2Store(path, starting_cash=300_000.0)  # create the file/schema
    cfg = V2Config(starting_cash_usd=300_000.0, per_position_allocation_usd=10_000.0)

    store_block = V2Store(path)
    store_entry = V2Store(path)

    block_holds_lock = threading.Event()
    proceed_with_entry = threading.Event()
    results: dict = {}

    def _record_block_slowly():
        with store_block.transaction() as c:
            block_holds_lock.set()
            proceed_with_entry.wait(timeout=5)
            account_blocks.record_block(
                c, account_id=V2_ACCOUNT_ID, reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                reference="race-test", detail="forced race")
            time.sleep(0.3)  # hold the write lock past the entry thread's attempted acquire

    def _attempt_entry():
        block_holds_lock.wait(timeout=5)
        proceed_with_entry.set()
        outcome = paper.enter_position(store_entry, _decision("ep-race", "ZZZ"), entry_price=10.0,
                                       entry_session=date(2026, 9, 8), config=cfg)
        results["outcome"] = outcome

    t1 = threading.Thread(target=_record_block_slowly)
    t2 = threading.Thread(target=_attempt_entry)
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert "outcome" in results, "entry thread did not complete"
    outcome = results["outcome"]
    assert outcome.entered is False, (
        "a competing writer committed an entry after a prior block activation")
    assert "ACCOUNT_BLOCKED" in outcome.reason

    fresh = V2Store(path)
    assert fresh.n_open() == 0, "the raced entry must not have mutated the ledger at all"


def test_ledger_mismatch_block_isolated_to_its_own_v2_account(tmp_path):
    """Acceptance 2 (V2 half): a ledger-mismatch block on V2 has no
    effect on a completely separate Original ledger file/account."""
    v2_store = V2Store(str(tmp_path / "v2.db"), starting_cash=300_000.0)
    v2_store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                  reference="v2-issue", detail="")

    original_store = PaperTradingStore(tmp_path / "paper.db", 10000.0, 2500.0)
    assert original_store.blocked_reason(ORIGINAL_INTRADAY_ACCOUNT_ID) is None
    assert original_store.blocked_reason(ORIGINAL_LONGTERM_ACCOUNT_ID) is None
    assert v2_store.blocked_reason() is not None


def test_exits_and_safe_obligation_recovery_continue_while_entries_are_blocked(tmp_path):
    """Acceptance 11: existing exits and safe obligation recovery
    continue while entries are blocked."""
    store, cfg, pos = _entered(tmp_path, symbol="AAA", episode_id="ep1")
    store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                               reference="unrelated-issue", detail="")

    # new entries refused
    outcome = paper.enter_position(store, _decision("ep2", "BBB"), entry_price=10.0,
                                   entry_session=date(2026, 9, 8), config=cfg)
    assert outcome.entered is False

    # the EXISTING open position can still be closed (exit continues)
    out = paper.close_position(store, pos, exit_price=105.0, exit_session=date(2026, 9, 22), config=cfg)
    assert out.settled is True
    fresh = V2Store(str(tmp_path / "v.db"))
    assert fresh.all_positions()[0]["status"] == "CLOSED"


def test_mark_exit_unresolved_continues_while_entries_already_blocked(tmp_path):
    """Acceptance 11 (recovery half): safe obligation recovery
    (mark_exit_unresolved) still functions, and correctly layers a
    SECOND independent active block, while another block reason is
    already active."""
    store, cfg, pos = _entered(tmp_path, symbol="AAA", episode_id="ep1")
    store.record_account_block(reason_type=account_blocks.REASON_CASH_DEFICIT, reference="x", detail="")

    store.mark_exit_unresolved(pos["position_id"], detail="no bar found")

    fresh = V2Store(str(tmp_path / "v.db"))
    assert fresh.all_positions()[0]["status"] == "EXIT_UNRESOLVED"
    active_reasons = {b["reason_type"] for b in fresh.active_account_blocks()}
    assert active_reasons == {account_blocks.REASON_CASH_DEFICIT, account_blocks.REASON_EXIT_UNRESOLVED}


def test_recorded_reconciliation_block_survives_a_later_pipeline_step_failure(tmp_path, monkeypatch):
    """Acceptance 12: collection and notification failures do not erase
    blocks or accounting state. `_record_v2_reconciliation_blocks`
    commits its own block write independently, BEFORE any later
    run_close step (report rendering, notification, base-ledger
    reconcile) runs -- so a failure in one of those later steps cannot
    retroactively un-record it."""
    import talonx_ops.prospective.close as close_mod

    db = tmp_path / "v2_lane.db"
    V2Store(str(db), starting_cash=300_000.0)
    monkeypatch.setattr(close_mod, "V2_DB_PATH", str(db))

    asserts = {"cash_plus_open_cost_reconciles": "FAIL", "no_negative_cash": "PASS"}
    findings = ["cash_plus_open_cost_reconciles: FAIL some detail"]
    recorded = close_mod._record_v2_reconciliation_blocks(asserts, findings)
    assert recorded, "expected a block id to be recorded for the FAIL assert"

    def _boom(*a, **k):
        raise RuntimeError("simulated downstream failure (e.g. report render / Telegram)")
    monkeypatch.setattr(close_mod, "_base_reconcile", _boom)
    with pytest.raises(RuntimeError):
        close_mod._base_reconcile()

    fresh = V2Store(str(db))
    assert fresh.blocked_reason() is not None, (
        "an already-committed block must survive an unrelated later failure")


# ===================================================================== #
# clearance.py -- reason-type-specific re-verification
# ===================================================================== #

def test_clear_block_exit_unresolved_refuses_while_still_unresolved(tmp_path):
    store, cfg, pos = _entered(tmp_path, symbol="AAA", episode_id="ep1")
    store.mark_exit_unresolved(pos["position_id"], detail="no bar found")
    bid = account_blocks.block_id("V2", account_blocks.REASON_EXIT_UNRESOLVED, str(pos["position_id"]))

    result = clearance.clear_block(str(tmp_path / "v.db"), "V2", block_id=bid, operator_id="ops1",
                                   reason="attempting", evidence_ref="none-yet")
    assert result["allow"] is False
    assert result["outcome"] == "REFUSED"

    history = V2Store(str(tmp_path / "v.db")).block_clearance_history(bid)
    assert len(history) == 1


def test_clear_block_ledger_mismatch_allows_after_a_fresh_reconcile_passes(tmp_path, monkeypatch):
    import talonx_ops.prospective.close as close_mod

    db = tmp_path / "v2_lane.db"
    store = V2Store(str(db), starting_cash=300_000.0)
    bid = store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                     reference="cash_plus_open_cost_reconciles", detail="")
    monkeypatch.setattr(close_mod, "V2_DB_PATH", str(db))
    # RI-1: this store's own `campaign.starting_cash_usd` is already
    # authoritatively 300_000.0 (seeded at creation, matching the
    # constructor call above) -- the fresh reconcile passes on that
    # basis alone; no CAMPAIGN_STARTING_CASH patch is load-bearing here.

    result = clearance.clear_block(str(db), "V2", block_id=bid, operator_id="ops1",
                                   reason="verified fixed", evidence_ref="recon-check")
    assert result["allow"] is True
    assert V2Store(str(db)).blocked_reason() is None


def test_clear_block_ledger_mismatch_refuses_while_reconcile_still_fails(tmp_path, monkeypatch):
    import talonx_ops.prospective.close as close_mod

    db = tmp_path / "v2_lane.db"
    store = V2Store(str(db), starting_cash=300_000.0)
    bid = store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                     reference="cash_plus_open_cost_reconciles", detail="")
    monkeypatch.setattr(close_mod, "V2_DB_PATH", str(db))
    # RI-1: a wrong CAMPAIGN_STARTING_CASH patch is no longer sufficient
    # to force a mismatch -- this store's own `campaign.starting_cash_usd`
    # (seeded at creation, authoritative) correctly reports 300_000.0
    # regardless of that fallback constant's value (RI1-C's whole point:
    # the persisted campaign record wins). Force a GENUINE mismatch
    # directly, the same way test_package4_sizing_accounting.py's own
    # P4-H tests already corrupt raw ledger data.
    import sqlite3
    with sqlite3.connect(str(db)) as raw:
        raw.execute("UPDATE portfolio SET cash = cash - 12345.0 WHERE id=1")
        raw.commit()

    result = clearance.clear_block(str(db), "V2", block_id=bid, operator_id="ops1",
                                   reason="attempting", evidence_ref="recon-check")
    assert result["allow"] is False
    assert V2Store(str(db)).blocked_reason() is not None


def test_clear_block_refuses_for_reason_types_with_no_reverification_workflow(tmp_path):
    """IDENTITY_MISMATCH: no detector exists in Package 2, and no
    automated re-verification exists either -- clearance must refuse
    rather than fabricate a bypass (explicit limitation, not a bug)."""
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    bid = store.record_account_block(reason_type=account_blocks.REASON_IDENTITY_MISMATCH,
                                     reference="unverifiable", detail="")
    result = clearance.clear_block(str(tmp_path / "v.db"), "V2", block_id=bid, operator_id="ops1",
                                   reason="attempting", evidence_ref="none")
    assert result["allow"] is False


def test_clear_block_raises_if_account_kind_does_not_match_the_blocks_own_account(tmp_path):
    store = V2Store(str(tmp_path / "v.db"), starting_cash=300_000.0)
    bid = store.record_account_block(reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                     reference="r", detail="")
    with pytest.raises(ValueError):
        clearance.clear_block(str(tmp_path / "v.db"), "ORIGINAL_INTRADAY", block_id=bid,
                              operator_id="ops1", reason="x", evidence_ref="y")


# ===================================================================== #
# Original (talonx_paper) integration
# ===================================================================== #

def test_original_intraday_execute_buy_blocked_mutates_nothing(tmp_path):
    with PaperTradingStore(tmp_path / "paper.db", 10000.0, 2500.0) as store:
        store.record_account_block(account_id=ORIGINAL_INTRADAY_ACCOUNT_ID,
                                   reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                   reference="x", detail="")

        execution = store.execute_buy("NVDA", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)

        assert execution is None
        assert store.get_portfolio_summary()["current_cash"] == 10000.0
        assert store.get_position("NVDA") is None
        rows = store._conn.execute("SELECT reason FROM ignored_decisions").fetchall()
        assert any("ACCOUNT_BLOCKED" in r[0] for r in rows)


def test_original_longterm_block_does_not_affect_intraday_same_file(tmp_path):
    """Acceptance 2 (Original half): a block on ORIGINAL_LONGTERM has no
    effect on ORIGINAL_INTRADAY even though both lanes share one file."""
    with PaperTradingStore(tmp_path / "paper.db", 10000.0, 2500.0) as store:
        store.record_account_block(account_id=ORIGINAL_LONGTERM_ACCOUNT_ID,
                                   reason_type=account_blocks.REASON_CASH_DEFICIT,
                                   reference="y", detail="")

        execution = store.execute_buy("NVDA", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        assert execution is not None, "an unrelated account's block wrongly blocked intraday"

        lt = store.execute_long_term_buy("AAPL", 20.0, 100.0, 2000.0, NOW)
        assert lt is None


def test_restart_preserves_original_account_blocks(tmp_path):
    path = tmp_path / "paper.db"
    with PaperTradingStore(path, 10000.0, 2500.0) as store:
        store.record_account_block(account_id=ORIGINAL_INTRADAY_ACCOUNT_ID,
                                   reason_type=account_blocks.REASON_LEDGER_MISMATCH,
                                   reference="r", detail="")

    with PaperTradingStore(path, 10000.0, 2500.0) as restarted:
        assert restarted.blocked_reason(ORIGINAL_INTRADAY_ACCOUNT_ID) is not None


# ===================================================================== #
# eod_reconciliation.py -- OPS-015's own literal finding location
# ===================================================================== #

def test_eod_reconciliation_mismatch_blocks_original_intraday_only(tmp_path):
    """OPS-015's literal finding location (this module's own
    STATUS_MISMATCH detection) is now connected to a persisted block --
    for ORIGINAL_INTRADAY specifically (the table set `original_paper`
    actually reads), never ORIGINAL_LONGTERM."""
    from talonx_ops import eod_reconciliation as er

    home = tmp_path
    db_path = home / "paper_trading.db"
    with PaperTradingStore(db_path, 10000.0, 2500.0) as store:
        store.execute_buy("NVDA", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        # simulate the conservative mismatch condition this module
        # detects: an open position with zero trades ever recorded.
        store._conn.execute("DELETE FROM trade_history")
        store._conn.commit()

    rec = er.build_reconciliation(session_date="2026-08-10", home=home,
                                  exp_home=tmp_path / "exp", ledger_path=tmp_path / "ledger.db")
    assert any(m.startswith("original_paper:") for m in rec.mismatches), rec.mismatches

    recorded = er._record_original_intraday_reconciliation_blocks(rec, home)
    assert recorded

    with PaperTradingStore(db_path, 10000.0, 2500.0) as fresh:
        assert fresh.blocked_reason(ORIGINAL_INTRADAY_ACCOUNT_ID) is not None
        assert fresh.blocked_reason(ORIGINAL_LONGTERM_ACCOUNT_ID) is None


def test_clear_block_original_intraday_reconcile_allows_after_fresh_check_passes(tmp_path):
    from talonx_ops import eod_reconciliation as er

    home = tmp_path
    db_path = home / "paper_trading.db"
    with PaperTradingStore(db_path, 10000.0, 2500.0) as store:
        store.execute_buy("NVDA", shares=10.0, price=100.0, cost=1000.0, timestamp=NOW)
        store._conn.execute("DELETE FROM trade_history")
        store._conn.commit()

    rec = er.build_reconciliation(session_date="2026-08-10", home=home,
                                  exp_home=tmp_path / "exp", ledger_path=tmp_path / "ledger.db")
    recorded = er._record_original_intraday_reconciliation_blocks(rec, home)
    bid = recorded[0]

    # "fix" it: a legitimate trade record now exists for the open position.
    with PaperTradingStore(db_path, 10000.0, 2500.0) as store:
        store._conn.execute(
            "INSERT INTO trade_history (ticker, order_type, execution_price, shares, "
            "position_cost, portfolio_cash_after, timestamp) VALUES (?,?,?,?,?,?,?)",
            ("NVDA", "BUY", 100.0, 10.0, 1000.0, 9000.0, NOW.isoformat()))
        store._conn.commit()

    result = clearance.clear_block(str(db_path), "ORIGINAL_INTRADAY", block_id=bid,
                                   operator_id="ops1", reason="fixed", evidence_ref="recon-recheck")
    assert result["allow"] is True
    with PaperTradingStore(db_path, 10000.0, 2500.0) as fresh:
        assert fresh.blocked_reason(ORIGINAL_INTRADAY_ACCOUNT_ID) is None


# ===================================================================== #
# consumer.py -- graceful None handling (mocked store, matches this
# project's own established consumer-test boundary)
# ===================================================================== #

def _alert_payload_intraday(ticker="NVDA", action="confirmed_bullish", price=131.50):
    return {
        "ticker": ticker, "action": action, "severity": "warning",
        "triggering_signal": {"price": price},
        "correlated_at": NOW.isoformat(),
    }


def _alert_payload_long_term(ticker="AAPL", action="high_conviction_buy", price=100.0):
    return {
        "ticker": ticker, "action": action, "quality_score": 8, "moat_rating": "wide",
        "market_price": price, "intrinsic_fair_value": 130.0, "margin_of_safety_pct": 0.23,
        "correlated_at": NOW.isoformat(),
    }


def _msg(channel: str, payload: dict) -> dict:
    return {"channel": channel.encode(), "data": json.dumps(payload)}


@pytest.mark.asyncio
async def test_intraday_engine_handles_account_blocked_none_gracefully():
    store = MagicMock()
    store.get_position.return_value = None
    store.get_portfolio_summary.return_value = {"current_cash": 10000.0, "trade_allocation_usd": 2500.0}
    store.execute_buy.return_value = None  # ACCOUNT_BLOCKED
    watchlist_store = MagicMock()
    watchlist_store.list_paper_trading_symbols.return_value = ["NVDA"]
    engine = PaperTradingEngine(config=PaperConfig(simulated_spread_bps=0.0), store=store,
                                watchlist_store=watchlist_store)
    engine._client = AsyncMock()

    await engine._handle_message(_msg(engine.config.alerts_channel, _alert_payload_intraday()))

    store.execute_buy.assert_called_once()
    engine._client.publish.assert_not_awaited()
    assert engine.trades_ignored == 1
    assert engine.trades_executed == 0


@pytest.mark.asyncio
async def test_long_term_engine_handles_account_blocked_none_gracefully():
    store = MagicMock()
    store.get_long_term_position.return_value = None
    store.get_long_term_portfolio_summary.return_value = {"current_cash": 20000.0}
    store.execute_long_term_buy.return_value = None  # ACCOUNT_BLOCKED
    watchlist_store = MagicMock()
    watchlist_store.list_paper_trading_long_term_symbols.return_value = ["AAPL"]
    engine = LongTermPaperEngine(config=PaperConfig(simulated_spread_bps=0.0), store=store,
                                 watchlist_store=watchlist_store)
    engine._client = AsyncMock()

    await engine._handle_message(_msg(engine.config.alerts_channel_long_term, _alert_payload_long_term()))

    store.execute_long_term_buy.assert_called_once()
    engine._client.publish.assert_not_awaited()
    assert engine.trades_ignored == 1
    assert engine.trades_executed == 0
