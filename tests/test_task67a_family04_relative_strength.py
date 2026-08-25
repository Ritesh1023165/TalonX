"""
tests/test_task67a_family04_relative_strength.py
---------------------------------------------------------
Focused synthetic-data tests for Family 4 (relative strength vs SPY /
sector ETF) in research/scripts/task67a_family04_relative_strength.py.
Covers: (1) beta estimation correctness on a known synthetic linear
relationship, (2) the causality regression test proving beta estimation
never touches application-half data, (3) event-condition correctness
(RS extremity triggers, direction sign), (4) fail-closed behavior when
calibration-half observations are insufficient. Never real market data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.task67a_lib.screening_framework import add_bar_features, add_trading_day
from research.scripts.task67a_family04_relative_strength import (
    MIN_PAIRED_OBS_FOR_BETA,
    _compute_beta,
    build_rs_candidates,
    calibration_application_split,
    compute_all_betas,
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _return_pattern(n: int) -> np.ndarray:
    """Deterministic, non-degenerate (nonzero variance) synthetic 1-min
    return sequence -- no randomness, so tests are bit-reproducible."""
    idx = np.arange(n)
    return 0.001 * np.sin(idx * 0.13) + 0.0004 * np.cos(idx * 0.05) + 0.0002


def _price_bars_from_returns(symbol: str, day: str, start_hour: int, base_price: float, rets: np.ndarray) -> pd.DataFrame:
    """Builds 1-min OHLCV bars whose close-to-close returns exactly equal
    `rets` (closes[i+1] = closes[i] * (1 + rets[i])); n = len(rets) + 1
    bars total."""
    n = len(rets) + 1
    closes = np.empty(n, dtype=float)
    closes[0] = base_price
    for i, r in enumerate(rets):
        closes[i + 1] = closes[i] * (1.0 + r)
    times = pd.date_range(f"{day} {start_hour:02d}:00:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({
        "timestamp": times, "symbol": symbol,
        "open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000,
    })


def _build_two_day_beta_dataset(stock_multiplier_calib: float, stock_multiplier_app: float, n_per_day: int = 900):
    """Builds a 6-trading-day universe (3 calibration days, 3 application
    days -- calibration_application_split gives an even 3/3 split for a
    6-day input) for one stock ("TESTX", mapped to sector ETF "SECX") vs
    SPY: calibration-half stock returns = stock_multiplier_calib * SPY
    returns; application-half stock returns = stock_multiplier_app * SPY
    returns (a DIFFERENT relationship). `n_per_day` defaults to 900 (this
    dataset's real ~900 bars/session pace) and bars start at 08:00 UTC so
    a day's bars never cross the UTC midnight boundary into the next
    calendar date (900 minutes from 08:00 ends at 23:00, still same UTC
    date) -- crossing midnight would silently create a bogus extra
    "trading day" via add_trading_day's UTC-date normalization. Returns
    (bars_feat, benchmarks, symbol_to_etf, calibration_days,
    application_days).
    """
    days = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05", "2026-06-06"]
    multipliers = [stock_multiplier_calib] * 3 + [stock_multiplier_app] * 3

    spy_frames, stock_frames = [], []
    for day_idx, (day, mult) in enumerate(zip(days, multipliers)):
        spy_rets = _return_pattern(n_per_day) * (1.0 if day_idx % 2 == 0 else 1.3)  # slight variety per day
        spy_bars = _price_bars_from_returns("SPY", day, 8, 500.0, spy_rets)
        stock_bars = _price_bars_from_returns("TESTX", day, 8, 100.0, mult * spy_rets)
        spy_frames.append(spy_bars)
        stock_frames.append(stock_bars)

    spy_all = add_trading_day(pd.concat(spy_frames, ignore_index=True))
    stock_all = add_trading_day(pd.concat(stock_frames, ignore_index=True))
    # A fake sector ETF, identical in shape to SPY but irrelevant to what
    # these tests assert on (beta_spy) -- present only so compute_all_betas
    # (which always computes both) doesn't need special-casing.
    sec_all = spy_all.copy()
    sec_all["symbol"] = "SECX"

    bars_feat = add_bar_features(stock_all)
    benchmarks = {"SPY": spy_all, "SECX": sec_all}
    symbol_to_etf = {"TESTX": "SECX"}

    calibration_days, application_days = calibration_application_split(bars_feat)
    return bars_feat, benchmarks, symbol_to_etf, calibration_days, application_days


# ---------------------------------------------------------------------
# 1. Beta estimation correctness
# ---------------------------------------------------------------------

def test_compute_beta_recovers_known_calibration_slope():
    bars_feat, benchmarks, symbol_to_etf, calibration_days, _ = _build_two_day_beta_dataset(
        stock_multiplier_calib=2.0, stock_multiplier_app=-1.0,
    )
    beta_df = compute_all_betas(bars_feat, benchmarks, symbol_to_etf, calibration_days)
    row = beta_df.set_index("symbol").loc["TESTX"]
    assert row["trustworthy_spy"]
    assert row["n_pairs_spy"] >= MIN_PAIRED_OBS_FOR_BETA
    assert row["beta_spy"] == pytest.approx(2.0, abs=1e-6)


def test_compute_beta_direct_low_level_matches_slope():
    # Direct _compute_beta call on the calibration-half frames alone
    # (below the family-script's own calibration_application_split), for
    # a second, more isolated correctness signal.
    rets = _return_pattern(3000)
    spy_bars = add_trading_day(_price_bars_from_returns("SPY", "2026-06-01", 8, 500.0, rets))
    stock_bars = add_trading_day(_price_bars_from_returns("TESTX", "2026-06-01", 8, 100.0, 1.5 * rets))
    beta, n = _compute_beta(stock_bars, spy_bars)
    assert n >= MIN_PAIRED_OBS_FOR_BETA
    assert beta == pytest.approx(1.5, abs=1e-6)


# ---------------------------------------------------------------------
# 2. Causality regression test: beta never uses application-half data
# ---------------------------------------------------------------------

def test_beta_never_uses_application_half_data():
    # Version 1: application half has stock = -1.0 * SPY.
    bars_feat_v1, benchmarks_v1, symbol_to_etf, calibration_days_v1, _ = _build_two_day_beta_dataset(
        stock_multiplier_calib=2.0, stock_multiplier_app=-1.0,
    )
    beta_v1 = compute_all_betas(bars_feat_v1, benchmarks_v1, symbol_to_etf, calibration_days_v1)
    beta_spy_v1 = beta_v1.set_index("symbol").loc["TESTX", "beta_spy"]

    # Version 2: SAME calibration half, WILDLY DIFFERENT application half
    # (stock = +7.0 * SPY instead of -1.0 * SPY). If beta estimation ever
    # touched application-half data, this would change the computed beta.
    bars_feat_v2, benchmarks_v2, symbol_to_etf2, calibration_days_v2, _ = _build_two_day_beta_dataset(
        stock_multiplier_calib=2.0, stock_multiplier_app=7.0,
    )
    beta_v2 = compute_all_betas(bars_feat_v2, benchmarks_v2, symbol_to_etf2, calibration_days_v2)
    beta_spy_v2 = beta_v2.set_index("symbol").loc["TESTX", "beta_spy"]

    assert beta_spy_v1 == pytest.approx(2.0, abs=1e-6)
    assert beta_spy_v2 == pytest.approx(2.0, abs=1e-6)
    assert beta_spy_v1 == pytest.approx(beta_spy_v2, abs=1e-9), (
        "beta_spy changed when only the APPLICATION half's data changed -- "
        "beta estimation must be strictly calibration-half-only."
    )


# ---------------------------------------------------------------------
# 3. Fail-closed behavior on insufficient calibration observations
# ---------------------------------------------------------------------

def test_compute_beta_fails_closed_on_insufficient_observations():
    n_small = 50  # well below MIN_PAIRED_OBS_FOR_BETA
    rets = _return_pattern(n_small)
    spy_bars = add_trading_day(_price_bars_from_returns("SPY", "2026-06-01", 8, 500.0, rets))
    stock_bars = add_trading_day(_price_bars_from_returns("TESTX", "2026-06-01", 8, 100.0, 2.0 * rets))
    beta, n = _compute_beta(stock_bars, spy_bars)
    assert n == n_small
    assert n < MIN_PAIRED_OBS_FOR_BETA
    assert beta is None, "beta must fail closed (None), not fall back to any default, when n < MIN_PAIRED_OBS_FOR_BETA"


def test_compute_all_betas_flags_fail_closed_symbol():
    bars_feat, benchmarks, symbol_to_etf, calibration_days, _ = _build_two_day_beta_dataset(
        stock_multiplier_calib=2.0, stock_multiplier_app=-1.0, n_per_day=50,  # too few pairs per day
    )
    beta_df = compute_all_betas(bars_feat, benchmarks, symbol_to_etf, calibration_days)
    row = beta_df.set_index("symbol").loc["TESTX"]
    assert not row["trustworthy_spy"]
    assert row["beta_spy"] is None


# ---------------------------------------------------------------------
# 4. Event-condition correctness: RS extremity + direction sign
# ---------------------------------------------------------------------

def _rs_event_dataset():
    """One symbol, one application day: SPY is flat throughout; the
    symbol is flat for most of the day except a short strong rally near
    the end (well after 14:00 UTC, well before session close) and a
    short strong selloff earlier (also outside the exclusion windows).
    Most of the day should have RAW RS ~ 0 (not extreme); the rally/
    selloff bars should be the extreme tail."""
    day = "2026-07-01"
    n = 300
    times = pd.date_range(f"{day} 13:00:00", periods=n, freq="1min", tz="UTC")

    spy_close = np.full(n, 500.0)  # perfectly flat SPY all day

    stock_close = np.full(n, 100.0)
    # Selloff block: minutes 60-74 (14:00-14:14 UTC) -- after the 14:00 cutoff.
    selloff_start, selloff_end = 60, 75
    stock_close[selloff_start:selloff_end] = np.linspace(100.0, 92.0, selloff_end - selloff_start)
    stock_close[selloff_end:] = 92.0
    # Rally block: minutes 200-214 (16:20-16:34 UTC), well before RTH close (20:00 UTC).
    rally_start, rally_end = 200, 215
    stock_close[rally_start:rally_end] = np.linspace(92.0, 105.0, rally_end - rally_start)
    stock_close[rally_end:] = 105.0

    spy_bars = pd.DataFrame({
        "timestamp": times, "symbol": "SPY",
        "open": spy_close, "high": spy_close, "low": spy_close, "close": spy_close, "volume": 1000,
    })
    stock_bars = pd.DataFrame({
        "timestamp": times, "symbol": "TESTX",
        "open": stock_close, "high": stock_close, "low": stock_close, "close": stock_close, "volume": 1000,
    })
    spy_all = add_trading_day(spy_bars)
    sec_all = spy_all.copy()
    sec_all["symbol"] = "SECX"
    bars_feat = add_bar_features(add_trading_day(stock_bars))
    benchmarks = {"SPY": spy_all, "SECX": sec_all}
    symbol_to_etf = {"TESTX": "SECX"}
    application_days = bars_feat["trading_day"].unique()
    return bars_feat, benchmarks, symbol_to_etf, application_days, times, rally_end - 1, selloff_end - 1


def test_rs_event_fires_with_correct_direction_sign():
    bars_feat, benchmarks, symbol_to_etf, application_days, times, rally_last_idx, selloff_last_idx = _rs_event_dataset()
    cand, tail_info = build_rs_candidates(bars_feat, benchmarks, symbol_to_etf, application_days, window_minutes=30)

    assert not cand.empty, "expected the rally/selloff blocks to fire as extreme RAW RS events"

    rally_ts = times[rally_last_idx]
    selloff_ts = times[selloff_last_idx]

    rally_rows = cand[cand["timestamp"] == rally_ts]
    selloff_rows = cand[cand["timestamp"] == selloff_ts]
    assert len(rally_rows) == 1, "the rally's final bar (strongest positive RS) should fire"
    assert len(selloff_rows) == 1, "the selloff's final bar (strongest negative RS) should fire"
    assert rally_rows.iloc[0]["direction"] == 1
    assert rally_rows.iloc[0]["raw_rs"] > 0
    assert selloff_rows.iloc[0]["direction"] == -1
    assert selloff_rows.iloc[0]["raw_rs"] < 0


def test_rs_event_does_not_fire_on_flat_middle_of_day():
    bars_feat, benchmarks, symbol_to_etf, application_days, times, *_ = _rs_event_dataset()
    cand, _ = build_rs_candidates(bars_feat, benchmarks, symbol_to_etf, application_days, window_minutes=30)
    # A bar deep in the flat stretch between the selloff and the rally
    # (RAW RS == 0 there) must not be flagged as an extreme-tail event.
    flat_ts = times[150]
    assert not (cand["timestamp"] == flat_ts).any()


def test_rs_event_excludes_first_30_minutes_of_rth():
    # Re-run the same dataset but with the selloff moved into the first
    # 30 minutes of RTH (13:30-14:00 UTC) -- must not fire there
    # regardless of how extreme the RS signal is.
    day = "2026-07-01"
    n = 120
    times = pd.date_range(f"{day} 13:30:00", periods=n, freq="1min", tz="UTC")
    spy_close = np.full(n, 500.0)
    stock_close = np.full(n, 100.0)
    stock_close[5:20] = np.linspace(100.0, 80.0, 15)
    stock_close[20:] = 80.0

    spy_bars = add_trading_day(pd.DataFrame({
        "timestamp": times, "symbol": "SPY",
        "open": spy_close, "high": spy_close, "low": spy_close, "close": spy_close, "volume": 1000,
    }))
    sec_bars = spy_bars.copy()
    sec_bars["symbol"] = "SECX"
    stock_bars = pd.DataFrame({
        "timestamp": times, "symbol": "TESTX",
        "open": stock_close, "high": stock_close, "low": stock_close, "close": stock_close, "volume": 1000,
    })
    bars_feat = add_bar_features(add_trading_day(stock_bars))
    benchmarks = {"SPY": spy_bars, "SECX": sec_bars}
    symbol_to_etf = {"TESTX": "SECX"}
    application_days = bars_feat["trading_day"].unique()

    cand, _ = build_rs_candidates(bars_feat, benchmarks, symbol_to_etf, application_days, window_minutes=15)
    assert cand.empty, "a qualifying RS extremity entirely within the first 30m of RTH must not fire"


def test_rs_event_restricted_to_application_half_only():
    # Build a dataset where an equally extreme RS burst occurs on a
    # CALIBRATION-half day; build_rs_candidates must not fire on it even
    # though the raw signal itself would otherwise qualify.
    bars_feat, benchmarks, symbol_to_etf, application_days, times, *_ = _rs_event_dataset()
    # Deliberately pass an EMPTY application_days set standing in for "this
    # day is calibration, not application" -- the whole day's events must
    # vanish even though the underlying RS signal is identical.
    empty_application_days = bars_feat["trading_day"].unique()[:0]
    cand, _ = build_rs_candidates(bars_feat, benchmarks, symbol_to_etf, empty_application_days, window_minutes=30)
    assert cand.empty, "no event should fire when its trading_day is not in application_days"
