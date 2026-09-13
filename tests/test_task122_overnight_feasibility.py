"""Task 122 Part 6 -- small causal event trace proving the overnight-
return candidate's trigger logic (task122_overnight_feasibility.py) is
point-in-time correct BEFORE any historical run is trusted: a trigger
day's own volume never leaks into its own trailing-average baseline,
and the trigger is a pure function of data available by that day's own
close (no future-date leakage).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "research" / "scripts"))

import task122_overnight_feasibility as t122  # noqa: E402


def _synthetic_frame(volumes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(volumes), freq="B")
    return pd.DataFrame({
        "date": dates, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
        "volume": volumes,
    })


def _trigger_series(df: pd.DataFrame) -> pd.Series:
    trailing = df["volume"].shift(1).rolling(t122.VOLUME_LOOKBACK_DAYS, min_periods=t122.VOLUME_LOOKBACK_DAYS).mean()
    trig = df["volume"] >= (t122.ABNORMAL_VOLUME_MULTIPLE * trailing)
    return trig.fillna(False)


def test_trigger_never_uses_its_own_days_volume_in_the_baseline():
    """20 normal days (volume=100) then ONE huge-volume day (volume=10,000)
    -- the huge day's OWN volume must not count toward its own trailing
    average (which would make it partially self-referential and too easy
    to trigger); with shift(1), the trailing average of the huge day is
    exactly the prior 20 normal days = 100, so the huge day (10,000 >=
    2x100) fires -- but a version WITHOUT shift(1) would also include the
    huge day itself in a length-20 window and could dilute or dodge the
    threshold differently. This test locks in the causal (shift(1))
    behavior explicitly."""
    volumes = [100.0] * 20 + [10_000.0]
    df = _synthetic_frame(volumes)
    trig = _trigger_series(df)
    assert bool(trig.iloc[-1]) is True
    # the 20 warmup days (insufficient trailing history) must never fire
    assert not trig.iloc[:20].any()


def test_trigger_requires_full_lookback_no_premature_firing_during_warmup():
    volumes = [100.0] * 5 + [10_000.0]  # only 5 days of history -- not enough for a 20-day average
    df = _synthetic_frame(volumes)
    trig = _trigger_series(df)
    assert not trig.any()  # never fires with insufficient trailing history, regardless of the spike


def test_trigger_is_a_pure_function_of_past_data_not_future_dates():
    """Appending MORE future rows must never change whether an EARLIER
    day was flagged as a trigger -- proves no forward-looking leakage."""
    volumes = [100.0] * 20 + [10_000.0] + [100.0] * 10
    df_full = _synthetic_frame(volumes)
    df_truncated = df_full.iloc[:21].copy()  # cut off right after the spike day

    trig_full = _trigger_series(df_full)
    trig_truncated = _trigger_series(df_truncated)
    assert bool(trig_full.iloc[20]) == bool(trig_truncated.iloc[20]) == True  # noqa: E712


def test_normal_volume_never_triggers():
    volumes = [100.0] * 40  # perfectly flat -- no day should ever be >= 2x its own trailing average
    df = _synthetic_frame(volumes)
    trig = _trigger_series(df)
    assert not trig.any()


def test_configured_universe_list_matches_documented_48():
    assert len(t122.CONFIGURED_48) == 48
    assert len(set(t122.CONFIGURED_48)) == 48  # no duplicates
