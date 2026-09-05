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

import math
from datetime import datetime, timezone

import pytest

from talonx_quant.config import QuantConfig
from talonx_quant.indicators import DailyPivots, IndicatorSnapshot
from talonx_quant.schemas import SignalDirection, SignalType
from talonx_quant.strategy import (
    FALLBACK_REASON_NO_STRUCTURAL_SUPPORT,
    FALLBACK_REASON_STRUCTURE_INVALID_OR_NONFINITE,
    FALLBACK_REASON_STRUCTURE_NOT_BELOW_ENTRY,
    GEOMETRY_PATH_ATR_FALLBACK,
    GEOMETRY_PATH_STRUCTURAL_PRIMARY,
    _confluence_score,
    _structural_risk_reward,
    calculate_trade_geometry,
    evaluate_signals,
)


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


def test_rsi_volume_setup_fires_overbought_on_the_recovery_bar(config):
    # RSI Reversal Curl (symmetric): RSI was overbought (72) last bar,
    # recovered back down to 68 (<= 70) this bar.
    snap = _snapshot(rsi=68.0, rsi_prev=72.0, volume_surge_ratio=2.5)

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].signal_type == SignalType.RSI_OVERBOUGHT_VOLUME_SURGE


def test_rsi_volume_setup_does_not_fire_on_the_initial_rise_into_overbought(config):
    # RSI Reversal Curl (symmetric): rising INTO overbought (68 -> 72)
    # must NOT fire a short on its own anymore -- only the recovery back
    # below 70 does.
    snap = _snapshot(rsi=72.0, rsi_prev=68.0, volume_surge_ratio=2.5)

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


def test_rsi_volume_setup_does_not_refire_while_already_recovered_from_overbought(config):
    # Both this bar and the previous bar are already at/below 70 -- no
    # fresh recovery edge.
    snap = _snapshot(rsi=65.0, rsi_prev=68.0, volume_surge_ratio=2.5)

    signals = evaluate_signals("AAPL", snap, config)

    assert signals == []


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

    assert _confluence_score(
        snap, config, config.volume_surge_ratio_threshold, SignalDirection.BULLISH,
        SignalType.RSI_OVERSOLD_VOLUME_SURGE,
    ) == 1


def test_confluence_bullish_scores_zero_for_overbought_rsi(config):
    # The core Direction-Aware Confluence fix: an overbought bar (> 70)
    # must earn a BULLISH candidate ZERO points for the RSI leg.
    snap = _snapshot(rsi=75.0)

    assert _confluence_score(
        snap, config, config.volume_surge_ratio_threshold, SignalDirection.BULLISH,
        SignalType.RSI_OVERSOLD_VOLUME_SURGE,
    ) == 0


def test_confluence_bearish_counts_overbought_rsi(config):
    snap = _snapshot(rsi=75.0)  # overbought -- supports a BEARISH read

    assert _confluence_score(
        snap, config, config.volume_surge_ratio_threshold, SignalDirection.BEARISH,
        SignalType.RSI_OVERBOUGHT_VOLUME_SURGE,
    ) == 1


def test_confluence_bearish_scores_zero_for_oversold_rsi(config):
    snap = _snapshot(rsi=22.0)

    assert _confluence_score(
        snap, config, config.volume_surge_ratio_threshold, SignalDirection.BEARISH,
        SignalType.RSI_OVERBOUGHT_VOLUME_SURGE,
    ) == 0


def test_confluence_score_counts_all_three_factors_bullish(config):
    # Non-MACD-triggered (RSI) candidate with a COINCIDENT, INDEPENDENT MACD
    # cross on the same bar -- exactly the case the No-Self-Credit fix (Task
    # 49) is meant to keep crediting: the MACD leg here is NOT the
    # candidate's own trigger, so it remains a legitimate confirmation.
    snap = _snapshot(
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,  # independent MACD cross
        rsi=25.0,  # oversold -- supports BULLISH
        volume_surge_ratio=3.0,  # above threshold
    )

    assert _confluence_score(
        snap, config, config.volume_surge_ratio_threshold, SignalDirection.BULLISH,
        SignalType.RSI_OVERSOLD_VOLUME_SURGE,
    ) == 3


def test_confluence_score_is_zero_when_nothing_qualifies(config):
    snap = _snapshot(rsi=50.0, volume_surge_ratio=1.0)

    assert _confluence_score(
        snap, config, config.volume_surge_ratio_threshold, SignalDirection.BULLISH,
        SignalType.RSI_OVERSOLD_VOLUME_SURGE,
    ) == 0


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
    # No-Self-Credit (Task 49): this candidate's own trigger IS the MACD
    # cross, so that leg no longer counts as its confirmation. MACD leg (0,
    # self-credit excluded) + volume surge (1) + RSI leg (0, overbought
    # doesn't support a bullish read) = 1, not 3 (and not 2, pre-Task-49).
    assert signals[0].confluence_score == 1


