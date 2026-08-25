"""
tests/test_task67a_family06_opening_later.py
-----------------------------------------------------
Focused synthetic-data tests for the Family 6 (opening information ->
later-session continuation) event-CONDITION functions in
research/scripts/task67a_family06_opening_later.py -- hand-constructed
1-minute bars where the opening-window (13:30-14:00 UTC) open/close/
volume values are directly controlled. Never real market data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.task67a_lib.screening_framework import add_bar_features, add_trading_day
from research.scripts.task67a_family06_opening_later import (
    OPENING_WINDOW_MIN_BARS,
    SIGNAL_TOP_TERTILE_QUANTILE,
    _decision_bars,
    _leave_one_day_out_median,
    _opening_window_agg,
    definition_a_opening_return_magnitude,
    definition_b_opening_relative_strength,
    definition_c_opening_relative_volume,
)

_WIN_START = 13 * 60 + 30  # 810 = 13:30 UTC
_WIN_END = 14 * 60  # 840 = 14:00 UTC


def _flat_day_bars(symbol, day, start_hour=8, end_hour=16, price=100.0, volume=1000):
    """One trading day's worth of 1-minute bars, all identical
    OHLC=`price`/volume=`volume` -- a deliberately inert baseline that
    tests then overwrite specific slices of (via boolean minutes-of-day
    masks) to build controlled opening-window / later-session values."""
    start = pd.Timestamp(f"{day} {start_hour:02d}:00:00", tz="UTC")
    end = pd.Timestamp(f"{day} {end_hour:02d}:00:00", tz="UTC")
    times = pd.date_range(start, end, freq="1min", inclusive="left")
    n = len(times)
    return pd.DataFrame({
        "timestamp": times, "symbol": symbol,
        "open": float(price), "high": float(price), "low": float(price), "close": float(price),
        "volume": volume,
    }).astype({"open": float, "high": float, "low": float, "close": float})


def _minutes_of_day(bars: pd.DataFrame) -> pd.Series:
    return bars["timestamp"].dt.hour * 60 + bars["timestamp"].dt.minute


def _set_opening_window(bars: pd.DataFrame, *, open_price=100.0, close_price=100.0, volume=None) -> pd.DataFrame:
    """Mutates `bars` in place: sets the opening-window (13:30-14:00 UTC)
    bars' first-bar open to `open_price` and last-bar close to
    `close_price` (the two values `_opening_window_agg` actually reads),
    and optionally overrides the whole window's per-bar volume."""
    mod = _minutes_of_day(bars)
    idxw = bars.index[((mod >= _WIN_START) & (mod < _WIN_END)).to_numpy()]
    assert len(idxw) > 0, "test bars must cover the 13:30-14:00 UTC window"
    bars.loc[idxw, "open"] = 100.0
    bars.loc[idxw, "close"] = 100.0
    bars.loc[idxw[0], "open"] = open_price
    bars.loc[idxw[-1], "close"] = close_price
    if volume is not None:
        bars.loc[idxw, "volume"] = 0
        bars.loc[idxw[0], "volume"] = volume
    return bars


def _multi_day_bars(symbol, days, opening_returns, *, start_hour=13, end_hour=16, base_price=100.0):
    frames = []
    for day, r in zip(days, opening_returns):
        bars = _flat_day_bars(symbol, day, start_hour=start_hour, end_hour=end_hour, price=base_price, volume=1000)
        _set_opening_window(bars, open_price=base_price, close_price=base_price * (1 + r))
        frames.append(bars)
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------
# _opening_window_agg: signal computation correctness
# ---------------------------------------------------------------------

def test_opening_window_agg_basic_correctness():
    bars = _flat_day_bars("AAA", "2026-06-01", start_hour=13, end_hour=15, price=100.0, volume=1000)
    mod = _minutes_of_day(bars)
    idxw = bars.index[((mod >= _WIN_START) & (mod < _WIN_END)).to_numpy()]
    n = len(idxw)
    assert n == 30
    bars.loc[idxw, "open"] = np.linspace(100.0, 102.9, n)
    bars.loc[idxw, "close"] = np.linspace(100.1, 103.0, n)
    bars.loc[idxw, "volume"] = 500

    bars = add_trading_day(bars)
    agg = _opening_window_agg(bars)
    assert len(agg) == 1
    row = agg.iloc[0]
    assert row["window_open"] == pytest.approx(bars.loc[idxw[0], "open"])
    assert row["window_close"] == pytest.approx(bars.loc[idxw[-1], "close"])
    expected_return = (row["window_close"] - row["window_open"]) / row["window_open"]
    assert row["opening_return"] == pytest.approx(expected_return)
    assert row["window_volume"] == pytest.approx(500 * n)
    assert row["n_bars"] == n


