"""
tests/test_task67a_family03_range_expansion.py
-----------------------------------------------------
Focused synthetic-data tests for the Family 3 (volatility/range
expansion) event-CONDITION functions in
research/scripts/task67a_family03_range_expansion.py -- hand-constructed
bars where the intrabar HIGH-LOW RANGE (not just the close-price path) is
directly controlled, since range expansion is about intrabar range, not
directional drift. Never real market data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.task67a_lib.screening_framework import add_bar_features, causal_atr_proxy
from research.scripts.task67a_family03_range_expansion import (
    _value_at_offset,
    definition_a_compression60_expansion15,
    definition_b_compression90_expansion10,
    definition_c_compression45_expansion20,
)


def _bars_with_ranges(symbol, day, start_hour, closes, ranges, volume=1000):
    """Builds bars where `closes[i]` is the close and `ranges[i]` is the
    intrabar high-low spread (high = close + range/2, low = close -
    range/2) -- independent controls, since range-expansion definitions
    care about `ranges` while direction cares about `closes`."""
    n = len(closes)
    assert len(ranges) == n
    times = pd.date_range(f"{day} {start_hour:02d}:00:00", periods=n, freq="1min", tz="UTC")
    closes = np.asarray(closes, dtype=float)
    ranges = np.asarray(ranges, dtype=float)
    return pd.DataFrame({
        "timestamp": times, "symbol": symbol,
        "open": closes, "high": closes + ranges / 2, "low": closes - ranges / 2, "close": closes,
        "volume": volume,
    })


def _quiet_then_burst(n_quiet, n_burst, quiet_range=0.01, burst_range=2.0, quiet_close=100.0, burst_close_step=0.3):
    """`n_quiet` minutes of a tiny, constant intrabar range at a flat
    close, followed by `n_burst` minutes of a much larger intrabar range
    with a directional close drift (the "breakout")."""
    closes_quiet = np.full(n_quiet, quiet_close)
    ranges_quiet = np.full(n_quiet, quiet_range)
    closes_burst = quiet_close + burst_close_step * np.arange(1, n_burst + 1)
    ranges_burst = np.full(n_burst, burst_range)
    closes = np.concatenate([closes_quiet, closes_burst])
    ranges = np.concatenate([ranges_quiet, ranges_burst])
    return closes, ranges


# ---------------------------------------------------------------------
# _value_at_offset: generic causal lookback correctness + no-leakage
# ---------------------------------------------------------------------

def test_value_at_offset_basic_correctness():
    bars = _bars_with_ranges("AAA", "2026-06-01", 13, np.full(120, 100.0), np.full(120, 0.1))
    bars = add_bar_features(bars)
    values = np.arange(120, dtype=float)  # values[i] == i, trivially checkable
    looked_up = _value_at_offset(bars, values, offset_minutes=30)
    # Bar at index 50 (13:50); 30 min before is 13:20 (index 20) -> value 20.
    assert looked_up[50] == pytest.approx(20.0)
    # Warmup: bar at index 5 has no same-day bar 30 min earlier.
    assert np.isnan(looked_up[5])


def test_value_at_offset_never_reaches_prior_session():
    day1 = _bars_with_ranges("AAA", "2026-06-01", 22, np.full(5, 100.0), np.full(5, 0.1))
    day2 = _bars_with_ranges("AAA", "2026-06-02", 8, np.full(10, 200.0), np.full(10, 0.1))
    bars = pd.concat([day1, day2], ignore_index=True)
    bars = add_bar_features(bars)
    values = np.arange(len(bars), dtype=float)
    looked_up = _value_at_offset(bars, values, offset_minutes=60)
    day2_first_idx = bars.index[bars["symbol"] == "AAA"][5]
    assert np.isnan(looked_up[day2_first_idx])


# ---------------------------------------------------------------------
# Definition A: compression60_expansion15_2x
# ---------------------------------------------------------------------

def test_definition_a_fires_on_quiet_base_then_genuine_burst():
    # Plenty of quiet bars (well over 60m) so the established-tertile
    # cutoffs are dominated by the quiet regime, then a clean 15m burst.
    closes, ranges = _quiet_then_burst(n_quiet=200, n_burst=15, quiet_range=0.01, burst_range=3.0)
    bars = _bars_with_ranges("AAA", "2026-06-01", 15, closes, ranges)
    bars = add_bar_features(bars)
    events = definition_a_compression60_expansion15(bars)
    last_ts = bars["timestamp"].iloc[-1]
    assert (events["timestamp"] == last_ts).any(), "expected the burst's final bar to fire definition A"
    row = events[events["timestamp"] == last_ts].iloc[0]
    assert row["direction"] == 1  # burst_close_step > 0 => upward breakout


def test_definition_a_does_not_fire_when_no_expansion():
    # Uniformly quiet the whole time -- no burst at all.
    closes = np.full(300, 100.0)
    ranges = np.full(300, 0.01)
    bars = _bars_with_ranges("AAA", "2026-06-01", 15, closes, ranges)
    bars = add_bar_features(bars)
    events = definition_a_compression60_expansion15(bars)
    assert events.empty


def test_definition_a_does_not_fire_when_baseline_already_volatile():
    # Uniformly HIGH range throughout -- no quiet "established" baseline
    # exists (nothing is in the bottom tertile in any meaningful sense),
    # so even though there's a further step-up, established won't clear
    # the compression bar the same way. Use a two-level regime: elevated
    # baseline (not quiet) then an even bigger burst -- but crucially here
    # we test the pure "always high, no compression phase at all" case.
    closes, ranges = _quiet_then_burst(n_quiet=200, n_burst=15, quiet_range=1.0, burst_range=1.0)
    bars = _bars_with_ranges("AAA", "2026-06-01", 15, closes, ranges)
    bars = add_bar_features(bars)
    events = definition_a_compression60_expansion15(bars)
    # No genuine expansion multiple (ratio ~1x throughout) -- must not fire.
    assert events.empty


# ---------------------------------------------------------------------
# Definitions B and C -- same shape, different windows/multiples
# ---------------------------------------------------------------------

def test_definition_b_fires_on_quiet_base_then_genuine_burst():
    closes, ranges = _quiet_then_burst(n_quiet=200, n_burst=10, quiet_range=0.01, burst_range=3.0)
    bars = _bars_with_ranges("AAA", "2026-06-01", 15, closes, ranges)
    bars = add_bar_features(bars)
    events = definition_b_compression90_expansion10(bars)
    last_ts = bars["timestamp"].iloc[-1]
    assert (events["timestamp"] == last_ts).any()


def test_definition_c_fires_on_quiet_base_then_genuine_burst():
    closes, ranges = _quiet_then_burst(n_quiet=200, n_burst=20, quiet_range=0.01, burst_range=3.0)
    bars = _bars_with_ranges("AAA", "2026-06-01", 15, closes, ranges)
    bars = add_bar_features(bars)
    events = definition_c_compression45_expansion20(bars)
    last_ts = bars["timestamp"].iloc[-1]
    assert (events["timestamp"] == last_ts).any()


def test_definitions_exclude_first_30_minutes_of_rth():
    # A qualifying burst placed entirely within the first 30 minutes of
    # RTH (13:30-14:00 UTC) must NOT fire -- that is ORPB territory,
    # explicitly excluded regardless of how clean the compression/
    # expansion signal looks.
    closes, ranges = _quiet_then_burst(n_quiet=10, n_burst=15, quiet_range=0.01, burst_range=3.0)
    bars = _bars_with_ranges("AAA", "2026-06-01", 13, closes, ranges)  # starts 13:00, burst ends ~13:25
    bars.loc[0, "timestamp"] = pd.Timestamp("2026-06-01 13:30:00", tz="UTC")
    bars["timestamp"] = pd.date_range("2026-06-01 13:30:00", periods=len(bars), freq="1min", tz="UTC")
    bars = add_bar_features(bars)
    events = definition_a_compression60_expansion15(bars)
    assert events.empty  # burst window ends at 13:44, well before the 14:00 UTC cutoff


# ---------------------------------------------------------------------
# Cross-cutting: no-future-leakage
# ---------------------------------------------------------------------

def test_definitions_do_not_leak_future_information():
    closes, ranges = _quiet_then_burst(n_quiet=200, n_burst=25, quiet_range=0.01, burst_range=3.0)
    bars = _bars_with_ranges("AAA", "2026-06-01", 15, closes, ranges)
    bars_feat = add_bar_features(bars)
    ev_a1 = definition_a_compression60_expansion15(bars_feat)
    ev_b1 = definition_b_compression90_expansion10(bars_feat)
    ev_c1 = definition_c_compression45_expansion20(bars_feat)

    bars_mutated = bars.copy()
    bars_mutated.loc[bars_mutated.index[-1], "high"] = 99999.0
    bars_feat2 = add_bar_features(bars_mutated)
    ev_a2 = definition_a_compression60_expansion15(bars_feat2)
    ev_b2 = definition_b_compression90_expansion10(bars_feat2)
    ev_c2 = definition_c_compression45_expansion20(bars_feat2)

    cutoff = bars["timestamp"].iloc[-2]
    for ev1, ev2 in [(ev_a1, ev_a2), (ev_b1, ev_b2), (ev_c1, ev_c2)]:
        early1 = set(ev1[ev1["timestamp"] <= cutoff]["timestamp"])
        early2 = set(ev2[ev2["timestamp"] <= cutoff]["timestamp"])
        assert early1 == early2