# --- No-Self-Credit Contract (Task 49: TRIGGER + ONE INDEPENDENT CONFIRMATION) --
#
# Requirement-proving tests for the 2026-08-22 fix: a MACD-triggered
# candidate's own MACD cross may no longer count as its own confluence
# confirmation. Task 47 measured a 100% self-credit rate before this fix
# (every MACD_BULLISH_CROSS/MACD_BEARISH_CROSS candidate's own trigger
# condition was identical to _confluence_score's MACD leg condition). These
# tests lock the corrected contract: a MACD candidate now needs BOTH an
# independent RSI-extreme reading AND a volume surge to reach
# confluence_score_min=2 (2 points), since its own MACD leg contributes 0 --
# unlike before, where the MACD leg alone plus any one other leg sufficed.

def test_case_a_macd_trigger_alone_does_not_satisfy_confluence(config):
    # MACD cross only -- no RSI extreme in the supporting direction, no
    # volume surge. Self-credit excluded -> score 0, nowhere near threshold.
    snap = _snapshot(
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,
        rsi=50.0, volume_surge_ratio=None,
    )

    signals = evaluate_signals("AAPL", snap, config)
    macd_signals = [s for s in signals if s.signal_type == SignalType.MACD_BULLISH_CROSS]

    assert len(macd_signals) == 1
    assert macd_signals[0].confluence_score == 0
    assert macd_signals[0].confluence_score < config.confluence_score_min


def test_case_b_macd_trigger_plus_rsi_alone_is_still_below_threshold(config):
    # MACD cross + an independent oversold RSI reading, but no volume surge.
    # RSI leg (1) is a genuine independent confirmation, but MACD's own leg
    # is excluded (0) -- one leg alone is not enough to clear
    # confluence_score_min=2 for a MACD-triggered candidate post-fix (it
    # would have been enough pre-fix, when the MACD leg self-credited).
    snap = _snapshot(
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,
        rsi=25.0, volume_surge_ratio=None,
    )

    signals = evaluate_signals("AAPL", snap, config)
    macd_signals = [s for s in signals if s.signal_type == SignalType.MACD_BULLISH_CROSS]

    assert len(macd_signals) == 1
    assert macd_signals[0].confluence_score == 1
    assert macd_signals[0].confluence_score < config.confluence_score_min


def test_case_c_macd_trigger_plus_ma_state_does_not_add_a_confluence_leg(config):
    # _confluence_score has no MA-state leg at all (only MACD/RSI/volume) --
    # a coincident MA crossover fires as its OWN independent signal (Task
    # 27's same-bar coincidence case) but contributes nothing to the MACD
    # candidate's own score. Documents actual implementation semantics
    # rather than fabricating an MA confluence leg that doesn't exist.
    snap = _snapshot(
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,
        price=500.0, sma_fast=138.0, sma_slow=137.0, sma_fast_prev=136.5, sma_slow_prev=137.0,
        rsi=50.0, volume_surge_ratio=None,
    )

    signals = evaluate_signals("AAPL", snap, config)
    macd_signals = [s for s in signals if s.signal_type == SignalType.MACD_BULLISH_CROSS]
    ma_signals = [s for s in signals if s.signal_type == SignalType.MA_GOLDEN_CROSS]

    assert len(macd_signals) == 1
    assert len(ma_signals) == 1  # fires independently, same bar
    assert macd_signals[0].confluence_score == 0  # MA state is not a confluence leg


def test_case_d_macd_trigger_plus_volume_alone_is_still_below_threshold(config):
    # MACD cross + volume surge, no RSI extreme. Volume leg (1) alone is not
    # enough post-fix, symmetric with case B.
    snap = _snapshot(
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,
        rsi=50.0, volume_surge_ratio=3.0,
    )

    signals = evaluate_signals("AAPL", snap, config)
    macd_signals = [s for s in signals if s.signal_type == SignalType.MACD_BULLISH_CROSS]

    assert len(macd_signals) == 1
    assert macd_signals[0].confluence_score == 1
    assert macd_signals[0].confluence_score < config.confluence_score_min


def test_case_macd_trigger_plus_rsi_and_volume_reaches_threshold(config):
    # The ONLY way a MACD-triggered candidate can reach confluence_score_min
    # (2) post-fix: BOTH remaining legs (RSI + volume), since its own MACD
    # leg contributes 0. Bearish mirror included for symmetry.
    snap = _snapshot(
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,
        rsi=25.0, volume_surge_ratio=3.0,
    )

    signals = evaluate_signals("AAPL", snap, config)
    macd_signals = [s for s in signals if s.signal_type == SignalType.MACD_BULLISH_CROSS]

    assert len(macd_signals) == 1
    assert macd_signals[0].confluence_score == 2
    assert macd_signals[0].confluence_score >= config.confluence_score_min

    bear_snap = _snapshot(
        macd=-0.05, macd_signal_line=-0.02, macd_prev=0.01, macd_signal_line_prev=-0.01,
        rsi=75.0, volume_surge_ratio=3.0,
    )
    bear_signals = evaluate_signals("AAPL", bear_snap, config)
    bear_macd_signals = [s for s in bear_signals if s.signal_type == SignalType.MACD_BEARISH_CROSS]
    assert len(bear_macd_signals) == 1
    assert bear_macd_signals[0].confluence_score == 2