# ---------------------------------------------------------------------
# Leakage-in-the-other-direction: the opening-window signal must never
# reach outside [13:30, 14:00) UTC.
# ---------------------------------------------------------------------

def test_opening_window_agg_never_reaches_outside_window():
    bars = _flat_day_bars("AAA", "2026-06-01", start_hour=13, end_hour=15, price=100.0, volume=1000)
    mod = _minutes_of_day(bars)
    pre_mask = (mod < _WIN_START).to_numpy()
    win_mask = ((mod >= _WIN_START) & (mod < _WIN_END)).to_numpy()
    post_mask = (mod >= _WIN_END).to_numpy()

    # Obviously-wrong sentinel values outside the window -- if the
    # aggregation ever leaked into these, the assertions below would fail.
    bars.loc[pre_mask, ["open", "close"]] = 111.0
    bars.loc[post_mask, ["open", "close"]] = 999.0
    idxw = bars.index[win_mask]
    bars.loc[idxw, "open"] = 50.0
    bars.loc[idxw, "close"] = 50.0
    bars.loc[idxw[0], "open"] = 50.0
    bars.loc[idxw[-1], "close"] = 55.0

    bars = add_trading_day(bars)
    agg = _opening_window_agg(bars)
    row = agg.iloc[0]
    assert row["window_open"] == pytest.approx(50.0)
    assert row["window_close"] == pytest.approx(55.0)
    assert row["opening_return"] == pytest.approx(0.1)


# ---------------------------------------------------------------------
# Decision timestamp placement
# ---------------------------------------------------------------------

def test_decision_bar_is_exactly_1400_utc_when_available():
    bars = _flat_day_bars("AAA", "2026-06-01", start_hour=13, end_hour=15)
    bars_feat = add_bar_features(bars)
    dec = _decision_bars(bars_feat)
    assert len(dec) == 1
    assert dec.iloc[0]["timestamp"] == pd.Timestamp("2026-06-01 14:00:00", tz="UTC")


def test_decision_bar_falls_back_to_next_available_bar_on_gap():
    bars = _flat_day_bars("AAA", "2026-06-01", start_hour=13, end_hour=15)
    bars = bars[bars["timestamp"] != pd.Timestamp("2026-06-01 14:00:00", tz="UTC")].reset_index(drop=True)
    bars_feat = add_bar_features(bars)
    dec = _decision_bars(bars_feat)
    assert len(dec) == 1
    assert dec.iloc[0]["timestamp"] == pd.Timestamp("2026-06-01 14:01:00", tz="UTC")


# ---------------------------------------------------------------------
# Definition A: opening_return_magnitude -- signal + tertile + direction
# ---------------------------------------------------------------------

def test_definition_a_signal_correctness_tertile_and_direction():
    days = [f"2026-06-{i + 1:02d}" for i in range(6)]
    # |returns| = [0.0010, 0.0020, 0.0200, 0.0300, 0.0015, 0.0012] -- top
    # global tertile (top 2 of 6, quantile-2/3 cutoff = 0.008, verified by
    # hand: sorted |r| = [0.0010,0.0012,0.0015,0.0020,0.0200,0.0300],
    # q=2/3 index=3.333 -> interpolate 0.0020 + 0.333*(0.0200-0.0020)
    # = 0.008) is exactly days[2] (+0.02) and days[3] (-0.03).
    returns = [0.001, -0.002, 0.02, -0.03, 0.0015, -0.0012]
    bars = _multi_day_bars("AAA", days, returns, start_hour=13, end_hour=15)
    bars_feat = add_bar_features(bars)
    events = definition_a_opening_return_magnitude(bars_feat)

    fired_days = set(pd.to_datetime(events["trading_day"]).dt.strftime("%Y-%m-%d"))
    assert fired_days == {days[2], days[3]}

    row2 = events[pd.to_datetime(events["trading_day"]).dt.strftime("%Y-%m-%d") == days[2]].iloc[0]
    row3 = events[pd.to_datetime(events["trading_day"]).dt.strftime("%Y-%m-%d") == days[3]].iloc[0]
    assert row2["direction"] == 1  # +0.02 open -> momentum-agnostic sign is +1
    assert row3["direction"] == -1  # -0.03 open -> sign is -1
    assert (events["timestamp"].dt.hour == 14).all() and (events["timestamp"].dt.minute == 0).all()


