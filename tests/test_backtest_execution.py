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


# --- screening_rr vs execution_rr (three distinct, all-correct R:R numbers) ---

def test_screening_rr_is_copied_verbatim_from_the_published_signal():
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)
    signal = signal.model_copy(update={"risk_reward_ratio": 17.18})  # e.g. a stale ATR/revalidation-price-based ratio
    sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)
    trade = sim.check_exit("AAPL", _dt(1), bar_high=111.0, bar_low=99.0)

    assert trade.risk_reward_ratio == pytest.approx(17.18)
    assert trade.screening_rr == trade.risk_reward_ratio  # explicit alias, always identical


def test_execution_rr_uses_the_real_fill_price_not_the_screening_reference_price():
    # entry filled BELOW the price the screening ratio was computed from
    # (the classic "signal published at 111.70, filled at 110.90 a bar
    # later" case) -- execution_rr must reflect the REAL fill, not the
    # stale screening number.
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)
    signal = signal.model_copy(update={"risk_reward_ratio": 17.18})
    sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)
    trade = sim.check_exit("AAPL", _dt(1), bar_high=111.0, bar_low=99.0)

    # risk = |entry(100) - stop(95)| = 5; reward = |target(110) - entry(100)| = 10
    assert trade.execution_rr == pytest.approx(2.0)
    assert trade.execution_rr != trade.screening_rr


def test_execution_rr_is_independent_of_how_the_trade_actually_exited():
    """execution_rr is a property of entry/stop/target geometry, fixed
    at entry time -- it must NOT change depending on whether the trade
    goes on to hit TARGET, STOP, or gets force-closed some other way."""
    stop_sim = TradeSimulator(ExecutionConfig())
    target_sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)

    stop_sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)
    stop_trade = stop_sim.check_exit("AAPL", _dt(1), bar_high=101.0, bar_low=94.0)  # hits STOP

    target_sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)
    target_trade = target_sim.check_exit("AAPL", _dt(1), bar_high=111.0, bar_low=99.0)  # hits TARGET

    assert stop_trade.exit_reason == "STOP"
    assert target_trade.exit_reason == "TARGET"
    assert stop_trade.execution_rr == pytest.approx(target_trade.execution_rr) == pytest.approx(2.0)
    # gross_R, in contrast, DOES depend on how the trade exited:
    assert stop_trade.gross_R == pytest.approx(-1.0)
    assert target_trade.gross_R == pytest.approx(2.0)


def test_execution_rr_matches_gross_r_exactly_when_target_is_hit_precisely():
    """The one case where execution_rr and gross_R DO coincide: the
    trade exits at exactly the target price (a clean TARGET hit with no
    slippage), since gross_R's realized reward then equals the planned
    reward execution_rr was computed from."""
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)
    sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)
    trade = sim.check_exit("AAPL", _dt(1), bar_high=111.0, bar_low=99.0)

    assert trade.exit_reason == "TARGET"
    assert trade.execution_rr == pytest.approx(trade.gross_R)


def test_execution_rr_is_none_when_risk_resolves_to_zero():
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=100.0, target=110.0)  # stop == entry -> risk resolves to 0
    sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)
    trade = sim.check_exit("AAPL", _dt(1), bar_high=111.0, bar_low=99.0)

    assert trade.execution_rr is None


def test_execution_rr_is_correct_for_a_bearish_short_trade():
    # BEARISH: stop is ABOVE entry, target is BELOW entry -- execution_rr
    # must still come out positive and correct since both the numerator
    # and denominator are abs() distances (2026-08-16 infra audit, Part A).
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BEARISH, stop=105.0, target=90.0)
    sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)
    trade = sim.check_exit("AAPL", _dt(1), bar_high=101.0, bar_low=89.0)  # hits TARGET

    # risk = |entry(100) - stop(105)| = 5; reward = |target(90) - entry(100)| = 10
    assert trade.exit_reason == "TARGET"
    assert trade.execution_rr == pytest.approx(2.0)
    assert trade.execution_rr == pytest.approx(trade.gross_R)  # exact TARGET hit, same coincidence as the bullish case


