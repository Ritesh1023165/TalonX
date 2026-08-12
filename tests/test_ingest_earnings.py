"""
tests/test_ingest_earnings.py
------------------------------------
Tests talonx_ingest.earnings -- the Event-Driven Earnings Radar's
yfinance calendar fetch. yfinance itself is mocked (an unofficial,
version-drifting external API, same "mock the external service" boundary
this project's other yfinance-touching code gets tested against) --
_extract_earnings_date's shape-handling is the actual logic under test.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from talonx_ingest.earnings import EarningsCalendarEntry, _extract_earnings_date, fetch_earnings_calendar


# --- _extract_earnings_date: shape handling ---------------------------------

def test_extracts_earliest_date_from_a_dict_calendar():
    calendar = {"Earnings Date": [date(2026, 8, 14), date(2026, 8, 13)]}
    assert _extract_earnings_date(calendar) == date(2026, 8, 13)


def test_extracts_a_single_date_not_wrapped_in_a_list():
    calendar = {"Earnings Date": date(2026, 8, 13)}
    assert _extract_earnings_date(calendar) == date(2026, 8, 13)


def test_returns_none_for_a_calendar_missing_earnings_date():
    assert _extract_earnings_date({"Dividend Date": date(2026, 1, 1)}) is None


def test_returns_none_for_an_empty_dict():
    assert _extract_earnings_date({}) is None


def test_returns_none_for_none_calendar():
    assert _extract_earnings_date(None) is None


def test_returns_none_when_earnings_date_list_is_empty():
    assert _extract_earnings_date({"Earnings Date": []}) is None


def test_extracts_from_a_dataframe_shaped_calendar():
    pd = __import__("pandas")
    # Older yfinance versions returned a DataFrame with "Earnings Date" as
    # the index label and each estimated date as its own column value in
    # that row (df.loc["Earnings Date"] -> a pandas Series of dates).
    df = pd.DataFrame([[date(2026, 8, 13), date(2026, 8, 14)]], index=["Earnings Date"], columns=[0, 1])
    assert _extract_earnings_date(df) == date(2026, 8, 13)


def test_returns_none_for_an_unrecognized_shape():
    assert _extract_earnings_date("not a calendar") is None


# --- fetch_earnings_calendar: yfinance orchestration ------------------------

def test_fetch_earnings_calendar_returns_entry_on_success():
    mock_ticker = MagicMock()
    mock_ticker.calendar = {"Earnings Date": [date(2026, 8, 13)]}
    with patch("yfinance.Ticker", return_value=mock_ticker) as mock_ctor:
        entry = fetch_earnings_calendar("aapl")

    mock_ctor.assert_called_once_with("AAPL")
    assert entry == EarningsCalendarEntry(ticker="AAPL", earnings_date=date(2026, 8, 13))
    assert entry.session == "UNSPECIFIED"


def test_fetch_earnings_calendar_returns_none_when_no_date_available():
    mock_ticker = MagicMock()
    mock_ticker.calendar = {}
    with patch("yfinance.Ticker", return_value=mock_ticker):
        assert fetch_earnings_calendar("AAPL") is None


def test_fetch_earnings_calendar_returns_none_on_yfinance_error():
    with patch("yfinance.Ticker", side_effect=RuntimeError("network error")):
        assert fetch_earnings_calendar("AAPL") is None  # fails soft, doesn't raise
