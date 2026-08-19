"""
tests/test_backtest_fill_geometry.py
------------------------------------------
2026-08-19 correctness fix (Task 13 defect, Task 13B): BacktestEngine.
_finalize_fill_geometry -- closes the gap between _revalidate's throttle-
flush-time geometry (bar N close) and the actual fill (bar N+1's open).
A real price gap between those two bars could previously leave a
revalidated stop_price on the WRONG SIDE of the price a position actually
filled at (execution.py's risk = abs(entry_price_raw - stop_price)
tolerates any sign), producing a "STOP" exit that was actually a
favorable move mislabeled as a loss, always net_R=+1.0 exactly. Confirmed
against 6 real historical trades in Task 13's own output before this fix
existed (see task13b_summary.md for the full reproduction).

Deliberately narrow fix, deliberately narrow tests: only the case where
the pre-existing stop/target has ALREADY been invalidated by the fill
price triggers a recompute; the far more common "fill differs slightly
but stop/target still correctly bracket it" case is untouched, preserving
tests/test_backtest_execution.py's existing execution_rr-diverges-from-
screening_rr behavior.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from talonx_backtest.engine import BacktestConfig, BacktestEngine, _PendingEntry
from talonx_quant.config import QuantConfig
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType

_NOW = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)


def _signal(
    direction: SignalDirection, price: float, stop_price: float, target_price: float,
    pivot_resistance: float | None, pivot_support: float | None, atr: float = 1.0,
    risk_reward_ratio: float = 5.0,
) -> QuantSignal:
    return QuantSignal(
        ticker="AAPL", signal_type=SignalType.MACD_BULLISH_CROSS, direction=direction,
        message="test", price=price, atr=atr, confluence_score=2, risk_reward_ratio=risk_reward_ratio,
        stop_price=stop_price, target_price=target_price,
        pivot_resistance=pivot_resistance, pivot_support=pivot_support,
        session="regular", bar_timestamp=_NOW, signal_generated_at=_NOW,
    )


@pytest.fixture
def engine() -> BacktestEngine:
    # atr_stop_multiplier=1.5 (default), atr_reward_multiplier=2.0 (default),
    # min_risk_reward_ratio=1.5 (default) -- unchanged, matches QuantConfig()'s
    # own frozen defaults.
    return BacktestEngine(BacktestConfig(quant_config=QuantConfig(), eod_flatten_enabled=False))


# --- LONG: normal fills (geometry untouched) ------------------------------

def test_normal_long_fill_within_bracket_leaves_geometry_unchanged(engine):
    signal = _signal(SignalDirection.BULLISH, price=100.0, stop_price=98.5, target_price=110.0,
                      pivot_resistance=110.0, pivot_support=90.0)
    result = engine._finalize_fill_geometry(signal, fill_price=100.3, now=_NOW)

    assert result is not None
    assert result.stop_price == pytest.approx(98.5)
    assert result.target_price == pytest.approx(110.0)
    assert engine.rejections == []


def test_gap_that_does_not_invalidate_stop_is_left_alone(engine):
    # fill moved from 100 to 99.0 -- still safely inside (98.5, 110).
    signal = _signal(SignalDirection.BULLISH, price=100.0, stop_price=98.5, target_price=110.0,
                      pivot_resistance=110.0, pivot_support=90.0)
    result = engine._finalize_fill_geometry(signal, fill_price=99.0, now=_NOW)

    assert result.stop_price == pytest.approx(98.5)
    assert result.target_price == pytest.approx(110.0)


# --- SHORT: normal fills (geometry untouched) ------------------------------

def test_normal_short_fill_within_bracket_leaves_geometry_unchanged(engine):
    signal = _signal(SignalDirection.BEARISH, price=100.0, stop_price=101.5, target_price=90.0,
                      pivot_resistance=110.0, pivot_support=90.0)
    result = engine._finalize_fill_geometry(signal, fill_price=99.7, now=_NOW)

    assert result.stop_price == pytest.approx(101.5)
    assert result.target_price == pytest.approx(90.0)
    assert engine.rejections == []


# --- LONG: gap through stop -------------------------------------------------

def test_long_gap_through_stop_recomputes_geometry_anchored_to_fill(engine):
    # Revalidated at price=100 (stop=98.5), but the ACTUAL fill gapped down
    # to 98.0 -- BELOW the revalidated stop -- exactly the Task 13 defect
    # pattern (a real PYPL case: stop 69.6173 > fill 69.37 for a bullish trade).
    signal = _signal(SignalDirection.BULLISH, price=100.0, stop_price=98.5, target_price=110.0,
                      pivot_resistance=110.0, pivot_support=90.0, atr=1.0)
    result = engine._finalize_fill_geometry(signal, fill_price=98.0, now=_NOW)

    assert result is not None
    # New stop anchored to the REAL fill: 98.0 - 1.5*1.0 = 96.5
    assert result.stop_price == pytest.approx(96.5)
    # Target still the pivot (110.0 > fill, still structurally valid)
    assert result.target_price == pytest.approx(110.0)
    # Required invariant holds by construction:
    assert result.stop_price < 98.0 < result.target_price
    assert engine.rejections == []


def test_long_gap_through_stop_screening_rr_is_never_overwritten(engine):
    """screening_rr (signal.risk_reward_ratio) is the strategy's gate-time
    R:R and must never be recalculated against the fill (see execution.py's
    own docstring on execution_rr) -- only stop/target are re-anchored."""
    signal = _signal(SignalDirection.BULLISH, price=100.0, stop_price=98.5, target_price=110.0,
                      pivot_resistance=110.0, pivot_support=90.0, risk_reward_ratio=17.18)
    result = engine._finalize_fill_geometry(signal, fill_price=98.0, now=_NOW)

    assert result.risk_reward_ratio == pytest.approx(17.18)


# --- SHORT: gap through stop -------------------------------------------------

def test_short_gap_through_stop_recomputes_geometry_anchored_to_fill(engine):
    # Revalidated at price=100 (stop=101.5), but the ACTUAL fill gapped up
    # to 102.0 -- ABOVE the revalidated stop -- the bearish mirror of the
    # Task 13 defect (a real STX case: stop 431.369 < fill 432.50 for a
    # bearish trade).
    signal = _signal(SignalDirection.BEARISH, price=100.0, stop_price=101.5, target_price=90.0,
                      pivot_resistance=110.0, pivot_support=90.0, atr=1.0)
    result = engine._finalize_fill_geometry(signal, fill_price=102.0, now=_NOW)

    assert result is not None
    # New stop anchored to the REAL fill: 102.0 + 1.5*1.0 = 103.5
    assert result.stop_price == pytest.approx(103.5)
    assert result.target_price == pytest.approx(90.0)
    assert result.target_price < 102.0 < result.stop_price
    assert engine.rejections == []


# --- Severe gap: recomputed geometry still fails the R:R gate -> reject ----

def test_severe_gap_rejects_entry_when_recomputed_rr_fails_gate(engine):
    # Bearish, atr=1.0 -> fixed risk = 1.5*1.0 = 1.5. Original stop (99.0)
    # is below fill (100.0) -- invalidated, triggers recompute. Recomputed
    # target uses pivot_support=98.5 (now very close to the fill price),
    # so reward = |100.0 - 98.5| = 1.5 -> R:R = 1.5/1.5 = 1.0, below the
    # 1.5 gate -- must reject, not silently publish a sub-gate trade.
    signal = _signal(SignalDirection.BEARISH, price=95.0, stop_price=99.0, target_price=80.0,
                      pivot_resistance=110.0, pivot_support=98.5, atr=1.0)
    result = engine._finalize_fill_geometry(signal, fill_price=100.0, now=_NOW)

    assert result is None
    assert len(engine.rejections) == 1
    assert engine.rejections[0].reason == "GEOMETRY_INVALIDATED_AT_FILL"
    assert engine.rejections[0].ticker == "AAPL"
    assert engine.rejections[0].count == 1


def test_missing_stop_or_target_passes_through_unchanged(engine):
    # Nothing to validate against -- unchanged, matches
    # test_backtest_execution.py's existing missing-stop/target coverage.
    signal = _signal(SignalDirection.BULLISH, price=100.0, stop_price=98.5, target_price=110.0,
                      pivot_resistance=110.0, pivot_support=90.0).model_copy(update={"stop_price": None})
    result = engine._finalize_fill_geometry(signal, fill_price=50.0, now=_NOW)

    assert result is signal
    assert engine.rejections == []


# --- Net_R sign correctness / no-fabricated-win invariant ------------------

def test_no_stop_exit_can_become_plus_one_r_from_a_wrong_side_stop(engine):
    """End-to-end through the real _process_symbol_bar wiring (not just the
    helper in isolation): a candidate whose stop would have landed on the
    wrong side of the fill must never produce a net_R=+1.0 'STOP' trade --
    it must either open with a correctly-re-anchored stop (and lose money
    on any subsequent bar low <= stop, since a losing exit must be
    net_R<=0), or be rejected outright."""
    import pandas as pd

    signal = _signal(SignalDirection.BULLISH, price=100.0, stop_price=98.5, target_price=110.0,
                      pivot_resistance=110.0, pivot_support=90.0, atr=1.0)
    engine._pending_entry["AAPL"] = _PendingEntry(signal=signal, opportunity_score=0.5)

    # Fill bar: opens at 98.0 (gapped through the stale stop), then
    # immediately trades down to 96.5 -- exactly the recomputed stop level.
    fill_bar = pd.Series({"open": 98.0, "high": 98.2, "low": 96.5, "close": 96.6, "volume": 1000.0})
    engine._process_symbol_bar("AAPL", _NOW, fill_bar, candidates=[])

    assert len(engine.trades) == 1
    trade = engine.trades[0]
    assert trade.exit_reason == "STOP"
    assert trade.stop_price < trade.entry_price  # invariant held at execution time
    assert trade.net_R == pytest.approx(-1.0)  # a genuine loss, never a fabricated +1.0
