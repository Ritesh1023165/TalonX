"""
tests/test_backtest_timezone.py
------------------------------------
talonx_backtest.data timezone handling (spec section 12): UTC input,
America/New_York input, and DST-transition safety. A naive timestamp
must be interpreted according to `--tz`/`tz=`, never silently assumed
to be something else -- a timezone mistake must not silently shift
which market session a bar falls into.
"""
from __future__ import annotations

import pandas as pd
import pytest

from talonx_backtest.data import DataValidationError, from_dataframe
from talonx_quant.session import get_session


def _frame(timestamps) -> pd.DataFrame:
    n = len(timestamps)
    return pd.DataFrame({
        "timestamp": timestamps, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 1000.0,
    })


def test_naive_timestamp_defaults_to_utc():
    df = _frame(pd.to_datetime(["2026-01-05 14:30:00"]))  # naive
    result = from_dataframe(df, symbol="AAPL")
    assert result["timestamp"].iloc[0] == pd.Timestamp("2026-01-05 14:30:00", tz="UTC")


def test_naive_timestamp_interpreted_as_america_new_york():
    # 09:30 ET in January (EST, UTC-5) is 14:30 UTC.
    df = _frame(pd.to_datetime(["2026-01-05 09:30:00"]))  # naive, meant as ET
    result = from_dataframe(df, symbol="AAPL", tz="America/New_York")
    assert result["timestamp"].iloc[0] == pd.Timestamp("2026-01-05 14:30:00", tz="UTC")


def test_wrong_tz_choice_would_shift_the_session_classification():
    """Demonstrates WHY --tz matters: the exact same naive "09:30:00"
    string lands in a completely different market session depending on
    which timezone it's interpreted as -- this is the mistake the docs
    warn about, made concrete as a test."""
    naive = pd.to_datetime(["2026-01-05 09:30:00"])

    as_et = from_dataframe(_frame(naive), symbol="AAPL", tz="America/New_York")
    as_utc = from_dataframe(_frame(naive), symbol="AAPL", tz="UTC")

    assert get_session(as_et["timestamp"].iloc[0]) == "regular"       # 09:30 ET -- market open
    assert get_session(as_utc["timestamp"].iloc[0]) == "pre_market"   # 09:30 UTC = 04:30 ET -- pre-market
    assert as_et["timestamp"].iloc[0] != as_utc["timestamp"].iloc[0]


def test_already_tz_aware_timestamp_ignores_the_tz_argument():
    # An explicit offset in the data wins regardless of what --tz says.
    df = _frame(pd.to_datetime(["2026-01-05 09:30:00-05:00"]))  # already EST-offset
    result = from_dataframe(df, symbol="AAPL", tz="UTC")  # --tz UTC should NOT be applied
    assert result["timestamp"].iloc[0] == pd.Timestamp("2026-01-05 14:30:00", tz="UTC")


def test_internal_representation_is_always_utc():
    df = _frame(pd.to_datetime(["2026-01-05 09:30:00"]))
    result = from_dataframe(df, symbol="AAPL", tz="America/New_York")
    assert str(result["timestamp"].dt.tz) == "UTC"


# --- DST transitions (US: spring-forward 2nd Sunday in March, fall-back 1st Sunday in November) ---

def test_dst_spring_forward_offset_changes_correctly():
    # 2026-03-08 is the Sunday DST starts (spring forward, 2am->3am).
    # 09:30 ET the day BEFORE (EST, UTC-5) vs the day AFTER (EDT, UTC-4)
    # must differ by exactly one hour in UTC despite both being "09:30" locally.
    before = _frame(pd.to_datetime(["2026-03-07 09:30:00"]))   # Saturday, still EST
    after = _frame(pd.to_datetime(["2026-03-09 09:30:00"]))    # Monday, now EDT

    before_utc = from_dataframe(before, symbol="AAPL", tz="America/New_York")["timestamp"].iloc[0]
    after_utc = from_dataframe(after, symbol="AAPL", tz="America/New_York")["timestamp"].iloc[0]

    assert before_utc.hour == 14  # 09:30 EST -> 14:30 UTC
    assert after_utc.hour == 13   # 09:30 EDT -> 13:30 UTC


def test_dst_fall_back_ambiguous_hour_is_rejected_not_guessed():
    # 2026-11-01 01:30:00 local occurs TWICE (once EDT, once EST) --
    # ambiguous, must abort rather than silently pick one.
    df = _frame(pd.to_datetime(["2026-11-01 01:30:00"]))
    with pytest.raises(DataValidationError):
        from_dataframe(df, symbol="AAPL", tz="America/New_York")


def test_regular_trading_hours_never_touch_the_dst_edge_cases():
    """The market's own regular session (09:30-16:00 ET) never overlaps
    either DST edge case (both occur at 2-3am local) -- confirms the
    DST-safety machinery exists for correctness/robustness, not because
    real trading data commonly hits it."""
    trading_hours_sample = pd.to_datetime(["2026-03-09 09:30:00", "2026-11-02 15:59:00"])
    result = from_dataframe(_frame(trading_hours_sample), symbol="AAPL", tz="America/New_York")
    assert len(result) == 2  # both parsed cleanly, no DataValidationError


def test_unparseable_timestamp_aborts():
    df = pd.DataFrame({
        "timestamp": ["not-a-real-timestamp"], "open": [100.0], "high": [100.5],
        "low": [99.5], "close": [100.2], "volume": [1000.0],
    })
    with pytest.raises(Exception):  # pandas raises at parse time, before tz handling even runs
        from_dataframe(df, symbol="AAPL")
