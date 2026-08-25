"""
tests/test_task67a_family_runner.py
--------------------------------------
Smoke/regression tests for research/task67a_lib/family_runner.py's shared
orchestration (dedup -> horizon/MFE-MAE -> matched-control pairing ->
clustered bootstrap -> concentration -> effect-surface -> verdict), on
small synthetic data (never real market data). This module has no event
CONDITION logic of its own -- families 1-3's own condition-definition
tests live in tests/test_task67a_family0{1,2,3}_*.py.

Key properties checked here:
  - the full pipeline runs end-to-end without raising on a realistic
    synthetic multi-symbol/multi-day bar set;
  - a definition fired on PURE NOISE (no real directional persistence)
    should not be verdicted PHENOMENON_PRESENT -- a cheap sanity check
    that the excess/CI machinery isn't systematically biased positive;
  - the zero-raw-candidate-events path returns INSUFFICIENT_DATA/
    SEVERELY_LIMITED without raising (empty-input robustness).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.task67a_lib.family_runner import run_family_definition
from research.task67a_lib.screening_framework import add_bar_features, causal_trailing_return


def _synthetic_bars(symbols, n_days, seed=1, minutes_per_day=300, base_price=100.0, vol=0.05):
    rng = np.random.default_rng(seed)
    days = pd.date_range("2026-06-01", periods=n_days, freq="B")
    frames = []
    for sym in symbols:
        for day in days:
            times = pd.date_range(f"{day.date()} 08:00:00", periods=minutes_per_day, freq="1min", tz="UTC")
            steps = rng.normal(0, vol, size=minutes_per_day)
            price = base_price + np.cumsum(steps)
            frames.append(pd.DataFrame({
                "timestamp": times, "symbol": sym,
                "open": price, "high": price + 0.05, "low": price - 0.05, "close": price,
                "volume": rng.integers(100, 1000, size=minutes_per_day),
            }))
    return pd.concat(frames, ignore_index=True).sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def _candidates_from_trailing_return(bars_feat, window_minutes, threshold):
    ret = causal_trailing_return(bars_feat, window_minutes)
    mask = np.abs(ret) >= threshold
    cand = bars_feat.loc[mask, [
        "symbol", "timestamp", "close", "trailing_vol_60m", "time_of_day_bucket", "vol_bucket", "trading_day",
    ]].rename(columns={"close": "entry_price"})
    cand["direction"] = np.where(ret[mask] > 0, 1, -1)
    return cand


def test_run_family_definition_end_to_end_on_pure_noise_does_not_raise_and_is_not_falsely_present():
    """Pure random-walk bars have no real trend-persistence phenomenon by
    construction -- a well-behaved pipeline must not verdict this
    PHENOMENON_PRESENT (that would indicate the excess/CI/verdict
    machinery is systematically biased toward false positives)."""
    bars = _synthetic_bars(["AAA", "BBB", "CCC", "DDD", "EEE"], n_days=10, seed=1, minutes_per_day=900)
    bars_feat = add_bar_features(bars)
    cand = _candidates_from_trailing_return(bars_feat, 60, threshold=0.003)
    assert len(cand) > 0  # sanity: the noise level chosen actually fires some candidates

    result = run_family_definition(
        bars=bars, bars_feat=bars_feat, candidate_events=cand,
        definition_name="noise_test", dedup_group_keys=["symbol"], dedup_min_gap_minutes=30,
    )
    assert result["verdict"] in {
        "PHENOMENON_PRESENT", "WEAK_SIGNAL", "PHENOMENON_NOT_OBSERVED", "INSUFFICIENT_DATA",
    }
    assert result["verdict"] != "PHENOMENON_PRESENT"
    assert result["n_dedup_events"] <= result["n_raw_events"]
    assert set(result["per_horizon"].keys()) == {"15m", "30m", "60m", "120m"}
    # events_df/horizon_metrics_df must be non-empty and internally consistent
    assert len(result["events_df"]) == result["n_dedup_events"]
    assert set(result["horizon_metrics_df"]["event_id"]) <= set(result["events_df"]["event_id"])


def test_run_family_definition_handles_zero_candidates_without_raising():
    bars = _synthetic_bars(["AAA"], n_days=3, seed=2, minutes_per_day=200)
    bars_feat = add_bar_features(bars)
    empty_cand = bars_feat.iloc[0:0][[
        "symbol", "timestamp", "close", "trailing_vol_60m", "time_of_day_bucket", "vol_bucket", "trading_day",
    ]].rename(columns={"close": "entry_price"})
    empty_cand["direction"] = pd.Series(dtype=int)

    result = run_family_definition(
        bars=bars, bars_feat=bars_feat, candidate_events=empty_cand,
        definition_name="empty_test", dedup_group_keys=["symbol"], dedup_min_gap_minutes=30,
    )
    assert result["n_raw_events"] == 0
    assert result["n_dedup_events"] == 0
    assert result["verdict"] == "INSUFFICIENT_DATA"
    assert result["data_sufficiency"] == "SEVERELY_LIMITED"


def test_run_family_definition_dedup_reduces_or_equals_raw_count():
    bars = _synthetic_bars(["AAA", "BBB"], n_days=8, seed=3, minutes_per_day=600)
    bars_feat = add_bar_features(bars)
    cand = _candidates_from_trailing_return(bars_feat, 30, threshold=0.002)
    result = run_family_definition(
        bars=bars, bars_feat=bars_feat, candidate_events=cand,
        definition_name="dedup_test", dedup_group_keys=["symbol"], dedup_min_gap_minutes=45,
    )
    assert result["n_dedup_events"] <= result["n_raw_events"]
    if result["n_dedup_events"] > 0:
        # every deduplicated event must be at least min_gap_minutes apart
        # from every other event on the same symbol (the whole point of dedup).
        for sym, g in result["events_df"].groupby("symbol"):
            times = g.sort_values("timestamp")["timestamp"].reset_index(drop=True)
            if len(times) > 1:
                gaps = times.diff().dropna().dt.total_seconds() / 60.0
                assert (gaps > 45 - 1e-9).all()