def test_case_e_macd_own_confirmation_is_structurally_impossible(config):
    # "MACD trigger + independent MACD confirmation" cannot exist as a
    # fixture: _macd_crossed_this_bar (the would-be confirmation condition)
    # IS the exact condition _check_macd_crossover uses to fire the trigger
    # in the first place -- there is no code path where a bar produces a
    # MACD_BULLISH_CROSS/MACD_BEARISH_CROSS trigger without also making
    # _macd_crossed_this_bar True for that same candidate. This test
    # documents that structural impossibility directly rather than
    # fabricating a fixture that could never occur in the real pipeline:
    # every MACD-triggered candidate's own_trigger_is_macd branch always
    # takes the self-credit-excluded path, unconditionally.
    snap = _snapshot(macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01)

    signals = evaluate_signals("AAPL", snap, config)
    macd_signals = [s for s in signals if s.signal_type == SignalType.MACD_BULLISH_CROSS]

    assert len(macd_signals) == 1
    # The trigger firing at all is definitional proof _macd_crossed_this_bar
    # was True for this candidate -- yet its own MACD leg still contributes 0.
    assert macd_signals[0].confluence_score == 0


def test_case_f_rsi_triggered_candidate_confluence_unchanged(config):
    # RSI-triggered candidates were never self-crediting (Task 28/33: the
    # curl-recovery trigger condition and the confluence RSI-extreme-state
    # condition are structurally disjoint) -- this fix must not touch them.
    # Same fixture/assertions as the pre-existing
    # test_bullish_curl_with_volume_and_coincident_macd_reaches_confluence_two.
    snap = _snapshot(
        rsi=31.0, rsi_prev=28.0, volume_surge_ratio=3.0,
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,
    )

    signals = evaluate_signals("AAPL", snap, config)
    rsi_signals = [s for s in signals if s.signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE]

    assert len(rsi_signals) == 1
    # Independent MACD leg (1, not this candidate's own trigger) + volume
    # (1) = 2 -- unchanged from pre-fix behavior.
    assert rsi_signals[0].confluence_score == 2


def test_case_g_ma_triggered_candidate_confluence_unchanged(config):
    # MA-triggered candidates were already ALIGNED (Task 33) -- _confluence_
    # score has no MA-state leg to self-credit from in the first place. This
    # fix must not touch them either: an MA candidate's score is driven
    # purely by (independent) MACD/RSI/volume state, exactly as before.
    snap = _snapshot(
        price=500.0, sma_fast=138.0, sma_slow=137.0, sma_fast_prev=136.5, sma_slow_prev=137.0,
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,  # independent MACD cross
        rsi=25.0, volume_surge_ratio=3.0,
    )

    signals = evaluate_signals("MSFT", snap, config)
    ma_signals = [s for s in signals if s.signal_type == SignalType.MA_GOLDEN_CROSS]

    assert len(ma_signals) == 1
    # MACD leg (1, independent) + RSI leg (1, oversold supports bullish) +
    # volume leg (1) = 3 -- identical to pre-fix behavior (MA never
    # self-credited, so nothing here changes).
    assert ma_signals[0].confluence_score == 3


def test_case_h_confluence_threshold_itself_is_unchanged(config):
    # The fix touches ONLY how the MACD leg is awarded, never
    # confluence_score_min itself.
    assert QuantConfig().confluence_score_min == 2


# --- RSI-Curl / Confluence Contract (Task 28: RSI_CONFLUENCE_STATE_BASED_CONFIRMED) ---
#
# Requirement-proving, not merely implementation-locking: these tests exist
# because Task 24 and Task 27 found that an RSI-curl candidate's own RSI
# value can never satisfy its own confluence RSI leg (the trigger fires on
# the RECOVERY bar -- RSI >= 30 bullish / <= 70 bearish -- while the
# confluence leg requires the opposite, still-extreme state -- RSI < 30 /
# > 70). Task 28's full requirements-archaeology investigation (see
# results/task28_rsi_confluence_requirement/) confirmed this is INTENDED
# behavior (RSI_CONFLUENCE_STATE_BASED_CONFIRMED): the confluence RSI leg
# is documented, consistently and repeatedly, to measure CURRENT state, not
# the reversal EVENT. These tests lock that confirmed contract in so a
# future change to _confluence_score or _check_rsi_volume_setup that
# silently makes an RSI-curl candidate's own RSI value count towards its
# own score is caught as a requirement violation, not treated as a bug fix.
# The requirement is fully readable from the test bodies below; no test
# reads a results/ artifact file at runtime.

def test_bullish_curl_with_volume_and_no_macd_is_capped_at_confluence_one(config):
    # Contract case A: RSI curl + volume, no coincident MACD cross.
    # RSI leg = 0 (state-based: current RSI 31 is not < 30, even though the
    # curl itself required the RECOVERY from 28 -> 31). Volume leg = 1.
    # MACD leg = 0 (no cross this bar). Total = 1, one point short of
    # confluence_score_min=2 -- this candidate cannot publish on its own.
    snap = _snapshot(rsi=31.0, rsi_prev=28.0, volume_surge_ratio=3.0)

    signals = evaluate_signals("AAPL", snap, config)

    rsi_signals = [s for s in signals if s.signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE]
    assert len(rsi_signals) == 1
    assert rsi_signals[0].direction == SignalDirection.BULLISH
    assert rsi_signals[0].confluence_score == 1
    assert rsi_signals[0].confluence_score < config.confluence_score_min


