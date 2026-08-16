"""
tests/test_download_historical_1m.py
------------------------------------------
scripts/download_historical_1m.py -- provider selection, symbol
parsing, retry/backoff behavior, and each provider's fetch function.

Every provider call is MOCKED here (never a real network/API call),
matching this repo's established convention for yfinance-dependent code
(see test_yfinance_poller.py/test_yfinance_extended_hours.py: always
`patch("yfinance.Ticker", ...)`, never a live call in the automated
suite). time.sleep is also mocked in the retry tests so they run
instantly regardless of the configured backoff.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scripts.download_historical_1m import (
    DownloadError,
    _parse_symbols,
    _retry,
    download_symbol,
    fetch_alpaca,
    fetch_polygon,
    fetch_yfinance,
    main,
    select_provider,
)


# --- _parse_symbols ---

def test_parse_symbols_comma_separated_list():
    assert _parse_symbols("aapl, MSFT ,nvda") == ["AAPL", "MSFT", "NVDA"]


def test_parse_symbols_from_file(tmp_path):
    path = tmp_path / "tickers.txt"
    path.write_text("AAPL\nmsft\n# a comment\n\nNVDA\n", encoding="utf-8")
    assert _parse_symbols(str(path)) == ["AAPL", "MSFT", "NVDA"]


# --- select_provider ---

def test_select_provider_explicit_choice_wins(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "x")
    assert select_provider("yfinance") == "yfinance"


def test_select_provider_prefers_polygon(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "x")
    monkeypatch.setenv("APCA_API_KEY_ID", "y")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "z")
    assert select_provider(None) == "polygon"


def test_select_provider_falls_back_to_alpaca_without_polygon_key(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    monkeypatch.setenv("APCA_API_KEY_ID", "y")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "z")
    assert select_provider(None) == "alpaca"


def test_select_provider_requires_both_alpaca_vars(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    monkeypatch.setenv("APCA_API_KEY_ID", "y")
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    assert select_provider(None) == "yfinance"


def test_select_provider_defaults_to_yfinance_with_no_keys(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    assert select_provider(None) == "yfinance"


# --- _retry ---

def test_retry_succeeds_after_transient_failures(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    result = _retry(flaky, max_retries=5, base_seconds=0.01, max_seconds=0.01, description="test")
    assert result == "ok"
    assert calls["n"] == 3


def test_retry_raises_download_error_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)

    def always_fails():
        raise ConnectionError("persistent failure")

    with pytest.raises(DownloadError):
        _retry(always_fails, max_retries=3, base_seconds=0.01, max_seconds=0.01, description="test")


# --- fetch_yfinance ---

def _yf_history_df(n=5):
    ts = pd.date_range("2026-08-01 09:30:00", periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({"Open": 100.0, "High": 100.5, "Low": 99.5, "Close": 100.2, "Volume": 1000.0}, index=ts)


def test_fetch_yfinance_returns_normalized_bars(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _yf_history_df(5)

    with patch("yfinance.Ticker", return_value=mock_ticker) as mock_cls:
        bars = fetch_yfinance("AAPL", "2026-08-01", "2026-08-02", max_retries=3)

    mock_cls.assert_called_once_with("AAPL")
    mock_ticker.history.assert_called_once_with(start="2026-08-01", end="2026-08-02", interval="1m", prepost=True)
    assert len(bars) == 5
    assert bars[0]["open"] == 100.0
    assert bars[0]["timestamp"].tzinfo is not None


def test_fetch_yfinance_empty_history_returns_empty_list(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()

    with patch("yfinance.Ticker", return_value=mock_ticker):
        bars = fetch_yfinance("AAPL", "2026-08-01", "2026-08-02", max_retries=3)
    assert bars == []


def test_fetch_yfinance_warns_on_wide_date_range(monkeypatch, caplog):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _yf_history_df(1)
    with patch("yfinance.Ticker", return_value=mock_ticker):
        with caplog.at_level("WARNING"):
            fetch_yfinance("AAPL", "2024-01-01", "2024-06-30", max_retries=3)
    assert any("30 trailing days" in rec.message for rec in caplog.records)


# --- fetch_polygon ---

def test_fetch_polygon_normalizes_aggs(monkeypatch):
    monkeypatch.setenv("POLYGON_API_KEY", "fake-key")
    monkeypatch.setattr(time, "sleep", lambda _: None)

    agg = MagicMock()
    agg.timestamp = int(datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc).timestamp() * 1000)
    agg.open, agg.high, agg.low, agg.close, agg.volume = 100.0, 100.5, 99.5, 100.2, 1000.0

    mock_client = MagicMock()
    mock_client.list_aggs.return_value = iter([agg])

    fake_polygon_module = MagicMock()
    fake_polygon_module.RESTClient.return_value = mock_client

    with patch.dict("sys.modules", {"polygon": fake_polygon_module}):
        bars = fetch_polygon("AAPL", "2026-08-01", "2026-08-02", max_retries=3)

    fake_polygon_module.RESTClient.assert_called_once_with("fake-key")
    mock_client.list_aggs.assert_called_once_with("AAPL", 1, "minute", "2026-08-01", "2026-08-02", limit=50000, adjusted=True)
    assert len(bars) == 1
    assert bars[0]["close"] == 100.2


# --- fetch_alpaca ---

def test_fetch_alpaca_paginates_via_next_page_token(monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "id")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")
    monkeypatch.setattr(time, "sleep", lambda _: None)

    page1 = MagicMock()
    page1.status_code = 200
    page1.json.return_value = {
        "bars": [{"t": "2026-08-01T09:30:00Z", "o": 100.0, "h": 100.5, "l": 99.5, "c": 100.2, "v": 1000.0}],
        "next_page_token": "abc",
    }
    page2 = MagicMock()
    page2.status_code = 200
    page2.json.return_value = {
        "bars": [{"t": "2026-08-01T09:31:00Z", "o": 100.2, "h": 100.6, "l": 99.9, "c": 100.4, "v": 900.0}],
        "next_page_token": None,
    }

    fake_requests = MagicMock()
    fake_requests.get.side_effect = [page1, page2]

    with patch.dict("sys.modules", {"requests": fake_requests}):
        bars = fetch_alpaca("AAPL", "2026-08-01", "2026-08-02", max_retries=3)

    assert len(bars) == 2
    assert fake_requests.get.call_count == 2
    second_call_params = fake_requests.get.call_args_list[1].kwargs["params"]
    assert second_call_params["page_token"] == "abc"


# --- download_symbol / main (end to end, mocked provider) ---

def test_download_symbol_returns_none_on_empty_result(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _: None)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    with patch("yfinance.Ticker", return_value=mock_ticker):
        result = download_symbol("AAPL", "2026-08-01", "2026-08-02", "yfinance", max_retries=2)
    assert result is None


def test_main_writes_a_valid_csv_that_passes_data_quality_checks(tmp_path, monkeypatch, capsys):
    from talonx_backtest.data import check_data_quality, load_ohlcv_csv

    monkeypatch.setattr(time, "sleep", lambda _: None)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _yf_history_df(10)

    with patch("yfinance.Ticker", return_value=mock_ticker):
        exit_code = main([
            "--symbols", "AAPL", "--start-date", "2026-08-01", "--end-date", "2026-08-02",
            "--output-dir", str(tmp_path), "--provider", "yfinance",
        ])

    assert exit_code == 0
    out_csv = tmp_path / "AAPL.csv"
    assert out_csv.is_file()

    df = load_ohlcv_csv(out_csv, symbol="AAPL")
    report = check_data_quality(df, symbol="AAPL")
    assert not report.has_critical_corruption
    assert report.rows == 10

    out = capsys.readouterr().out
    assert "1/1 symbol(s) written" in out


def test_main_reports_failed_symbols_without_aborting_the_batch(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(time, "sleep", lambda _: None)

    def fake_history(*args, **kwargs):
        return pd.DataFrame()  # empty for every symbol

    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = fake_history

    with patch("yfinance.Ticker", return_value=mock_ticker):
        exit_code = main([
            "--symbols", "AAPL,MSFT", "--start-date", "2026-08-01", "--end-date", "2026-08-02",
            "--output-dir", str(tmp_path), "--provider", "yfinance",
        ])

    assert exit_code == 1  # every symbol failed/empty
    out = capsys.readouterr().out
    assert "Failed/empty: AAPL, MSFT" in out
