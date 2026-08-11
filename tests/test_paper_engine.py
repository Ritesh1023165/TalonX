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

from talonx_paper.engine import DecisionKind, calculate_buy, calculate_sell_pnl, decide_trade
from talonx_paper.schemas import ActionableAlert, AlertAction, TriggeringSignalRef

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