def test_bullish_curl_with_volume_and_coincident_macd_reaches_confluence_two(config):
    # Contract case B: same RSI curl as above, PLUS a same-bar MACD
    # bullish cross -- the only way an RSI-curl candidate can reach
    # confluence_score_min=2, since its own RSI leg is structurally
    # unavailable (see test above) and volume alone only supplies 1.
    snap = _snapshot(
        rsi=31.0, rsi_prev=28.0, volume_surge_ratio=3.0,
        macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01,
    )

    signals = evaluate_signals("AAPL", snap, config)

    rsi_signals = [s for s in signals if s.signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE]
    assert len(rsi_signals) == 1
    assert rsi_signals[0].confluence_score == 2
    assert rsi_signals[0].confluence_score >= config.confluence_score_min
    # The coincident MACD_BULLISH_CROSS also fires independently on this
    # bar (Task 27 §9's same-bar coincidence case) -- not asserted further
    # here, already covered by test_multiple_signal_types_can_fire_on_the_same_bar.


def test_bearish_curl_with_volume_and_no_macd_is_capped_at_confluence_one(config):
    # Contract case C: bearish mirror of case A.
    snap = _snapshot(rsi=69.0, rsi_prev=72.0, volume_surge_ratio=3.0)

    signals = evaluate_signals("AAPL", snap, config)

    rsi_signals = [s for s in signals if s.signal_type == SignalType.RSI_OVERBOUGHT_VOLUME_SURGE]
    assert len(rsi_signals) == 1
    assert rsi_signals[0].direction == SignalDirection.BEARISH
    assert rsi_signals[0].confluence_score == 1
    assert rsi_signals[0].confluence_score < config.confluence_score_min


def test_bearish_curl_with_volume_and_coincident_macd_reaches_confluence_two(config):
    # Contract case D: bearish mirror of case B.
    snap = _snapshot(
        rsi=69.0, rsi_prev=72.0, volume_surge_ratio=3.0,
        macd=-0.05, macd_signal_line=-0.02, macd_prev=0.01, macd_signal_line_prev=-0.01,
    )

    signals = evaluate_signals("AAPL", snap, config)

    rsi_signals = [s for s in signals if s.signal_type == SignalType.RSI_OVERBOUGHT_VOLUME_SURGE]
    assert len(rsi_signals) == 1
    assert rsi_signals[0].confluence_score == 2
    assert rsi_signals[0].confluence_score >= config.confluence_score_min


# --- RSI-Curl / Confluence Contract: exact 30/70 boundary (Task 28 §5/§7) --
#
# Task 28's rsi_truth_table.csv identified these exact boundary cases had
# no prior test coverage. The curl trigger and the confluence leg use
# DIFFERENT boundary conventions on purpose: the trigger's `rsi_prev` check
# is strict (< / >), its `rsi` check is inclusive (>= / <=); the confluence
# leg's check is strict on the current bar (< / >) in both directions. This
# is what makes the two conditions complementary (never simultaneously
# true) at every point along the boundary, including exactly at 30.0/70.0.

def test_boundary_bullish_recovery_exactly_at_oversold_threshold_fires_curl(config):
    # 29.9 -> 30.0: curr (30.0) clears the inclusive >= 30 recovery check.
    snap = _snapshot(rsi=30.0, rsi_prev=29.9, volume_surge_ratio=3.0)

    signals = evaluate_signals("AAPL", snap, config)
    rsi_signals = [s for s in signals if s.signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE]

    assert len(rsi_signals) == 1
    # Confluence leg is strict (< 30): exactly 30.0 does NOT qualify.
    assert rsi_signals[0].confluence_score == 1  # volume only


