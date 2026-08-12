"""
tests/test_quant_strategy.py
---------------------------------
Tests talonx_quant.strategy.evaluate_signals -- a pure function over an
IndicatorSnapshot, so these are constructed directly rather than driven
through the full buffer/indicators pipeline. Covers the noise filters on
top of the original crossover logic: edge-triggering for the RSI+volume
setup (previously a level check that would re-fire every bar), hysteresis
for the MA crossover (previously fired on any nonzero spread, however
small), the ATR-move gate (a signal's own bar must clear
atr_move_multiplier x ATR to count as a real move, not routine noise),
and the bar-level confluence_score/risk_reward_ratio computations
attached to every signal.

_snapshot()'s atr/bar_true_range defaults (1.0 / 2.0) deliberately CLEAR
the default atr_move_multiplier=1.0 gate, so every pre-existing test below
keeps testing what it always tested rather than being silently suppressed
by the newer ATR gate -- tests that specifically exercise the gate
override these two fields.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from talonx_quant.config import QuantConfig
from talonx_quant.indicators import IndicatorSnapshot
from talonx_quant.schemas import SignalType
from talonx_quant.strategy import _confluence_score, _risk_reward_ratio, evaluate_signals


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
        atr=1.0,
        bar_true_range=2.0,  # clears the default 1.0x ATR move gate
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


# --- ATR-move gate (analyst-review addition) -------------------------------

def test_signal_suppressed_when_bar_true_range_under_atr_multiple(config):
    # RSI setup would otherwise fire, but this bar's own true range (0.5)
    # is under 1.0x ATR (1.0) -- a routine, average-sized bar, not the
    # genuine directional move the analyst review required.
    snap = _snapshot(rsi=28.0, rsi_prev=32.0, volume_surge_ratio=3.0, atr=1.0, bar_true_range=0.5)

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


def test_signal_suppressed_when_atr_is_missing(config):
    # Fails OPEN (no signal) when ATR hasn't warmed up yet, same posture
    # every other insufficient-data check in this module takes.
    snap = _snapshot(rsi=28.0, rsi_prev=32.0, volume_surge_ratio=3.0, atr=None, bar_true_range=None)

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


def test_signal_fires_when_bar_true_range_exactly_equals_atr_multiple(config):
    snap = _snapshot(rsi=28.0, rsi_prev=32.0, volume_surge_ratio=3.0, atr=1.0, bar_true_range=1.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1


# --- Confluence score (bar-level, shared across every signal that bar) ----

def test_confluence_score_counts_all_three_factors(config):
    snap = _snapshot(
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,  # MACD cross
        rsi=25.0,  # in oversold zone
        volume_surge_ratio=3.0,  # above threshold
    )

    assert _confluence_score(snap, config) == 3


def test_confluence_score_is_zero_when_nothing_qualifies(config):
    snap = _snapshot(rsi=50.0, volume_surge_ratio=1.0)

    assert _confluence_score(snap, config) == 0


def test_confluence_score_counts_rsi_extreme_without_a_fresh_cross(config):
    # RSI sitting in the extreme zone counts even without rsi_prev set to
    # show a fresh crossing -- confluence asks "is conviction high right
    # now," not "did this specific indicator just cross."
    snap = _snapshot(rsi=22.0)

    assert _confluence_score(snap, config) == 1


def test_confluence_score_is_shared_across_every_signal_on_the_bar(config):
    snap = _snapshot(
        rsi=28.0, rsi_prev=32.0, volume_surge_ratio=3.0,
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,
    )

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 2
    assert signals[0].confluence_score == signals[1].confluence_score == 3


# --- Risk/reward ratio -----------------------------------------------------

def test_risk_reward_ratio_uses_atr_reward_over_stop_loss_risk(config):
    # reward = 1.5 * atr(2.0) = 3.0; risk = 0.005 * price(100.0) = 0.5
    # ratio = 3.0 / 0.5 = 6.0
    snap = _snapshot(price=100.0, atr=2.0)

    ratio = _risk_reward_ratio(snap, config)

    assert ratio == pytest.approx(6.0)


def test_risk_reward_ratio_is_none_when_atr_missing(config):
    snap = _snapshot(price=100.0, atr=None)

    assert _risk_reward_ratio(snap, config) is None


def test_risk_reward_ratio_is_none_when_price_is_zero(config):
    snap = _snapshot(price=0.0, atr=2.0)

    assert _risk_reward_ratio(snap, config) is None


def test_risk_reward_ratio_varies_with_atr_unlike_the_naive_formula(config):
    # A sanity check on the analyst-review correction: pairing two
    # multiples of the SAME atr value (e.g. 1.5x/0.75x) always produces a
    # constant 2.0 regardless of market data. This formula must NOT do
    # that -- two different ATR values against the same price must
    # produce two different ratios.
    low_vol = _risk_reward_ratio(_snapshot(price=100.0, atr=0.5), config)
    high_vol = _risk_reward_ratio(_snapshot(price=100.0, atr=5.0), config)

    assert low_vol != high_vol


def test_signal_carries_atr_confluence_and_risk_reward(config):
    snap = _snapshot(
        rsi=28.0, rsi_prev=32.0, volume_surge_ratio=3.0, atr=2.0, bar_true_range=2.0,
    )

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].atr == 2.0
    assert signals[0].confluence_score == 2  # RSI extreme + volume surge, no MACD cross
    assert signals[0].risk_reward_ratio == pytest.approx(6.0)
