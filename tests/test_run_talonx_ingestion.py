"""
tests/test_run_talonx_ingestion.py
----------------------------------------
Tests run_talonx.WatchlistDrivenIngestion -- the reactive watcher that
triggers an immediate one-off filing/news/financials ingestion for a
ticker the moment it's added, resumed, or re-tagged LONG_TERM, instead
of waiting for periodic_ingestion_loop's/periodic_long_term_financials_
loop's next --interval-hours cycle. Uses a REAL TickerWatchlistStore
(tmp_path, same as talonx_watchlist's own tests) since the diff logic is
driven entirely by real store queries; run_ingestion/run_news_ingestion/
run_long_term_financials_ingestion are mocked -- same "mock the external
call, exercise the orchestration logic" boundary the rest of this
project's consumer tests use (they'd otherwise make real SEC EDGAR/
Redis/ChromaDB calls).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from run_talonx import WatchlistDrivenIngestion
from talonx_watchlist.store import TickerWatchlistStore


@pytest.fixture
def store(tmp_path) -> TickerWatchlistStore:
    s = TickerWatchlistStore(tmp_path / "watchlist.db")
    yield s
    s.close()


@pytest.fixture
def watcher(store) -> WatchlistDrivenIngestion:
    return WatchlistDrivenIngestion(store, poll_interval_seconds=10.0)


def _mocks():
    return (
        patch("run_talonx.run_ingestion", new_callable=AsyncMock, return_value={}),
        patch("run_talonx.run_news_ingestion", new_callable=AsyncMock, return_value={}),
        patch("run_talonx.run_long_term_financials_ingestion", new_callable=AsyncMock, return_value={}),
    )


@pytest.mark.asyncio
async def test_seeding_from_current_state_does_not_trigger_anything(store, watcher):
    """The initial batch is already handled by the periodic loops' own
    'run immediately on startup' behavior -- WatchlistDrivenIngestion
    must NOT re-trigger ingestion for tickers already present when it
    starts watching."""
    store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    watcher._known_active_symbols = set(store.list_active_symbols())
    watcher._known_long_term_symbols = set(store.list_by_horizon("LONG_TERM"))

    ingest, news, financials = _mocks()
    with ingest as m_ingest, news as m_news, financials as m_financials:
        await watcher._reconcile()

    m_ingest.assert_not_called()
    m_news.assert_not_called()
    m_financials.assert_not_called()


@pytest.mark.asyncio
async def test_a_newly_active_ticker_triggers_filing_and_news_ingestion(store, watcher):
    ingest, news, financials = _mocks()
    with ingest as m_ingest, news as m_news, financials as m_financials:
        store.add_ticker("NVDA", "NVIDIA Corporation")  # INTRADAY, active by default
        await watcher._reconcile()

    m_ingest.assert_awaited_once_with(["NVDA"])
    m_news.assert_awaited_once_with(["NVDA"])
    m_financials.assert_not_called()  # not LONG_TERM-tagged


@pytest.mark.asyncio
async def test_a_newly_long_term_ticker_triggers_financials_ingestion(store, watcher):
    ingest, news, financials = _mocks()
    with ingest as m_ingest, news as m_news, financials as m_financials:
        store.add_ticker("BRK.B", "Berkshire Hathaway", strategy_horizon="LONG_TERM")
        await watcher._reconcile()

    m_financials.assert_awaited_once_with(["BRK.B"])
    # ALSO newly active -- both paths fire for a brand-new LONG_TERM ticker.
    m_ingest.assert_awaited_once_with(["BRK.B"])
    m_news.assert_awaited_once_with(["BRK.B"])


@pytest.mark.asyncio
async def test_retagging_an_existing_ticker_to_long_term_only_triggers_financials(store, watcher):
    """The exact gap a live smoke test caught: CSCO/GOOGL/MSFT/etc. were
    re-tagged from INTRADAY to LONG_TERM mid-session, not newly added.
    Filing/news ingestion must NOT re-fire for an already-active ticker
    (it's not "new"); only the financials path should."""
    store.add_ticker("CSCO", "Cisco Systems")  # INTRADAY, active
    watcher._known_active_symbols = set(store.list_active_symbols())
    watcher._known_long_term_symbols = set(store.list_by_horizon("LONG_TERM"))

    ingest, news, financials = _mocks()
    with ingest as m_ingest, news as m_news, financials as m_financials:
        store.set_strategy_horizon("CSCO", "LONG_TERM")
        await watcher._reconcile()

    m_financials.assert_awaited_once_with(["CSCO"])
    m_ingest.assert_not_called()
    m_news.assert_not_called()


@pytest.mark.asyncio
async def test_an_unchanged_watchlist_triggers_nothing(store, watcher):
    store.add_ticker("AAPL", "Apple Inc.")
    watcher._known_active_symbols = set(store.list_active_symbols())
    watcher._known_long_term_symbols = set(store.list_by_horizon("LONG_TERM"))

    ingest, news, financials = _mocks()
    with ingest as m_ingest, news as m_news, financials as m_financials:
        await watcher._reconcile()  # nothing changed

    m_ingest.assert_not_called()
    m_news.assert_not_called()
    m_financials.assert_not_called()


@pytest.mark.asyncio
async def test_a_paused_ticker_is_not_treated_as_active(store, watcher):
    ingest, news, financials = _mocks()
    with ingest as m_ingest, news as m_news, financials as m_financials:
        store.add_ticker("AAPL", "Apple Inc.", status="paused")
        await watcher._reconcile()

    m_ingest.assert_not_called()
    m_news.assert_not_called()


@pytest.mark.asyncio
async def test_resuming_a_paused_ticker_triggers_ingestion(store, watcher):
    store.add_ticker("AAPL", "Apple Inc.", status="paused")
    watcher._known_active_symbols = set(store.list_active_symbols())  # empty -- AAPL is paused
    watcher._known_long_term_symbols = set(store.list_by_horizon("LONG_TERM"))

    ingest, news, financials = _mocks()
    with ingest as m_ingest, news as m_news, financials as m_financials:
        store.resume_ticker("AAPL")
        await watcher._reconcile()

    m_ingest.assert_awaited_once_with(["AAPL"])
    m_news.assert_awaited_once_with(["AAPL"])


@pytest.mark.asyncio
async def test_a_failed_filing_ingestion_does_not_block_news_ingestion(store, watcher):
    ingest = patch("run_talonx.run_ingestion", new_callable=AsyncMock, side_effect=RuntimeError("boom"))
    news = patch("run_talonx.run_news_ingestion", new_callable=AsyncMock, return_value={})
    financials = patch("run_talonx.run_long_term_financials_ingestion", new_callable=AsyncMock, return_value={})
    with ingest, news as m_news, financials:
        store.add_ticker("AAPL", "Apple Inc.")
        await watcher._reconcile()  # must not raise

    m_news.assert_awaited_once_with(["AAPL"])


@pytest.mark.asyncio
async def test_multiple_new_tickers_are_batched_into_one_call(store, watcher):
    ingest, news, financials = _mocks()
    with ingest as m_ingest, news as m_news, financials as m_financials:
        store.add_ticker("AAPL", "Apple Inc.")
        store.add_ticker("MSFT", "Microsoft Corporation")
        await watcher._reconcile()

    m_ingest.assert_awaited_once_with(["AAPL", "MSFT"])


@pytest.mark.asyncio
async def test_stop_causes_run_to_exit_promptly(tmp_path):
    store_ = TickerWatchlistStore(tmp_path / "watchlist_stop.db")
    try:
        watcher_ = WatchlistDrivenIngestion(store_, poll_interval_seconds=60.0)
        import asyncio
        task = asyncio.create_task(watcher_.run())
        await asyncio.sleep(0)  # let it seed and start waiting
        watcher_.stop()
        await asyncio.wait_for(task, timeout=2.0)  # must exit well before the 60s poll interval
    finally:
        store_.close()
