"""
tests/test_task67a_family02_structural_pullback.py
-------------------------------------------------------
Focused synthetic-data tests for the Family 2 (structural pullback)
event-CONDITION functions in
research/scripts/task67a_family02_structural_pullback.py -- hand-
constructed price paths that must (or must not) fire each definition.
Never real market data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.task67a_lib.screening_framework import add_bar_features
from research.scripts.task67a_family02_structural_pullback import (
    definition_a_strong_move90_shallow_retrace20,
    definition_b_pullback_toward_vwap_holds,
    definition_c_strong_move45_shallow_retrace10,
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


# ---------------------------------------------------------------------
# Definition A: strong_move90_shallow_retrace20
# base=90m, retrace=20m, move_threshold=0.6%, giveback_ratio_max=0.5
# ---------------------------------------------------------------------

def _strong_up_then_shallow_pullback(base=90, retrace=20, move_pct=1.2, giveback_frac=0.3, tail=1):
    """Price rises `move_pct`% over `base` minutes (t-base..t-retrace), then
    gives back `giveback_frac` of that move over the last `retrace` minutes
    (t-retrace..t), ending with `tail` extra flat minutes at the final
    level so the "now" bar is well-defined."""
    up_len = base - retrace
    start = 100.0
    up_move = start * move_pct / 100.0
    up = start + up_move * (np.arange(up_len + 1) / up_len)  # up_len+1 points, index up_len is the peak
    peak = up[-1]
    giveback_total = up_move * giveback_frac
    down = peak - giveback_total * (np.arange(1, retrace + 1) / retrace)
    prices = np.concatenate([up, down])
    if tail > 1:
        prices = np.concatenate([prices, np.full(tail - 1, prices[-1])])
    return prices


def test_definition_a_fires_on_strong_move_with_shallow_pullback():
    prices = _strong_up_then_shallow_pullback(move_pct=1.2, giveback_frac=0.3)
    bars = _bars("AAA", "2026-06-01", 13, prices)
    bars = add_bar_features(bars)
    events = definition_a_strong_move90_shallow_retrace20(bars)
    last_ts = bars["timestamp"].iloc[-1]
    assert (events["timestamp"] == last_ts).any()
    row = events[events["timestamp"] == last_ts].iloc[0]
    assert row["direction"] == 1


def test_definition_a_does_not_fire_when_giveback_too_deep():
    # Retrace 80% of the prior move -- well over the 50% shallow-giveback cap.
    prices = _strong_up_then_shallow_pullback(move_pct=1.2, giveback_frac=0.8)
    bars = _bars("AAA", "2026-06-01", 13, prices)
    bars = add_bar_features(bars)
    events = definition_a_strong_move90_shallow_retrace20(bars)
    last_ts = bars["timestamp"].iloc[-1]
    assert not (events["timestamp"] == last_ts).any()


def test_definition_a_does_not_fire_when_move_too_small():
    prices = _strong_up_then_shallow_pullback(move_pct=0.2, giveback_frac=0.3)
    bars = _bars("AAA", "2026-06-01", 13, prices)
    bars = add_bar_features(bars)
    events = definition_a_strong_move90_shallow_retrace20(bars)
    last_ts = bars["timestamp"].iloc[-1]
    assert not (events["timestamp"] == last_ts).any()


def test_definition_a_does_not_fire_on_continued_extension_not_pullback():
    # Price keeps rising in the "retrace" window instead of pulling back --
    # sign(giveback) == sign(prior_move), must be rejected (not a pullback).
    up1 = 100.0 + 1.2 * (np.arange(71) / 70)  # 0..70 min, +1.2%
    up2 = up1[-1] + 0.3 * (np.arange(1, 21) / 20)  # continues up for 20 more minutes
    prices = np.concatenate([up1, up2])
    bars = _bars("AAA", "2026-06-01", 13, prices)
    bars = add_bar_features(bars)
    events = definition_a_strong_move90_shallow_retrace20(bars)
    last_ts = bars["timestamp"].iloc[-1]
    assert not (events["timestamp"] == last_ts).any()


def test_definition_a_direction_negative_on_downmove():
    prices = -1.0 * (_strong_up_then_shallow_pullback(move_pct=1.2, giveback_frac=0.3) - 100.0) + 100.0
    bars = _bars("AAA", "2026-06-01", 13, prices)
    bars = add_bar_features(bars)
    events = definition_a_strong_move90_shallow_retrace20(bars)
    last_ts = bars["timestamp"].iloc[-1]
    assert (events["timestamp"] == last_ts).any()
    row = events[events["timestamp"] == last_ts].iloc[0]
    assert row["direction"] == -1


# ---------------------------------------------------------------------
# Definition C: strong_move45_shallow_retrace10 (coarser/faster timeframe)
# ---------------------------------------------------------------------

def test_definition_c_fires_on_strong_move_with_shallow_pullback():
    prices = _strong_up_then_shallow_pullback(base=45, retrace=10, move_pct=0.8, giveback_frac=0.3)
    bars = _bars("AAA", "2026-06-01", 13, prices)
    bars = add_bar_features(bars)
    events = definition_c_strong_move45_shallow_retrace10(bars)
    last_ts = bars["timestamp"].iloc[-1]
    assert (events["timestamp"] == last_ts).any()


def test_definition_c_does_not_fire_when_giveback_too_deep():
    prices = _strong_up_then_shallow_pullback(base=45, retrace=10, move_pct=0.8, giveback_frac=0.9)
    bars = _bars("AAA", "2026-06-01", 13, prices)
    bars = add_bar_features(bars)
    events = definition_c_strong_move45_shallow_retrace10(bars)
    last_ts = bars["timestamp"].iloc[-1]
    assert not (events["timestamp"] == last_ts).any()


# ---------------------------------------------------------------------
# Definition B: pullback_toward_vwap_holds
# ---------------------------------------------------------------------

def test_definition_b_fires_when_pullback_holds_above_vwap():
    # Flat-ish base to keep VWAP low, then a strong rally, then a small
    # pullback that stays above VWAP.
    base_flat = np.full(30, 100.0)
    rally_start_idx = 30
    up = 100.0 + 1.0 * (np.arange(31) / 30)  # +1% over next 30 min (t-60..t-30 relative to end)
    # After the rally we need 15 more minutes: hold near the peak then pull back slightly.
    hold = up[-1] - 0.05 * (np.arange(1, 16) / 15)  # small pullback over last 15m, well above VWAP
    prices = np.concatenate([base_flat, up, hold])
    bars = _bars("AAA", "2026-06-01", 13, prices, volume=1000)
    bars = add_bar_features(bars)
    events = definition_b_pullback_toward_vwap_holds(bars, base_minutes=45, retrace_minutes=15, move_threshold=0.005)
    last_ts = bars["timestamp"].iloc[-1]
    assert (events["timestamp"] == last_ts).any()
    row = events[events["timestamp"] == last_ts].iloc[0]
    assert row["direction"] == 1


def test_definition_b_does_not_fire_when_price_crosses_back_through_vwap():
    base_flat = np.full(30, 100.0)
    up = 100.0 + 1.0 * (np.arange(31) / 30)
    # Deep pullback that crosses well below VWAP (VWAP sits near ~100.3-100.5
    # given the flat base dominates cumulative volume).
    crash = up[-1] - 1.5 * (np.arange(1, 16) / 15)
    prices = np.concatenate([base_flat, up, crash])
    bars = _bars("AAA", "2026-06-01", 13, prices, volume=1000)
    bars = add_bar_features(bars)
    events = definition_b_pullback_toward_vwap_holds(bars, base_minutes=45, retrace_minutes=15, move_threshold=0.005)
    last_ts = bars["timestamp"].iloc[-1]
    assert not (events["timestamp"] == last_ts).any()


def test_definition_b_does_not_fire_when_move_too_small():
    base_flat = np.full(30, 100.0)
    up = 100.0 + 0.05 * (np.arange(31) / 30)  # tiny move
    hold = np.full(15, up[-1])
    prices = np.concatenate([base_flat, up, hold])
    bars = _bars("AAA", "2026-06-01", 13, prices, volume=1000)
    bars = add_bar_features(bars)
    events = definition_b_pullback_toward_vwap_holds(bars, base_minutes=45, retrace_minutes=15, move_threshold=0.005)
    last_ts = bars["timestamp"].iloc[-1]
    assert not (events["timestamp"] == last_ts).any()


# ---------------------------------------------------------------------
# Cross-cutting: no-future-leakage
# ---------------------------------------------------------------------

def test_definitions_do_not_leak_future_information():
    prices = _strong_up_then_shallow_pullback(move_pct=1.2, giveback_frac=0.3, tail=20)
    bars = _bars("AAA", "2026-06-01", 13, prices)
    bars_feat = add_bar_features(bars)
    ev_a1 = definition_a_strong_move90_shallow_retrace20(bars_feat)
    ev_b1 = definition_b_pullback_toward_vwap_holds(bars_feat)
    ev_c1 = definition_c_strong_move45_shallow_retrace10(bars_feat)

    bars_mutated = bars.copy()
    bars_mutated.loc[bars_mutated.index[-1], "close"] = -999999.0
    bars_feat2 = add_bar_features(bars_mutated)
    ev_a2 = definition_a_strong_move90_shallow_retrace20(bars_feat2)
    ev_b2 = definition_b_pullback_toward_vwap_holds(bars_feat2)
    ev_c2 = definition_c_strong_move45_shallow_retrace10(bars_feat2)

    cutoff = bars["timestamp"].iloc[-2]
    for ev1, ev2 in [(ev_a1, ev_a2), (ev_b1, ev_b2), (ev_c1, ev_c2)]:
        early1 = set(ev1[ev1["timestamp"] <= cutoff]["timestamp"])
        early2 = set(ev2[ev2["timestamp"] <= cutoff]["timestamp"])
        assert early1 == early2
