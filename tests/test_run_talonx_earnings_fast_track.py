"""
tests/test_run_talonx_earnings_fast_track.py
----------------------------------------------------
Tests run_talonx.EarningsFastTrackPoller (Event-Driven Earnings Radar,
Requirement 6) and LongTermPriceRunner's race-fix exclusion of tickers
currently owned by the fast-track poller. Uses a REAL TickerWatchlistStore
(tmp_path, same convention as this project's other run_talonx tests);
ingest_earnings_filing/fetch_extended_hours_quote/run_long_term_financials_
ingestion are mocked -- same "mock the external call, exercise the
orchestration logic" boundary test_run_talonx_ingestion.py already uses.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from run_talonx import EarningsFastTrackPoller, LongTermPriceRunner
from talonx_ingest.market_data.models import DataSource, MarketEvent, MarketEventType
from talonx_watchlist.store import TickerWatchlistStore


@pytest.fixture
def store(tmp_path) -> TickerWatchlistStore:
    s = TickerWatchlistStore(tmp_path / "watchlist.db")
    yield s
    s.close()


@pytest.fixture
def poller(store) -> EarningsFastTrackPoller:
    return EarningsFastTrackPoller(store, on_event=AsyncMock(), poll_interval_seconds=900.0)


# --- _tickers_in_window ------------------------------------------------------

def test_ticker_reporting_today_is_in_window(store, poller):
    store.upsert_upcoming_earnings("AAPL", datetime.now(timezone.utc).date().isoformat())
    assert "AAPL" in poller._tickers_in_window()


def test_ticker_reporting_tomorrow_is_in_window(store, poller):
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    store.upsert_upcoming_earnings("AAPL", tomorrow)
    assert "AAPL" in poller._tickers_in_window()


def test_ticker_reporting_far_in_the_future_is_not_in_window(store, poller):
    far_future = (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat()
    store.upsert_upcoming_earnings("AAPL", far_future)
    assert "AAPL" not in poller._tickers_in_window()


def test_ticker_that_already_reported_yesterday_is_not_in_window(store, poller):
    yesterday = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
    store.upsert_upcoming_earnings("AAPL", yesterday)
    assert "AAPL" not in poller._tickers_in_window()


def test_empty_watchlist_returns_empty_window(store, poller):
    assert poller._tickers_in_window() == []


# --- active_symbols ------------------------------------------------------

def test_active_symbols_empty_before_any_poll(poller):
    assert poller.active_symbols() == set()


@pytest.mark.asyncio
async def test_poll_once_updates_active_symbols(store, poller):
    store.upsert_upcoming_earnings("AAPL", datetime.now(timezone.utc).date().isoformat())
    poller._chunker = object()
    poller._vector_store = object()
    poller._ledger = object()
    poller._publisher = object()

    with (
        patch("run_talonx.EdgarClient") as mock_edgar_cls,
        patch("run_talonx.ingest_earnings_filing", new_callable=AsyncMock, return_value=False) as mock_ingest,
        patch("run_talonx.fetch_extended_hours_quote", return_value=None),
    ):
        mock_edgar_cls.return_value.__aenter__ = AsyncMock(return_value=object())
        mock_edgar_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await poller._poll_once()

    assert poller.active_symbols() == {"AAPL"}
    mock_ingest.assert_awaited_once()


@pytest.mark.asyncio
async def test_poll_once_triggers_financials_ingestion_when_earnings_filing_confirmed(store, poller):
    store.upsert_upcoming_earnings("AAPL", datetime.now(timezone.utc).date().isoformat())
    poller._chunker = object()
    poller._vector_store = object()
    poller._ledger = object()
    poller._publisher = object()

    with (
        patch("run_talonx.EdgarClient") as mock_edgar_cls,
        patch("run_talonx.ingest_earnings_filing", new_callable=AsyncMock, return_value=True),
        patch("run_talonx.run_long_term_financials_ingestion", new_callable=AsyncMock) as mock_financials,
        patch("run_talonx.fetch_extended_hours_quote", return_value=None),
    ):
        mock_edgar_cls.return_value.__aenter__ = AsyncMock(return_value=object())
        mock_edgar_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await poller._poll_once()

    mock_financials.assert_awaited_once_with(["AAPL"], is_earnings_related=True)


@pytest.mark.asyncio
async def test_poll_once_publishes_extended_hours_quote_via_on_event(store, poller):
    store.upsert_upcoming_earnings("AAPL", datetime.now(timezone.utc).date().isoformat())
    poller._chunker = object()
    poller._vector_store = object()
    poller._ledger = object()
    poller._publisher = object()
    quote = MarketEvent(
        symbol="AAPL", event_type=MarketEventType.BAR, source=DataSource.POLLING,
        timestamp=datetime.now(timezone.utc), close=175.5,
    )

    with (
        patch("run_talonx.EdgarClient") as mock_edgar_cls,
        patch("run_talonx.ingest_earnings_filing", new_callable=AsyncMock, return_value=False),
        patch("run_talonx.fetch_extended_hours_quote", return_value=quote),
    ):
        mock_edgar_cls.return_value.__aenter__ = AsyncMock(return_value=object())
        mock_edgar_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await poller._poll_once()

    poller._on_event.assert_awaited_once_with(quote)


@pytest.mark.asyncio
async def test_poll_once_isolates_a_failing_ticker(store, poller):
    store.upsert_upcoming_earnings("AAPL", datetime.now(timezone.utc).date().isoformat())
    store.upsert_upcoming_earnings("MSFT", datetime.now(timezone.utc).date().isoformat())
    poller._chunker = object()
    poller._vector_store = object()
    poller._ledger = object()
    poller._publisher = object()

    async def _ingest_side_effect(ticker, *args, **kwargs):
        if ticker == "AAPL":
            raise RuntimeError("network error")
        return False

    with (
        patch("run_talonx.EdgarClient") as mock_edgar_cls,
        patch("run_talonx.ingest_earnings_filing", new_callable=AsyncMock, side_effect=_ingest_side_effect) as mock_ingest,
        patch("run_talonx.fetch_extended_hours_quote", return_value=None),
    ):
        mock_edgar_cls.return_value.__aenter__ = AsyncMock(return_value=object())
        mock_edgar_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await poller._poll_once()  # must not raise

    assert mock_ingest.await_count == 2  # both tickers still attempted


@pytest.mark.asyncio
async def test_poll_once_is_a_noop_with_an_empty_window(store, poller):
    with patch("run_talonx.EdgarClient") as mock_edgar_cls:
        await poller._poll_once()

    mock_edgar_cls.assert_not_called()
    assert poller.active_symbols() == set()


# --- LongTermPriceRunner race fix -------------------------------------------

def test_long_term_price_runner_excludes_active_earnings_symbols(store):
    store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    store.add_ticker("MSFT", "Microsoft Corporation", strategy_horizon="LONG_TERM")
    runner = LongTermPriceRunner(
        store, on_event=AsyncMock(), watchlist_poll_interval_seconds=10.0,
        price_poll_interval_seconds=86400.0, active_earnings_symbols_fn=lambda: {"AAPL"},
    )

    symbols = runner._long_term_only_symbols()

    assert symbols == {"MSFT"}  # AAPL excluded -- owned by the fast-track poller


def test_long_term_price_runner_without_earnings_fn_is_unaffected(store):
    store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    runner = LongTermPriceRunner(
        store, on_event=AsyncMock(), watchlist_poll_interval_seconds=10.0,
        price_poll_interval_seconds=86400.0,
    )

    assert runner._long_term_only_symbols() == {"AAPL"}