def test_boundary_bullish_prev_at_threshold_is_not_a_recovery(config):
    # 30.0 -> 31.0: rsi_prev (30.0) fails the STRICT < 30 "was oversold"
    # check -- prev was already AT the threshold, not below it, so this is
    # not a qualifying recovery (there was nothing to recover from).
    snap = _snapshot(rsi=31.0, rsi_prev=30.0, volume_surge_ratio=3.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert [s for s in signals if s.signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE] == []


def test_boundary_bullish_current_just_shy_of_threshold_does_not_fire_curl(config):
    # 28.0 -> 29.9: curr (29.9) has not yet reached the inclusive >= 30
    # recovery threshold -- still oversold, no curl.
    snap = _snapshot(rsi=29.9, rsi_prev=28.0, volume_surge_ratio=3.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert [s for s in signals if s.signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE] == []
    # The confluence leg, checked in isolation, WOULD score this state
    # (still oversold, 29.9 < 30) -- but no candidate exists to attach it
    # to since no trigger fired. RSI leg (1) + volume leg (1) = 2.
    # Demonstrates the two checks are evaluated on entirely separate
    # conditions, not just "the same value seen twice".
    assert _confluence_score(
        snap, config, config.volume_surge_ratio_threshold, SignalDirection.BULLISH,
        SignalType.RSI_OVERSOLD_VOLUME_SURGE,
    ) == 2


def test_boundary_bearish_recovery_exactly_at_overbought_threshold_fires_curl(config):
    # 70.1 -> 70.0: curr (70.0) clears the inclusive <= 70 recovery check.
    snap = _snapshot(rsi=70.0, rsi_prev=70.1, volume_surge_ratio=3.0)

    signals = evaluate_signals("AAPL", snap, config)
    rsi_signals = [s for s in signals if s.signal_type == SignalType.RSI_OVERBOUGHT_VOLUME_SURGE]

    assert len(rsi_signals) == 1
    assert rsi_signals[0].confluence_score == 1  # volume only; strict > 70 confluence leg does not qualify at 70.0


def test_boundary_bearish_prev_at_threshold_is_not_a_recovery(config):
    # 70.0 -> 69.0: rsi_prev (70.0) fails the STRICT > 70 "was overbought"
    # check -- prev was already AT the threshold, not above it.
    snap = _snapshot(rsi=69.0, rsi_prev=70.0, volume_surge_ratio=3.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert [s for s in signals if s.signal_type == SignalType.RSI_OVERBOUGHT_VOLUME_SURGE] == []


def test_boundary_bearish_current_just_above_threshold_does_not_fire_curl(config):
    # 72.0 -> 70.1: curr (70.1) has not yet reached the inclusive <= 70
    # recovery threshold -- still overbought, no curl.
    snap = _snapshot(rsi=70.1, rsi_prev=72.0, volume_surge_ratio=3.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert [s for s in signals if s.signal_type == SignalType.RSI_OVERBOUGHT_VOLUME_SURGE] == []
    # RSI leg (1, still overbought at 70.1 > 70) + volume leg (1) = 2.
    assert _confluence_score(
        snap, config, config.volume_surge_ratio_threshold, SignalDirection.BEARISH,
        SignalType.RSI_OVERBOUGHT_VOLUME_SURGE,
    ) == 2


# --- Structural R:R Calculation --------------------------------------------

def test_structural_rr_uses_pivot_resistance_and_atr_stop_multiplier(config):
    # reward = resistance(110) - price(100) = 10; risk = atr_stop_multiplier(1.5) * atr(2) = 3.
    # support(105) is deliberately >= price(100) -- invalid as a structural
    # stop anchor (Task 35), so this specifically exercises the ATR-
    # fallback stop path; see the "Structural Stop Geometry" section below
    # for the STRUCTURAL_PRIMARY case.
    snap = _snapshot(price=100.0, atr=2.0)
    pivots = _pivots(resistance=110.0, support=105.0)

    ratio = _structural_risk_reward(snap, SignalDirection.BULLISH, pivots, config)

    assert ratio == pytest.approx(10.0 / 3.0)


def test_structural_rr_bearish_uses_pivot_support(config):
    # reward = price(100) - support(92) = 8; risk = atr_stop_multiplier(1.5) * atr(2) = 3
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
    # Task 35: support(90) < price(100) is now a VALID structural stop
    # anchor -- risk = price(100) - support(90) = 10, not the ATR risk(3)
    # this test asserted pre-Task-35. reward is unchanged (resistance(110)
    # - price(100) = 10), so ratio is now 10/10 = 1.0.
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, atr=2.0, bar_true_range=2.0, price=100.0)
    pivots = _pivots(resistance=110.0, support=90.0)

    signals = evaluate_signals("AAPL", snap, config, daily_pivots=pivots)

    assert len(signals) == 1
    assert signals[0].atr == 2.0
    assert signals[0].risk_reward_ratio == pytest.approx(10.0 / 10.0)
    assert signals[0].pivot_resistance == pytest.approx(110.0)
    assert signals[0].pivot_support == pytest.approx(90.0)
    assert signals[0].stop_price == pytest.approx(90.0)
    assert signals[0].geometry_path == "STRUCTURAL_PRIMARY"


def test_signal_risk_reward_is_none_without_pivots(config):
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, atr=2.0, bar_true_range=2.0, price=100.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].risk_reward_ratio is None
    assert signals[0].pivot_resistance is None


def test_gated_risk_reward_matches_the_actually_executed_stop_distance(config):
    """2026-08-16 quant-audit regression: risk_reward_ratio's implied
    risk distance (config.atr_stop_multiplier x ATR) must equal
    price - stop_price exactly -- a candidate must never be gated on a
    WIDER (or narrower) risk distance than the stop it's actually
    published with. Before the fix, the gate used
    pivot_stop_atr_multiplier (1.5x ATR) while the executed stop used a
    separate atr_stop_multiplier (1.0x ATR): a $6 pivot target against a
    $2 ATR gated at R:R=2.0 (6 / (1.5*2)=3) but would have EXECUTED at
    R:R=3.0 (6 / (1.0*2)=2) -- passing the >=1.5 gate on a materially
    different number than the trade actually risked.

    support(101) is deliberately >= price(100), invalid as a Task 35
    structural stop anchor, so this specifically exercises the ATR-
    fallback stop path -- see
    test_gated_risk_reward_matches_the_actually_executed_stop_distance_under_structural_stop
    below for the same invariant proven under STRUCTURAL_PRIMARY."""
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, atr=2.0, bar_true_range=2.0, price=100.0)
    pivots = _pivots(resistance=106.0, support=101.0)

    signals = evaluate_signals("AAPL", snap, config, daily_pivots=pivots)

    assert len(signals) == 1
    signal = signals[0]
    implied_risk_distance = config.atr_stop_multiplier * signal.atr
    executed_risk_distance = signal.price - signal.stop_price
    assert implied_risk_distance == pytest.approx(executed_risk_distance)
    # And the published ratio must equal reward / the SAME executed distance.
    reward_distance = signal.pivot_resistance - signal.price
    assert signal.risk_reward_ratio == pytest.approx(reward_distance / executed_risk_distance)


# --- Explicit $ stop/target -------------------------------------------------

def test_bullish_signal_target_uses_pivot_resistance_when_available(config):
    # support(101) is deliberately >= price(100), invalid as a Task 35
    # structural stop anchor, isolating this test's own focus (target
    # selection) from the stop-selection behavior covered separately below.
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, price=100.0, atr=2.0, bar_true_range=2.0)
    pivots = _pivots(resistance=108.0, support=101.0)

    signals = evaluate_signals("AAPL", snap, config, daily_pivots=pivots)

    assert len(signals) == 1
    assert signals[0].stop_price == pytest.approx(97.0)  # atr_stop_multiplier(1.5) * atr(2.0)
    assert signals[0].target_price == pytest.approx(108.0)  # pivot resistance, not 2x ATR


