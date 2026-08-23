"""
tests/test_backtest_preroll.py
--------------------------------
Task 53 -- causal PRE-ROLL/WARMUP mechanism (BacktestEngine.run(df, warmup_df=...)).

Central property under test: pre-roll reconstructs the SAME causal market
state (1m/15m/60m buffers, indicators, HTF SMA, daily pivots, volatility
regime) as a continuous run over warmup+evaluation combined, while (a) never
generating candidates/rejections/signals/trades/cooldown/loss-lockout/
throttle activity during the warmup portion, and (b) never counting warmup
bars toward bars_processed/evaluation metrics. A plain run(df) with no
warmup_df must remain byte-for-byte the pre-Task-53 behavior.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from talonx_backtest.data import from_dataframe
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_quant.config import QuantConfig
from talonx_quant.indicators import compute_daily_pivots, compute_htf_trend, compute_indicators, compute_volatility_regime, evaluate_regime

_START = datetime(2026, 1, 5, 15, 0, tzinfo=timezone.utc)  # 10:00 ET, regular session


def _small_config() -> QuantConfig:
    """Deliberately tiny htf_sma_period (5, vs the real 200) so the fixture
    can be small/fast -- tests the PRE-ROLL MECHANISM (parity/causality/
    no-contamination), not the real-world 200-bar magnitude (that's
    exercised by the actual Task 53 A/B replay, not a unit test).
    min_bars_required is left at its documented-safe default (must be >=
    macd_slow+macd_signal=35 for compute_indicators to behave -- see
    config.py's own docstring); shrinking it independently is NOT a valid
    way to speed up this fixture and breaks pandas_ta's MACD computation
    on a too-small buffer."""
    return dataclasses.replace(
        QuantConfig(), atr_move_multiplier=0.0, htf_sma_period=5,
    )


def _bars_df(n: int, start: datetime, symbol: str = "AAPL") -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n):
        price += 0.05 if i % 2 == 0 else -0.03
        vol = 1200.0 + (i % 5) * 50
        rows.append({
            "timestamp": start + timedelta(minutes=i), "open": price, "high": price + 0.4,
            "low": price - 0.4, "close": price, "volume": vol,
        })
    return from_dataframe(pd.DataFrame(rows), symbol=symbol)


# ======================================================================
# Causality
# ======================================================================

def test_warmup_must_be_strictly_earlier_than_evaluation():
    config = _small_config()
    bc = BacktestConfig(quant_config=config, eod_flatten_enabled=False)
    warmup = _bars_df(150, _START)
    # overlapping: evaluation starts BEFORE warmup ends
    overlapping_eval = _bars_df(20, _START + timedelta(minutes=100))
    engine = BacktestEngine(bc)
    with pytest.raises(ValueError, match="strictly earlier"):
        engine.run(overlapping_eval, warmup_df=warmup)


def test_warmup_exactly_adjacent_to_evaluation_is_allowed():
    config = _small_config()
    bc = BacktestConfig(quant_config=config, eod_flatten_enabled=False)
    warmup = _bars_df(150, _START)
    evaluation = _bars_df(10, _START + timedelta(minutes=150))  # starts exactly where warmup ends
    engine = BacktestEngine(bc)
    result = engine.run(evaluation, warmup_df=warmup)  # must not raise
    assert result.warmup_bars_processed == 150
    assert result.bars_processed == 10


# ======================================================================
# State-only warmup: no strategy activity
# ======================================================================

def test_warmup_produces_no_signals_rejections_trades():
    config = _small_config()
    bc = BacktestConfig(quant_config=config, eod_flatten_enabled=False)
    warmup = _bars_df(150, _START)
    # empty df would short-circuit before warmup even runs (see run()'s own df.empty
    # check) -- use a 1-bar evaluation instead to actually exercise the warmup path.
    evaluation = _bars_df(1, _START + timedelta(minutes=150))
    engine = BacktestEngine(bc, research_telemetry=True)
    result = engine.run(evaluation, warmup_df=warmup)
    assert result.warmup_bars_processed == 150
    assert engine.signals_generated == 0 or all(
        c["timestamp"] >= evaluation["timestamp"].min() for c in engine.candidate_telemetry
    )
    assert all(r.timestamp >= evaluation["timestamp"].min() for r in result.rejections)
    assert result.trades == []


def test_warmup_does_not_arm_cooldown_or_loss_lockout():
    config = _small_config()
    bc = BacktestConfig(quant_config=config, eod_flatten_enabled=False)
    warmup = _bars_df(150, _START)
    evaluation = _bars_df(5, _START + timedelta(minutes=150))
    engine = BacktestEngine(bc)
    engine.run(evaluation, warmup_df=warmup)
    assert engine._cooldown_until == {}
    assert engine._loss_lockout_until == {}
    assert engine._pending_entry == {}
    assert engine._pending_exit == {}


# ======================================================================
# No evaluation contamination
# ======================================================================

def test_bars_processed_excludes_warmup():
    config = _small_config()
    bc = BacktestConfig(quant_config=config, eod_flatten_enabled=False)
    warmup = _bars_df(150, _START)
    evaluation = _bars_df(10, _START + timedelta(minutes=150))
    engine = BacktestEngine(bc)
    result = engine.run(evaluation, warmup_df=warmup)
    assert result.bars_processed == 10  # NOT 160
    assert result.warmup_bars_processed == 150
    assert result.start == evaluation["timestamp"].min()
    assert result.end == evaluation["timestamp"].max()


# ======================================================================
# Backward compatibility
# ======================================================================

def test_no_warmup_df_is_byte_identical_to_pre_task53_behavior():
    config = _small_config()
    bc = BacktestConfig(quant_config=config, eod_flatten_enabled=False)
    df = _bars_df(30, _START)
    engine = BacktestEngine(bc, research_telemetry=True)
    result = engine.run(df)  # no warmup_df at all
    assert result.warmup_bars_processed == 0
    assert result.bars_processed == 30
    assert engine.warmup_bars_processed == 0


# ======================================================================
# Continuous vs split parity -- the central proof
# ======================================================================

def test_continuous_vs_split_state_parity():
    config = _small_config()
    bc = BacktestConfig(quant_config=config, eod_flatten_enabled=False)
    warmup = _bars_df(150, _START)
    evaluation = _bars_df(10, _START + timedelta(minutes=150))
    continuous = pd.concat([warmup, evaluation], ignore_index=True)

    engine_a = BacktestEngine(bc, research_telemetry=True)  # PATH A: continuous
    engine_a.run(continuous)

    engine_b = BacktestEngine(bc, research_telemetry=True)  # PATH B: warmup + evaluation
    engine_b.run(evaluation, warmup_df=warmup)

    symbol = "AAPL"
    # 1m buffer tail
    df_a = engine_a.buffer.get_dataframe(symbol)
    df_b = engine_b.buffer.get_dataframe(symbol)
    pd.testing.assert_frame_equal(df_a.reset_index(drop=True), df_b.reset_index(drop=True))

    # IndicatorSnapshot
    qc = bc.quant_config
    snap_a = compute_indicators(df_a, qc)
    snap_b = compute_indicators(df_b, qc)
    assert snap_a == snap_b

    # 15m HTF buffer + htf_sma_200
    htf_a = engine_a.buffer_htf.get_dataframe(symbol)
    htf_b = engine_b.buffer_htf.get_dataframe(symbol)
    pd.testing.assert_frame_equal(htf_a.reset_index(drop=True), htf_b.reset_index(drop=True))
    assert compute_htf_trend(htf_a, qc.htf_sma_period) == compute_htf_trend(htf_b, qc.htf_sma_period)

    # daily pivots
    assert compute_daily_pivots(htf_a, df_a.index[-1]) == compute_daily_pivots(htf_b, df_b.index[-1])

    # 60m buffer + regime
    b60_a = engine_a.buffer_60m.get_dataframe(symbol)
    b60_b = engine_b.buffer_60m.get_dataframe(symbol)
    pd.testing.assert_frame_equal(b60_a.reset_index(drop=True), b60_b.reset_index(drop=True))
    ts = df_a.index[-1]
    regime_a = compute_volatility_regime(htf_a, b60_a, qc.atr_period, ts)
    regime_b = compute_volatility_regime(htf_b, b60_b, qc.atr_period, ts)
    assert regime_a == regime_b
    assert evaluate_regime(regime_a) == evaluate_regime(regime_b)

    # contamination proof, alongside parity: engine_b's rejections/candidate_telemetry
    # must contain nothing from the warmup period
    assert all(r.timestamp >= evaluation["timestamp"].min() for r in engine_b.rejections)
    assert all(c["timestamp"] >= evaluation["timestamp"].min() for c in engine_b.candidate_telemetry)


def test_first_evaluation_bar_readiness_with_sufficient_warmup():
    """Explicit readiness check (step 9): with >= htf_sma_period warmup 15m
    bars available, htf_sma_200 must be non-None at/near the first
    evaluation bar -- not "eventually", not after several more days."""
    config = _small_config()  # htf_sma_period=5 -- needs 5*15=75 min of RTH 15m bars
    bc = BacktestConfig(quant_config=config, eod_flatten_enabled=False)
    warmup = _bars_df(150, _START)  # 150 min of regular-session bars -> 10 complete 15m bars, well over 5
    evaluation = _bars_df(1, _START + timedelta(minutes=150))
    engine = BacktestEngine(bc)
    engine.run(evaluation, warmup_df=warmup)
    htf_df = engine.buffer_htf.get_dataframe("AAPL")
    assert compute_htf_trend(htf_df, config.htf_sma_period) is not None, "HTF SMA should be READY after sufficient warmup"


def test_insufficient_warmup_reports_not_ready_honestly():
    config = _small_config()  # needs 5 completed 15m bars = 75 min
    bc = BacktestConfig(quant_config=config, eod_flatten_enabled=False)
    warmup = _bars_df(30, _START)  # only 30 min -> at most 2 completed 15m bars, short of 5
    evaluation = _bars_df(1, _START + timedelta(minutes=30))
    engine = BacktestEngine(bc)
    engine.run(evaluation, warmup_df=warmup)
    htf_df = engine.buffer_htf.get_dataframe("AAPL")
    assert compute_htf_trend(htf_df, config.htf_sma_period) is None, "HTF SMA should be honestly NOT_READY with insufficient warmup"
