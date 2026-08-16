"""
tests/test_quant_strategy.py
---------------------------------
Tests talonx_quant.strategy.evaluate_signals -- a pure function over an
IndicatorSnapshot, so these are constructed directly rather than driven
through the full buffer/indicators pipeline. Covers the noise filters on
top of the original crossover logic: edge-triggering for the RSI+volume
setup, hysteresis for the MA crossover, the ATR-move gate, and the
per-signal (direction-aware) confluence_score/risk_reward_ratio
computations attached to every signal.

Also covers the 2026-08-16 requirement-doc gap fixes:
  - Direction-Aware Confluence (_confluence_score now takes `direction`).
  - Structural R:R Calculation (_structural_risk_reward, pivot-based).
  - RSI Reversal Curl (_check_rsi_volume_setup's bullish leg fires on
    RECOVERY above rsi_oversold, not the initial dip below it).

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
from talonx_quant.indicators import DailyPivots, IndicatorSnapshot
from talonx_quant.schemas import SignalDirection, SignalType
from talonx_quant.strategy import _confluence_score, _structural_risk_reward, evaluate_signals


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
        dollar_volume_avg=None,
        atr=1.0,
        bar_true_range=2.0,  # clears the default 1.0x ATR move gate
    )
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


def _pivots(resistance: float, support: float, pivot: float | None = None) -> DailyPivots:
    return DailyPivots(pivot=pivot if pivot is not None else (resistance + support) / 2, resistance=resistance, support=support)


@pytest.fixture
def config() -> QuantConfig:
    return QuantConfig()


# --- RSI + volume setup: RSI Reversal Curl (bullish waits for recovery) --

def test_rsi_volume_setup_fires_on_the_recovery_bar(config):
    # RSI was oversold (28) last bar, recovered back to 32 (>= 30) this bar.
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE
    assert signals[0].direction == SignalDirection.BULLISH


def test_rsi_volume_setup_does_not_fire_on_the_initial_dip_below_oversold(config):
    # RSI Reversal Curl: dropping INTO oversold (32 -> 28) must NOT fire a
    # buy on its own anymore -- only the recovery back above 30 does.
    snap = _snapshot(rsi=28.0, rsi_prev=32.0, volume_surge_ratio=3.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


def test_rsi_volume_setup_does_not_refire_while_already_recovered(config):
    # Both this bar and the previous bar are already at/above 30 -- no
    # fresh recovery edge.
    snap = _snapshot(rsi=35.0, rsi_prev=32.0, volume_surge_ratio=3.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


def test_rsi_volume_setup_requires_volume_surge_on_the_recovery_bar(config):
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=1.2)  # below 2.0x threshold

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


def test_rsi_volume_setup_fires_overbought_on_the_crossing_bar(config):
    # Bearish leg unchanged: still fires on the initial cross INTO overbought.
    snap = _snapshot(rsi=72.0, rsi_prev=68.0, volume_surge_ratio=2.5)

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
        rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0,  # RSI recovery
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
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, atr=1.0, bar_true_range=0.5)

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


def test_signal_suppressed_when_atr_is_missing(config):
    # Fails OPEN (no signal) when ATR hasn't warmed up yet, same posture
    # every other insufficient-data check in this module takes.
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, atr=None, bar_true_range=None)

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


def test_signal_fires_when_bar_true_range_exactly_equals_atr_multiple(config):
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, atr=1.0, bar_true_range=1.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1


# --- Direction-Aware Confluence --------------------------------------------

def test_confluence_bullish_counts_oversold_rsi(config):
    snap = _snapshot(rsi=22.0)  # oversold -- supports a BULLISH read

    assert _confluence_score(snap, config, config.volume_surge_ratio_threshold, SignalDirection.BULLISH) == 1


def test_confluence_bullish_scores_zero_for_overbought_rsi(config):
    # The core Direction-Aware Confluence fix: an overbought bar (> 70)
    # must earn a BULLISH candidate ZERO points for the RSI leg.
    snap = _snapshot(rsi=75.0)

    assert _confluence_score(snap, config, config.volume_surge_ratio_threshold, SignalDirection.BULLISH) == 0


def test_confluence_bearish_counts_overbought_rsi(config):
    snap = _snapshot(rsi=75.0)  # overbought -- supports a BEARISH read

    assert _confluence_score(snap, config, config.volume_surge_ratio_threshold, SignalDirection.BEARISH) == 1


def test_confluence_bearish_scores_zero_for_oversold_rsi(config):
    snap = _snapshot(rsi=22.0)

    assert _confluence_score(snap, config, config.volume_surge_ratio_threshold, SignalDirection.BEARISH) == 0


def test_confluence_score_counts_all_three_factors_bullish(config):
    snap = _snapshot(
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,  # MACD cross
        rsi=25.0,  # oversold -- supports BULLISH
        volume_surge_ratio=3.0,  # above threshold
    )

    assert _confluence_score(snap, config, config.volume_surge_ratio_threshold, SignalDirection.BULLISH) == 3


def test_confluence_score_is_zero_when_nothing_qualifies(config):
    snap = _snapshot(rsi=50.0, volume_surge_ratio=1.0)

    assert _confluence_score(snap, config, config.volume_surge_ratio_threshold, SignalDirection.BULLISH) == 0


def test_confluence_score_is_computed_per_signal_direction(config):
    # A MACD bullish cross AND overbought RSI on the same bar: the MACD
    # signal is BULLISH (RSI leg scores 0, overbought doesn't support a
    # long), while a hypothetical BEARISH read of the same bar would
    # score the RSI leg -- direction-specific, not a single shared value.
    snap = _snapshot(
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,
        rsi=75.0, volume_surge_ratio=3.0,
    )

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.MACD_BULLISH_CROSS
    # MACD cross (1) + volume surge (1) + RSI leg (0, overbought doesn't
    # support a bullish read) = 2, not 3.
    assert signals[0].confluence_score == 2


# --- Structural R:R Calculation --------------------------------------------

def test_structural_rr_uses_pivot_resistance_and_pivot_stop_atr_multiplier(config):
    # reward = resistance(110) - price(100) = 10; risk = 1.5 * atr(2) = 3
    snap = _snapshot(price=100.0, atr=2.0)
    pivots = _pivots(resistance=110.0, support=90.0)

    ratio = _structural_risk_reward(snap, SignalDirection.BULLISH, pivots, config)

    assert ratio == pytest.approx(10.0 / 3.0)


def test_structural_rr_bearish_uses_pivot_support(config):
    # reward = price(100) - support(92) = 8; risk = 1.5 * atr(2) = 3
    snap = _snapshot(price=100.0, atr=2.0)
    pivots = _pivots(resistance=115.0, support=92.0)

    ratio = _structural_risk_reward(snap, SignalDirection.BEARISH, pivots, config)

    assert ratio == pytest.approx(8.0 / 3.0)


def test_structural_rr_is_none_when_pivots_unavailable(config):
    snap = _snapshot(price=100.0, atr=2.0)

    assert _structural_risk_reward(snap, SignalDirection.BULLISH, None, config) is None


def test_structural_rr_is_none_when_atr_missing(config):
    snap = _snapshot(price=100.0, atr=None)
    pivots = _pivots(resistance=110.0, support=90.0)

    assert _structural_risk_reward(snap, SignalDirection.BULLISH, pivots, config) is None


def test_structural_rr_is_none_when_price_already_through_resistance(config):
    # No room left to a bullish target -- price already at/above R1.
    snap = _snapshot(price=112.0, atr=2.0)
    pivots = _pivots(resistance=110.0, support=90.0)

    assert _structural_risk_reward(snap, SignalDirection.BULLISH, pivots, config) is None


def test_structural_rr_varies_with_pivot_distance_not_a_constant(config):
    # Unlike the old ATR-multiple-only ratio, this genuinely varies with
    # market-derived pivot distance, not just the configured multipliers.
    snap = _snapshot(price=100.0, atr=2.0)
    tight = _structural_risk_reward(snap, SignalDirection.BULLISH, _pivots(resistance=103.0, support=90.0), config)
    wide = _structural_risk_reward(snap, SignalDirection.BULLISH, _pivots(resistance=130.0, support=90.0), config)

    assert tight != wide


def test_signal_carries_structural_risk_reward_and_pivots(config):
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, atr=2.0, bar_true_range=2.0, price=100.0)
    pivots = _pivots(resistance=110.0, support=90.0)

    signals = evaluate_signals("AAPL", snap, config, daily_pivots=pivots)

    assert len(signals) == 1
    assert signals[0].atr == 2.0
    assert signals[0].risk_reward_ratio == pytest.approx(10.0 / 3.0)
    assert signals[0].pivot_resistance == pytest.approx(110.0)
    assert signals[0].pivot_support == pytest.approx(90.0)


def test_signal_risk_reward_is_none_without_pivots(config):
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, atr=2.0, bar_true_range=2.0, price=100.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].risk_reward_ratio is None
    assert signals[0].pivot_resistance is None


# --- Explicit $ stop/target -------------------------------------------------

def test_bullish_signal_target_uses_pivot_resistance_when_available(config):
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, price=100.0, atr=2.0, bar_true_range=2.0)
    pivots = _pivots(resistance=108.0, support=90.0)

    signals = evaluate_signals("AAPL", snap, config, daily_pivots=pivots)

    assert len(signals) == 1
    assert signals[0].stop_price == pytest.approx(98.0)  # atr_stop_multiplier(1.0) * atr(2.0)
    assert signals[0].target_price == pytest.approx(108.0)  # pivot resistance, not 2x ATR


def test_bullish_signal_falls_back_to_atr_target_without_pivots(config):
    # price=100, atr=2 -> stop = 100 - 1*2 = 98, target = 100 + 2*2 = 104 (fallback)
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, price=100.0, atr=2.0, bar_true_range=2.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].stop_price == pytest.approx(98.0)
    assert signals[0].target_price == pytest.approx(104.0)


def test_bearish_signal_target_uses_pivot_support_when_available(config):
    snap = _snapshot(rsi=72.0, rsi_prev=68.0, volume_surge_ratio=3.0, price=100.0, atr=2.0, bar_true_range=2.0)
    pivots = _pivots(resistance=115.0, support=93.0)

    signals = evaluate_signals("AAPL", snap, config, daily_pivots=pivots)

    assert len(signals) == 1
    assert signals[0].stop_price == pytest.approx(102.0)
    assert signals[0].target_price == pytest.approx(93.0)


def test_bearish_signal_falls_back_to_atr_target_without_pivots(config):
    # price=100, atr=2 -> stop = 100 + 1*2 = 102, target = 100 - 2*2 = 96 (fallback)
    snap = _snapshot(rsi=72.0, rsi_prev=68.0, volume_surge_ratio=3.0, price=100.0, atr=2.0, bar_true_range=2.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].stop_price == pytest.approx(102.0)
    assert signals[0].target_price == pytest.approx(96.0)


def test_stop_and_target_are_none_when_atr_missing(config):
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, atr=None, bar_true_range=None)

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []  # ATR-move gate also fails open here, nothing to assert on


# --- 15-min 200 SMA trend gate metadata (regular session, bullish only) --

def test_trend_aligned_true_when_price_above_htf_sma(config):
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, price=100.0)  # bullish, regular session

    signals = evaluate_signals("AAPL", snap, config, htf_sma_200=95.0)

    assert signals[0].trend_aligned is True
    assert signals[0].htf_sma_200 == pytest.approx(95.0)


def test_trend_aligned_false_when_price_at_or_below_htf_sma(config):
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, price=100.0)

    signals = evaluate_signals("AAPL", snap, config, htf_sma_200=105.0)

    assert signals[0].trend_aligned is False


def test_trend_aligned_is_none_when_htf_sma_not_yet_available(config):
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, price=100.0)

    signals = evaluate_signals("AAPL", snap, config, htf_sma_200=None)

    assert signals[0].trend_aligned is None


def test_trend_aligned_is_none_for_bearish_signals_regardless_of_htf_sma(config):
    # Requirement doc: the trend gate applies to BULLISH setups only.
    snap = _snapshot(rsi=72.0, rsi_prev=68.0, volume_surge_ratio=3.0, price=100.0)

    signals = evaluate_signals("AAPL", snap, config, htf_sma_200=50.0)  # would be "aligned" if checked

    assert signals[0].direction == SignalDirection.BEARISH
    assert signals[0].trend_aligned is None


def test_trend_aligned_is_none_pre_market_even_when_bullish(config):
    # 08:00 UTC = 04:00 ET -- pre-market, not regular session.
    snap = _snapshot(
        rsi=32.0, rsi_prev=28.0, volume_surge_ratio=5.0, price=100.0,
        bar_timestamp=datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc),
    )

    signals = evaluate_signals("AAPL", snap, config, htf_sma_200=50.0)

    assert signals[0].session == "pre_market"
    assert signals[0].trend_aligned is None


# --- Session-aware volume-surge threshold (pre-market stricter) ----------

def test_premarket_bar_requires_the_stricter_volume_surge_threshold(config):
    # 2.5x clears the regular threshold (2.0x) but not the pre-market one (3.0x).
    snap = _snapshot(
        rsi=32.0, rsi_prev=28.0, volume_surge_ratio=2.5,
        bar_timestamp=datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc),
    )

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


def test_premarket_bar_fires_once_volume_surge_clears_the_stricter_threshold(config):
    snap = _snapshot(
        rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.5,
        bar_timestamp=datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc),
    )

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].session == "pre_market"