def test_bullish_signal_falls_back_to_atr_target_without_pivots(config):
    # price=100, atr=2 -> stop = 100 - 1.5*2 = 97, target = 100 + 2*2 = 104 (fallback)
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, price=100.0, atr=2.0, bar_true_range=2.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].stop_price == pytest.approx(97.0)
    assert signals[0].target_price == pytest.approx(104.0)


def test_bearish_signal_target_uses_pivot_support_when_available(config):
    snap = _snapshot(rsi=68.0, rsi_prev=72.0, volume_surge_ratio=3.0, price=100.0, atr=2.0, bar_true_range=2.0)
    pivots = _pivots(resistance=115.0, support=93.0)

    signals = evaluate_signals("AAPL", snap, config, daily_pivots=pivots)

    assert len(signals) == 1
    assert signals[0].stop_price == pytest.approx(103.0)
    assert signals[0].target_price == pytest.approx(93.0)


def test_bearish_signal_falls_back_to_atr_target_without_pivots(config):
    # price=100, atr=2 -> stop = 100 + 1.5*2 = 103, target = 100 - 2*2 = 96 (fallback)
    snap = _snapshot(rsi=68.0, rsi_prev=72.0, volume_surge_ratio=3.0, price=100.0, atr=2.0, bar_true_range=2.0)

    signals = evaluate_signals("AAPL", snap, config)

    assert len(signals) == 1
    assert signals[0].stop_price == pytest.approx(103.0)
    assert signals[0].target_price == pytest.approx(96.0)


# --- Structural Stop Geometry (Task 35: owner-confirmed ATR-RISK-001,
# MARKET_STRUCTURE_PRIMARY) --------------------------------------------
#
# Requirement-proving, not merely implementation-locking: LONG stop
# geometry must primarily reflect market-structure invalidation (the
# existing, causal prior-session S1 pivot support), falling back to the
# unmodified 1.5x-ATR formula ONLY when no valid structural anchor
# exists. Task 34 proved the PRIOR (ATR-only, unconditional) behavior was
# systematically misaligned with this now-confirmed contract; these tests
# lock the corrected behavior in directly against calculate_trade_geometry,
# with no dependency on any results/ artifact at runtime. No structural
# buffer is applied -- Task 34 found no existing repository requirement
# defines one (see docs/modules/quant.md's STRUCTURAL_BUFFER_REQUIREMENT_
# NOT_DEFINED note); pivot_support is used LITERALLY as the stop.

def test_geometry_case_a_valid_structure_below_entry_is_used_as_the_stop(config):
    # entry=100, pivot_support=95 (valid, < entry) -- ATR fallback would
    # have been 100 - 1.5*2 = 97, but structure takes priority.
    geometry = calculate_trade_geometry(
        price=100.0, atr=2.0, direction=SignalDirection.BULLISH,
        pivot_resistance=None, pivot_support=95.0, config=config,
    )

    assert geometry is not None
    assert geometry.stop_price == pytest.approx(95.0)
    assert geometry.geometry_path == GEOMETRY_PATH_STRUCTURAL_PRIMARY
    assert geometry.fallback_reason is None
    assert geometry.structural_level == pytest.approx(95.0)
    assert geometry.structural_level_type == "prior_session_S1_pivot"