def test_definition_a_no_future_leakage():
    days = [f"2026-06-{i + 1:02d}" for i in range(6)]
    returns = [0.001, -0.002, 0.02, -0.03, 0.0015, -0.0012]
    bars = _multi_day_bars("AAA", days, returns, start_hour=13, end_hour=16)
    bars_feat1 = add_bar_features(bars)
    ev1 = definition_a_opening_return_magnitude(bars_feat1)

    bars_mutated = bars.copy()
    post_mask = (_minutes_of_day(bars_mutated) > _WIN_END).to_numpy()
    bars_mutated.loc[post_mask, ["open", "high", "low", "close"]] = 999999.0
    bars_feat2 = add_bar_features(bars_mutated)
    ev2 = definition_a_opening_return_magnitude(bars_feat2)

    pd.testing.assert_frame_equal(
        ev1.sort_values("trading_day").reset_index(drop=True),
        ev2.sort_values("trading_day").reset_index(drop=True),
    )


# ---------------------------------------------------------------------
# Definition B: opening_relative_strength_vs_spy
# ---------------------------------------------------------------------

def test_definition_b_relative_signal_is_symbol_minus_spy():
    days = [f"2026-06-{i + 1:02d}" for i in range(6)]
    # Symbol's own opening returns; SPY's are NOT flat this time, so the
    # relative signal genuinely differs from the absolute one -- verifies
    # the subtraction, not just a degenerate flat-SPY passthrough.
    sym_returns = [0.01, 0.01, 0.01, -0.01, -0.01, -0.01]
    spy_returns = [0.001, 0.005, 0.03, -0.001, -0.005, -0.03]
    # relative = sym - spy:
    #   day0: 0.009, day1: 0.005, day2: -0.02, day3: -0.009, day4: -0.005, day5: 0.02
    # |relative| sorted = [0.005,0.005,0.009,0.009,0.02,0.02]; q=2/3 index=3.333
    # -> interpolate sorted[3]=0.009 + 0.333*(0.02-0.009) = 0.01267 -> only
    # day2 (-0.02) and day5 (+0.02) clear the cutoff.
    bars = _multi_day_bars("AAA", days, sym_returns, start_hour=13, end_hour=15)
    spy_bars = _multi_day_bars("SPY", days, spy_returns, start_hour=13, end_hour=15)
    bars_feat = add_bar_features(bars)
    spy_with_day = add_trading_day(spy_bars)

    events = definition_b_opening_relative_strength(bars_feat, spy_with_day)
    fired_days = set(pd.to_datetime(events["trading_day"]).dt.strftime("%Y-%m-%d"))
    assert fired_days == {days[2], days[5]}

    row2 = events[pd.to_datetime(events["trading_day"]).dt.strftime("%Y-%m-%d") == days[2]].iloc[0]
    row5 = events[pd.to_datetime(events["trading_day"]).dt.strftime("%Y-%m-%d") == days[5]].iloc[0]
    assert row2["direction"] == -1  # relative = -0.02
    assert row5["direction"] == 1  # relative = +0.02


def test_definition_b_no_future_leakage():
    days = [f"2026-06-{i + 1:02d}" for i in range(6)]
    sym_returns = [0.01, 0.01, 0.01, -0.01, -0.01, -0.01]
    spy_returns = [0.001, 0.005, 0.03, -0.001, -0.005, -0.03]
    bars = _multi_day_bars("AAA", days, sym_returns, start_hour=13, end_hour=16)
    spy_bars = _multi_day_bars("SPY", days, spy_returns, start_hour=13, end_hour=16)
    spy_with_day = add_trading_day(spy_bars)

    bars_feat1 = add_bar_features(bars)
    ev1 = definition_b_opening_relative_strength(bars_feat1, spy_with_day)

    bars_mutated = bars.copy()
    post_mask = (_minutes_of_day(bars_mutated) > _WIN_END).to_numpy()
    bars_mutated.loc[post_mask, ["open", "high", "low", "close"]] = 999999.0
    bars_feat2 = add_bar_features(bars_mutated)
    ev2 = definition_b_opening_relative_strength(bars_feat2, spy_with_day)

    pd.testing.assert_frame_equal(
        ev1.sort_values("trading_day").reset_index(drop=True),
        ev2.sort_values("trading_day").reset_index(drop=True),
    )


# ---------------------------------------------------------------------
# _leave_one_day_out_median: direct correctness
# ---------------------------------------------------------------------

def test_leave_one_day_out_median_even_count():
    values = np.array([1000.0, 2000.0, 3000.0, 4000.0])
    result = _leave_one_day_out_median(values)
    assert result[0] == pytest.approx(3000.0)  # median([2000,3000,4000])
    assert result[1] == pytest.approx(3000.0)  # median([1000,3000,4000])
    assert result[2] == pytest.approx(2000.0)  # median([1000,2000,4000])
    assert result[3] == pytest.approx(2000.0)  # median([1000,2000,3000])


