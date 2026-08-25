"""
tests/test_task67a_family05_compression_expansion.py
-------------------------------------------------------
Focused synthetic-data tests for the Family 5 (compression -> expansion,
compression as a PRECONDITION) event-CONDITION functions in
research/scripts/task67a_family05_compression_expansion.py -- hand-
constructed bars where the intrabar HIGH-LOW RANGE (not just the
close-price path) is directly controlled. Never real market data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.task67a_lib.screening_framework import add_bar_features
from research.scripts.task67a_family05_compression_expansion import (
    _persistently_compressed_mask,
    _value_at_offset,
    definition_a_persistent_compression,
    definition_b_relative_narrow_range,
    definition_c_declining_compression,
)


def _bars_with_ranges(symbol, day, start_hour, closes, ranges, volume=1000, start_minute=0):
    """Builds bars where `closes[i]` is the close and `ranges[i]` is the
    intrabar high-low spread (high = close + range/2, low = close -
    range/2) -- independent controls."""
    n = len(closes)
    assert len(ranges) == n
    times = pd.date_range(f"{day} {start_hour:02d}:{start_minute:02d}:00", periods=n, freq="1min", tz="UTC")
    closes = np.asarray(closes, dtype=float)
    ranges = np.asarray(ranges, dtype=float)
    return pd.DataFrame({
        "timestamp": times, "symbol": symbol,
        "open": closes, "high": closes + ranges / 2, "low": closes - ranges / 2, "close": closes,
        "volume": volume,
    })


def _drifting_closes(n, start=100.0, step=0.0):
    return start + step * np.arange(n)


def _jitter(ranges, frac=0.03, seed=42):
    """Adds tiny, deterministic (seeded) relative jitter to a `ranges`
    array. Without this, a long run of an EXACTLY constant range value
    can land as a large tied block sitting precisely at (or adjacent to)
    a global percentile cutoff -- `_global_percentile_cutoff` computes a
    single interpolated cutoff over the WHOLE pooled dataset (matching
    Family 3's own `_global_low_tertile_mask` convention: cutoffs are
    global-population statistics, not causal per-bar quantities), so a
    tiny, otherwise-irrelevant mutation elsewhere in the dataset (e.g.
    the no-future-leakage test's single mutated future bar) can nudge
    that interpolated cutoff by a floating-point epsilon and flip an
    exactly-tied bar's classification. A little jitter keeps every
    definition's intended compressed/non-compressed character (still
    tiny vs. still large) while removing exact ties, so classification
    is robust to that kind of far-away, functionally-irrelevant change."""
    rng = np.random.default_rng(seed)
    ranges = np.asarray(ranges, dtype=float)
    return ranges * (1.0 + rng.uniform(-frac, frac, size=len(ranges)))


# A tiny, uniform per-minute drift used for "compressed"/"quiet" regions in the fixtures below.
# Independent of the (separately-controlled) intrabar high-low RANGE -- see `_bars_with_ranges` --
# so it does not affect any compression condition, but it DOES keep the weak directional signal
# (sign of the trailing return) well-defined and nonzero throughout, which every definition
# requires (see module docstring's direction convention). Deliberately much smaller than any
# `ranges` value used below so it cannot be mistaken for a real intrabar expansion.
QUIET_DRIFT_STEP = 0.01


# ---------------------------------------------------------------------
# Shared fixture: a 3-symbol combined dataset giving meaningful GLOBAL
# tertile/median cutoffs (a single-symbol series would make "bottom
# tertile" degenerate -- see script docstring's direction-convention
# discussion for why cross-symbol context matters here).
#   AAA: genuine, PERSISTENT compression (quiet for a long run) then a
#        later volatility burst (the burst is irrelevant to whether the
#        CONDITION fires -- conditions are causal -- but included so the
#        overall shape resembles the phenomenon under study).
#   BBB: uniformly HIGH/volatile range throughout -- no compression at
#        all; anchors the "high" end of the global distribution.
#   CCC: quiet, but INTERRUPTED by a brief spike every ~10 minutes -- so
#        `compressed_now` is true most of the time, but persistence
#        (definition A) is never satisfied for a genuine continuous run.
# ---------------------------------------------------------------------

def _three_symbol_bars(start_hour=15, start_minute=0):
    n_quiet_aaa = 200
    n_burst_aaa = 20
    closes_aaa = np.concatenate([
        _drifting_closes(n_quiet_aaa, start=100.0, step=QUIET_DRIFT_STEP),
        (100.0 + QUIET_DRIFT_STEP * n_quiet_aaa) + 0.3 * np.arange(1, n_burst_aaa + 1),
    ])
    ranges_aaa = _jitter(np.concatenate([np.full(n_quiet_aaa, 0.01), np.full(n_burst_aaa, 3.0)]), seed=1)
    aaa = _bars_with_ranges("AAA", "2026-06-01", start_hour, closes_aaa, ranges_aaa, start_minute=start_minute)

    n_bbb = n_quiet_aaa + n_burst_aaa
    closes_bbb = _drifting_closes(n_bbb, start=200.0, step=QUIET_DRIFT_STEP)
    ranges_bbb = _jitter(np.full(n_bbb, 2.0), seed=2)
    bbb = _bars_with_ranges("BBB", "2026-06-01", start_hour, closes_bbb, ranges_bbb, start_minute=start_minute)

    n_ccc = n_bbb
    closes_ccc = _drifting_closes(n_ccc, start=150.0, step=QUIET_DRIFT_STEP)
    ranges_ccc = np.full(n_ccc, 0.01)
    ranges_ccc[9::10] = 3.0  # a spike bar every 10 minutes breaks persistence
    ranges_ccc = _jitter(ranges_ccc, seed=3)
    ccc = _bars_with_ranges("CCC", "2026-06-01", start_hour, closes_ccc, ranges_ccc, start_minute=start_minute)

    bars = pd.concat([aaa, bbb, ccc], ignore_index=True).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return add_bar_features(bars)


# ---------------------------------------------------------------------
# _value_at_offset (copied/adapted helper) -- basic correctness + no
# reach into a prior session (same shape as Family 3's own test)
# ---------------------------------------------------------------------

def test_value_at_offset_basic_correctness():
    bars = _bars_with_ranges("AAA", "2026-06-01", 13, np.full(120, 100.0), np.full(120, 0.1))
    bars = add_bar_features(bars)
    values = np.arange(120, dtype=float)
    looked_up = _value_at_offset(bars, values, offset_minutes=30)
    assert looked_up[50] == pytest.approx(20.0)
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
# _persistently_compressed_mask: direct unit check of the helper itself
# ---------------------------------------------------------------------

def test_persistently_compressed_mask_requires_full_continuous_window():
    bars = _bars_with_ranges("AAA", "2026-06-01", 13, np.full(100, 100.0), np.full(100, 0.1))
    bars = add_bar_features(bars)
    compressed_now = np.ones(100, dtype=bool)
    compressed_now[40] = False  # one violation bar
    mask = _persistently_compressed_mask(bars, compressed_now, persist_minutes=30)
    # Bar 39 (just before the violation): its trailing 30m window [9,39] is clean -> True (if warmup satisfied).
    assert mask[39]
    # Bar 41: trailing window [11,41] includes the violation at 40 -> False.
    assert not mask[41]
    # Bar 70: trailing window [40,70] includes the violation at 40 -> False.
    assert not mask[70]
    # Bar 71: trailing window [41,71] no longer includes bar 40 -> True.
    assert mask[71]
    # Bar 0: the very first same-day bar has NO prior bar at all -- the one true warmup case
    # this helper (matching causal_atr_proxy's own convention) treats as "cannot have fired".
    assert not mask[0]
    # Bar 5: some (but less than a full 30m) same-day history exists; whatever's available is
    # all True here, so this DOES fire -- matching causal_atr_proxy's "use what's available,
    # only bar 0 is true warmup" convention rather than requiring a literal elapsed duration.
    assert mask[5]


# ---------------------------------------------------------------------
# Definition A: persistent_compression_atr30_persist30
# ---------------------------------------------------------------------

def test_definition_a_fires_on_genuine_persistent_compression():
    bars_feat = _three_symbol_bars()
    events = definition_a_persistent_compression(bars_feat)
    aaa_events = events[events["symbol"] == "AAA"]
    assert len(aaa_events) > 0, "expected AAA's long persistent-quiet run to fire definition A"
    # Should NOT fire during the first ~30 minutes of AAA's quiet run (persistence not yet built up),
    # but should fire well into it.
    early_cutoff = bars_feat.loc[(bars_feat["symbol"] == "AAA")].iloc[35]["timestamp"]
    late_ts = bars_feat.loc[(bars_feat["symbol"] == "AAA")].iloc[150]["timestamp"]
    assert not (aaa_events["timestamp"] == bars_feat.loc[(bars_feat["symbol"] == "AAA")].iloc[10]["timestamp"]).any()
    assert (aaa_events["timestamp"] == late_ts).any()


def test_definition_a_does_not_fire_without_compression():
    bars_feat = _three_symbol_bars()
    events = definition_a_persistent_compression(bars_feat)
    assert events[events["symbol"] == "BBB"].empty, "uniformly volatile BBB must never satisfy compression"


def test_definition_a_does_not_fire_when_persistence_not_met():
    bars_feat = _three_symbol_bars()
    events = definition_a_persistent_compression(bars_feat)
    assert events[events["symbol"] == "CCC"].empty, (
        "CCC is quiet 90% of the time but never continuously compressed for a full 30m -- must not fire"
    )


# ---------------------------------------------------------------------
# Definition B: relative_narrow_range_15v90
# ---------------------------------------------------------------------

def _def_b_bars():
    # AAA: 120 minutes of a MODERATE, steady range (builds up a "typical" 90m pace),
    # then 20 minutes of a much NARROWER range (recent 15m window << own typical pace).
    # n_narrow is deliberately large relative to n_base: with a comparison symbol (BBB) whose
    # ratio sits at a constant 1.0 for its entire history, a bottom-GLOBAL-tertile cutoff
    # computed from the pooled AAA+BBB distribution only lands strictly BELOW that 1.0 plateau
    # (excluding BBB entirely) once AAA's genuinely-narrow tail makes up more than 1/3 of the
    # pooled valid (post-90m-warmup) sample -- a short narrow tail would tie exactly at the
    # cutoff and (with an inclusive `<=`) spuriously catch BBB's whole constant-1.0 population too.
    n_base, n_narrow = 120, 80
    closes_aaa = _drifting_closes(n_base + n_narrow, start=100.0, step=QUIET_DRIFT_STEP)
    ranges_aaa = _jitter(np.concatenate([np.full(n_base, 1.0), np.full(n_narrow, 0.02)]), seed=4, frac=0.003)
    aaa = _bars_with_ranges("AAA", "2026-06-01", 13, closes_aaa, ranges_aaa)

    # BBB: uniform pace throughout (own-typical ratio stays ~1) -- must never fire.
    n_bbb = n_base + n_narrow
    closes_bbb = _drifting_closes(n_bbb, start=200.0, step=QUIET_DRIFT_STEP)
    ranges_bbb = _jitter(np.full(n_bbb, 1.0), seed=5, frac=0.003)
    bbb = _bars_with_ranges("BBB", "2026-06-01", 13, closes_bbb, ranges_bbb)

    bars = pd.concat([aaa, bbb], ignore_index=True).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return add_bar_features(bars)


def test_definition_b_fires_when_recent_range_narrow_relative_to_own_typical():
    bars_feat = _def_b_bars()
    events = definition_b_relative_narrow_range(bars_feat)
    aaa_events = events[events["symbol"] == "AAA"]
    assert len(aaa_events) > 0, "expected AAA's narrow-relative-to-own-typical tail to fire definition B"
    last_ts = bars_feat.loc[bars_feat["symbol"] == "AAA", "timestamp"].iloc[-1]
    assert (aaa_events["timestamp"] == last_ts).any()


def test_definition_b_does_not_fire_on_uniformly_volatile_data():
    bars_feat = _def_b_bars()
    events = definition_b_relative_narrow_range(bars_feat)
    assert events[events["symbol"] == "BBB"].empty, "BBB's own ratio never dips -- must not fire"


# ---------------------------------------------------------------------
# Definition C: declining_compression_atr30_lag30
# ---------------------------------------------------------------------

def _def_c_bars():
    # AAA: quiet the whole time, but with a STEP-DOWN in range partway through -- so ATR30-now
    # ends up strictly below ATR30-30m-ago at some point (genuinely declining), while BOTH stay
    # low (well below the global median once combined with BBB below).
    n1, n2 = 150, 90
    closes_aaa = _drifting_closes(n1 + n2, start=100.0, step=QUIET_DRIFT_STEP)
    ranges_aaa = _jitter(np.concatenate([np.full(n1, 0.5), np.full(n2, 0.05)]), seed=6)
    # start_hour=15 (not 8): must stay within [14:00 UTC, ~19:45 UTC] to clear both the
    # opening-range exclusion and the min-lead-before-close requirement (240 bars from 15:00
    # UTC ends at 19:00 UTC, comfortably inside both bounds).
    aaa = _bars_with_ranges("AAA", "2026-06-01", 15, closes_aaa, ranges_aaa)

    # BBB: uniformly HIGH range throughout (anchors the "high" half of the global median split;
    # its own ATR never declines -- constant -- so it should not fire declining-compression).
    n_bbb = n1 + n2
    closes_bbb = _drifting_closes(n_bbb, start=200.0, step=QUIET_DRIFT_STEP)
    ranges_bbb = _jitter(np.full(n_bbb, 3.0), seed=7)
    bbb = _bars_with_ranges("BBB", "2026-06-01", 15, closes_bbb, ranges_bbb)

    bars = pd.concat([aaa, bbb], ignore_index=True).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return add_bar_features(bars)


def test_definition_c_fires_on_genuinely_declining_compression():
    bars_feat = _def_c_bars()
    events = definition_c_declining_compression(bars_feat)
    aaa_events = events[events["symbol"] == "AAA"]
    assert len(aaa_events) > 0, "expected AAA's step-down in range to fire definition C once the decline registers"


def test_definition_c_does_not_fire_when_trend_is_not_declining():
    bars_feat = _def_c_bars()
    events = definition_c_declining_compression(bars_feat)
    # BBB's ATR is CONSTANT (never declining, and not below the global median either) -- must not fire.
    assert events[events["symbol"] == "BBB"].empty


def test_definition_c_does_not_fire_on_constant_low_volatility():
    # A genuinely constant-low-vol series never satisfies "now < prior" (they're equal) -- the
    # declining requirement, not just the low-volatility requirement, must gate firing.
    n = 200
    closes = _drifting_closes(n, start=100.0, step=QUIET_DRIFT_STEP)
    ranges = np.full(n, 0.05)
    aaa = _bars_with_ranges("AAA", "2026-06-01", 15, closes, ranges)
    closes_bbb = _drifting_closes(n, start=200.0, step=QUIET_DRIFT_STEP)
    ranges_bbb = np.full(n, 3.0)
    bbb = _bars_with_ranges("BBB", "2026-06-01", 15, closes_bbb, ranges_bbb)
    bars = pd.concat([aaa, bbb], ignore_index=True).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    bars_feat = add_bar_features(bars)
    events = definition_c_declining_compression(bars_feat)
    assert events[events["symbol"] == "AAA"].empty, "constant (non-declining) low volatility must not fire"


# ---------------------------------------------------------------------
# Opening-range exclusion (all three definitions)
# ---------------------------------------------------------------------

def test_definitions_exclude_first_30_minutes_of_rth():
    # Construct the three-symbol fixture starting AT 13:30 UTC (the RTH open) instead of the
    # usual 15:00 UTC, so AAA's persistence-building window (bars ~0-35) falls inside the
    # excluded [13:30, 14:00) opening-range window.
    bars_feat2 = _three_symbol_bars(start_hour=13, start_minute=30)

    events_a = definition_a_persistent_compression(bars_feat2)
    aaa_events = events_a[events_a["symbol"] == "AAA"]
    # Any AAA events still firing must be at/after 14:00 UTC.
    minutes_of_day = pd.to_datetime(aaa_events["timestamp"]).dt.hour * 60 + pd.to_datetime(aaa_events["timestamp"]).dt.minute
    assert (minutes_of_day >= 14 * 60).all()
    # And specifically: nothing fires inside [13:30, 14:00).
    in_opening_range = aaa_events[(pd.to_datetime(aaa_events["timestamp"]).dt.hour == 13)]
    assert in_opening_range.empty


# ---------------------------------------------------------------------
# Cross-cutting: no-future-leakage
# ---------------------------------------------------------------------

def test_definitions_do_not_leak_future_information():
    bars_feat = _three_symbol_bars()
    bars_raw = bars_feat[["timestamp", "symbol", "open", "high", "low", "close", "volume"]].copy()

    ev_a1 = definition_a_persistent_compression(bars_feat)
    ev_b1 = definition_b_relative_narrow_range(_def_b_bars())
    ev_c1 = definition_c_declining_compression(_def_c_bars())

    bars_mutated = bars_raw.copy()
    aaa_idx = bars_mutated.index[bars_mutated["symbol"] == "AAA"]
    bars_mutated.loc[aaa_idx[-1], "high"] = 99999.0
    bars_feat2 = add_bar_features(bars_mutated)
    ev_a2 = definition_a_persistent_compression(bars_feat2)

    def_b_bars = _def_b_bars()
    def_b_raw = def_b_bars[["timestamp", "symbol", "open", "high", "low", "close", "volume"]].copy()
    b_aaa_idx = def_b_raw.index[def_b_raw["symbol"] == "AAA"]
    def_b_raw.loc[b_aaa_idx[-1], "high"] = 99999.0
    ev_b2 = definition_b_relative_narrow_range(add_bar_features(def_b_raw))

    def_c_bars = _def_c_bars()
    def_c_raw = def_c_bars[["timestamp", "symbol", "open", "high", "low", "close", "volume"]].copy()
    c_aaa_idx = def_c_raw.index[def_c_raw["symbol"] == "AAA"]
    def_c_raw.loc[c_aaa_idx[-1], "high"] = 99999.0
    ev_c2 = definition_c_declining_compression(add_bar_features(def_c_raw))

    cutoff_a = bars_feat.loc[bars_feat["symbol"] == "AAA", "timestamp"].iloc[-2]
    cutoff_c = def_c_bars.loc[def_c_bars["symbol"] == "AAA", "timestamp"].iloc[-2]
    # Definition B's ratio metric RAMPS (not steps) from ~1 down toward the narrow-phase value
    # over the ~90m long window's own warmup after the transition -- some bar in that ramp
    # necessarily sits arbitrarily close to the global cutoff, and a mutation FAR away (both in
    # time and value) can nudge that interpolated float cutoff by an epsilon and flip that one
    # ambiguous bar's classification, independent of how much anti-tie jitter is used. That is a
    # property of any smooth threshold crossing, not a causal-window bug, so the comparison here
    # is scoped to AAA's STABLE base phase (bar 60, well before the transition begins at bar
    # 120) rather than the whole timeline, to test the actual causality property (an event's
    # firing must not depend on bars strictly after it) without being confounded by that
    # inherent near-a-threshold fragility.
    cutoff_b = def_b_bars.loc[def_b_bars["symbol"] == "AAA", "timestamp"].iloc[60]

    for ev1, ev2, cutoff in [(ev_a1, ev_a2, cutoff_a), (ev_b1, ev_b2, cutoff_b), (ev_c1, ev_c2, cutoff_c)]:
        early1 = set(ev1[ev1["timestamp"] <= cutoff]["timestamp"])
        early2 = set(ev2[ev2["timestamp"] <= cutoff]["timestamp"])
        assert early1 == early2
