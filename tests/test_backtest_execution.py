"""
tests/test_backtest_execution.py
-------------------------------------
talonx_backtest.execution: same-bar stop/target ambiguity (spec section
6, default "stop_first"), slippage/spread cost direction (spec sections
7-8), and TradeSimulator's MFE/MAE + exit lifecycle.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from talonx_backtest.execution import (
    ExecutionConfig,
    TradeSimulator,
    apply_entry_cost,
    apply_exit_cost,
    check_bar_for_exit,
)
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType


def _dt(minute: int = 0) -> datetime:
    return datetime(2026, 1, 5, 15, minute, tzinfo=timezone.utc)


def _signal(direction: SignalDirection, stop: float, target: float, price: float = 100.0) -> QuantSignal:
    return QuantSignal(
        ticker="AAPL", signal_type=SignalType.RSI_OVERSOLD_VOLUME_SURGE, direction=direction,
        message="test", price=price, atr=1.0, confluence_score=3, risk_reward_ratio=2.0,
        stop_price=stop, target_price=target, session="regular", bar_timestamp=_dt(),
    )


# --- Same-bar stop/target ambiguity (spec section 6) ---

def test_bullish_bar_hitting_only_target_resolves_target():
    outcome = check_bar_for_exit(SignalDirection.BULLISH, stop_price=95.0, target_price=105.0, bar_high=106.0, bar_low=99.0)
    assert outcome == "target"


def test_bullish_bar_hitting_only_stop_resolves_stop():
    outcome = check_bar_for_exit(SignalDirection.BULLISH, stop_price=95.0, target_price=105.0, bar_high=100.0, bar_low=94.0)
    assert outcome == "stop"


def test_bullish_bar_hitting_neither_resolves_none():
    outcome = check_bar_for_exit(SignalDirection.BULLISH, stop_price=95.0, target_price=105.0, bar_high=101.0, bar_low=99.0)
    assert outcome is None


def test_bullish_same_bar_ambiguity_defaults_to_stop_first():
    outcome = check_bar_for_exit(SignalDirection.BULLISH, stop_price=95.0, target_price=105.0, bar_high=106.0, bar_low=94.0)
    assert outcome == "stop"


def test_bullish_same_bar_ambiguity_target_first_is_configurable():
    outcome = check_bar_for_exit(
        SignalDirection.BULLISH, stop_price=95.0, target_price=105.0, bar_high=106.0, bar_low=94.0,
        same_bar_resolution="target_first",
    )
    assert outcome == "target"


def test_bearish_same_bar_ambiguity_defaults_to_stop_first():
    # BEARISH: stop is ABOVE price, target is BELOW.
    outcome = check_bar_for_exit(SignalDirection.BEARISH, stop_price=105.0, target_price=95.0, bar_high=106.0, bar_low=94.0)
    assert outcome == "stop"


def test_invalid_same_bar_resolution_rejected():
    with pytest.raises(ValueError):
        ExecutionConfig(same_bar_resolution="whatever")


# --- Slippage / spread cost direction (spec sections 7-8) ---

def test_entry_slippage_moves_bullish_entry_price_up():
    cfg = ExecutionConfig(entry_slippage_bps=10.0)
    filled = apply_entry_cost(100.0, SignalDirection.BULLISH, cfg)
    assert filled > 100.0
    assert filled == pytest.approx(100.0 * 1.001)


def test_entry_slippage_moves_bearish_entry_price_down():
    cfg = ExecutionConfig(entry_slippage_bps=10.0)
    filled = apply_entry_cost(100.0, SignalDirection.BEARISH, cfg)
    assert filled < 100.0


def test_exit_slippage_moves_bullish_exit_price_down():
    cfg = ExecutionConfig(exit_slippage_bps=20.0)
    filled = apply_exit_cost(100.0, SignalDirection.BULLISH, cfg)
    assert filled < 100.0


def test_exit_slippage_moves_bearish_exit_price_up():
    cfg = ExecutionConfig(exit_slippage_bps=20.0)
    filled = apply_exit_cost(100.0, SignalDirection.BEARISH, cfg)
    assert filled > 100.0


def test_zero_cost_config_leaves_price_unchanged():
    cfg = ExecutionConfig()
    assert apply_entry_cost(100.0, SignalDirection.BULLISH, cfg) == 100.0
    assert apply_exit_cost(100.0, SignalDirection.BEARISH, cfg) == 100.0


# --- TradeSimulator lifecycle / MFE-MAE ---

def test_target_hit_produces_a_winning_trade_with_correct_r():
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)
    sim.open_position(signal, entry_timestamp=_dt(1), entry_price_raw=100.0, opportunity_score=0.5)

    trade = sim.check_exit("AAPL", _dt(2), bar_high=111.0, bar_low=99.0)
    assert trade is not None
    assert trade.exit_reason == "TARGET"
    assert trade.gross_pnl == pytest.approx(10.0)  # 110 - 100
    assert trade.gross_R == pytest.approx(2.0)      # risk = 100-95 = 5; reward = 10 -> 2R


def test_stop_hit_produces_a_losing_trade():
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)
    sim.open_position(signal, entry_timestamp=_dt(1), entry_price_raw=100.0)

    trade = sim.check_exit("AAPL", _dt(2), bar_high=101.0, bar_low=94.0)
    assert trade.exit_reason == "STOP"
    assert trade.gross_R == pytest.approx(-1.0)


def test_mfe_mae_track_the_running_extremes_before_exit():
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=90.0, target=120.0)
    sim.open_position(signal, entry_timestamp=_dt(1), entry_price_raw=100.0)

    sim.check_exit("AAPL", _dt(2), bar_high=108.0, bar_low=97.0)   # ran up to 108, dipped to 97
    sim.check_exit("AAPL", _dt(3), bar_high=104.0, bar_low=95.0)   # dipped further to 95
    trade = sim.check_exit("AAPL", _dt(4), bar_high=121.0, bar_low=100.0)  # target hit

    assert trade.mfe_price == pytest.approx(121.0)
    assert trade.mae_price == pytest.approx(95.0)
    assert trade.mfe_r == pytest.approx((121.0 - 100.0) / 10.0)
    assert trade.mae_r == pytest.approx((95.0 - 100.0) / 10.0)


def test_holding_seconds_is_entry_to_exit():
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)
    sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)
    trade = sim.check_exit("AAPL", _dt(23), bar_high=111.0, bar_low=99.0)
    assert trade.holding_seconds == pytest.approx(23 * 60)


def test_force_close_uses_the_given_reason_and_price():
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)
    sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)
    trade = sim.force_close("AAPL", _dt(5), price_raw=102.0, reason="END_OF_SESSION")
    assert trade.exit_reason == "END_OF_SESSION"
    assert trade.exit_price == 102.0
    assert not sim.has_open("AAPL")


def test_net_pnl_reflects_costs_while_gross_does_not():
    cfg = ExecutionConfig(entry_slippage_bps=10.0, exit_slippage_bps=10.0, spread_bps=10.0)
    sim = TradeSimulator(cfg)
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)
    sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)
    trade = sim.check_exit("AAPL", _dt(1), bar_high=111.0, bar_low=99.0)
    assert trade.gross_pnl == pytest.approx(10.0)
    assert trade.net_pnl < trade.gross_pnl