def test_geometry_case_b_no_structure_falls_back_to_atr_with_explicit_reason(config):
    geometry = calculate_trade_geometry(
        price=100.0, atr=2.0, direction=SignalDirection.BULLISH,
        pivot_resistance=None, pivot_support=None, config=config,
    )

    assert geometry is not None
    assert geometry.stop_price == pytest.approx(97.0)  # 100 - 1.5*2, unmodified ATR fallback formula
    assert geometry.geometry_path == GEOMETRY_PATH_ATR_FALLBACK
    assert geometry.fallback_reason == FALLBACK_REASON_NO_STRUCTURAL_SUPPORT
    assert geometry.structural_level is None
    assert geometry.structural_level_type is None


def test_geometry_case_c_structure_above_entry_is_rejected_not_used(config):
    # pivot_support(101) > entry(100) -- on the wrong side, must NOT be
    # used as a long stop (a stop above entry is nonsensical for a long).
    geometry = calculate_trade_geometry(
        price=100.0, atr=2.0, direction=SignalDirection.BULLISH,
        pivot_resistance=None, pivot_support=101.0, config=config,
    )

    assert geometry is not None
    assert geometry.stop_price == pytest.approx(97.0)  # ATR fallback, unmodified formula
    assert geometry.geometry_path == GEOMETRY_PATH_ATR_FALLBACK
    assert geometry.fallback_reason == FALLBACK_REASON_STRUCTURE_NOT_BELOW_ENTRY


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_geometry_case_d_non_finite_structure_never_propagates_invalid_geometry(config, bad_value):
    geometry = calculate_trade_geometry(
        price=100.0, atr=2.0, direction=SignalDirection.BULLISH,
        pivot_resistance=None, pivot_support=bad_value, config=config,
    )

    assert geometry is not None
    assert math.isfinite(geometry.stop_price)  # never NaN/Inf, regardless of the bad input
    assert geometry.stop_price == pytest.approx(97.0)  # ATR fallback, unmodified formula
    assert geometry.geometry_path == GEOMETRY_PATH_ATR_FALLBACK
    assert geometry.fallback_reason == FALLBACK_REASON_STRUCTURE_INVALID_OR_NONFINITE


def test_geometry_case_e_structure_exactly_equal_to_entry_is_invalid(config):
    # A stop AT entry would be a zero-risk trade -- must be rejected, not
    # silently accepted as "technically below or equal."
    geometry = calculate_trade_geometry(
        price=100.0, atr=2.0, direction=SignalDirection.BULLISH,
        pivot_resistance=None, pivot_support=100.0, config=config,
    )

    assert geometry is not None
    assert geometry.stop_price == pytest.approx(97.0)  # ATR fallback, not a zero-risk stop at entry
    assert geometry.geometry_path == GEOMETRY_PATH_ATR_FALLBACK
    assert geometry.fallback_reason == FALLBACK_REASON_STRUCTURE_NOT_BELOW_ENTRY
    assert geometry.risk > 0


def test_geometry_case_f_structure_far_below_entry_is_used_literally_not_clamped(config):
    # A structural level far away (large risk) must still be used AS-IS --
    # this task does not add a buffer or a "too far, fall back to ATR"
    # rule. The downstream R:R gate, not this function, is what may
    # eventually reject a candidate whose risk is this large.
    geometry = calculate_trade_geometry(
        price=100.0, atr=2.0, direction=SignalDirection.BULLISH,
        pivot_resistance=None, pivot_support=50.0, config=config,
    )

    assert geometry is not None
    assert geometry.stop_price == pytest.approx(50.0)  # used literally, not clamped toward the ATR(97) stop
    assert geometry.geometry_path == GEOMETRY_PATH_STRUCTURAL_PRIMARY
    assert geometry.risk == pytest.approx(50.0)  # 100 - 50, far larger than the ATR risk (3) would have been


def test_geometry_bearish_direction_is_unchanged_by_task_35(config):
    # The owner's MARKET_STRUCTURE_PRIMARY contract is scoped to LONG
    # trades only -- BEARISH must remain exactly the pre-Task-35 ATR-only
    # formula, unconditionally, even when a valid-looking pivot_support
    # sits below price (which would be irrelevant for a bearish stop
    # anyway -- bearish uses pivot_support only for its TARGET, unchanged).
    geometry = calculate_trade_geometry(
        price=100.0, atr=2.0, direction=SignalDirection.BEARISH,
        pivot_resistance=None, pivot_support=95.0, config=config,
    )

    assert geometry is not None
    assert geometry.stop_price == pytest.approx(103.0)  # 100 + 1.5*2, unchanged formula
    assert geometry.geometry_path == GEOMETRY_PATH_ATR_FALLBACK
    assert geometry.fallback_reason is None  # bearish never "attempts" structural, so never "falls back" either
    assert geometry.structural_level is None


# --- R:R recalculation under the selected stop path (Task 35 §18-19) ------

