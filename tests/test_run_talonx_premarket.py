"""
tests/test_run_talonx_premarket.py
----------------------------------------------------
Tests run_talonx.PreMarketPoller. Same "REAL TickerWatchlistStore (tmp_path),
mock the external yfinance call" boundary as
test_run_talonx_earnings_fast_track.py uses for EarningsFastTrackPoller.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from run_talonx import PreMarketPoller
from talonx_ingest.market_data.models import DataSource, MarketEvent, MarketEventType
from talonx_watchlist.store import TickerWatchlistStore


@pytest.fixture
def store(tmp_path) -> TickerWatchlistStore:
    s = TickerWatchlistStore(tmp_path / "watchlist.db")
    yield s
    s.close()


def _poller(store, **kwargs) -> PreMarketPoller:
    defaults = dict(
        watchlist_store=store, on_event=AsyncMock(), poll_interval_seconds=300.0,
        start_utc=time(0, 0), end_utc=time(23, 59),
    )
    defaults.update(kwargs)
    return PreMarketPoller(**defaults)


# --- _in_window ------------------------------------------------------

def test_in_window_when_within_configured_range_on_a_weekday(store):
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        pytest.skip("weekday-only check -- weekend behavior covered separately below")
    start = (now - timedelta(minutes=5)).time()
    end = (now + timedelta(minutes=5)).time()
    poller = _poller(store, start_utc=start, end_utc=end)
    assert poller._in_window()


def test_not_in_window_before_start(store):
    now = datetime.now(timezone.utc)
    start = (now + timedelta(minutes=5)).time()
    end = (now + timedelta(minutes=10)).time()
    poller = _poller(store, start_utc=start, end_utc=end)
    assert not poller._in_window()


def test_not_in_window_after_end(store):
    now = datetime.now(timezone.utc)
    start = (now - timedelta(minutes=10)).time()
    end = (now - timedelta(minutes=5)).time()
    poller = _poller(store, start_utc=start, end_utc=end)
    assert not poller._in_window()


def test_not_in_window_on_a_weekend(store):
    now = datetime.now(timezone.utc)
    days_until_saturday = (5 - now.weekday()) % 7
    saturday = now + timedelta(days=days_until_saturday, hours=1)
    poller = _poller(store)  # 00:00-23:59 window -- would otherwise always be "in window"
    with patch("run_talonx.datetime") as mock_datetime:
        mock_datetime.now.return_value = saturday
        assert not poller._in_window()


# --- _symbols ------------------------------------------------------

def test_symbols_returns_full_active_watchlist_by_default(store):
    store.add_ticker("AAPL", "Apple Inc.")
    store.add_ticker("MSFT", "Microsoft Corporation")
    poller = _poller(store)
    assert poller._symbols() == {"AAPL", "MSFT"}


def test_symbols_excludes_active_earnings_symbols(store):
    store.add_ticker("AAPL", "Apple Inc.")
    store.add_ticker("MSFT", "Microsoft Corporation")
    poller = _poller(store, active_earnings_symbols_fn=lambda: {"AAPL"})
    assert poller._symbols() == {"MSFT"}  # AAPL owned by EarningsFastTrackPoller instead


# --- _poll_once ------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_once_publishes_a_quote_per_symbol(store):
    store.add_ticker("AAPL", "Apple Inc.")
    quote = MarketEvent(
        symbol="AAPL", event_type=MarketEventType.BAR, source=DataSource.POLLING,
        timestamp=datetime.now(timezone.utc), close=175.5,
    )
    poller = _poller(store)
    with patch("run_talonx.fetch_extended_hours_quote", return_value=quote):
        await poller._poll_once()
    poller._on_event.assert_awaited_once_with(quote)


@pytest.mark.asyncio
async def test_poll_once_skips_a_symbol_with_no_usable_quote(store):
    store.add_ticker("AAPL", "Apple Inc.")
    poller = _poller(store)
    with patch("run_talonx.fetch_extended_hours_quote", return_value=None):
        await poller._poll_once()
    poller._on_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_once_isolates_a_failing_symbol(store):
    store.add_ticker("AAPL", "Apple Inc.")
    store.add_ticker("MSFT", "Microsoft Corporation")

    def _side_effect(symbol):
        if symbol == "AAPL":
            raise RuntimeError("yfinance error")
        return None

    poller = _poller(store)
    with patch("run_talonx.fetch_extended_hours_quote", side_effect=_side_effect) as mock_fetch:
        await poller._poll_once()  # must not raise

    assert mock_fetch.call_count == 2  # both tickers still attempted


@pytest.mark.asyncio
async def test_poll_once_is_a_noop_with_no_symbols(store):
    poller = _poller(store)
    with patch("run_talonx.fetch_extended_hours_quote") as mock_fetch:
        await poller._poll_once()
    mock_fetch.assert_not_called()
