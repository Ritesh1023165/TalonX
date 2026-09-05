"""
tests/test_independent_confirmation_contract.py
-------------------------------------------------
Task 51 -- INDEPENDENT_CONFIRMATION_EXPERIMENTAL confluence contract
(talonx_quant.config.ConfluenceContract, talonx_quant.strategy.
evaluate_independent_confirmations). Exactly two contracts: LEGACY (the
default, and the ONLY contract QuantScanner -- live/paper-shadow -- will
ever accept) and INDEPENDENT_CONFIRMATION_EXPERIMENTAL (research/
backtest-only).

The owner's contract, implemented literally: TRIGGER + AT LEAST ONE
independent, directionally-supportive confirmation, for every family
(RSI/MACD/MA). As with every prior contract-mode task, LEGACY must remain
byte-for-byte the pre-Task-51 behavior -- see test_quant_strategy.py's own
existing suite (unchanged, all passing) for that half of the proof; this
file covers the new EXPERIMENTAL contract plus the shared
direction-aware-MACD helpers (which the LEGACY _confluence_score formula
does NOT use -- it keeps the original direction-agnostic
_macd_crossed_this_bar for zero-drift).
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from talonx_quant.config import ConfluenceContract, QuantConfig
from talonx_quant.consumer import _opportunity_score
from talonx_quant.indicators import DailyPivots, IndicatorSnapshot
from talonx_quant.schemas import SignalDirection, SignalType
from talonx_quant.strategy import (
    ConfirmationState,
    _macd_bearish_crossed_this_bar,
    _macd_bullish_crossed_this_bar,
    evaluate_independent_confirmations,
    evaluate_signals,
)


def _snapshot(**overrides) -> IndicatorSnapshot:
    defaults = dict(
        price=100.0,
        bar_timestamp=datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc),
        rsi=None, rsi_prev=None,
        macd=None, macd_signal_line=None, macd_prev=None, macd_signal_line_prev=None,
        sma_fast=None, sma_slow=None, sma_fast_prev=None, sma_slow_prev=None,
        volume=None, volume_avg=None, volume_surge_ratio=None, dollar_volume_avg=None,
        atr=1.0, bar_true_range=2.0,
    )
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


def _pivots(resistance: float, support: float) -> DailyPivots:
    return DailyPivots(pivot=(resistance + support) / 2, resistance=resistance, support=support)


EXPERIMENTAL = ConfluenceContract.INDEPENDENT_CONFIRMATION_EXPERIMENTAL


def _config(contract: ConfluenceContract = EXPERIMENTAL) -> QuantConfig:
    return dataclasses.replace(QuantConfig(), confluence_contract=contract)


BULLISH_MACD = dict(macd=0.05, macd_signal_line=0.02, macd_prev=-0.01, macd_signal_line_prev=0.01)
BEARISH_MACD = dict(macd=-0.05, macd_signal_line=-0.02, macd_prev=0.01, macd_signal_line_prev=-0.01)
OVERSOLD_RSI = dict(rsi=25.0)
OVERBOUGHT_RSI = dict(rsi=75.0)
SURGE_VOLUME = dict(volume_surge_ratio=3.0)
NEUTRAL = dict(rsi=50.0, volume_surge_ratio=1.0)


# ======================================================================
# MACD family (cases A-F)
# ======================================================================

def test_a_macd_trigger_only_fails():
    config = _config()
    snap = _snapshot(**BULLISH_MACD, **NEUTRAL)
    signals = evaluate_signals("AAPL", snap, config)
    macd = [s for s in signals if s.signal_type == SignalType.MACD_BULLISH_CROSS]
    assert len(macd) == 1
    assert macd[0].confirmation_count == 0
    assert macd[0].confluence_score == 0


def test_b_macd_plus_supporting_rsi_passes():
    config = _config()
    snap = _snapshot(**BULLISH_MACD, **OVERSOLD_RSI, volume_surge_ratio=1.0)
    signals = evaluate_signals("AAPL", snap, config)
    macd = [s for s in signals if s.signal_type == SignalType.MACD_BULLISH_CROSS][0]
    assert macd.confirmation_count == 1
    assert macd.confirmation_rsi is True
    assert macd.confirmation_volume is False


def test_c_macd_plus_volume_passes():
    config = _config()
    snap = _snapshot(**BULLISH_MACD, rsi=50.0, **SURGE_VOLUME)
    signals = evaluate_signals("AAPL", snap, config)
    macd = [s for s in signals if s.signal_type == SignalType.MACD_BULLISH_CROSS][0]
    assert macd.confirmation_count == 1
    assert macd.confirmation_volume is True
    assert macd.confirmation_rsi is False


def test_d_macd_plus_rsi_plus_volume_count_two():
    config = _config()
    snap = _snapshot(**BULLISH_MACD, **OVERSOLD_RSI, **SURGE_VOLUME)
    signals = evaluate_signals("AAPL", snap, config)
    macd = [s for s in signals if s.signal_type == SignalType.MACD_BULLISH_CROSS][0]
    assert macd.confirmation_count == 2
    assert macd.confluence_score == 2
    assert macd.confirmation_rsi is True and macd.confirmation_volume is True


def test_e_bullish_macd_trigger_cannot_self_credit():
    config = _config()
    snap = _snapshot(**BULLISH_MACD, **NEUTRAL)
    state = evaluate_independent_confirmations(
        snap, SignalType.MACD_BULLISH_CROSS, SignalDirection.BULLISH, config.volume_surge_ratio_threshold, config,
    )
    assert state.macd_confirmed is False
    assert state.confirmation_count == 0


def test_f_bearish_macd_trigger_cannot_self_credit():
    config = _config()
    snap = _snapshot(**BEARISH_MACD, **NEUTRAL)
    state = evaluate_independent_confirmations(
        snap, SignalType.MACD_BEARISH_CROSS, SignalDirection.BEARISH, config.volume_surge_ratio_threshold, config,
    )
    assert state.macd_confirmed is False
    assert state.confirmation_count == 0


# ======================================================================
# RSI family (cases G-L)
# ======================================================================

def test_g_curl_without_volume_creates_experimental_candidate():
    config = _config()
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=None)
    signals = evaluate_signals("AAPL", snap, config)
    rsi_signals = [s for s in signals if s.signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE]
    assert len(rsi_signals) == 1  # trigger fires on curl alone under EXPERIMENTAL
    assert rsi_signals[0].confirmation_count == 0  # but no confirmation yet -> ineligible


def test_h_curl_plus_volume_passes():
    config = _config()
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, **SURGE_VOLUME)
    signals = evaluate_signals("AAPL", snap, config)
    rsi_signals = [s for s in signals if s.signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE][0]
    assert rsi_signals.confirmation_count == 1
    assert rsi_signals.confirmation_volume is True


def test_i_curl_plus_same_direction_macd_passes():
    config = _config()
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=None, **BULLISH_MACD)
    signals = evaluate_signals("AAPL", snap, config)
    rsi_signals = [s for s in signals if s.signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE][0]
    assert rsi_signals.confirmation_count == 1
    assert rsi_signals.confirmation_macd is True


def test_j_curl_alone_fails():
    config = _config()
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=None)
    signals = evaluate_signals("AAPL", snap, config)
    rsi_signals = [s for s in signals if s.signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE][0]
    assert rsi_signals.confirmation_count == 0


def test_k_opposite_direction_macd_does_not_confirm_rsi():
    config = _config()
    # bullish RSI curl, but the coincident MACD cross is BEARISH -- must not confirm.
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=None, **BEARISH_MACD)
    signals = evaluate_signals("AAPL", snap, config)
    rsi_signals = [s for s in signals if s.signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE][0]
    assert rsi_signals.confirmation_macd is False
    assert rsi_signals.confirmation_count == 0


def test_l_legacy_rsi_still_requires_volume_exactly_as_before():
    config = _config(ConfluenceContract.LEGACY)
    snap = _snapshot(rsi=32.0, rsi_prev=28.0, volume_surge_ratio=None)
    signals = evaluate_signals("AAPL", snap, config)
    assert [s for s in signals if s.signal_type == SignalType.RSI_OVERSOLD_VOLUME_SURGE] == []


# ======================================================================
# MA family (cases M-Q)
# ======================================================================

MA_GOLDEN = dict(price=500.0, sma_fast=138.0, sma_slow=137.0, sma_fast_prev=136.5, sma_slow_prev=137.0)


def test_m_ma_plus_same_direction_macd_passes():
    config = _config()
    snap = _snapshot(**MA_GOLDEN, **BULLISH_MACD, **NEUTRAL)
    signals = evaluate_signals("MSFT", snap, config)
    ma = [s for s in signals if s.signal_type == SignalType.MA_GOLDEN_CROSS][0]
    assert ma.confirmation_count == 1
    assert ma.confirmation_macd is True


def test_n_ma_plus_rsi_passes():
    config = _config()
    snap = _snapshot(**MA_GOLDEN, **OVERSOLD_RSI, volume_surge_ratio=1.0)
    signals = evaluate_signals("MSFT", snap, config)
    ma = [s for s in signals if s.signal_type == SignalType.MA_GOLDEN_CROSS][0]
    assert ma.confirmation_count == 1
    assert ma.confirmation_rsi is True


def test_o_ma_plus_volume_passes():
    config = _config()
    snap = _snapshot(**MA_GOLDEN, rsi=50.0, **SURGE_VOLUME)
    signals = evaluate_signals("MSFT", snap, config)
    ma = [s for s in signals if s.signal_type == SignalType.MA_GOLDEN_CROSS][0]
    assert ma.confirmation_count == 1
    assert ma.confirmation_volume is True


def test_p_ma_alone_fails():
    config = _config()
    snap = _snapshot(**MA_GOLDEN, **NEUTRAL)
    signals = evaluate_signals("MSFT", snap, config)
    ma = [s for s in signals if s.signal_type == SignalType.MA_GOLDEN_CROSS][0]
    assert ma.confirmation_count == 0


def test_q_opposite_direction_macd_does_not_confirm_ma():
    config = _config()
    snap = _snapshot(**MA_GOLDEN, **BEARISH_MACD, **NEUTRAL)  # MA is bullish (golden cross), MACD is bearish
    signals = evaluate_signals("MSFT", snap, config)
    ma = [s for s in signals if s.signal_type == SignalType.MA_GOLDEN_CROSS][0]
    assert ma.confirmation_macd is False
    assert ma.confirmation_count == 0


# ======================================================================
# General (cases R-Z)
# ======================================================================

def test_r_one_independent_confirmation_is_sufficient():
    config = _config()
    snap = _snapshot(**BULLISH_MACD, rsi=50.0, **SURGE_VOLUME)
    signals = evaluate_signals("AAPL", snap, config)
    macd = [s for s in signals if s.signal_type == SignalType.MACD_BULLISH_CROSS][0]
    assert macd.confirmation_count >= 1  # eligible: exactly the >=1 contract, no threshold sweep


def test_s_confirmation_count_exact_three_for_ma():
    config = _config()
    snap = _snapshot(**MA_GOLDEN, **BULLISH_MACD, **OVERSOLD_RSI, **SURGE_VOLUME)
    signals = evaluate_signals("MSFT", snap, config)
    ma = [s for s in signals if s.signal_type == SignalType.MA_GOLDEN_CROSS][0]
    assert ma.confirmation_count == 3
    assert ma.confluence_score == 3


def test_t_legacy_confluence_score_min_unchanged():
    assert QuantConfig().confluence_score_min == 2


def test_u_experimental_no_family_self_credits_its_own_trigger():
    config = _config()
    # MACD self-exclusion
    macd_state = evaluate_independent_confirmations(
        _snapshot(**BULLISH_MACD), SignalType.MACD_BULLISH_CROSS, SignalDirection.BULLISH,
        config.volume_surge_ratio_threshold, config,
    )
    assert macd_state.macd_confirmed is False
    # RSI self-exclusion (own extreme state cannot confirm its own curl trigger)
    rsi_state = evaluate_independent_confirmations(
        _snapshot(rsi=25.0), SignalType.RSI_OVERSOLD_VOLUME_SURGE, SignalDirection.BULLISH,
        config.volume_surge_ratio_threshold, config,
    )
    assert rsi_state.rsi_confirmed is False
    # MA: no own leg exists to exclude -- confirms nothing is silently invented
    ma_state = evaluate_independent_confirmations(
        _snapshot(), SignalType.MA_GOLDEN_CROSS, SignalDirection.BULLISH,
        config.volume_surge_ratio_threshold, config,
    )
    assert ma_state.confirmation_count == 0


def test_v_direction_aware_macd_helpers():
    bullish_snap = _snapshot(**BULLISH_MACD)
    bearish_snap = _snapshot(**BEARISH_MACD)
    assert _macd_bullish_crossed_this_bar(bullish_snap) is True
    assert _macd_bearish_crossed_this_bar(bullish_snap) is False
    assert _macd_bullish_crossed_this_bar(bearish_snap) is False
    assert _macd_bearish_crossed_this_bar(bearish_snap) is True


def test_w_opportunity_score_ordering_deterministic():
    config = _config()
    snap_one_confirmation = _snapshot(**BULLISH_MACD, rsi=50.0, **SURGE_VOLUME)
    snap_two_confirmations = _snapshot(**BULLISH_MACD, **OVERSOLD_RSI, **SURGE_VOLUME)
    sig_one = [s for s in evaluate_signals("AAPL", snap_one_confirmation, config)
               if s.signal_type == SignalType.MACD_BULLISH_CROSS][0]
    sig_two = [s for s in evaluate_signals("AAPL", snap_two_confirmations, config)
               if s.signal_type == SignalType.MACD_BULLISH_CROSS][0]
    assert _opportunity_score(sig_two, config) > _opportunity_score(sig_one, config)


def test_x_schema_serialization_backward_compatible():
    config = _config(ConfluenceContract.LEGACY)
    snap = _snapshot(**BULLISH_MACD, **OVERSOLD_RSI, **SURGE_VOLUME)
    signals = evaluate_signals("AAPL", snap, config)
    macd = [s for s in signals if s.signal_type == SignalType.MACD_BULLISH_CROSS][0]
    assert macd.confirmation_count is None  # LEGACY never populates these
    assert macd.confirmation_contract is None
    payload = macd.to_redis_payload()
    from talonx_quant.schemas import QuantSignal
    roundtripped = QuantSignal.model_validate_json(payload)
    assert roundtripped.confirmation_count is None
    assert roundtripped.confluence_score == macd.confluence_score
    # an OLD payload with no confirmation_* keys at all must still parse fine
    import json
    old_style = json.loads(payload)
    for key in ("confirmation_count", "confirmation_macd", "confirmation_rsi",
                "confirmation_volume", "confirmation_contract"):
        old_style.pop(key, None)
    QuantSignal.model_validate_json(json.dumps(old_style))  # must not raise


def test_y_direct_confirmation_function_is_pure_and_shared():
    # talonx_backtest.engine reuses evaluate_signals (and therefore
    # evaluate_independent_confirmations) unchanged -- no second
    # implementation. Proven here by calling the same function twice with
    # identical inputs and asserting bit-identical results (a prerequisite
    # for "live and backtest agree" -- both call this exact function).
    config = _config()
    snap = _snapshot(**BULLISH_MACD, **OVERSOLD_RSI, **SURGE_VOLUME)
    a = evaluate_independent_confirmations(snap, SignalType.MACD_BULLISH_CROSS, SignalDirection.BULLISH,
                                            config.volume_surge_ratio_threshold, config)
    b = evaluate_independent_confirmations(snap, SignalType.MACD_BULLISH_CROSS, SignalDirection.BULLISH,
                                            config.volume_surge_ratio_threshold, config)
    assert a == b


def test_z_repeated_deterministic_run_identical():
    config = _config()
    snap = _snapshot(**BULLISH_MACD, **OVERSOLD_RSI, **SURGE_VOLUME)
    run1 = evaluate_signals("AAPL", snap, config)
    run2 = evaluate_signals("AAPL", snap, config)
    assert len(run1) == len(run2)
    for s1, s2 in zip(run1, run2):
        assert s1.confluence_score == s2.confluence_score
        assert s1.confirmation_count == s2.confirmation_count
        assert s1.confirmation_macd == s2.confirmation_macd
        assert s1.confirmation_rsi == s2.confirmation_rsi
        assert s1.confirmation_volume == s2.confirmation_volume
