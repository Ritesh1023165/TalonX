"""
tests/test_yfinance_vectorized_quotes.py
--------------------------------------------
Tests talonx_ingest.market_data.yfinance_poll.fetch_quotes_vectorized --
the Vectorized Multi-Quote Poller requirement-doc gap fix. yfinance
itself is mocked (an unofficial, version-drifting external API), same
boundary test_yfinance_extended_hours.py uses for fetch_extended_hours_quote.
"""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from talonx_ingest.market_data.models import DataSource, MarketEventType
from talonx_ingest.market_data.yfinance_poll import fetch_quotes_vectorized


def _grouped_df(per_symbol: dict[str, list[dict]]) -> pd.DataFrame:
    """Mimics yf.download(..., group_by="ticker")'s MultiIndex-columned
    shape for 2+ symbols: top-level column = symbol, second level = field."""
    frames = {}
    for symbol, rows in per_symbol.items():
        df = pd.DataFrame(rows)
        df.index = pd.date_range("2026-08-13 12:00", periods=len(rows), freq="1min", tz="UTC")
        frames[symbol] = df
    return pd.concat(frames, axis=1)


def _flat_df(rows: list[dict]) -> pd.DataFrame:
    """Mimics yf.download's single-ticker (ungrouped) return shape."""
    df = pd.DataFrame(rows)
    df.index = pd.date_range("2026-08-13 12:00", periods=len(rows), freq="1min", tz="UTC")
    return df


def test_returns_empty_dict_for_no_symbols():
    assert fetch_quotes_vectorized([]) == {}


def test_returns_the_latest_bar_per_symbol_from_a_grouped_frame():
    data = _grouped_df({
        "AAPL": [
            {"Open": 174.0, "High": 175.0, "Low": 173.5, "Close": 174.5, "Volume": 1000},
            {"Open": 174.5, "High": 176.0, "Low": 174.0, "Close": 175.8, "Volume": 1200},
        ],
        "MSFT": [
            {"Open": 410.0, "High": 412.0, "Low": 409.0, "Close": 411.0, "Volume": 800},
            {"Open": 411.0, "High": 413.0, "Low": 410.5, "Close": 412.5, "Volume": 900},
        ],
    })
    with patch("yfinance.download", return_value=data) as mock_download:
        results = fetch_quotes_vectorized(["aapl", "msft"])

    mock_download.assert_called_once()
    assert set(results.keys()) == {"AAPL", "MSFT"}
    assert results["AAPL"].close == 175.8
    assert results["AAPL"].open == 174.5
    assert results["MSFT"].close == 412.5
    assert results["AAPL"].event_type == MarketEventType.BAR
    assert results["AAPL"].source == DataSource.POLLING


def test_returns_the_latest_bar_for_a_single_ungrouped_symbol():
    data = _flat_df([
        {"Open": 174.0, "High": 175.0, "Low": 173.5, "Close": 174.5, "Volume": 1000},
        {"Open": 174.5, "High": 176.0, "Low": 174.0, "Close": 175.8, "Volume": 1200},
    ])
    with patch("yfinance.download", return_value=data):
        results = fetch_quotes_vectorized(["AAPL"])

    assert set(results.keys()) == {"AAPL"}
    assert results["AAPL"].close == 175.8


def test_a_symbol_missing_from_the_batch_is_simply_absent():
    data = _grouped_df({
        "AAPL": [{"Open": 174.0, "High": 175.0, "Low": 173.5, "Close": 174.5, "Volume": 1000}],
    })
    with patch("yfinance.download", return_value=data):
        results = fetch_quotes_vectorized(["AAPL", "DELISTED"])

    assert set(results.keys()) == {"AAPL"}


def test_returns_empty_dict_when_download_returns_none():
    with patch("yfinance.download", return_value=None):
        assert fetch_quotes_vectorized(["AAPL"]) == {}


def test_returns_empty_dict_when_download_returns_empty_frame():
    with patch("yfinance.download", return_value=pd.DataFrame()):
        assert fetch_quotes_vectorized(["AAPL"]) == {}


def test_returns_empty_dict_on_yfinance_error():
    with patch("yfinance.download", side_effect=RuntimeError("network error")):
        assert fetch_quotes_vectorized(["AAPL"]) == {}  # fails soft, doesn't raise


def test_one_bad_symbol_does_not_block_the_rest_of_the_batch():
    data = _grouped_df({
        "AAPL": [{"Open": 174.0, "High": 175.0, "Low": 173.5, "Close": float("nan"), "Volume": 1000}],
        "MSFT": [{"Open": 410.0, "High": 412.0, "Low": 409.0, "Close": 411.0, "Volume": 800}],
    })
    with patch("yfinance.download", return_value=data):
        results = fetch_quotes_vectorized(["AAPL", "MSFT"])

    assert set(results.keys()) == {"MSFT"}  # AAPL's NaN close excluded, MSFT still returned


def test_timestamp_gets_utc_tzinfo_when_naive():
    df = pd.DataFrame([{"Open": 174.0, "High": 175.0, "Low": 173.5, "Close": 174.5, "Volume": 1000}])
    df.index = pd.date_range("2026-08-13 12:00", periods=1, freq="1min")  # no tz
    with patch("yfinance.download", return_value=df):
        results = fetch_quotes_vectorized(["AAPL"])

    assert results["AAPL"].timestamp.tzinfo is not None
