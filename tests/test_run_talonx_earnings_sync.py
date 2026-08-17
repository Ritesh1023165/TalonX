"""
tests/test_run_talonx_earnings_sync.py
--------------------------------------------
Tests run_talonx.periodic_earnings_calendar_sync_loop -- the Event-Driven
Earnings Radar's weekly yfinance calendar sync. Uses a REAL
TickerWatchlistStore (tmp_path, same as this project's other
run_talonx/watchlist tests); fetch_earnings_calendar is mocked -- same
"mock the external call, exercise the orchestration logic" boundary
test_run_talonx_ingestion.py already uses for run_ingestion et al.

No direct test exists for periodic_ingestion_loop/periodic_long_term_
financials_loop either (see that file's own docstring) -- this loop is
exercised the same way those would be: patch the external call with a
side_effect that sets stop_event so the loop runs exactly one cycle, then
assert on what got written.
"""
from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import patch

import pytest

from run_talonx import periodic_earnings_calendar_sync_loop
from talonx_ingest.earnings import EarningsCalendarEntry
from talonx_watchlist.store import TickerWatchlistStore


@pytest.fixture
def store(tmp_path) -> TickerWatchlistStore:
    s = TickerWatchlistStore(tmp_path / "watchlist.db")
    yield s
    s.close()


@pytest.mark.asyncio
async def test_syncs_earnings_date_for_long_term_tickers_only(store):
    store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    store.add_ticker("NVDA", "NVIDIA Corporation", strategy_horizon="INTRADAY")
    stop_event = asyncio.Event()

    def _fake_fetch(ticker):
        stop_event.set()  # stop after this (the only) ticker in the cycle
        return EarningsCalendarEntry(
            ticker=ticker, earnings_date=date(2026, 8, 13),
            session="AFTER_MARKET", reporting_period="Q2 2026",
        )

    with patch("run_talonx.fetch_earnings_calendar", side_effect=_fake_fetch):
        await periodic_earnings_calendar_sync_loop(store, interval_hours=0.0, stop_event=stop_event)

    row = store.get_upcoming_earnings("AAPL")
    assert row is not None
    assert row["earnings_date"] == "2026-08-13"
    assert row["session"] == "AFTER_MARKET"
    assert row["reporting_period"] == "Q2 2026"
    assert store.get_upcoming_earnings("NVDA") is None  # INTRADAY -- never synced


@pytest.mark.asyncio
async def test_dual_horizon_ticker_is_synced_too(store):
    store.add_ticker("MSFT", "Microsoft Corporation", strategy_horizon="DUAL_HORIZON")
    stop_event = asyncio.Event()

    def _fake_fetch(ticker):
        stop_event.set()
        return EarningsCalendarEntry(ticker=ticker, earnings_date=date(2026, 8, 13))

    with patch("run_talonx.fetch_earnings_calendar", side_effect=_fake_fetch):
        await periodic_earnings_calendar_sync_loop(store, interval_hours=0.0, stop_event=stop_event)

    assert store.get_upcoming_earnings("MSFT") is not None


@pytest.mark.asyncio
async def test_a_ticker_with_no_available_date_is_skipped_not_fatal(store):
    store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    store.add_ticker("MSFT", "Microsoft Corporation", strategy_horizon="LONG_TERM")
    stop_event = asyncio.Event()
    call_count = 0

    def _fake_fetch(ticker):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        return None  # neither ticker has a date this cycle

    with patch("run_talonx.fetch_earnings_calendar", side_effect=_fake_fetch):
        await periodic_earnings_calendar_sync_loop(store, interval_hours=0.0, stop_event=stop_event)

    assert store.list_upcoming_earnings() == []  # no crash, nothing written


@pytest.mark.asyncio
async def test_a_fetch_exception_does_not_kill_the_cycle(store):
    store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    store.add_ticker("MSFT", "Microsoft Corporation", strategy_horizon="LONG_TERM")
    stop_event = asyncio.Event()

    def _fake_fetch(ticker):
        if ticker == "AAPL":
            raise RuntimeError("network error")
        stop_event.set()
        return EarningsCalendarEntry(ticker=ticker, earnings_date=date(2026, 8, 13))

    with patch("run_talonx.fetch_earnings_calendar", side_effect=_fake_fetch):
        await periodic_earnings_calendar_sync_loop(store, interval_hours=0.0, stop_event=stop_event)

    assert store.get_upcoming_earnings("AAPL") is None  # the failing one -- skipped
    assert store.get_upcoming_earnings("MSFT") is not None  # the rest of the cycle still ran


@pytest.mark.asyncio
async def test_empty_watchlist_does_not_call_fetch(store):
    # Nothing added to the watchlist -- the "if not tickers" branch should
    # wait on stop_event rather than fetch anything. A long interval means
    # that wait would hang for the whole test run, so it's stopped from a
    # concurrent task shortly after starting instead of pre-setting
    # stop_event (which would skip entering the loop body at all).
    stop_event = asyncio.Event()

    with patch("run_talonx.fetch_earnings_calendar") as mock_fetch:
        task = asyncio.create_task(
            periodic_earnings_calendar_sync_loop(store, interval_hours=1.0, stop_event=stop_event)
        )
        await asyncio.sleep(0.05)
        stop_event.set()
        await asyncio.wait_for(task, timeout=5.0)

    mock_fetch.assert_not_called()
