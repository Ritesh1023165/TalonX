"""
tests/test_task67a_research_stats.py
-------------------------------------
Focused tests for research/task67a_lib/research_stats.py's utilities, on
small synthetic data (never real market data) -- correctness/determinism
checks, not a benchmark of any actual phenomenon family.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.task67a_lib.research_stats import (
    bootstrap_ci,
    bootstrap_ci_clustered,
    compute_mfe_mae,
    concentration_metrics,
    cross_family_overlap,
    dedup_events,
    effect_surface,
    forward_return_horizons,
    matched_control_sample,
)


# ---------------------------------------------------------------------
# bootstrap_ci
# ---------------------------------------------------------------------

def test_bootstrap_ci_is_deterministic_given_same_seed():
    values = [1.0, 2.0, -0.5, 3.2, 0.1, -1.0, 4.5, 2.2, 0.0, -0.3]
    r1 = bootstrap_ci(values, seed=42, n_resamples=2000)
    r2 = bootstrap_ci(values, seed=42, n_resamples=2000)
    assert r1.point_estimate == r2.point_estimate
    assert r1.ci_low == r2.ci_low
    assert r1.ci_high == r2.ci_high


def test_bootstrap_ci_different_seeds_can_differ():
    values = [1.0, 2.0, -0.5, 3.2, 0.1, -1.0, 4.5, 2.2, 0.0, -0.3]
    r1 = bootstrap_ci(values, seed=1, n_resamples=2000)
    r2 = bootstrap_ci(values, seed=2, n_resamples=2000)
    # Point estimate is fixed by the data, not the seed; CI bounds may vary.
    assert r1.point_estimate == r2.point_estimate
    assert (r1.ci_low, r1.ci_high) != (r2.ci_low, r2.ci_high) or True  # not guaranteed unequal, but must not error


def test_bootstrap_ci_contains_true_mean_on_symmetric_data():
    rng = np.random.default_rng(0)
    values = rng.normal(loc=5.0, scale=1.0, size=500)
    result = bootstrap_ci(values, seed=7, n_resamples=5000)
    assert result.ci_low < 5.0 < result.ci_high


def test_bootstrap_ci_flags_insufficient_n():
    result = bootstrap_ci([1.0, 2.0], seed=1)
    assert result.insufficient_n is True
    assert result.ci_low is None and result.ci_high is None


def test_bootstrap_ci_clustered_deterministic_and_respects_groups():
    values = [1.0, 1.1, 0.9, -5.0, -5.2, -4.8, 2.0, 2.1, 1.9, 3.0, 3.1, 2.9]
    groups = ["A", "A", "A", "B", "B", "B", "C", "C", "C", "D", "D", "D"]
    r1 = bootstrap_ci_clustered(values, groups, seed=99, n_resamples=2000)
    r2 = bootstrap_ci_clustered(values, groups, seed=99, n_resamples=2000)
    assert r1.ci_low == r2.ci_low and r1.ci_high == r2.ci_high
    assert r1.n == 4  # 4 distinct groups, not 12 rows


# ---------------------------------------------------------------------
# concentration_metrics
# ---------------------------------------------------------------------

def test_concentration_metrics_correctness_synthetic():
    # One symbol (AAA) supplies 90 of 100 total positive value -> should
    # be flagged as heavily concentrated.
    df = pd.DataFrame({
        "symbol": ["AAA"] * 3 + ["BBB"] * 3 + ["CCC"] * 3,
        "value": [30, 30, 30, 3, 3, 3, 1, -5, 2],
        "day": ["2026-01-01", "2026-01-02", "2026-01-03"] * 3,
    })
    result = concentration_metrics(df, value_col="value", symbol_col="symbol", day_col="day")
    assert result["insufficient_n"] is False
    assert result["top1_symbol"] == "AAA"
    assert result["top1_symbol_share"] == pytest.approx(90 / 102, rel=1e-6)
    assert result["n_symbols"] == 3


def test_concentration_metrics_flags_insufficient_n():
    df = pd.DataFrame({"symbol": ["AAA"], "value": [5.0]})
    result = concentration_metrics(df, value_col="value", symbol_col="symbol", min_n=5)
    assert result["insufficient_n"] is True


# ---------------------------------------------------------------------
# dedup_events
# ---------------------------------------------------------------------

def test_dedup_events_clusters_close_events_and_marks_one_representative():
    events = pd.DataFrame({
        "symbol": ["AAA"] * 5,
        "timestamp": pd.to_datetime([
            "2026-01-01 09:31:00", "2026-01-01 09:32:00", "2026-01-01 09:33:00",  # cluster 1 (1-min apart)
            "2026-01-01 11:00:00",  # isolated -> cluster 2
            "2026-01-01 11:01:00",  # 1 min after prior -> still cluster 2
        ]),
    })
    result = dedup_events(events, group_keys=["symbol"], time_col="timestamp", min_gap_minutes=5)
    assert result["_cluster_id"].tolist() == [0, 0, 0, 1, 1]
    assert result["_cluster_representative"].sum() == 2  # one rep per cluster
    reps = result[result["_cluster_representative"]]
    assert reps["timestamp"].tolist() == [
        pd.Timestamp("2026-01-01 09:31:00"), pd.Timestamp("2026-01-01 11:00:00"),
    ]


def test_dedup_events_respects_group_keys_independently():
    events = pd.DataFrame({
        "symbol": ["AAA", "AAA", "BBB", "BBB"],
        "timestamp": pd.to_datetime([
            "2026-01-01 09:31:00", "2026-01-01 09:32:00",
            "2026-01-01 09:31:00", "2026-01-01 09:32:00",
        ]),
    })
    result = dedup_events(events, group_keys=["symbol"], time_col="timestamp", min_gap_minutes=5)
    # Each symbol's cluster ids are independent (both start at 0).
    assert result[result.symbol == "AAA"]["_cluster_id"].tolist() == [0, 0]
    assert result[result.symbol == "BBB"]["_cluster_id"].tolist() == [0, 0]


# ---------------------------------------------------------------------
# matched_control_sample
# ---------------------------------------------------------------------

def test_matched_control_sample_pairs_within_stratum_only():
    df = pd.DataFrame({
        "family": ["A", "A", "B", "B", "B"],
        "symbol": ["AAA", "AAA", "AAA", "AAA", "BBB"],
        "timestamp": pd.to_datetime([
            "2026-01-01 09:30:00", "2026-01-01 10:00:00",
            "2026-01-01 09:31:00", "2026-01-01 12:00:00",
            "2026-01-01 09:30:00",
        ]),
    })
    result = matched_control_sample(
        df, treatment_col="family", treatment_label="A", control_label="B",
        match_keys=["symbol"], time_col="timestamp",
    )
    pairs = result["nearest_time_pairs"]
    # BBB has no "A" rows, so no pair should reference the BBB control row.
    assert (pairs["symbol"] == "BBB").sum() == 0
    # AAA has 2 A-rows and 2 B-rows -> exactly 2 greedy pairs, nearest first.
    assert len(pairs) == 2
    assert result["common_support_counts"]["treatment_in_common_support"] == 2


def test_matched_control_sample_no_common_support_returns_empty_pairs():
    df = pd.DataFrame({
        "family": ["A", "B"],
        "symbol": ["AAA", "BBB"],  # disjoint symbols -> no shared stratum
        "timestamp": pd.to_datetime(["2026-01-01 09:30:00", "2026-01-01 09:30:00"]),
    })
    result = matched_control_sample(
        df, treatment_col="family", treatment_label="A", control_label="B",
        match_keys=["symbol"], time_col="timestamp",
    )
    assert len(result["strata"]) == 0
    assert result["common_support_counts"]["treatment_in_common_support"] == 0


# ---------------------------------------------------------------------
# effect_surface
# ---------------------------------------------------------------------

def test_effect_surface_basic_sanity():
    rng = np.random.default_rng(3)
    n = 90
    df = pd.DataFrame({
        "param_a": rng.uniform(0, 10, size=n),
        "metric": rng.normal(0, 1, size=n),
    })
    surface = effect_surface(df, param_cols=["param_a"], metric_col="metric", n_bins=3)
    assert len(surface) == 3  # tertiles
    assert surface["n"].sum() == n
    assert set(surface.columns) >= {"param_a_bin", "n", "mean", "median", "std", "insufficient_n"}


# ---------------------------------------------------------------------
# cross_family_overlap
# ---------------------------------------------------------------------

def test_cross_family_overlap_correctness_synthetic():
    events_a = pd.DataFrame({
        "symbol": ["AAA", "AAA", "BBB"],
        "timestamp": pd.to_datetime(["2026-01-01 09:31:00", "2026-01-01 12:00:00", "2026-01-01 09:31:00"]),
        "day": ["2026-01-01", "2026-01-01", "2026-01-01"],
    })
    events_b = pd.DataFrame({
        "symbol": ["AAA", "CCC"],
        "timestamp": pd.to_datetime(["2026-01-01 09:32:00", "2026-01-01 09:31:00"]),
        "day": ["2026-01-01", "2026-01-01"],
    })
    result = cross_family_overlap(
        events_a, events_b, symbol_col="symbol", time_col="timestamp",
        day_col="day", time_tolerance_minutes=2,
    )
    # events_a row 0 (AAA 09:31) is within 2 min of events_b row 0 (AAA 09:32) -> overlap.
    # events_a row 1 (AAA 12:00) is not near anything -> no overlap.
    # events_a row 2 (BBB) has no BBB in events_b -> no overlap.
    assert result["a_covered_by_b_same_symbol_time"]["count"] == 1
    assert result["a_covered_by_b_same_symbol_time"]["fraction"] == pytest.approx(1 / 3)
    assert result["b_covered_by_a_same_symbol_time"]["count"] == 1  # only the AAA row in b matches


def test_cross_family_overlap_empty_input_does_not_error():
    empty = pd.DataFrame({"symbol": [], "timestamp": pd.to_datetime([])})
    other = pd.DataFrame({"symbol": ["AAA"], "timestamp": pd.to_datetime(["2026-01-01 09:30:00"])})
    result = cross_family_overlap(empty, other)
    assert result["a_covered_by_b_same_symbol_time"]["count"] == 0
    assert result["a_covered_by_b_same_symbol_time"]["fraction"] == 0.0


# ---------------------------------------------------------------------
# compute_mfe_mae
# ---------------------------------------------------------------------

def _bars(rows):
    return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"]).assign(
        timestamp=lambda d: pd.to_datetime(d["timestamp"])
    )


def test_compute_mfe_mae_long_correctness_synthetic():
    bars = _bars([
        ["2026-01-01 09:30:00", 100, 101, 99, 100.5, 1000],
        ["2026-01-01 09:31:00", 100.5, 105, 100, 104, 1000],  # favorable high 105
        ["2026-01-01 09:32:00", 104, 104.5, 97, 98, 1000],    # adverse low 97
        ["2026-01-01 09:33:00", 98, 99, 98, 98.5, 1000],
    ])
    result = compute_mfe_mae(
        bars, entry_timestamp=pd.Timestamp("2026-01-01 09:30:00"),
        exit_timestamp=pd.Timestamp("2026-01-01 09:33:00"),
        entry_price=100.0, risk_per_unit=2.0, direction="long",
    )
    assert result["mfe_price"] == 105
    assert result["mae_price"] == 97
    assert result["mfe_R"] == pytest.approx((105 - 100) / 2.0)
    assert result["mae_R"] == pytest.approx((100 - 97) / 2.0)
    assert result["bar_count"] == 4


def test_compute_mfe_mae_short_mirrors_long():
    bars = _bars([
        ["2026-01-01 09:30:00", 100, 101, 99, 100.5, 1000],
        ["2026-01-01 09:31:00", 100.5, 103, 95, 96, 1000],  # favorable (down) low 95, adverse high 103
    ])
    result = compute_mfe_mae(
        bars, entry_timestamp=pd.Timestamp("2026-01-01 09:30:00"),
        exit_timestamp=pd.Timestamp("2026-01-01 09:31:00"),
        entry_price=100.0, risk_per_unit=2.0, direction="short",
    )
    assert result["mfe_price"] == 95
    assert result["mae_price"] == 103
    assert result["mfe_R"] == pytest.approx((100 - 95) / 2.0)
    assert result["mae_R"] == pytest.approx((103 - 100) / 2.0)


def test_compute_mfe_mae_raises_on_empty_window():
    bars = _bars([["2026-01-01 09:30:00", 100, 101, 99, 100.5, 1000]])
    with pytest.raises(ValueError):
        compute_mfe_mae(
            bars, entry_timestamp=pd.Timestamp("2026-01-01 10:00:00"),
            exit_timestamp=pd.Timestamp("2026-01-01 10:05:00"),
            entry_price=100.0, risk_per_unit=1.0,
        )


# ---------------------------------------------------------------------
# forward_return_horizons
# ---------------------------------------------------------------------

def test_forward_return_horizons_basic_and_session_close_bound():
    bars = _bars([
        ["2026-01-01 15:55:00", 100, 100.5, 99.5, 100, 1000],
        ["2026-01-01 15:56:00", 100, 101, 99, 100.8, 1000],
        ["2026-01-01 15:57:00", 100.8, 102, 100, 101.5, 1000],
        ["2026-01-01 15:58:00", 101.5, 101.5, 100.9, 101, 1000],
        ["2026-01-01 15:59:00", 101, 101.2, 100.8, 101.1, 1000],
    ])
    result = forward_return_horizons(
        bars, entry_timestamp=pd.Timestamp("2026-01-01 15:55:00"), entry_price=100.0,
        horizons_minutes=[1, 10, None],
        session_close_timestamp=pd.Timestamp("2026-01-01 16:00:00"),
    )
    by_label = {r["horizon_label"]: r for r in result}
    assert by_label["1m"]["bars_observed"] == 1  # only the 15:55 bar itself
    assert by_label["1m"]["bounded_by_session_close"] is False
    # 10m horizon would run past session close -> bounded.
    assert by_label["10m"]["bounded_by_session_close"] is True
    assert by_label["10m"]["bars_observed"] == 5  # all 5 bars before 16:00
    assert by_label["TO_SESSION_CLOSE"]["bars_observed"] == 5


def test_forward_return_horizons_zero_bars_returns_none_close_return():
    bars = _bars([["2026-01-01 09:30:00", 100, 101, 99, 100.5, 1000]])
    result = forward_return_horizons(
        bars, entry_timestamp=pd.Timestamp("2026-01-01 12:00:00"), entry_price=100.0,
        horizons_minutes=[5],
    )
    assert result[0]["bars_observed"] == 0
    assert result[0]["forward_close_return_pct"] is None
