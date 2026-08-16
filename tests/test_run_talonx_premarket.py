"""
tests/test_run_talonx_premarket.py
----------------------------------------------------
Tests run_talonx.PreMarketPoller. Same "REAL TickerWatchlistStore (tmp_path),
mock the external yfinance call" boundary as
test_run_talonx_earnings_fast_track.py uses for EarningsFastTrackPoller.

Covers the 2026-08-16 requirement-doc gap fixes:
  - Dynamic ET Timezone: _in_window delegates to
    talonx_ingest.session.is_premarket_window (ZoneInfo-based), not a
    flat hardcoded UTC window -- mocked at the talonx_ingest.session
    level, not via run_talonx.datetime, since run_talonx no longer does
    its own time-of-day comparison.
  - Vectorized Multi-Quote Poller: _poll_once fetches the WHOLE watchlist
    in one call to fetch_watchlist_quotes, not a per-symbol rotating
    batch.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
    )
    defaults.update(kwargs)
    return PreMarketPoller(**defaults)


# --- _in_window (Dynamic ET Timezone) ---------------------------------

def test_in_window_delegates_to_is_premarket_window_true(store):
    poller = _poller(store)
    with patch("run_talonx.is_premarket_window", return_value=True) as mock_check:
        assert poller._in_window() is True
    mock_check.assert_called_once_with()


def test_in_window_delegates_to_is_premarket_window_false(store):
    poller = _poller(store)
    with patch("run_talonx.is_premarket_window", return_value=False):
        assert poller._in_window() is False


def test_in_window_reflects_real_dst_aware_premarket_hours(store):
    # A known pre-market instant: 2026-08-03 13:00 UTC = 09:00 EDT
    # (August is EDT, UTC-4) -- squarely inside 04:00-09:30 ET.
    poller = _poller(store)
    premarket_instant = datetime(2026, 8, 3, 13, 0, tzinfo=timezone.utc)
    with patch("talonx_ingest.session.datetime") as mock_datetime:
        mock_datetime.now.return_value = premarket_instant
        assert poller._in_window() is True


def test_in_window_false_outside_premarket_hours(store):
    # 15:00 UTC = 11:00 EDT -- regular session, not pre-market.
    poller = _poller(store)
    regular_instant = datetime(2026, 8, 3, 15, 0, tzinfo=timezone.utc)
    with patch("talonx_ingest.session.datetime") as mock_datetime:
        mock_datetime.now.return_value = regular_instant
        assert poller._in_window() is False


def test_in_window_false_on_a_weekend(store):
    poller = _poller(store)
    # 2026-08-08 is a Saturday; 13:00 UTC is well inside the pre-market
    # TIME-of-day window, but weekends are always closed.
    saturday_premarket_time = datetime(2026, 8, 8, 13, 0, tzinfo=timezone.utc)
    with patch("talonx_ingest.session.datetime") as mock_datetime:
        mock_datetime.now.return_value = saturday_premarket_time
        assert poller._in_window() is False


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


# --- _poll_once (Vectorized Multi-Quote Poller) -----------------------

@pytest.mark.asyncio
async def test_poll_once_publishes_a_quote_per_symbol_via_one_vectorized_call(store):
    store.add_ticker("AAPL", "Apple Inc.")
    store.add_ticker("MSFT", "Microsoft Corporation")
    aapl_quote = MarketEvent(
        symbol="AAPL", event_type=MarketEventType.BAR, source=DataSource.POLLING,
        timestamp=datetime.now(timezone.utc), close=175.5,
    )
    msft_quote = MarketEvent(
        symbol="MSFT", event_type=MarketEventType.BAR, source=DataSource.POLLING,
        timestamp=datetime.now(timezone.utc), close=410.0,
    )
    poller = _poller(store)
    with patch("run_talonx.fetch_watchlist_quotes", return_value=[aapl_quote, msft_quote]) as mock_fetch:
        await poller._poll_once()

    mock_fetch.assert_called_once_with(["AAPL", "MSFT"], poller._refresh_warn_seconds)
    assert poller._on_event.await_count == 2
    poller._on_event.assert_any_await(aapl_quote)
    poller._on_event.assert_any_await(msft_quote)


@pytest.mark.asyncio
async def test_poll_once_skips_publishing_when_no_quotes_found(store):
    store.add_ticker("AAPL", "Apple Inc.")
    poller = _poller(store)
    with patch("run_talonx.fetch_watchlist_quotes", return_value=[]):
        await poller._poll_once()
    poller._on_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_once_does_not_raise_when_the_vectorized_fetch_fails(store):
    store.add_ticker("AAPL", "Apple Inc.")
    store.add_ticker("MSFT", "Microsoft Corporation")
    poller = _poller(store)
    with patch("run_talonx.fetch_watchlist_quotes", side_effect=RuntimeError("yfinance error")):
        await poller._poll_once()  # must not raise
    poller._on_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_once_is_a_noop_with_no_symbols(store):
    poller = _poller(store)
    with patch("run_talonx.fetch_watchlist_quotes") as mock_fetch:
        await poller._poll_once()
    mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_poll_once_uses_the_configured_refresh_warn_seconds(store):
    store.add_ticker("AAPL", "Apple Inc.")
    poller = _poller(store, refresh_warn_seconds=45.0)
    with patch("run_talonx.fetch_watchlist_quotes", return_value=[]) as mock_fetch:
        await poller._poll_once()
    mock_fetch.assert_called_once_with(["AAPL"], 45.0)