def test_leave_one_day_out_median_odd_count():
    values = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    result = _leave_one_day_out_median(values)
    assert result[2] == pytest.approx(30.0)  # median([10,20,40,50])
    assert result[0] == pytest.approx(35.0)  # median([20,30,40,50])
    assert result[4] == pytest.approx(25.0)  # median([10,20,30,40])


# ---------------------------------------------------------------------
# Definition C: opening_relative_volume -- LOO normalization end-to-end
# ---------------------------------------------------------------------

def test_definition_c_leave_one_day_out_normalization_and_direction():
    volumes = [900.0, 950.0, 1000.0, 1050.0, 1100.0, 5000.0]
    days = [f"2026-06-{i + 1:02d}" for i in range(len(volumes))]
    frames = []
    for day, vol in zip(days, volumes):
        bars = _flat_day_bars("AAA", day, start_hour=13, end_hour=15, price=100.0, volume=0)
        # +1% opening return every day (same sign) so direction never zeroes
        # out and only the VOLUME condition determines which days fire.
        _set_opening_window(bars, open_price=100.0, close_price=101.0, volume=vol)
        frames.append(bars)
    bars_all = pd.concat(frames, ignore_index=True)
    bars_feat = add_bar_features(bars_all)

    # Independently recompute expected LOO medians / relative volumes /
    # fired days here (NOT via the module's own helper) so this is a real
    # regression check, not a tautology.
    vol_arr = np.array(volumes)
    expected_loo_median = np.array([np.median(np.delete(vol_arr, i)) for i in range(len(vol_arr))])
    expected_relative_volume = vol_arr / expected_loo_median
    expected_cutoff = pd.Series(expected_relative_volume).quantile(SIGNAL_TOP_TERTILE_QUANTILE)
    expected_fired = {days[i] for i in range(len(days)) if expected_relative_volume[i] >= expected_cutoff}

    events = definition_c_opening_relative_volume(bars_feat)
    fired_days = set(pd.to_datetime(events["trading_day"]).dt.strftime("%Y-%m-%d"))
    assert fired_days == expected_fired
    assert days[-1] in fired_days  # the 5000-volume outlier day must fire
    # Every fired event's direction should be +1 (every day's opening return is +1%).
    assert (events["direction"] == 1).all()


def test_definition_c_no_future_leakage():
    volumes = [900.0, 950.0, 1000.0, 1050.0, 1100.0, 5000.0]
    days = [f"2026-06-{i + 1:02d}" for i in range(len(volumes))]
    frames = []
    for day, vol in zip(days, volumes):
        bars = _flat_day_bars("AAA", day, start_hour=13, end_hour=16, price=100.0, volume=0)
        _set_opening_window(bars, open_price=100.0, close_price=101.0, volume=vol)
        frames.append(bars)
    bars = pd.concat(frames, ignore_index=True)
    bars_feat1 = add_bar_features(bars)
    ev1 = definition_c_opening_relative_volume(bars_feat1)

    bars_mutated = bars.copy()
    post_mask = (_minutes_of_day(bars_mutated) > _WIN_END).to_numpy()
    bars_mutated.loc[post_mask, ["open", "high", "low", "close"]] = 999999.0
    bars_feat2 = add_bar_features(bars_mutated)
    ev2 = definition_c_opening_relative_volume(bars_feat2)

    pd.testing.assert_frame_equal(
        ev1.sort_values("trading_day").reset_index(drop=True),
        ev2.sort_values("trading_day").reset_index(drop=True),
    )


# ---------------------------------------------------------------------
# Data-quality guard: sparse opening window must not fire
# ---------------------------------------------------------------------

def test_sparse_opening_window_below_min_bars_does_not_fire():
    bars = _flat_day_bars("AAA", "2026-06-01", start_hour=13, end_hour=15, price=100.0, volume=1000)
    mod = _minutes_of_day(bars)
    win_mask = ((mod >= _WIN_START) & (mod < _WIN_END)).to_numpy()
    idxw = bars.index[win_mask]
    assert len(idxw) == 30
    # Keep only 5 of the 30 opening-window bars (well below OPENING_WINDOW_MIN_BARS).
    keep = set(idxw[:5])
    drop_idx = [i for i in idxw if i not in keep]
    bars = bars.drop(index=drop_idx).reset_index(drop=True)
    bars.loc[bars.index[bars["symbol"] == "AAA"][:5], "close"] = [100, 101, 102, 103, 110]  # large move, would otherwise fire

    bars_feat = add_bar_features(bars)
    assert OPENING_WINDOW_MIN_BARS == 20
    events = definition_a_opening_return_magnitude(bars_feat)
    assert events.empty
