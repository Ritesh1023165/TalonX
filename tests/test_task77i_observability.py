"""Task 77I Stage 4 -- observability.build_integrated_projection unit
tests. TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE (all ledger content here is
synthetic, written directly to isolated tmp_path files)."""
from __future__ import annotations

import json

from talonx_piv.observability import build_integrated_projection


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_empty_state_dir_yields_all_zero_counts_never_an_error(tmp_path):
    projection = build_integrated_projection(tmp_path)
    assert projection["decisions"]["total"] == 0
    assert projection["notifications"]["total"] == 0
    assert projection["shadow"]["total"] == 0
    assert projection["paper_orders"]["total"] == 0


def test_counters_reconcile_to_their_own_ledger(tmp_path):
    _write(tmp_path / "session_identity.json", {"session_id": "s1", "trading_date_et": "2026-08-27"})
    _write(tmp_path / "decision_ledger.json", {
        "d1": {"session_id": "s1", "recommendation": "BUY", "reason_codes": [], "decision_execution_status": "ENTRY_ELIGIBLE"},
        "d2": {"session_id": "s1", "recommendation": "NO_TRADE", "reason_codes": ["STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION"], "decision_execution_status": "NO_ACTION"},
        "d3": {"session_id": "OTHER_SESSION", "recommendation": "BUY", "reason_codes": [], "decision_execution_status": "ENTRY_ELIGIBLE"},
    })
    _write(tmp_path / "notification_outbox.json", {
        "n1": {"decision_id": "d1", "status": "SENT"},
        "n2": {"decision_id": "d2", "status": "PENDING"},
        "n3": {"decision_id": "d3", "status": "SENT"},  # belongs to a DIFFERENT session -- must be excluded
    })
    _write(tmp_path / "shadow_ledger.json", {
        "sh1": {"decision_id": "d1", "status": "OPEN"},
        "sh2": {"decision_id": "d3", "status": "CLOSED"},  # different session -- excluded
    })
    projection = build_integrated_projection(tmp_path)
    assert projection["decisions"]["total"] == 2  # d3 excluded (different session)
    assert projection["decisions"]["observational_watch_count"] == 1
    assert projection["decisions"]["actionable_approved_count"] == 1
    assert projection["notifications"]["total"] == 2  # n3 excluded
    assert projection["notifications"]["sent"] == 1
    assert projection["notifications"]["pending"] == 1
    assert projection["shadow"]["total"] == 1  # sh2 excluded
    assert projection["shadow"]["open"] == 1


def test_historical_probe_records_do_not_leak_into_current_session(tmp_path):
    _write(tmp_path / "session_identity.json", {"session_id": "today", "trading_date_et": "2026-08-27"})
    _write(tmp_path / "decision_ledger.json", {
        "old1": {"session_id": "yesterday", "recommendation": "BUY", "reason_codes": [], "decision_execution_status": "ENTRY_ELIGIBLE"},
    })
    projection = build_integrated_projection(tmp_path, session_id="today")
    assert projection["decisions"]["total"] == 0


def test_paper_order_status_buckets(tmp_path):
    _write(tmp_path / "lifecycle_state.json", {"orders": {
        "o1": {"status": "SUBMITTED"}, "o2": {"status": "filled"},
        "o3": {"status": "rejected"}, "o4": {"status": "UNCONFIRMED_TIMEOUT"},
    }})
    projection = build_integrated_projection(tmp_path)
    assert projection["paper_orders"]["submitted"] == 1
    assert projection["paper_orders"]["filled"] == 1
    assert projection["paper_orders"]["rejected"] == 1
    assert projection["paper_orders"]["unknown"] == 1


def test_explicit_session_scope_overrides_identity_file(tmp_path):
    _write(tmp_path / "session_identity.json", {"session_id": "file-session"})
    _write(tmp_path / "decision_ledger.json", {"d1": {"session_id": "explicit-session", "recommendation": "HOLD", "reason_codes": [], "decision_execution_status": "NO_ACTION"}})
    projection = build_integrated_projection(tmp_path, session_id="explicit-session")
    assert projection["scope"]["session_id"] == "explicit-session"
    assert projection["decisions"]["total"] == 1
