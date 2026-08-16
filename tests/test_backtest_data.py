"""
tests/test_backtest_data.py
--------------------------------
talonx_backtest.data: normalization + data-quality checks (spec section
18). check_data_quality must never silently repair anything -- these
tests assert issues are REPORTED, and that sort_and_dedupe (the one
opt-in repair helper) actually fixes what it claims to.
"""
from __future__ import annotations

import pandas as pd
import pytest

from talonx_backtest.data import check_data_quality, from_dataframe, sort_and_dedupe


def _clean_frame(n: int = 10) -> pd.DataFrame:
    ts = pd.date_range("2026-01-05 14:30:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "symbol": ["AAPL"] * n,
        "open": [100.0 + i for i in range(n)],
        "high": [100.5 + i for i in range(n)],
        "low": [99.5 + i for i in range(n)],
        "close": [100.2 + i for i in range(n)],
        "volume": [1000.0] * n,
    })


def test_clean_data_reports_zero_issues():
    df = _clean_frame()
    report = check_data_quality(df, symbol="AAPL")
    assert report.is_clean
    assert report.rows == 10
    assert report.duplicate_timestamps == 0
    assert report.missing_bars == 0


def test_detects_duplicate_timestamps():
    df = _clean_frame()
    dup_row = df.iloc[[3]]
    df = pd.concat([df, dup_row], ignore_index=True)
    report = check_data_quality(df, symbol="AAPL")
    assert report.duplicate_timestamps == 1
    assert not report.is_clean


def test_detects_out_of_order_timestamps():
    df = _clean_frame()
    a, b = df.loc[2, "timestamp"], df.loc[3, "timestamp"]
    df.loc[2, "timestamp"], df.loc[3, "timestamp"] = b, a
    report = check_data_quality(df, symbol="AAPL")
    assert report.out_of_order_timestamps >= 1


def test_detects_missing_bars():
    df = _clean_frame(n=10)
    df = df.drop(index=[4, 5]).reset_index(drop=True)  # remove 2 consecutive 1-min bars -> one 2-bar gap
    report = check_data_quality(df, symbol="AAPL")
    assert report.missing_bars == 2
    assert len(report.missing_bar_gaps) == 1


def test_detects_invalid_prices_zero_and_negative():
    df = _clean_frame()
    df.loc[2, "close"] = 0.0
    df.loc[5, "low"] = -1.0
    report = check_data_quality(df, symbol="AAPL")
    assert report.invalid_prices == 2


def test_detects_invalid_ohlc_relationship():
    df = _clean_frame()
    df.loc[3, "high"] = 50.0  # high below low/open/close -- physically impossible bar
    report = check_data_quality(df, symbol="AAPL")
    assert report.invalid_ohlc_relationship >= 1


def test_detects_negative_volume():
    df = _clean_frame()
    df.loc[1, "volume"] = -500.0
    report = check_data_quality(df, symbol="AAPL")
    assert report.negative_volume == 1


def test_detects_nan_values():
    df = _clean_frame()
    df.loc[4, "close"] = float("nan")
    report = check_data_quality(df, symbol="AAPL")
    assert report.nan_values == 1


def test_detects_infinite_values():
    df = _clean_frame()
    df.loc[4, "close"] = float("inf")
    report = check_data_quality(df, symbol="AAPL")
    assert report.infinite_values == 1


def test_timezone_is_reported_as_utc_after_normalization():
    df = from_dataframe(_clean_frame().assign(timestamp=lambda d: d["timestamp"].dt.tz_localize(None)), symbol="AAPL", tz="America/New_York")
    report = check_data_quality(df, symbol="AAPL")
    assert report.timezone == "UTC"


def test_sort_and_dedupe_removes_duplicate_symbol_timestamp_rows():
    df = _clean_frame()
    dup_row = df.iloc[[3]].copy()
    dup_row["close"] = 999.0  # a "later" re-report of the same bucket
    dirty = pd.concat([df, dup_row], ignore_index=True)

    cleaned = sort_and_dedupe(dirty, keep="last")
    report_before = check_data_quality(dirty, symbol="AAPL")
    report_after = check_data_quality(cleaned, symbol="AAPL")

    assert report_before.duplicate_timestamps == 1
    assert report_after.duplicate_timestamps == 0
    assert cleaned[cleaned["timestamp"] == df.loc[3, "timestamp"]]["close"].iloc[0] == 999.0


def test_load_raises_on_missing_required_column():
    bad = _clean_frame().drop(columns=["volume"])
    with pytest.raises(ValueError):
        from_dataframe(bad, symbol="AAPL")
