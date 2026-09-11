"""Task 76S Stage 1/5 -- decision-contract behaviour tests.

Pure unit tests of talonx_piv.decision_contract.decide(): no broker, no
event bus, no network of any kind is constructed anywhere in this file.
All strategy-approval-status=APPROVED cases are TEST_FIXTURE_ONLY -- NOT
ALPHA EVIDENCE (no production code path ever sets APPROVED for a real
strategy -- see decision_contract.py's own module docstring)."""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_piv.decision_contract import (
    DataReadiness, Decision, ExecutionStatus, MarketView, Recommendation,
    StrategyApprovalStatus, decide,
)

NOW = datetime(2026, 8, 28, 14, 30, tzinfo=timezone.utc)


def _decide(**overrides):
    """TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Sensible eligible-BUY
    defaults, overridden per test to isolate exactly one condition."""
    base = dict(
        decision_id="dec-1", session_id="sess-1", trading_date_et="2026-08-28", ticker="AAPL",
        market_view=MarketView.BULLISH, has_open_long=False, approved_exit_condition=False,
        strategy_approval_status=StrategyApprovalStatus.APPROVED, data_readiness=DataReadiness.READY,
        paper_entry_enabled=True, now=NOW,
    )
    base.update(overrides)
    return decide(**base)


def test_eligible_approved_bullish_setup_no_holding_is_buy():
    d = _decide()
    assert d.recommendation == Recommendation.BUY
    assert d.execution_status == ExecutionStatus.ENTRY_ELIGIBLE
    assert "ELIGIBLE_APPROVED_BULLISH_SETUP_NO_HOLDING" in d.reason_codes


def test_unvalidated_strategy_cannot_become_actionable_buy():
    d = _decide(strategy_approval_status=StrategyApprovalStatus.UNVALIDATED)
    assert d.recommendation == Recommendation.NO_TRADE
    assert d.execution_status == ExecutionStatus.NO_ACTION
    assert any("UNVALIDATED" in code for code in d.reason_codes)


def test_default_strategy_status_is_unvalidated_and_fails_closed():
    """No `strategy_approval_status` override -- confirms the type itself
    has no implicit 'approved' default a careless caller could fall into."""
    d = _decide(strategy_approval_status=StrategyApprovalStatus.UNVALIDATED, paper_entry_enabled=True)
    assert d.recommendation == Recommendation.NO_TRADE


def test_bearish_while_flat_is_no_trade():
    d = _decide(market_view=MarketView.BEARISH)
    assert d.recommendation == Recommendation.NO_TRADE
    assert d.execution_status == ExecutionStatus.NO_ACTION
    assert "BEARISH_OR_NEUTRAL_VIEW_NO_HOLDING" in d.reason_codes


def test_neutral_while_flat_is_no_trade():
    d = _decide(market_view=MarketView.NEUTRAL)
    assert d.recommendation == Recommendation.NO_TRADE


def test_existing_long_without_exit_condition_is_hold():
    d = _decide(has_open_long=True, approved_exit_condition=False, market_view=MarketView.BULLISH)
    assert d.recommendation == Recommendation.HOLD
    assert d.execution_status == ExecutionStatus.NO_ACTION
    assert "EXISTING_LONG_NO_APPROVED_EXIT_CONDITION" in d.reason_codes


def test_existing_long_with_valid_exit_is_sell_to_close():
    d = _decide(has_open_long=True, approved_exit_condition=True)
    assert d.recommendation == Recommendation.SELL_TO_CLOSE
    assert d.execution_status == ExecutionStatus.EXIT_ELIGIBLE
    assert "EXISTING_LONG_APPROVED_EXIT_CONDITION" in d.reason_codes


def test_bearish_view_while_holding_without_exit_condition_is_hold_not_a_new_exit_rule():
    """The one hard invariant: a bearish OBSERVATION alone must never
    introduce an untested exit -- only an explicit, already-authorised
    `approved_exit_condition` may produce SELL_TO_CLOSE."""
    d = _decide(has_open_long=True, approved_exit_condition=False, market_view=MarketView.BEARISH)
    assert d.recommendation == Recommendation.HOLD


def test_data_insufficient_for_entry_is_no_trade_with_explicit_reason():
    d = _decide(data_readiness=DataReadiness.DATA_NOT_READY)
    assert d.recommendation == Recommendation.NO_TRADE
    assert any("DATA_INSUFFICIENT_FOR_ENTRY" in code for code in d.reason_codes)
    assert "DATA_NOT_READY" in d.reason_codes[0]


def test_pending_data_readiness_also_blocks_entry():
    d = _decide(data_readiness=DataReadiness.PENDING)
    assert d.recommendation == Recommendation.NO_TRADE


def test_valid_buy_but_paper_entry_disabled_preserves_buy_and_blocks_entry():
    d = _decide(paper_entry_enabled=False)
    assert d.recommendation == Recommendation.BUY  # preserved, not downgraded
    assert d.execution_status == ExecutionStatus.ENTRY_BLOCKED_PAPER_DISABLED
    assert "PAPER_ENTRY_DISABLED_FOR_TICKER" in d.reason_codes


def test_paper_entry_disabled_does_not_change_recommendation_for_hold_or_no_trade():
    """paper_entry_enabled must only ever affect a BUY -- never invent a
    different recommendation for HOLD/NO_TRADE/SELL_TO_CLOSE cases."""
    hold = _decide(has_open_long=True, approved_exit_condition=False, paper_entry_enabled=False)
    assert hold.recommendation == Recommendation.HOLD
    no_trade = _decide(market_view=MarketView.BEARISH, paper_entry_enabled=False)
    assert no_trade.recommendation == Recommendation.NO_TRADE
    sell = _decide(has_open_long=True, approved_exit_condition=True, paper_entry_enabled=False)
    assert sell.recommendation == Recommendation.SELL_TO_CLOSE
    assert sell.execution_status == ExecutionStatus.EXIT_ELIGIBLE  # never blocked by paper_entry_enabled


def test_levels_are_passed_through_not_invented():
    d = _decide(entry_price=100.0, stop_price=97.0, target_price=106.0, horizon="INTRADAY_SHORT")
    assert d.entry_price == 100.0 and d.stop_price == 97.0 and d.target_price == 106.0
    assert d.horizon == "INTRADAY_SHORT"


def test_no_levels_supplied_stay_none_not_fabricated():
    d = _decide()
    assert d.entry_price is None and d.stop_price is None and d.target_price is None


def test_decision_record_carries_all_required_fields():
    d = _decide(strategy_id="MACD_BULLISH_CROSS", strategy_version="2ae6216bca70")
    required = d.to_dict()
    for field in (
        "decision_id", "session_id", "trading_date_et", "ticker", "market_view", "recommendation",
        "reason_codes", "strategy_id", "strategy_version", "strategy_approval_status", "data_readiness",
        "paper_entry_enabled", "execution_status", "timestamp",
    ):
        assert field in required, f"missing required decision field: {field}"
    assert required["strategy_id"] == "MACD_BULLISH_CROSS"
    assert required["timestamp"] == NOW.isoformat()


def test_ticker_is_normalized_uppercase():
    d = _decide(ticker="aapl")
    assert d.ticker == "AAPL"


def test_decision_is_a_frozen_immutable_record():
    d = _decide()
    assert isinstance(d, Decision)
    try:
        d.recommendation = Recommendation.HOLD  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised, "Decision must be frozen -- a later component must never mutate a recorded decision"
