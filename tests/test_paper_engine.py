"""
tests/test_paper_engine.py
--------------------------------
Tests talonx_paper.engine's pure functions -- no I/O, same testability
philosophy as tests/test_core_decision.py. Covers decide_trade for every
action x position-state combination (the trigger mapping the doc's
fictional action names had to be translated onto), calculate_buy
(including insufficient cash), and calculate_sell_pnl against a worked
example matching the requirement doc's own numbers.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_paper.engine import (
    DecisionKind,
    LongTermDecisionKind,
    apply_spread,
    calculate_average_cost_basis,
    calculate_buy,
    calculate_partial_sell_pnl,
    calculate_sell_pnl,
    check_stop_take,
    decide_long_term_trade,
    decide_trade,
)
from talonx_paper.schemas import ActionableAlert, AlertAction, LongTermActionableAlert, MoatRating, TriggeringSignalRef

NOW = datetime(2026, 8, 10, 14, 37, 0, tzinfo=timezone.utc)


def _alert(action: AlertAction, price: float = 135.60) -> ActionableAlert:
    return ActionableAlert(
        ticker="SPCX", action=action, triggering_signal=TriggeringSignalRef(price=price), correlated_at=NOW,
    )


def _position(entry_price: float = 135.0, shares: float = 18.5185) -> dict:
    return {"ticker": "SPCX", "shares": shares, "entry_price": entry_price, "cost_basis": shares * entry_price}


# --- decide_trade -------------------------------------------------------

def test_confirmed_bullish_flat_produces_buy():
    decision = decide_trade(_alert(AlertAction.CONFIRMED_BULLISH), position=None)
    assert decision.kind == DecisionKind.BUY
    assert decision.ticker == "SPCX"


def test_confirmed_bullish_already_long_is_ignored():
    decision = decide_trade(_alert(AlertAction.CONFIRMED_BULLISH), position=_position())
    assert decision.kind == DecisionKind.IGNORED
    assert decision.reason == "POSITION_ALREADY_OPEN"


def test_confirmed_bearish_long_produces_sell():
    decision = decide_trade(_alert(AlertAction.CONFIRMED_BEARISH), position=_position())
    assert decision.kind == DecisionKind.SELL


def test_confirmed_bearish_flat_is_ignored():
    decision = decide_trade(_alert(AlertAction.CONFIRMED_BEARISH), position=None)
    assert decision.kind == DecisionKind.IGNORED
    assert decision.reason == "NO_ACTIVE_POSITION"


def test_contradicted_long_produces_sell():
    # The requirement doc's own Telegram example shows CONTRADICTED
    # triggering a SELL -- confirms this mapping, not just CONFIRMED_BEARISH.
    decision = decide_trade(_alert(AlertAction.CONTRADICTED), position=_position())
    assert decision.kind == DecisionKind.SELL


def test_contradicted_flat_is_ignored():
    decision = decide_trade(_alert(AlertAction.CONTRADICTED), position=None)
    assert decision.kind == DecisionKind.IGNORED
    assert decision.reason == "NO_ACTIVE_POSITION"


def test_degraded_quant_alert_is_not_a_trading_trigger_flat():
    assert decide_trade(_alert(AlertAction.DEGRADED_QUANT_ALERT), position=None) is None


def test_degraded_quant_alert_is_not_a_trading_trigger_long():
    assert decide_trade(_alert(AlertAction.DEGRADED_QUANT_ALERT), position=_position()) is None


def test_decision_carries_the_triggering_price():
    decision = decide_trade(_alert(AlertAction.CONFIRMED_BULLISH, price=131.50), position=None)
    assert decision.price == 131.50


# --- calculate_buy -------------------------------------------------------

def test_calculate_buy_spends_the_fixed_allocation_when_cash_is_sufficient():
    shares, cost = calculate_buy(cash=10000.0, allocation_usd=2500.0, price=100.0)
    assert cost == 2500.0
    assert shares == 25.0


def test_calculate_buy_caps_spend_at_available_cash():
    shares, cost = calculate_buy(cash=1000.0, allocation_usd=2500.0, price=100.0)
    assert cost == 1000.0
    assert shares == 10.0


def test_calculate_buy_returns_none_when_no_cash_left():
    assert calculate_buy(cash=0.0, allocation_usd=2500.0, price=100.0) is None
    assert calculate_buy(cash=-5.0, allocation_usd=2500.0, price=100.0) is None


def test_calculate_buy_returns_none_for_non_positive_price():
    assert calculate_buy(cash=10000.0, allocation_usd=2500.0, price=0.0) is None
    assert calculate_buy(cash=10000.0, allocation_usd=2500.0, price=-1.0) is None


# --- calculate_sell_pnl ----------------------------------------------------

def test_calculate_sell_pnl_matches_the_requirement_docs_worked_example():
    # Doc's Telegram example: Entry $135.00 -> Exit $135.60, Trade PnL +$44.81 (+0.45%).
    shares = 44.81 / (135.60 - 135.00)  # back out the share count the doc's own numbers imply
    pnl_usd, pnl_pct = calculate_sell_pnl(shares, entry_price=135.00, exit_price=135.60)
    assert round(pnl_usd, 2) == 44.81
    assert round(pnl_pct, 2) == 0.44  # (0.60 / 135.00) * 100 = 0.4444...


def test_calculate_sell_pnl_negative_for_a_loss():
    pnl_usd, pnl_pct = calculate_sell_pnl(shares=10.0, entry_price=100.0, exit_price=90.0)
    assert pnl_usd == -100.0
    assert pnl_pct == -10.0


def test_calculate_sell_pnl_zero_for_a_flat_exit():
    pnl_usd, pnl_pct = calculate_sell_pnl(shares=10.0, entry_price=100.0, exit_price=100.0)
    assert pnl_usd == 0.0
    assert pnl_pct == 0.0


# --- check_stop_take -------------------------------------------------------

def test_check_stop_take_triggers_stop_loss_when_price_falls_far_enough():
    # entry 100, stop 0.5% -> stop price 99.50
    assert check_stop_take(100.0, 99.40, stop_loss_pct=0.005, take_profit_pct=0.01) == "STOP_LOSS"


def test_check_stop_take_triggers_take_profit_when_price_rises_far_enough():
    # entry 100, take 1% -> target 101.00
    assert check_stop_take(100.0, 101.10, stop_loss_pct=0.005, take_profit_pct=0.01) == "TAKE_PROFIT"


def test_check_stop_take_returns_none_inside_the_band():
    assert check_stop_take(100.0, 100.20, stop_loss_pct=0.005, take_profit_pct=0.01) is None
    assert check_stop_take(100.0, 99.80, stop_loss_pct=0.005, take_profit_pct=0.01) is None


def test_check_stop_take_exact_stop_boundary_triggers():
    assert check_stop_take(100.0, 99.50, stop_loss_pct=0.005, take_profit_pct=0.01) == "STOP_LOSS"


def test_check_stop_take_exact_take_profit_boundary_triggers():
    assert check_stop_take(100.0, 101.00, stop_loss_pct=0.005, take_profit_pct=0.01) == "TAKE_PROFIT"


def test_check_stop_take_stop_loss_wins_if_somehow_both_cross_at_once():
    # Contrived (can't really happen since stop is below entry and take
    # is above), but confirms stop-loss is checked first.
    assert check_stop_take(100.0, 50.0, stop_loss_pct=0.005, take_profit_pct=0.01) == "STOP_LOSS"


def test_check_stop_take_returns_none_for_non_positive_entry_price():
    assert check_stop_take(0.0, 100.0, stop_loss_pct=0.005, take_profit_pct=0.01) is None


# --- check_stop_take: ATR-anchored levels (Phase 2 requirement doc) -------
# When both stop_price/target_price are provided, they OVERRIDE the
# percentage bands entirely -- entry=100 with pct bands that would fire at
# 99.50/101.00 is used below with much wider ATR levels to prove the
# percentage config is genuinely ignored, not just coincidentally satisfied.

def test_check_stop_take_uses_atr_stop_price_when_provided_long():
    assert check_stop_take(
        100.0, 96.0, stop_loss_pct=0.005, take_profit_pct=0.01,
        stop_price=95.0, target_price=110.0,
    ) is None  # inside the ATR band even though outside the pct band


def test_check_stop_take_atr_stop_price_triggers_long():
    assert check_stop_take(
        100.0, 94.0, stop_loss_pct=0.005, take_profit_pct=0.01,
        stop_price=95.0, target_price=110.0,
    ) == "STOP_LOSS"


def test_check_stop_take_atr_target_price_triggers_long():
    assert check_stop_take(
        100.0, 111.0, stop_loss_pct=0.005, take_profit_pct=0.01,
        stop_price=95.0, target_price=110.0,
    ) == "TAKE_PROFIT"


def test_check_stop_take_falls_back_to_pct_when_only_one_atr_level_given():
    # Only stop_price provided -- treated as "not available", falls back
    # to the percentage bands (entry=100, stop pct=0.5% -> 99.50).
    assert check_stop_take(
        100.0, 99.40, stop_loss_pct=0.005, take_profit_pct=0.01, stop_price=95.0, target_price=None,
    ) == "STOP_LOSS"


# --- apply_spread ------------------------------------------------------------

def test_apply_spread_buy_fills_above_quoted_price():
    filled = apply_spread(100.0, spread_bps=10.0, side="BUY")
    assert round(filled, 4) == 100.05  # +half of 10bps = +5bps = +0.05


def test_apply_spread_sell_fills_below_quoted_price():
    filled = apply_spread(100.0, spread_bps=10.0, side="SELL")
    assert round(filled, 4) == 99.95


def test_apply_spread_zero_bps_is_a_noop():
    assert apply_spread(131.50, spread_bps=0.0, side="BUY") == 131.50
    assert apply_spread(131.50, spread_bps=0.0, side="SELL") == 131.50


# ==========================================================================
# Phase 2 LONG_TERM path
# ==========================================================================

def _long_term_alert(action: AlertAction, price: float = 100.0) -> LongTermActionableAlert:
    return LongTermActionableAlert(
        ticker="AAPL", action=action, quality_score=8, moat_rating=MoatRating.WIDE,
        market_price=price, intrinsic_fair_value=120.0, margin_of_safety_pct=0.20, correlated_at=NOW,
    )


def _long_term_position(avg_cost_basis: float = 90.0, total_shares: float = 25.0) -> dict:
    return {
        "ticker": "AAPL", "total_shares": total_shares, "avg_cost_basis": avg_cost_basis,
        "first_entry_at": NOW.isoformat(), "total_contributed_usd": total_shares * avg_cost_basis,
    }


# --- decide_long_term_trade ---------------------------------------------

def test_high_conviction_buy_flat_produces_buy():
    decision = decide_long_term_trade(_long_term_alert(AlertAction.HIGH_CONVICTION_BUY), position=None, rebalance_trim_pct=0.33)
    assert decision.kind == LongTermDecisionKind.BUY
    assert decision.ticker == "AAPL"


def test_high_conviction_buy_already_long_is_ignored():
    decision = decide_long_term_trade(
        _long_term_alert(AlertAction.HIGH_CONVICTION_BUY), position=_long_term_position(), rebalance_trim_pct=0.33,
    )
    assert decision.kind == LongTermDecisionKind.IGNORED
    assert decision.reason == "POSITION_ALREADY_OPEN"


def test_take_profit_rebalance_long_produces_sell_partial():
    decision = decide_long_term_trade(
        _long_term_alert(AlertAction.TAKE_PROFIT_REBALANCE), position=_long_term_position(), rebalance_trim_pct=0.33,
    )
    assert decision.kind == LongTermDecisionKind.SELL_PARTIAL
    assert decision.trim_fraction == 0.33


def test_take_profit_rebalance_flat_is_ignored():
    decision = decide_long_term_trade(
        _long_term_alert(AlertAction.TAKE_PROFIT_REBALANCE), position=None, rebalance_trim_pct=0.33,
    )
    assert decision.kind == LongTermDecisionKind.IGNORED
    assert decision.reason == "NO_ACTIVE_POSITION"


def test_under_perform_rebalance_long_produces_sell_full():
    decision = decide_long_term_trade(
        _long_term_alert(AlertAction.UNDER_PERFORM_REBALANCE), position=_long_term_position(), rebalance_trim_pct=0.33,
    )
    assert decision.kind == LongTermDecisionKind.SELL_FULL


def test_under_perform_rebalance_flat_is_ignored():
    decision = decide_long_term_trade(
        _long_term_alert(AlertAction.UNDER_PERFORM_REBALANCE), position=None, rebalance_trim_pct=0.33,
    )
    assert decision.kind == LongTermDecisionKind.IGNORED
    assert decision.reason == "NO_ACTIVE_POSITION"


def test_hold_quality_is_not_a_trading_trigger():
    assert decide_long_term_trade(_long_term_alert(AlertAction.HOLD_QUALITY), position=None, rebalance_trim_pct=0.33) is None
    assert decide_long_term_trade(
        _long_term_alert(AlertAction.HOLD_QUALITY), position=_long_term_position(), rebalance_trim_pct=0.33,
    ) is None


def test_long_term_decision_carries_the_triggering_price():
    decision = decide_long_term_trade(
        _long_term_alert(AlertAction.HIGH_CONVICTION_BUY, price=88.5), position=None, rebalance_trim_pct=0.33,
    )
    assert decision.price == 88.5


# --- calculate_average_cost_basis ----------------------------------------

def test_calculate_average_cost_basis_first_buy_from_flat():
    avg = calculate_average_cost_basis(existing_shares=0.0, existing_avg_cost=0.0, new_shares=10.0, new_price=100.0)
    assert avg == 100.0


def test_calculate_average_cost_basis_weighted_average_worked_example():
    # 10 shares @ $100 (existing) + 10 shares @ $120 (new DCA buy)
    # -> avg = (1000 + 1200) / 20 = 110.0
    avg = calculate_average_cost_basis(existing_shares=10.0, existing_avg_cost=100.0, new_shares=10.0, new_price=120.0)
    assert avg == 110.0


def test_calculate_average_cost_basis_zero_total_shares_falls_back_to_new_price():
    avg = calculate_average_cost_basis(existing_shares=0.0, existing_avg_cost=0.0, new_shares=0.0, new_price=50.0)
    assert avg == 50.0


# --- calculate_partial_sell_pnl -------------------------------------------

def test_calculate_partial_sell_pnl_worked_example():
    pnl_usd, pnl_pct = calculate_partial_sell_pnl(shares_to_sell=10.0, avg_cost_basis=90.0, exit_price=120.0)
    assert pnl_usd == 300.0  # 10 * (120 - 90)
    assert round(pnl_pct, 2) == 33.33


def test_calculate_partial_sell_pnl_only_covers_the_sold_shares():
    # Position is 25 shares, but only 8 (a trim fraction) are being sold --
    # PnL must reflect just those 8, not the full 25.
    pnl_usd, _ = calculate_partial_sell_pnl(shares_to_sell=8.0, avg_cost_basis=90.0, exit_price=120.0)
    assert pnl_usd == 240.0  # 8 * (120 - 90)


def test_calculate_partial_sell_pnl_negative_for_a_loss():
    pnl_usd, pnl_pct = calculate_partial_sell_pnl(shares_to_sell=10.0, avg_cost_basis=100.0, exit_price=90.0)
    assert pnl_usd == -100.0
    assert pnl_pct == -10.0


def test_calculate_partial_sell_pnl_zero_cost_basis_does_not_divide_by_zero():
    pnl_usd, pnl_pct = calculate_partial_sell_pnl(shares_to_sell=10.0, avg_cost_basis=0.0, exit_price=90.0)
    assert pnl_usd == 900.0
    assert pnl_pct == 0.0
