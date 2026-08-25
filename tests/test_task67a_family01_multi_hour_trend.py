"""
tests/test_task67a_family01_multi_hour_trend.py
---------------------------------------------------
Focused synthetic-data tests for the Family 1 (multi-hour trend
persistence) event-CONDITION functions in
research/scripts/task67a_family01_multi_hour_trend.py -- hand-constructed
price paths that must (or must not) fire each definition, per the Task
67B brief's testing requirement. Never real market data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.task67a_lib.screening_framework import add_bar_features
from research.scripts.task67a_family01_multi_hour_trend import (
    definition_a_trend60_slope_consistent,
    definition_b_trend90_subwindow_agreement,
    definition_c_multiwindow_agreement_30_60_90,
)


def _bars(symbol, day, start_hour, prices, volume=1000):
    n = len(prices)
    times = pd.date_range(f"{day} {start_hour:02d}:00:00", periods=n, freq="1min", tz="UTC")
    prices = np.asarray(prices, dtype=float)
    return pd.DataFrame({
        "timestamp": times, "symbol": symbol,
        "open": prices, "high": prices + 0.02, "low": prices - 0.02, "close": prices,
        "volume": volume,
    })


def _steady_uptrend(n, start=100.0, step=0.02):
    return start + step * np.arange(n)


def _flat(n, level=100.0):
    return np.full(n, level, dtype=float)


# ---------------------------------------------------------------------
# Definition A: trend60_slope_consistent
# ---------------------------------------------------------------------

def test_definition_a_fires_on_steady_uptrend():
    # 0.02/min * 60min = 1.2 total move on base 100 => 1.2% >> 0.4% threshold,
    # and every 20m sub-window is monotonically up (consistent slope).
    bars = _bars("AAA", "2026-06-01", 13, _steady_uptrend(120, step=0.02))
    bars = add_bar_features(bars)
    events = definition_a_trend60_slope_consistent(bars)
    # Bar at 90 minutes in (14:30) should qualify: full 60m history behind it.
    assert (events["timestamp"] == pd.Timestamp("2026-06-01 14:30:00", tz="UTC")).any()
    fired = events[events["timestamp"] == pd.Timestamp("2026-06-01 14:30:00", tz="UTC")].iloc[0]
    assert fired["direction"] == 1


def test_definition_a_does_not_fire_on_flat_price():
    bars = _bars("AAA", "2026-06-01", 13, _flat(120))
    bars = add_bar_features(bars)
    events = definition_a_trend60_slope_consistent(bars)
    assert events.empty


def test_definition_a_does_not_fire_on_inconsistent_slope():
    # Up, then down, then up again within the 60m window -- big enough net
    # move but sub-windows disagree in sign, so slope-consistency must reject it.
    n = 120
    prices = np.concatenate([
        100.0 + 0.05 * np.arange(20),        # up 20m
        100.0 + 0.05 * 20 - 0.05 * np.arange(20),  # down 20m (reverses)
        (100.0 + 0.05 * 20 - 0.05 * 20) + 0.05 * np.arange(80),  # up rest
    ])
    bars = _bars("AAA", "2026-06-01", 13, prices)
    bars = add_bar_features(bars)
    events = definition_a_trend60_slope_consistent(bars)
    # The bar exactly 60 minutes after start (index 60, offsets 0/20/40/60 land
    # on the reversal boundaries) must NOT fire since sub2 (20-40m ago) opposes.
    target_ts = pd.Timestamp("2026-06-01 14:00:00", tz="UTC")
    assert not (events["timestamp"] == target_ts).any()


def test_definition_a_direction_is_negative_on_downtrend():
    bars = _bars("AAA", "2026-06-01", 13, _steady_uptrend(120, step=-0.02))
    bars = add_bar_features(bars)
    events = definition_a_trend60_slope_consistent(bars)
    assert len(events) > 0
    assert (events["direction"] == -1).all()


# ---------------------------------------------------------------------
# Definition B: trend90_subwindow_agreement
# ---------------------------------------------------------------------

def test_definition_b_fires_on_steady_uptrend_90m():
    bars = _bars("AAA", "2026-06-01", 13, _steady_uptrend(150, step=0.02))
    bars = add_bar_features(bars)
    events = definition_b_trend90_subwindow_agreement(bars)
    target_ts = pd.Timestamp("2026-06-01 14:30:00", tz="UTC")  # 90 min after 13:00
    assert (events["timestamp"] == target_ts).any()


def test_definition_b_does_not_fire_when_majority_of_subwindows_disagree():
    # Alternate direction every 15 minutes -- at most half the sub-windows can
    # agree with the net 90m sign, well under the required 5/6.
    n = 150
    chunks = []
    level = 100.0
    for k in range(10):
        step = 0.05 if k % 2 == 0 else -0.05
        chunk = level + step * np.arange(15)
        chunks.append(chunk)
        level = chunk[-1]
    prices = np.concatenate(chunks)
    bars = _bars("AAA", "2026-06-01", 13, prices)
    bars = add_bar_features(bars)
    events = definition_b_trend90_subwindow_agreement(bars)
    assert events.empty


def test_definition_b_requires_minimum_magnitude():
    # Consistent direction but tiny magnitude (well under 0.5% threshold).
    bars = _bars("AAA", "2026-06-01", 13, _steady_uptrend(150, step=0.0005))
    bars = add_bar_features(bars)
    events = definition_b_trend90_subwindow_agreement(bars)
    assert events.empty


# ---------------------------------------------------------------------
# Definition C: multiwindow_agreement_30_60_90
# ---------------------------------------------------------------------

def test_definition_c_fires_on_steady_uptrend():
    bars = _bars("AAA", "2026-06-01", 13, _steady_uptrend(150, step=0.02))
    bars = add_bar_features(bars)
    events = definition_c_multiwindow_agreement_30_60_90(bars)
    target_ts = pd.Timestamp("2026-06-01 14:30:00", tz="UTC")
    assert (events["timestamp"] == target_ts).any()


def test_definition_c_does_not_fire_when_recent_window_reverses():
    # Up for 90 minutes total, but the most recent 30m reversed direction --
    # 30m window disagrees with 60m/90m windows' sign.
    up = 100.0 + 0.05 * np.arange(120)
    down = up[-1] - 0.08 * np.arange(30)
    prices = np.concatenate([up, down])
    bars = _bars("AAA", "2026-06-01", 13, prices)
    bars = add_bar_features(bars)
    events = definition_c_multiwindow_agreement_30_60_90(bars)
    target_ts = pd.Timestamp("2026-06-01 15:29:00", tz="UTC")  # last bar, right after the reversal
    assert not (events["timestamp"] == target_ts).any()


# ---------------------------------------------------------------------
# Cross-cutting: no-future-leakage (mutating a future bar must not change
# whether an earlier bar fires any of the three definitions).
# ---------------------------------------------------------------------

def test_definitions_do_not_leak_future_information():
    bars = _bars("AAA", "2026-06-01", 13, _steady_uptrend(150, step=0.03))
    bars_feat = add_bar_features(bars)
    ev_a1 = definition_a_trend60_slope_consistent(bars_feat)
    ev_b1 = definition_b_trend90_subwindow_agreement(bars_feat)
    ev_c1 = definition_c_multiwindow_agreement_30_60_90(bars_feat)

    bars_mutated = bars.copy()
    bars_mutated.loc[bars_mutated.index[-1], "close"] = -999999.0
    bars_feat2 = add_bar_features(bars_mutated)
    ev_a2 = definition_a_trend60_slope_consistent(bars_feat2)
    ev_b2 = definition_b_trend90_subwindow_agreement(bars_feat2)
    ev_c2 = definition_c_multiwindow_agreement_30_60_90(bars_feat2)

    early_cutoff = pd.Timestamp("2026-06-01 15:00:00", tz="UTC")
    for ev1, ev2 in [(ev_a1, ev_a2), (ev_b1, ev_b2), (ev_c1, ev_c2)]:
        early1 = set(ev1[ev1["timestamp"] < early_cutoff]["timestamp"])
        early2 = set(ev2[ev2["timestamp"] < early_cutoff]["timestamp"])
        assert early1 == early2