def test_execution_rr_is_none_when_stop_price_is_missing():
    # force_close, not check_exit -- see the module-level note below on
    # why check_exit itself cannot safely be called with stop_price=None.
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)
    signal = signal.model_copy(update={"stop_price": None})
    sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)
    trade = sim.force_close("AAPL", _dt(1), price_raw=102.0, reason="END_OF_SESSION")

    assert trade.execution_rr is None
    assert trade.gross_R is None  # risk is None -- no divide-by-zero, no fabricated ratio
    assert trade.net_R is None


def test_check_exit_raises_rather_than_silently_misbehaving_on_a_missing_stop_price():
    """2026-08-16 infra audit (Part A) finding: open_position()'s own risk
    calculation defends against signal.stop_price being None (risk
    resolves to None, never a crash -- see the two tests above), but
    check_exit -> check_bar_for_exit does a direct float comparison
    (`bar_low <= stop_price`) with no None-guard, so a None stop_price
    reaching check_exit crashes with an unhandled TypeError instead of
    failing safely. NOT reachable via the real engine today -- every
    signal that reaches open_position() has already survived
    engine._revalidate/consumer._revalidate_candidate, which only
    publishes a candidate with a fully-populated TradeGeometry (stop_price
    is a non-Optional float there) -- but TradeSimulator is a
    general-purpose, independently-importable module, not exclusively
    fed by that revalidated path, so the inconsistency is worth pinning
    down rather than leaving implicit. This test documents the CURRENT
    (fragile) behavior; it is not a statement that a crash is desired."""
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)
    signal = signal.model_copy(update={"stop_price": None})
    sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)

    with pytest.raises(TypeError):
        sim.check_exit("AAPL", _dt(1), bar_high=111.0, bar_low=99.0)


def test_execution_rr_is_none_when_target_price_is_missing():
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)
    signal = signal.model_copy(update={"target_price": None})
    sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0)
    # force_close rather than check_exit -- with target_price=None,
    # check_bar_for_exit's own target comparison would break first; this
    # isolates execution_rr's target_price=None guard specifically.
    trade = sim.force_close("AAPL", _dt(1), price_raw=102.0, reason="END_OF_SESSION")

    assert trade.execution_rr is None
    assert trade.gross_R == pytest.approx(2.0 / 5.0)  # gross_R is unaffected -- it never uses target_price


def test_opportunity_score_is_unaffected_by_execution_rr_divergence():
    """R:R contributes opportunity_score_rr_weight (30% by default) to
    the Composite Opportunity Score -- but that score is computed by
    talonx_quant.consumer._opportunity_score BEFORE entry, from
    signal.risk_reward_ratio (== screening_rr) alone. TradeSimulator
    never recomputes it: `opportunity_score` is passed in at
    open_position() time and copied onto the Trade verbatim. This test
    proves that end of the chain -- a real fill price that makes
    execution_rr diverge sharply from screening_rr must NOT change the
    opportunity_score already carried on the resulting Trade. See
    test_backtest_engine_state.py for the other end of the chain (the
    engine computing that score FROM screening_rr in the first place)."""
    sim = TradeSimulator(ExecutionConfig())
    signal = _signal(SignalDirection.BULLISH, stop=95.0, target=110.0)
    signal = signal.model_copy(update={"risk_reward_ratio": 5.0})  # screening_rr, fed to opportunity scoring upstream

    precomputed_score = 0.73  # stands in for consumer._opportunity_score(signal, qc)'s output
    sim.open_position(signal, entry_timestamp=_dt(0), entry_price_raw=100.0, opportunity_score=precomputed_score)
    trade = sim.check_exit("AAPL", _dt(1), bar_high=111.0, bar_low=99.0)

    # execution_rr (2.0: reward 10 / risk 5 at the REAL fill) is nowhere
    # near screening_rr (5.0, what actually fed opportunity scoring) --
    # yet opportunity_score is untouched by that divergence.
    assert trade.execution_rr == pytest.approx(2.0)
    assert trade.screening_rr == pytest.approx(5.0)
    assert trade.execution_rr != pytest.approx(trade.screening_rr)
    assert trade.opportunity_score == pytest.approx(precomputed_score)
