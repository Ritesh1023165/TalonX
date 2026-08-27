"""Task 78I Stage 1C -- status projection tests. build_decision_status is a
PURE function of on-disk ledger state -- every test here proves rebuilding
it after a "restart" (fresh read) and after late/duplicate events produces
the correct, non-regressed result. TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE."""
from __future__ import annotations

import json

from talonx_piv.observability import build_decision_status


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_unknown_decision_id_reports_not_found(tmp_path):
    result = build_decision_status(tmp_path, "nonexistent")
    assert result == {"decision_id": "nonexistent", "found": False}


def test_hold_decision_execution_status_not_attempted_by_design(tmp_path):
    _write(tmp_path / "decision_ledger.json", {
        "d1": {"recommendation": "HOLD", "decision_execution_status": "NO_ACTION"},
    })
    status = build_decision_status(tmp_path, "d1")
    assert status["execution_status"] == "NOT_ATTEMPTED_BY_DESIGN"
    assert status["notification_status"] == "NOT_APPLICABLE"
    assert status["shadow_status"] == "NOT_APPLICABLE"


def test_eligible_buy_with_no_persisted_intent_is_honestly_unknown(tmp_path):
    _write(tmp_path / "decision_ledger.json", {
        "d1": {"recommendation": "BUY", "decision_execution_status": "ENTRY_ELIGIBLE"},
    })
    status = build_decision_status(tmp_path, "d1")
    assert status["execution_status"] == "ATTEMPTED_OUTCOME_UNKNOWN_NO_PERSISTED_INTENT"


def test_eligible_buy_with_filled_order_reports_filled(tmp_path):
    _write(tmp_path / "decision_ledger.json", {
        "d1": {"recommendation": "BUY", "decision_execution_status": "ENTRY_ELIGIBLE"},
    })
    _write(tmp_path / "lifecycle_state.json", {
        "intents": {"intent1": {"decision_id": "d1", "status": "SUBMITTED"}},
        "orders": {"order1": {"intent_id": "intent1", "status": "filled"}},
    })
    status = build_decision_status(tmp_path, "d1")
    assert status["execution_status"] == "FILLED"


def test_eligible_buy_with_unconfirmed_timeout_order_reports_unconfirmed(tmp_path):
    _write(tmp_path / "decision_ledger.json", {
        "d1": {"recommendation": "BUY", "decision_execution_status": "ENTRY_ELIGIBLE"},
    })
    _write(tmp_path / "lifecycle_state.json", {
        "intents": {"intent1": {"decision_id": "d1", "status": "SUBMITTED"}},
        "orders": {"order1": {"intent_id": "intent1", "status": "UNCONFIRMED_TIMEOUT"}},
    })
    status = build_decision_status(tmp_path, "d1")
    assert status["execution_status"] == "UNCONFIRMED"


def test_rejected_intent_reports_rejected(tmp_path):
    _write(tmp_path / "decision_ledger.json", {
        "d1": {"recommendation": "BUY", "decision_execution_status": "ENTRY_ELIGIBLE"},
    })
    _write(tmp_path / "lifecycle_state.json", {
        "intents": {"intent1": {"decision_id": "d1", "status": "REJECTED"}},
        "orders": {},
    })
    status = build_decision_status(tmp_path, "d1")
    assert status["execution_status"] == "REJECTED"


def test_notification_and_shadow_status_join_by_decision_id(tmp_path):
    _write(tmp_path / "decision_ledger.json", {
        "d1": {"recommendation": "BUY", "decision_execution_status": "ENTRY_ELIGIBLE"},
    })
    _write(tmp_path / "notification_outbox.json", {"n1": {"decision_id": "d1", "status": "SENT"}})
    _write(tmp_path / "shadow_ledger.json", {"s1": {"decision_id": "d1", "status": "OPEN"}})
    status = build_decision_status(tmp_path, "d1")
    assert status["notification_status"] == "SENT"
    assert status["shadow_status"] == "OPEN"


def test_late_event_updates_status_without_regression(tmp_path):
    """Simulates a late-arriving fill: the projection built BEFORE the fill
    shows PENDING; rebuilt AFTER the fill is persisted, it correctly shows
    FILLED -- never stuck at a stale PENDING, and never regresses backward
    on a subsequent rebuild of the SAME final state."""
    _write(tmp_path / "decision_ledger.json", {
        "d1": {"recommendation": "BUY", "decision_execution_status": "ENTRY_ELIGIBLE"},
    })
    _write(tmp_path / "lifecycle_state.json", {
        "intents": {"intent1": {"decision_id": "d1", "status": "SUBMITTED"}},
        "orders": {"order1": {"intent_id": "intent1", "status": "accepted"}},
    })
    before = build_decision_status(tmp_path, "d1")
    assert before["execution_status"] == "PENDING"

    _write(tmp_path / "lifecycle_state.json", {
        "intents": {"intent1": {"decision_id": "d1", "status": "SUBMITTED"}},
        "orders": {"order1": {"intent_id": "intent1", "status": "filled"}},
    })
    after = build_decision_status(tmp_path, "d1")
    assert after["execution_status"] == "FILLED"

    rebuilt_again = build_decision_status(tmp_path, "d1")
    assert rebuilt_again == after  # idempotent re-read, no regression


def test_rebuild_after_restart_produces_identical_result(tmp_path):
    _write(tmp_path / "decision_ledger.json", {
        "d1": {"recommendation": "SELL_TO_CLOSE", "decision_execution_status": "EXIT_ELIGIBLE"},
    })
    _write(tmp_path / "lifecycle_state.json", {
        "intents": {"intent1": {"decision_id": "d1", "status": "SUBMITTED"}},
        "orders": {"order1": {"intent_id": "intent1", "status": "filled"}},
    })
    first = build_decision_status(tmp_path, "d1")
    second = build_decision_status(tmp_path, "d1")  # a fresh call, simulating a restarted process re-reading the same files
    assert first == second
