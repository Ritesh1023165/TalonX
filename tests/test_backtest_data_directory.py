"""
tests/test_backtest_data_directory.py
------------------------------------------
talonx_backtest.data.load_ohlcv_directory -- both supported directory
layouts (data/SYMBOL/*.csv subdirectories, and a flat data/SYMBOL.csv
layout), symbol filtering, and error handling.
"""
from __future__ import annotations

import pandas as pd
import pytest

from talonx_backtest.data import load_ohlcv_directory


def _write_csv(path, n=5, start="2026-01-05 14:30:00"):
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    df = pd.DataFrame({
        "timestamp": ts, "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 1000.0,
    })
    df.to_csv(path, index=False)


def test_subdirectory_layout_concatenates_multiple_files_per_symbol(tmp_path):
    (tmp_path / "AAPL").mkdir()
    _write_csv(tmp_path / "AAPL" / "2024.csv", n=3, start="2024-01-02 14:30:00")
    _write_csv(tmp_path / "AAPL" / "2025.csv", n=3, start="2025-01-02 14:30:00")

    df = load_ohlcv_directory(tmp_path)
    assert set(df["symbol"]) == {"AAPL"}
    assert len(df) == 6
    assert df["timestamp"].is_monotonic_increasing


def test_flat_layout_uses_filename_stem_as_symbol(tmp_path):
    _write_csv(tmp_path / "AAPL.csv")
    _write_csv(tmp_path / "MSFT.csv")

    df = load_ohlcv_directory(tmp_path)
    assert set(df["symbol"]) == {"AAPL", "MSFT"}


def test_mixed_layout_both_subdirectories_and_flat_files(tmp_path):
    (tmp_path / "AAPL").mkdir()
    _write_csv(tmp_path / "AAPL" / "2024.csv")
    _write_csv(tmp_path / "MSFT.csv")

    df = load_ohlcv_directory(tmp_path)
    assert set(df["symbol"]) == {"AAPL", "MSFT"}


def test_symbols_filter_skips_unwanted_files(tmp_path):
    _write_csv(tmp_path / "AAPL.csv")
    _write_csv(tmp_path / "MSFT.csv")
    _write_csv(tmp_path / "TSLA.csv")

    df = load_ohlcv_directory(tmp_path, symbols=["aapl", "TSLA"])  # case-insensitive
    assert set(df["symbol"]) == {"AAPL", "TSLA"}


def test_raises_on_missing_directory(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_ohlcv_directory(tmp_path / "does_not_exist")


def test_raises_on_empty_directory_with_no_matches(tmp_path):
    (tmp_path / "not_a_csv.txt").write_text("hello")
    with pytest.raises(ValueError):
        load_ohlcv_directory(tmp_path)


def test_result_is_sorted_by_symbol_then_timestamp(tmp_path):
    _write_csv(tmp_path / "MSFT.csv", start="2026-02-01 14:30:00")
    _write_csv(tmp_path / "AAPL.csv", start="2026-01-01 14:30:00")

    df = load_ohlcv_directory(tmp_path)
    assert df["symbol"].tolist() == sorted(df["symbol"].tolist())
    aapl = df[df["symbol"] == "AAPL"]
    assert aapl["timestamp"].is_monotonic_increasing
