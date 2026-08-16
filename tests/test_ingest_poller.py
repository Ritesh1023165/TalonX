"""
tests/test_ingest_poller.py
--------------------------------
Tests talonx_ingest.poller.fetch_watchlist_quotes -- the timing/logging
wrapper around yfinance_poll.fetch_quotes_vectorized that
run_talonx.PreMarketPoller now uses for its full-watchlist refresh.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from talonx_ingest.market_data.models import DataSource, MarketEvent, MarketEventType
from talonx_ingest.poller import fetch_watchlist_quotes


def _quote(symbol: str) -> MarketEvent:
    return MarketEvent(
        symbol=symbol, event_type=MarketEventType.BAR, source=DataSource.POLLING,
        timestamp=datetime.now(timezone.utc), close=100.0,
    )


def test_returns_empty_list_for_no_symbols():
    with patch("talonx_ingest.poller.fetch_quotes_vectorized") as mock_fetch:
        assert fetch_watchlist_quotes([]) == []
    mock_fetch.assert_not_called()


def test_returns_the_fetched_quotes_as_a_list():
    quotes = {"AAPL": _quote("AAPL"), "MSFT": _quote("MSFT")}
    with patch("talonx_ingest.poller.fetch_quotes_vectorized", return_value=quotes) as mock_fetch:
        result = fetch_watchlist_quotes(["AAPL", "MSFT"])

    mock_fetch.assert_called_once_with(["AAPL", "MSFT"])
    assert {q.symbol for q in result} == {"AAPL", "MSFT"}


def test_logs_info_when_within_the_warn_threshold(caplog):
    import logging
    with patch("talonx_ingest.poller.fetch_quotes_vectorized", return_value={}):
        with caplog.at_level(logging.INFO, logger="talonx_ingest.poller"):
            fetch_watchlist_quotes(["AAPL"], warn_threshold_seconds=30.0)

    assert any("within" in record.message for record in caplog.records)
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


def test_logs_warning_when_over_the_warn_threshold(caplog):
    import logging
    import time as time_module

    call_count = {"n": 0}

    def fake_monotonic():
        call_count["n"] += 1
        return 0.0 if call_count["n"] == 1 else 45.0  # simulate a 45s elapsed fetch

    with patch("talonx_ingest.poller.fetch_quotes_vectorized", return_value={}):
        with patch.object(time_module, "monotonic", side_effect=fake_monotonic):
            with caplog.at_level(logging.INFO, logger="talonx_ingest.poller"):
                fetch_watchlist_quotes(["AAPL"], warn_threshold_seconds=30.0)

    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert any("OVER" in record.message for record in caplog.records)
