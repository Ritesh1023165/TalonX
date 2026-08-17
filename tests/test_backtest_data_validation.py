"""
tests/test_backtest_data_validation.py
-------------------------------------------
talonx_backtest.data: critical-corruption abort behavior (spec section
5) vs recoverable-issue handling -- NaN/infinite/negative prices, a bad
OHLC relationship, and negative volume must ABORT (DataValidationError),
never silently continue; duplicate/out-of-order timestamps remain
recoverable (opt-in --auto-dedupe), not an abort condition.
"""
from __future__ import annotations

import pandas as pd
import pytest

from talonx_backtest.data import (
    DataValidationError,
    abort_on_critical_corruption,
    check_data_quality,
    check_dataset_quality,
)


def _clean_frame(n: int = 10) -> pd.DataFrame:
    ts = pd.date_range("2026-01-05 14:30:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts, "symbol": ["AAPL"] * n,
        "open": [100.0 + i for i in range(n)], "high": [100.5 + i for i in range(n)],
        "low": [99.5 + i for i in range(n)], "close": [100.2 + i for i in range(n)],
        "volume": [1000.0] * n,
    })


@pytest.mark.parametrize("mutator,field", [
    (lambda df: df.assign(close=lambda d: d["close"].where(d.index != 2, 0.0)), "invalid_prices"),
    (lambda df: df.assign(low=lambda d: d["low"].where(d.index != 2, -1.0)), "invalid_prices"),
    (lambda df: df.assign(high=lambda d: d["high"].where(d.index != 2, 50.0)), "invalid_ohlc_relationship"),
    (lambda df: df.assign(volume=lambda d: d["volume"].where(d.index != 2, -500.0)), "negative_volume"),
    (lambda df: df.assign(close=lambda d: d["close"].where(d.index != 2, float("nan"))), "nan_values"),
    (lambda df: df.assign(close=lambda d: d["close"].where(d.index != 2, float("inf"))), "infinite_values"),
])
def test_each_critical_corruption_type_is_flagged_and_aborts(mutator, field):
    df = mutator(_clean_frame())
    report = check_data_quality(df, symbol="AAPL")

    assert getattr(report, field) > 0
    assert report.has_critical_corruption

    with pytest.raises(DataValidationError):
        abort_on_critical_corruption({"AAPL": report})


def test_clean_data_does_not_abort():
    report = check_data_quality(_clean_frame(), symbol="AAPL")
    assert not report.has_critical_corruption
    abort_on_critical_corruption({"AAPL": report})  # must not raise


def test_duplicate_timestamps_are_recoverable_not_critical():
    df = _clean_frame()
    df = pd.concat([df, df.iloc[[3]]], ignore_index=True)
    report = check_data_quality(df, symbol="AAPL")

    assert report.duplicate_timestamps == 1
    assert report.has_recoverable_issues
    assert not report.has_critical_corruption
    abort_on_critical_corruption({"AAPL": report})  # must NOT raise -- recoverable only


def test_out_of_order_timestamps_are_recoverable_not_critical():
    df = _clean_frame()
    a, b = df.loc[2, "timestamp"], df.loc[3, "timestamp"]
    df.loc[2, "timestamp"], df.loc[3, "timestamp"] = b, a
    report = check_data_quality(df, symbol="AAPL")

    assert report.out_of_order_timestamps >= 1
    assert report.has_recoverable_issues
    assert not report.has_critical_corruption
    abort_on_critical_corruption({"AAPL": report})  # must NOT raise


def test_abort_on_critical_corruption_reports_every_bad_symbol():
    good = check_data_quality(_clean_frame(), symbol="GOOD")
    bad_df = _clean_frame().assign(close=lambda d: d["close"].where(d.index != 0, -1.0))
    bad = check_data_quality(bad_df, symbol="BAD")

    with pytest.raises(DataValidationError) as excinfo:
        abort_on_critical_corruption({"GOOD": good, "BAD": bad})
    assert "BAD" in str(excinfo.value)
    assert "GOOD" not in str(excinfo.value)


def test_multi_symbol_dataset_quality_isolates_corruption_per_symbol():
    good_df = _clean_frame().assign(symbol="GOOD")
    bad_df = _clean_frame().assign(symbol="BAD", close=lambda d: d["close"].where(d.index != 0, -1.0))
    combined = pd.concat([good_df, bad_df], ignore_index=True)

    reports = check_dataset_quality(combined)
    assert not reports["GOOD"].has_critical_corruption
    assert reports["BAD"].has_critical_corruption
