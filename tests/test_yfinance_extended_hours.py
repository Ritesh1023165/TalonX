"""
tests/test_yfinance_extended_hours.py
--------------------------------------------
Tests talonx_ingest.market_data.yfinance_poll.fetch_extended_hours_quote
-- the Event-Driven Earnings Radar's Requirement 6 extended-hours price
capture. yfinance itself is mocked (an unofficial, version-drifting
external API), same boundary test_ingest_earnings.py uses for the
calendar fetch.
"""
from __future__ import annotations

from datetime import timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from talonx_ingest.market_data.models import DataSource, MarketEventType
from talonx_ingest.market_data.yfinance_poll import fetch_extended_hours_quote


def _history_df(rows: list[dict], index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if index is not None:
        df.index = index
    else:
        df.index = pd.date_range("2026-08-13 20:00", periods=len(rows), freq="1min", tz="UTC")
    return df


def test_returns_the_latest_bar():
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _history_df([
        {"Open": 174.0, "High": 175.0, "Low": 173.5, "Close": 174.5, "Volume": 1000},
        {"Open": 174.5, "High": 176.0, "Low": 174.0, "Close": 175.8, "Volume": 1200},
    ])
    with patch("yfinance.Ticker", return_value=mock_ticker) as mock_ctor:
        event = fetch_extended_hours_quote("aapl")

    mock_ctor.assert_called_once_with("AAPL")
    mock_ticker.history.assert_called_once_with(period="1d", interval="1m", prepost=True)
    assert event is not None
    assert event.symbol == "AAPL"
    assert event.close == 175.8
    assert event.open == 174.5
    assert event.event_type == MarketEventType.BAR
    assert event.source == DataSource.POLLING


def test_timestamp_gets_utc_tzinfo_when_naive():
    mock_ticker = MagicMock()
    naive_index = pd.date_range("2026-08-13 20:00", periods=1, freq="1min")  # no tz
    mock_ticker.history.return_value = _history_df(
        [{"Open": 174.0, "High": 175.0, "Low": 173.5, "Close": 174.5, "Volume": 1000}], index=naive_index,
    )
    with patch("yfinance.Ticker", return_value=mock_ticker):
        event = fetch_extended_hours_quote("AAPL")

    assert event.timestamp.tzinfo is not None


def test_returns_none_when_history_is_empty():
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    with patch("yfinance.Ticker", return_value=mock_ticker):
        assert fetch_extended_hours_quote("AAPL") is None


def test_returns_none_when_history_is_none():
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = None
    with patch("yfinance.Ticker", return_value=mock_ticker):
        assert fetch_extended_hours_quote("AAPL") is None


def test_returns_none_when_close_is_nan():
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _history_df([
        {"Open": 174.0, "High": 175.0, "Low": 173.5, "Close": float("nan"), "Volume": 1000},
    ])
    with patch("yfinance.Ticker", return_value=mock_ticker):
        assert fetch_extended_hours_quote("AAPL") is None


def test_returns_none_on_yfinance_error():
    with patch("yfinance.Ticker", side_effect=RuntimeError("network error")):
        assert fetch_extended_hours_quote("AAPL") is None  # fails soft, doesn't raise
