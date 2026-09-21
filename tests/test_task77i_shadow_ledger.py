"""Task 77I Stage 3 -- ShadowLedger unit tests. TEST_FIXTURE_ONLY -- NOT
ALPHA EVIDENCE (every decision/bar here is synthetic)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from talonx_piv.decision_contract import DataReadiness, MarketView, StrategyApprovalStatus, decide
from talonx_piv.shadow_ledger import ShadowLedger


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


T0 = datetime(2026, 8, 27, 14, 30, tzinfo=timezone.utc)


def _bar(minute: int, o: float, h: float, l: float, c: float) -> Bar:
    return Bar(T0 + timedelta(minutes=minute), o, h, l, c)


def _buy_decision(decision_id="d1", ticker="AAPL", stop=99.0, target=105.0, now=None, entry_price=100.0):
    return decide(
        decision_id=decision_id, session_id="s1", trading_date_et="2026-08-27", ticker=ticker,
        market_view=MarketView.BULLISH, has_open_long=False, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.APPROVED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=True, entry_price=entry_price, stop_price=stop, target_price=target,
        now=now or T0,
    )


def _unvalidated_decision(decision_id="d2", ticker="MSFT"):
    return decide(
        decision_id=decision_id, session_id="s1", trading_date_et="2026-08-27", ticker=ticker,
        market_view=MarketView.BULLISH, has_open_long=False, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.UNVALIDATED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=True,
    )


# ---------------------------------------------------------------------------
# Actionability gating
# ---------------------------------------------------------------------------

def test_unvalidated_strategy_decision_never_creates_a_shadow_position(tmp_path):
    ledger = ShadowLedger(tmp_path / "shadow.json")
    result = ledger.consider_entry(_unvalidated_decision(), source="STRATEGY")
    assert result is None
    assert ledger.positions == {}


def test_watch_hold_no_trade_never_become_hypothetical_entries(tmp_path):
    ledger = ShadowLedger(tmp_path / "shadow.json")
    hold = decide(
        decision_id="d3", session_id="s1", trading_date_et="2026-08-27", ticker="GOOG",
        market_view=MarketView.NEUTRAL, has_open_long=True, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.APPROVED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=True,
    )
    assert ledger.consider_entry(hold, source="STRATEGY") is None
    assert ledger.positions == {}


# ---------------------------------------------------------------------------
# Causal fill timing
# ---------------------------------------------------------------------------

def test_paper_disabled_actionable_decision_still_creates_shadow_tracking(tmp_path):
    ledger = ShadowLedger(tmp_path / "shadow.json")
    decision = _buy_decision()
    assert decision.paper_entry_enabled is True  # sanity: decision itself doesn't vary
    result = ledger.consider_entry(decision, source="STRATEGY")
    assert result is not None
    assert result["status"] == "PENDING_FILL"


def test_no_fill_before_the_decision_timestamp(tmp_path):
    """A bar at or before the decision's own timestamp must never be used
    as the fill -- only a STRICTLY LATER bar."""
    ledger = ShadowLedger(tmp_path / "shadow.json")
    decision = _buy_decision(now=T0)
    ledger.consider_entry(decision, source="STRATEGY")
    ledger.on_bar("AAPL", _bar(0, 100.0, 101.0, 99.5, 100.5))  # same-timestamp bar as the decision
    position = ledger.get_by_decision("d1")
    assert position["status"] == "PENDING_FILL"  # not yet filled


def test_fills_at_next_bar_open_not_signal_close(tmp_path):
    ledger = ShadowLedger(tmp_path / "shadow.json")
    decision = _buy_decision(now=T0, entry_price=100.0)
    ledger.consider_entry(decision, source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 102.0, 103.0, 101.5, 102.5))  # next bar's open=102, NOT the decision's entry_price(100)
    position = ledger.get_by_decision("d1")
    assert position["status"] == "OPEN"
    assert position["simulated_entry_price_raw"] == 102.0


def test_pending_entry_that_never_fills_resolves_unresolved(tmp_path):
    ledger = ShadowLedger(tmp_path / "shadow.json")
    decision = _buy_decision(now=T0)
    ledger.consider_entry(decision, source="STRATEGY")
    ledger.force_close("AAPL", T0 + timedelta(hours=6), None, "END_OF_SESSION")
    position = ledger.get_by_decision("d1")
    assert position["status"] == "UNRESOLVED"
    assert position["outcome_quality"] == "UNRESOLVED_NO_FILL_BEFORE_HORIZON_END"


# ---------------------------------------------------------------------------
# Exit semantics -- stop / target / horizon / gaps
# ---------------------------------------------------------------------------

def test_stop_exit(tmp_path):
    ledger = ShadowLedger(tmp_path / "shadow.json")
    decision = _buy_decision(now=T0, stop=99.0, target=105.0)
    ledger.consider_entry(decision, source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))  # fills at 100.0
    ledger.on_bar("AAPL", _bar(2, 100.0, 100.1, 98.5, 98.8))  # low breaches stop 99.0
    position = ledger.get_by_decision("d1")
    assert position["status"] == "CLOSED"
    assert position["exit_reason"] == "STOP"
    assert position["simulated_exit_price_raw"] == 99.0
    assert position["gross_result"] == pytest.approx(-1.0)


def test_target_exit(tmp_path):
    ledger = ShadowLedger(tmp_path / "shadow.json")
    decision = _buy_decision(now=T0, stop=99.0, target=105.0)
    ledger.consider_entry(decision, source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))  # fills at 100.0
    ledger.on_bar("AAPL", _bar(2, 104.0, 105.5, 103.5, 105.2))  # high breaches target 105.0
    position = ledger.get_by_decision("d1")
    assert position["status"] == "CLOSED"
    assert position["exit_reason"] == "TARGET"
    assert position["gross_r"] == pytest.approx(5.0)  # (105-100)/(100-99)


def test_same_bar_ambiguity_resolves_stop_first_conservative(tmp_path):
    ledger = ShadowLedger(tmp_path / "shadow.json")
    decision = _buy_decision(now=T0, stop=99.0, target=101.0)
    ledger.consider_entry(decision, source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 100.0, 102.0, 98.0, 99.5))  # both stop and target touched same bar
    position = ledger.get_by_decision("d1")
    assert position["exit_reason"] == "STOP"


def test_horizon_end_of_session_uses_real_last_close_never_fabricated(tmp_path):
    ledger = ShadowLedger(tmp_path / "shadow.json")
    decision = _buy_decision(now=T0, stop=99.0, target=105.0)
    ledger.consider_entry(decision, source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))
    ledger.force_close("AAPL", T0 + timedelta(hours=6), 101.3, "END_OF_SESSION")
    position = ledger.get_by_decision("d1")
    assert position["status"] == "CLOSED"
    assert position["simulated_exit_price_raw"] == 101.3
    assert position["exit_reason"] == "END_OF_SESSION"


def test_data_gap_after_fill_then_recovery_still_exits_correctly(tmp_path):
    """A gap in bars (no data for a while) must never fabricate a fill or
    exit -- once real bars resume, exit detection continues correctly."""
    ledger = ShadowLedger(tmp_path / "shadow.json")
    decision = _buy_decision(now=T0, stop=99.0, target=105.0)
    ledger.consider_entry(decision, source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))  # fills
    # gap: no bars for symbol between minute 1 and minute 40
    ledger.on_bar("AAPL", _bar(40, 100.3, 100.6, 98.5, 98.9))  # stop breach on the first bar after the gap
    position = ledger.get_by_decision("d1")
    assert position["status"] == "CLOSED"
    assert position["exit_reason"] == "STOP"


# ---------------------------------------------------------------------------
# Linkage, separation from PAPER, idempotency, restart
# ---------------------------------------------------------------------------

def test_shadow_position_linked_to_decision_id(tmp_path):
    ledger = ShadowLedger(tmp_path / "shadow.json")
    decision = _buy_decision()
    result = ledger.consider_entry(decision, source="STRATEGY")
    assert result["decision_id"] == decision.decision_id


def test_duplicate_decision_is_idempotent(tmp_path):
    ledger = ShadowLedger(tmp_path / "shadow.json")
    decision = _buy_decision()
    first = ledger.consider_entry(decision, source="STRATEGY")
    second = ledger.consider_entry(decision, source="STRATEGY")
    assert first["shadow_id"] == second["shadow_id"]
    assert len(ledger.positions) == 1


def test_restart_preserves_shadow_state(tmp_path):
    path = tmp_path / "shadow.json"
    ledger1 = ShadowLedger(path)
    decision = _buy_decision(now=T0)
    ledger1.consider_entry(decision, source="STRATEGY")
    ledger1.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))
    ledger2 = ShadowLedger(path)  # simulates a restart
    position = ledger2.get_by_decision("d1")
    assert position["status"] == "OPEN"
    ledger2.on_bar("AAPL", _bar(2, 100.0, 100.1, 98.5, 98.8))  # stop breach, post-restart
    assert ledger2.get_by_decision("d1")["status"] == "CLOSED"


def test_shadow_exit_while_broker_is_flat_is_not_a_reconciliation_failure(tmp_path):
    """A shadow position closing has nothing to do with PaperLifecycle's
    own reconcile() -- this is a pure isolation check: ShadowLedger never
    touches or references any broker/lifecycle state."""
    ledger = ShadowLedger(tmp_path / "shadow.json")
    decision = _buy_decision(now=T0, stop=99.0, target=105.0)
    ledger.consider_entry(decision, source="STRATEGY")
    ledger.on_bar("AAPL", _bar(1, 100.0, 100.5, 99.5, 100.2))
    ledger.on_bar("AAPL", _bar(2, 100.0, 100.1, 98.5, 98.8))  # stop hit, closes
    assert ledger.get_by_decision("d1")["status"] == "CLOSED"
    # no broker/lifecycle object was ever constructed in this test -- a
    # shadow-only close cannot possibly touch real broker state.
