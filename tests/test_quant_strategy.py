"""
tests/test_quant_strategy.py
---------------------------------
Tests talonx_quant.strategy.evaluate_signals -- a pure function over an
IndicatorSnapshot, so these are constructed directly rather than driven
through the full buffer/indicators pipeline. Covers the two noise filters
added on top of the original crossover logic: edge-triggering for the
RSI+volume setup (previously a level check that would re-fire every bar)
and hysteresis for the MA crossover (previously fired on any nonzero
spread, however small).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from talonx_quant.config import QuantConfig
from talonx_quant.indicators import IndicatorSnapshot
from talonx_quant.schemas import SignalType
from talonx_quant.strategy import evaluate_signals


def _snapshot(**overrides) -> IndicatorSnapshot:
    defaults = dict(
        price=100.0,
        bar_timestamp=datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc),
        rsi=None,
        rsi_prev=None,
        macd=None,
        macd_signal_line=None,
        macd_prev=None,
        macd_signal_line_prev=None,
        sma_fast=None,
        sma_slow=None,
        sma_fast_prev=None,
        sma_slow_prev=None,
        volume=None,
        volume_avg=None,
        volume_surge_ratio=None,
    )
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


@pytest.fixture
def config() -> QuantConfig:
    return QuantConfig()


# --- RSI + volume setup: edge-triggering ---------------------------------

def test_rsi_volume_setup_fires_on_the_crossing_bar(config):
    snap = _snapshot(rsi=28.0, rsi_prev=32.0, volume_surge_ratio=3.0)  # crossed under 30 this bar

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE


def test_rsi_volume_setup_does_not_refire_while_still_oversold(config):
    # RSI was already under 30 on the previous bar too -- no fresh crossing.
    snap = _snapshot(rsi=20.0, rsi_prev=25.0, volume_surge_ratio=3.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


def test_rsi_volume_setup_requires_volume_surge_on_the_crossing_bar(config):
    snap = _snapshot(rsi=28.0, rsi_prev=32.0, volume_surge_ratio=1.2)  # below 2.0x threshold

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


def test_rsi_volume_setup_fires_overbought_on_the_crossing_bar(config):
    snap = _snapshot(rsi=72.0, rsi_prev=68.0, volume_surge_ratio=2.5)  # crossed over 70 this bar

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.RSI_OVERBOUGHT_VOLUME_SURGE


# --- MACD crossover (regression baseline, unchanged behavior) ------------

def test_macd_bullish_cross_fires_on_the_crossing_bar(config):
    snap = _snapshot(macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01)

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.MACD_BULLISH_CROSS


def test_macd_does_not_refire_while_still_above(config):
    snap = _snapshot(macd=0.05, macd_signal_line=0.02, macd_prev=0.04, macd_signal_line_prev=0.01)

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


# --- MA crossover: hysteresis ---------------------------------------------

def test_ma_crossover_fires_when_spread_clears_hysteresis(config):
    # 500 * 0.0015 = 0.75 minimum spread; give it 1.00 -- a real crossover.
    snap = _snapshot(price=500.0, sma_fast=138.0, sma_slow=137.0, sma_fast_prev=136.5, sma_slow_prev=137.0)

    signals = evaluate_signals("MSFT", snap, config)

    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.MA_GOLDEN_CROSS


def test_ma_crossover_suppressed_by_micro_spread(config):
    # The exact scenario from the noise report: a $0.03 drift on a $500
    # stock (~0.006%), technically a crossover but far under the 0.15%
    # (=$0.75) minimum spread -- should NOT fire.
    snap = _snapshot(
        price=500.0, sma_fast=137.93, sma_slow=137.90, sma_fast_prev=137.89, sma_slow_prev=137.90
    )

    signals = evaluate_signals("MSFT", snap, config)

    assert signals == []


def test_ma_death_cross_fires_when_spread_clears_hysteresis(config):
    snap = _snapshot(price=500.0, sma_fast=136.0, sma_slow=137.0, sma_fast_prev=137.5, sma_slow_prev=137.0)

    signals = evaluate_signals("MSFT", snap, config)

    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.MA_DEATH_CROSS


# --- Multiple independent signals on one bar (unchanged design) ----------

def test_multiple_signal_types_can_fire_on_the_same_bar(config):
    snap = _snapshot(
        rsi=28.0, rsi_prev=32.0, volume_surge_ratio=3.0,
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,
    )

    signals = evaluate_signals("AAPL", snap, config)

    signal_types = {s.signal_type for s in signals}
    assert signal_types == {SignalType.RSI_OVERSOLD_VOLUME_SURGE, SignalType.MACD_BULLISH_CROSS}
