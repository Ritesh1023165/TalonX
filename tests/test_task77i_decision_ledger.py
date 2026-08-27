"""Task 77I Stage 2 -- DecisionLedger unit tests. TEST_FIXTURE_ONLY -- NOT
ALPHA EVIDENCE (all decisions here are synthetic fixtures)."""
from __future__ import annotations

from talonx_piv.decision_contract import (
    DataReadiness, Decision, ExecutionStatus, MarketView, Recommendation, StrategyApprovalStatus, decide,
)
from talonx_piv.decision_ledger import DecisionLedger


def _decision(**overrides) -> Decision:
    kwargs = dict(
        decision_id="d1", session_id="s1", trading_date_et="2026-08-27", ticker="AAPL",
        market_view=MarketView.BULLISH, has_open_long=False, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.APPROVED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=True,
    )
    kwargs.update(overrides)
    return decide(**kwargs)


def test_record_creates_a_full_record(tmp_path):
    ledger = DecisionLedger(tmp_path / "decisions.json")
    record = ledger.record(_decision(), event_id="e1", evidence_category="natural")
    assert record["decision_id"] == "d1"
    assert record["recommendation"] == "BUY"
    assert record["notification_status"] == "NOT_APPLICABLE"
    assert record["shadow_status"] == "NOT_APPLICABLE"
    assert record["execution_status"] == "NOT_APPLICABLE"


def test_record_is_idempotent_on_repeat_decision_id(tmp_path):
    ledger = DecisionLedger(tmp_path / "decisions.json")
    first = ledger.record(_decision(), event_id="e1", evidence_category="natural")
    ledger.update_status("d1", notification_status="SENT")
    second = ledger.record(_decision(), event_id="e2", evidence_category="natural")  # duplicate call
    assert second["notification_status"] == "SENT"  # unchanged by the second record() call
    assert second["event_id"] == "e1"  # original event_id preserved, not overwritten


def test_eligible_buy_remains_recorded_even_when_paper_entry_disabled(tmp_path):
    ledger = DecisionLedger(tmp_path / "decisions.json")
    decision = _decision(paper_entry_enabled=False)
    assert decision.recommendation == Recommendation.BUY
    assert decision.execution_status == ExecutionStatus.ENTRY_BLOCKED_PAPER_DISABLED
    record = ledger.record(decision, event_id="e1", evidence_category="natural")
    assert record["recommendation"] == "BUY"  # preserved, not downgraded


def test_persists_and_reloads_across_a_new_instance(tmp_path):
    path = tmp_path / "decisions.json"
    ledger1 = DecisionLedger(path)
    ledger1.record(_decision(), event_id="e1", evidence_category="natural")
    ledger2 = DecisionLedger(path)  # simulates a restart
    assert ledger2.get("d1") is not None


def test_none_path_is_in_memory_only_never_touches_disk(tmp_path):
    ledger = DecisionLedger(None)
    record = ledger.record(_decision(), event_id="e1", evidence_category="natural")
    assert record["decision_id"] == "d1"
    assert list(tmp_path.iterdir()) == []