def test_rr_uses_structural_risk_not_atr_risk_when_structural_stop_selected(config):
    # Same entry/target/ATR in both cases; only the stop source differs.
    atr_geometry = calculate_trade_geometry(
        price=100.0, atr=2.0, direction=SignalDirection.BULLISH,
        pivot_resistance=110.0, pivot_support=101.0, config=config,  # support invalid -> ATR fallback
    )
    structural_geometry = calculate_trade_geometry(
        price=100.0, atr=2.0, direction=SignalDirection.BULLISH,
        pivot_resistance=110.0, pivot_support=95.0, config=config,  # support valid -> structural
    )

    assert atr_geometry.stop_price == pytest.approx(97.0)
    assert atr_geometry.risk == pytest.approx(3.0)  # 1.5 * 2.0
    assert atr_geometry.risk_reward_ratio == pytest.approx(10.0 / 3.0)

    assert structural_geometry.stop_price == pytest.approx(95.0)
    assert structural_geometry.risk == pytest.approx(5.0)  # 100 - 95, NOT the ATR risk
    assert structural_geometry.risk_reward_ratio == pytest.approx(10.0 / 5.0)

    # Same target/reward in both cases; the structural stop's wider risk
    # produces a strictly LOWER R:R here -- proving the engine uses the
    # ACTUAL selected geometry, not a stale ATR-only figure.
    assert structural_geometry.risk_reward_ratio < atr_geometry.risk_reward_ratio


def test_gated_risk_reward_matches_the_actually_executed_stop_distance_under_structural_stop(config):
    # Sibling of test_gated_risk_reward_matches_the_actually_executed_stop_distance
    # above, proving the SAME invariant (the R:R gate's implied risk
    # distance must equal price - stop_price exactly) holds when the
    # selected stop is STRUCTURAL, not just under the ATR-fallback path.
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, atr=2.0, bar_true_range=2.0, price=100.0)
    pivots = _pivots(resistance=106.0, support=90.0)  # support valid -> STRUCTURAL_PRIMARY

    signals = evaluate_signals("AAPL", snap, config, daily_pivots=pivots)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.geometry_path == GEOMETRY_PATH_STRUCTURAL_PRIMARY
    executed_risk_distance = signal.price - signal.stop_price
    assert executed_risk_distance == pytest.approx(10.0)  # 100 - 90, NOT the ATR risk (3)
    reward_distance = signal.pivot_resistance - signal.price
    assert signal.risk_reward_ratio == pytest.approx(reward_distance / executed_risk_distance)


def test_rr_rejection_case_correct_geometry_fails_where_old_atr_geometry_would_have_passed(config):
    """Task 35 §19 -- essential correctness-not-tuning proof: a candidate
    whose OLD (ATR-only, pre-Task-35) geometry would have cleared
    min_risk_reward_ratio(1.5), but whose CORRECTED (structural) geometry
    does not, must actually be rejected end-to-end at evaluate_signals's
    own output (via a fails-below-threshold risk_reward_ratio, which
    consumer.py/backtest's LOW_RISK_REWARD gate then drops) -- proving
    this implementation is not quietly preserving the old candidate/
    signal count."""
    price, atr = 100.0, 2.0
    # OLD (pre-Task-35) geometry: risk = 1.5*2 = 3, reward = target(107)-100 = 7 -> R:R = 7/3 = 2.33 (PASSES 1.5)
    old_atr_only_geometry = calculate_trade_geometry(
        price=price, atr=atr, direction=SignalDirection.BULLISH,
        pivot_resistance=107.0, pivot_support=101.0, config=config,  # support invalid at old-geometry time (unused)
    )
    assert old_atr_only_geometry.risk_reward_ratio == pytest.approx(7.0 / 3.0)
    assert old_atr_only_geometry.risk_reward_ratio >= config.min_risk_reward_ratio

    # CORRECTED (Task 35) geometry: same entry/target/ATR, but a valid
    # structural support sits far below entry -- risk = 100-80 = 20,
    # reward is still 7 -> R:R = 7/20 = 0.35 (FAILS 1.5).
    corrected_geometry = calculate_trade_geometry(
        price=price, atr=atr, direction=SignalDirection.BULLISH,
        pivot_resistance=107.0, pivot_support=80.0, config=config,
    )
    assert corrected_geometry.geometry_path == GEOMETRY_PATH_STRUCTURAL_PRIMARY
    assert corrected_geometry.risk_reward_ratio == pytest.approx(7.0 / 20.0)
    assert corrected_geometry.risk_reward_ratio < config.min_risk_reward_ratio

    # End-to-end: evaluate_signals must publish the LOWER, correct ratio
    # on the signal object -- the actual gate rejection based on
    # min_risk_reward_ratio happens downstream (consumer.py/backtest), but
    # this is the exact number that gate reads.
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=3.0, atr=atr, bar_true_range=2.0, price=price)
    pivots = _pivots(resistance=107.0, support=80.0)
    signals = evaluate_signals("AAPL", snap, config, daily_pivots=pivots)
    assert len(signals) == 1
    assert signals[0].risk_reward_ratio == pytest.approx(7.0 / 20.0)
    assert signals[0].risk_reward_ratio < config.min_risk_reward_ratio


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
    snap = _snapshot(rsi=68.0, rsi_prev=72.0, volume_surge_ratio=3.0, price=100.0)

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
