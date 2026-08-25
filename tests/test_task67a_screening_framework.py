"""
tests/test_task67a_screening_framework.py
--------------------------------------------
Focused tests for research/task67a_lib/screening_framework.py on small
synthetic data (never real market data). Priorities per the Task 67A
brief: causal-windowing correctness, no-future-leakage, and session-close
boundary respected.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.task67a_lib.screening_framework import (
    RTH_CLOSE_UTC_HOUR,
    VerdictInputs,
    _naive_utc_ns,
    add_bar_features,
    add_trading_day,
    causal_atr_proxy,
    causal_price_at_offset,
    causal_session_vwap,
    causal_trailing_return,
    classify_economic_magnitude,
    compute_event_horizon_and_mfe_mae,
    data_sufficiency_label,
    determine_verdict,
    sample_control_candidates,
    session_close_timestamp_utc,
    time_of_day_bucket,
)


# ---------------------------------------------------------------------
# Regression test for the tz-aware object-dtype bug (Task 67B fix):
# pd.Series(tz-aware).to_numpy() yields an `object` array of Timestamps,
# which numpy cannot subtract a timedelta64 from
# (numpy._core._exceptions._UFuncBinaryResolutionError). Every
# causal_*/sample_control_candidates helper that does vectorized time
# arithmetic must route tz-aware timestamp columns through
# `_naive_utc_ns` first, never through a bare `pd.to_datetime(...).to_numpy()`.
# ---------------------------------------------------------------------

def test_naive_utc_ns_returns_datetime64_not_object_dtype_for_tz_aware_input():
    s = pd.Series(pd.date_range("2026-06-01 13:00:00", periods=5, freq="1min", tz="UTC"))
    arr = _naive_utc_ns(s)
    assert arr.dtype.kind == "M", f"expected a datetime64 dtype, got {arr.dtype!r} (object-dtype regression)"
    # Subtracting a timedelta64 must not raise (this is exactly what failed
    # before the fix, inside causal_price_at_offset/causal_atr_proxy).
    shifted = arr - np.timedelta64(60, "s")
    assert shifted[1] == arr[0]


def test_causal_price_at_offset_and_atr_proxy_do_not_raise_on_tz_aware_bars():
    """Direct regression pin for the exact failure mode: both helpers must
    run to completion (no UFuncBinaryResolutionError) on ordinary tz-aware
    bars, which is the only kind of bars this dataset ever has."""
    bars = _minute_bars("AAA", "2026-06-01", 13, 120)
    assert bars["timestamp"].dt.tz is not None  # precondition: genuinely tz-aware
    bars = add_trading_day(bars)
    ref = causal_price_at_offset(bars, 30)  # would raise UFuncBinaryResolutionError pre-fix
    atr = causal_atr_proxy(bars, window_minutes=30)  # ditto
    assert np.isfinite(ref[100])
    assert np.isfinite(atr[100])


def _minute_bars(symbol, day, start_hour, n_minutes, base_price=100.0, step=0.1):
    times = pd.date_range(
        f"{day} {start_hour:02d}:00:00", periods=n_minutes, freq="1min", tz="UTC"
    )
    prices = base_price + step * np.arange(n_minutes)
    return pd.DataFrame({
        "timestamp": times,
        "symbol": symbol,
        "open": prices,
        "high": prices + 0.05,
        "low": prices - 0.05,
        "close": prices,
        "volume": 1000,
    })


# ---------------------------------------------------------------------
# session_close_timestamp_utc
# ---------------------------------------------------------------------

def test_session_close_timestamp_is_20_00_utc_same_date():
    ts = pd.Timestamp("2026-06-01 14:23:00", tz="UTC")
    close = session_close_timestamp_utc(ts)
    assert close == pd.Timestamp("2026-06-01 20:00:00", tz="UTC")
    assert close.hour == RTH_CLOSE_UTC_HOUR


# ---------------------------------------------------------------------
# causal_price_at_offset / causal_trailing_return
# ---------------------------------------------------------------------

def test_causal_price_at_offset_basic_correctness():
    bars = _minute_bars("AAA", "2026-06-01", 13, 120)  # 13:00..14:59
    bars = add_trading_day(bars)
    ref = causal_price_at_offset(bars, 30)
    # Bar at index 40 is 13:40; 30 min before is 13:10 (index 10).
    assert ref[40] == pytest.approx(bars["close"].iloc[10])
    # Warmup: bar at index 5 (13:05) has no bar 30 min earlier same day.
    assert np.isnan(ref[5])


def test_causal_price_at_offset_never_reaches_into_prior_session():
    # Day 1 ends 23:59, day 2 starts 08:00 -- a huge overnight gap.
    day1 = _minute_bars("AAA", "2026-06-01", 22, 5, base_price=100.0)  # 22:00-22:04
    day2 = _minute_bars("AAA", "2026-06-02", 8, 10, base_price=200.0)  # 08:00-08:09
    bars = pd.concat([day1, day2], ignore_index=True)
    bars = add_trading_day(bars)
    # First bar of day 2 (08:00): 60-min lookback would target day1 23:00,
    # and searchsorted would otherwise find day1's last bar (22:04) as the
    # nearest prior bar overall -- must be rejected as NOT same-day.
    ref = causal_price_at_offset(bars, 60)
    day2_first_idx = bars.index[bars["symbol"] == "AAA"][5]  # index 5 is day2 row 0
    assert np.isnan(ref[day2_first_idx])


def test_causal_trailing_return_no_future_leakage():
    """Mutating a FUTURE bar's price must not change an EARLIER bar's
    trailing return -- the defining property of causality."""
    bars = _minute_bars("AAA", "2026-06-01", 13, 120)
    bars = add_trading_day(bars)
    r1 = causal_trailing_return(bars, 30)

    bars_mutated = bars.copy()
    # Blow up the price of the very last bar only.
    bars_mutated.loc[bars_mutated.index[-1], "close"] = 999999.0
    r2 = causal_trailing_return(bars_mutated, 30)

    # Every value except possibly the last row itself must be unchanged.
    np.testing.assert_array_equal(np.nan_to_num(r1[:-1], nan=-1), np.nan_to_num(r2[:-1], nan=-1))


def test_causal_trailing_return_correctness_synthetic():
    bars = _minute_bars("AAA", "2026-06-01", 13, 100, base_price=100.0, step=1.0)
    bars = add_trading_day(bars)
    r = causal_trailing_return(bars, 10)
    # Bar 50 (price = 100+50=150); bar 40 (price = 140); return = 10/140.
    assert r[50] == pytest.approx((150.0 - 140.0) / 140.0)


# ---------------------------------------------------------------------
# causal_atr_proxy
# ---------------------------------------------------------------------

def test_causal_atr_proxy_same_day_only_and_warmup_nan():
    day1 = _minute_bars("AAA", "2026-06-01", 22, 5)
    day2 = _minute_bars("AAA", "2026-06-02", 8, 10)
    bars = pd.concat([day1, day2], ignore_index=True)
    bars = add_trading_day(bars)
    atr = causal_atr_proxy(bars, window_minutes=60)
    day2_first_idx = bars.index[bars["symbol"] == "AAA"][5]
    assert np.isnan(atr[day2_first_idx])  # warmup: no same-day window yet


def test_causal_atr_proxy_is_mean_of_bar_ranges_in_window():
    bars = _minute_bars("AAA", "2026-06-01", 13, 20, base_price=100.0, step=0.0)
    bars = add_trading_day(bars)
    # Every bar has range 0.1 (high=price+0.05, low=price-0.05).
    atr = causal_atr_proxy(bars, window_minutes=5)
    assert atr[10] == pytest.approx(0.1, rel=1e-6)


# ---------------------------------------------------------------------
# causal_session_vwap
# ---------------------------------------------------------------------

def test_causal_session_vwap_expanding_and_causal():
    bars = pd.DataFrame({
        "timestamp": pd.date_range("2026-06-01 13:30:00", periods=3, freq="1min", tz="UTC"),
        "symbol": "AAA",
        "close": [100.0, 110.0, 120.0],
        "volume": [10, 10, 10],
    })
    bars = add_trading_day(bars)
    vwap = causal_session_vwap(bars)
    assert vwap[0] == pytest.approx(100.0)
    assert vwap[1] == pytest.approx((100 * 10 + 110 * 10) / 20)
    # Third bar's VWAP must not be influenced by any bar after it (there
    # are none here, but this asserts it only uses bars 0..2 inclusive).
    assert vwap[2] == pytest.approx((100 * 10 + 110 * 10 + 120 * 10) / 30)


# ---------------------------------------------------------------------
# time_of_day_bucket / add_bar_features
# ---------------------------------------------------------------------

def test_time_of_day_bucket_boundaries():
    ts = pd.Series(pd.to_datetime([
        "2026-06-01 10:00:00", "2026-06-01 13:45:00",
        "2026-06-01 16:00:00", "2026-06-01 19:00:00", "2026-06-01 21:00:00",
    ], utc=True))
    buckets = time_of_day_bucket(ts).tolist()
    assert buckets == ["PRE_MARKET", "OPEN_HOUR", "MIDDAY", "LATE_SESSION", "AFTER_HOURS"]


def test_add_bar_features_adds_expected_columns():
    bars = _minute_bars("AAA", "2026-06-01", 13, 200, base_price=100.0, step=0.01)
    out = add_bar_features(bars)
    assert {"trading_day", "time_of_day_bucket", "trailing_vol_60m", "vol_bucket"} <= set(out.columns)


# ---------------------------------------------------------------------
# compute_event_horizon_and_mfe_mae
# ---------------------------------------------------------------------

def test_compute_event_horizon_and_mfe_mae_respects_session_close_boundary():
    # Bars run 19:30 to 20:29 -- close is 20:00, so a 60m horizon from
    # 19:45 must be bounded to 15 minutes of actual bars, not 60.
    bars = _minute_bars("AAA", "2026-06-01", 19, 60, base_price=100.0, step=0.0)
    bars.loc[bars["timestamp"].dt.minute == 30, "timestamp"] += pd.Timedelta(0)
    events = pd.DataFrame({
        "event_id": [1],
        "symbol": ["AAA"],
        "timestamp": [pd.Timestamp("2026-06-01 19:45:00", tz="UTC")],
        "entry_price": [100.0],
        "direction": [1],
        "risk_per_unit": [1.0],
    })
    hm, mm = compute_event_horizon_and_mfe_mae(bars, events, horizons_minutes=[15, 60])
    row_60 = hm[hm["horizon_label"] == "60m"].iloc[0]
    # pandas stores a bool column as numpy bool dtype, so a value read back
    # via .iloc/[] is numpy.bool_, not the literal Python `True`/`False`
    # object -- compare by value (bool(...) is/== ), not by identity.
    assert bool(row_60["bounded_by_session_close"]) is True
    # From 19:45 to 20:00 close is only 15 minutes of bars.
    assert row_60["bars_observed"] == 15
    row_15 = hm[hm["horizon_label"] == "15m"].iloc[0]
    assert bool(row_15["bounded_by_session_close"]) is False


def test_compute_event_horizon_and_mfe_mae_direction_adjusts_short():
    bars = _minute_bars("AAA", "2026-06-01", 13, 30, base_price=100.0, step=-1.0)  # falling price
    events = pd.DataFrame({
        "event_id": [1],
        "symbol": ["AAA"],
        "timestamp": [pd.Timestamp("2026-06-01 13:00:00", tz="UTC")],
        "entry_price": [100.0],
        "direction": ["short"],
        "risk_per_unit": [1.0],
    })
    hm, mm = compute_event_horizon_and_mfe_mae(bars, events, horizons_minutes=[10])
    row = hm.iloc[0]
    # Price is falling -- favorable for a short -- so the direction-
    # adjusted forward_return_signed_pct must be POSITIVE even though the
    # raw close return is negative.
    assert row["forward_return_pct"] < 0
    assert row["forward_return_signed_pct"] > 0


def test_compute_event_horizon_and_mfe_mae_no_future_leakage():
    bars = _minute_bars("AAA", "2026-06-01", 13, 60, base_price=100.0, step=0.1)
    events = pd.DataFrame({
        "event_id": [1], "symbol": ["AAA"],
        "timestamp": [pd.Timestamp("2026-06-01 13:10:00", tz="UTC")],
        "entry_price": [101.0], "direction": [1], "risk_per_unit": [1.0],
    })
    hm1, mm1 = compute_event_horizon_and_mfe_mae(bars, events, horizons_minutes=[5])

    bars_mutated = bars.copy()
    # Change a bar far in the future (after the 5m horizon window ends).
    bars_mutated.loc[bars_mutated.index[-1], "high"] = 99999.0
    hm2, mm2 = compute_event_horizon_and_mfe_mae(bars_mutated, events, horizons_minutes=[5])

    assert hm1.iloc[0]["forward_return_pct"] == pytest.approx(hm2.iloc[0]["forward_return_pct"])
    assert mm1.iloc[0]["mfe_price"] == pytest.approx(mm2.iloc[0]["mfe_price"])


# ---------------------------------------------------------------------
# sample_control_candidates
# ---------------------------------------------------------------------

def test_sample_control_candidates_excludes_near_event_window():
    bars = _minute_bars("AAA", "2026-06-01", 13, 300, base_price=100.0, step=0.0)
    bars_feat = add_bar_features(bars)
    events = pd.DataFrame({
        "symbol": ["AAA"],
        "timestamp": [pd.Timestamp("2026-06-01 15:00:00", tz="UTC")],
    })
    pool = sample_control_candidates(
        bars_feat, events, stride_minutes=5, exclusion_buffer_minutes=30, warmup_minutes=0, min_lead_minutes=0,
    )
    close_to_event = pool[
        (pool["timestamp"] >= pd.Timestamp("2026-06-01 14:31:00", tz="UTC"))
        & (pool["timestamp"] <= pd.Timestamp("2026-06-01 15:29:00", tz="UTC"))
    ]
    assert close_to_event.empty


def test_sample_control_candidates_respects_warmup_and_lead():
    bars = _minute_bars("AAA", "2026-06-01", 8, 900, base_price=100.0, step=0.0)  # full session
    bars_feat = add_bar_features(bars)
    pool = sample_control_candidates(
        bars_feat, pd.DataFrame(columns=["symbol", "timestamp"]),
        stride_minutes=15, warmup_minutes=90, min_lead_minutes=30,
    )
    session_start = pd.Timestamp("2026-06-01 08:00:00", tz="UTC")
    assert (pool["timestamp"] >= session_start + pd.Timedelta(minutes=90)).all()
    close_ts = session_close_timestamp_utc(session_start)
    assert (pool["timestamp"] <= close_ts - pd.Timedelta(minutes=30)).all()


# ---------------------------------------------------------------------
# classify_economic_magnitude
# ---------------------------------------------------------------------

def test_classify_economic_magnitude_thresholds():
    assert classify_economic_magnitude(0.02, 0.05) == "ECONOMICALLY_TOO_SMALL"  # 2bps excess
    assert classify_economic_magnitude(0.15, 0.30) == "POTENTIALLY_TRADEABLE"  # 15bps excess, thin MFE
    assert classify_economic_magnitude(0.30, 0.50) == "STRONG_EFFECT"  # 30bps excess, ample MFE
    assert classify_economic_magnitude(None, 0.5) == "INSUFFICIENT_DATA"


# ---------------------------------------------------------------------
# data_sufficiency_label
# ---------------------------------------------------------------------

def test_data_sufficiency_label_severely_limited():
    assert data_sufficiency_label(n_events=10, n_symbols=3, n_days=2) == "SEVERELY_LIMITED"


def test_data_sufficiency_label_adequate():
    label = data_sufficiency_label(
        n_events=150, n_symbols=20, n_days=25, top1_symbol_share=0.1, best_day_share=0.1,
    )
    assert label == "ADEQUATE"


def test_data_sufficiency_label_concentration_downgrades_to_limited():
    label = data_sufficiency_label(
        n_events=150, n_symbols=20, n_days=25, top1_symbol_share=0.55, best_day_share=0.1,
    )
    assert label == "LIMITED"


# ---------------------------------------------------------------------
# determine_verdict
# ---------------------------------------------------------------------

def _all_good_verdict_inputs(**overrides) -> VerdictInputs:
    base = dict(
        coherent_direction=True, matched_control_support=True, nontrivial_economic_scale=True,
        adequate_event_count=True, temporal_breadth=True, symbol_breadth=True,
        stable_effect_surface=True, asymmetric_mfe_mae=True, concentration_low=True,
        excess_ci_excludes_zero=True, data_sufficiency="ADEQUATE",
    )
    base.update(overrides)
    return VerdictInputs(**base)


def test_determine_verdict_phenomenon_present():
    verdict, _ = determine_verdict(_all_good_verdict_inputs())
    assert verdict == "PHENOMENON_PRESENT"


def test_determine_verdict_insufficient_data_overrides_everything():
    verdict, _ = determine_verdict(_all_good_verdict_inputs(data_sufficiency="SEVERELY_LIMITED"))
    assert verdict == "INSUFFICIENT_DATA"


def test_determine_verdict_not_observed_when_most_early_kills_fail():
    verdict, _ = determine_verdict(_all_good_verdict_inputs(
        coherent_direction=False, nontrivial_economic_scale=False, stable_effect_surface=False,
        asymmetric_mfe_mae=False, concentration_low=False, excess_ci_excludes_zero=False,
    ))
    assert verdict == "PHENOMENON_NOT_OBSERVED"


def test_determine_verdict_weak_signal_when_mixed():
    verdict, _ = determine_verdict(_all_good_verdict_inputs(
        symbol_breadth=False, temporal_breadth=False,
    ))
    assert verdict == "WEAK_SIGNAL"
