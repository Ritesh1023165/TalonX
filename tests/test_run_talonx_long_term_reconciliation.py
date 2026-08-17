"""
tests/test_run_talonx_long_term_reconciliation.py
------------------------------------------------------
Tests run_talonx.reconcile_missing_long_term_factors -- the one-shot
startup fix for a confirmed-live gap: NewFundamentalsIngestedEvent is a
single Redis Pub/Sub publish with no replay/ack/retry, so a
FundamentalScanner that wasn't subscribed yet when
periodic_long_term_financials_loop's first cycle fired permanently loses
that ticker's event (the ledger marks the fiscal year "already ingested,"
so no future normal cycle ever re-fetches it). This reconciles by
comparing quant_store.get_latest_factors() against the LONG_TERM
watchlist and force-republishing whatever's missing.

Uses a REAL TickerWatchlistStore and QuantStateStore (tmp_path) since the
diff logic is driven entirely by real store queries; run_long_term_financials_
ingestion is mocked -- same "mock the external call, exercise the
orchestration logic" boundary test_run_talonx_ingestion.py already uses.
head_start_seconds is passed as a tiny value in every test so these don't
actually wait out the real 15s startup delay.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from run_talonx import reconcile_missing_long_term_factors
from talonx_quant.store import QuantStateStore
from talonx_watchlist.store import TickerWatchlistStore

NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def watchlist_store(tmp_path) -> TickerWatchlistStore:
    s = TickerWatchlistStore(tmp_path / "watchlist.db")
    yield s
    s.close()


@pytest.fixture
def quant_store(tmp_path) -> QuantStateStore:
    s = QuantStateStore(tmp_path / "quant.db")
    yield s
    s.close()


def _mock_reingest(return_value=None):
    return patch(
        "run_talonx.run_long_term_financials_ingestion",
        new_callable=AsyncMock, return_value=return_value or {},
    )


@pytest.mark.asyncio
async def test_tickers_with_no_computed_factors_are_reconciled(watchlist_store, quant_store):
    watchlist_store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    watchlist_store.add_ticker("MSFT", "Microsoft Corporation", strategy_horizon="LONG_TERM")
    # Neither ticker has ever had factors computed -- both should be reconciled.

    with _mock_reingest() as m:
        await reconcile_missing_long_term_factors(
            watchlist_store, quant_store, asyncio.Event(), head_start_seconds=0.0,
        )

    m.assert_awaited_once()
    args, kwargs = m.await_args
    assert sorted(args[0]) == ["AAPL", "MSFT"]
    assert kwargs["force"] is True


@pytest.mark.asyncio
async def test_tickers_with_computed_factors_are_left_alone(watchlist_store, quant_store):
    watchlist_store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    quant_store.save_latest_factors("AAPL", 2025, 0.21, 8, 0.05, 5.5, 1.2, NOW)

    with _mock_reingest() as m:
        await reconcile_missing_long_term_factors(
            watchlist_store, quant_store, asyncio.Event(), head_start_seconds=0.0,
        )

    m.assert_not_called()


@pytest.mark.asyncio
async def test_only_the_missing_subset_is_reconciled(watchlist_store, quant_store):
    watchlist_store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    watchlist_store.add_ticker("MSFT", "Microsoft Corporation", strategy_horizon="LONG_TERM")
    quant_store.save_latest_factors("AAPL", 2025, 0.21, 8, 0.05, 5.5, 1.2, NOW)  # AAPL already has factors

    with _mock_reingest() as m:
        await reconcile_missing_long_term_factors(
            watchlist_store, quant_store, asyncio.Event(), head_start_seconds=0.0,
        )

    m.assert_awaited_once_with(["MSFT"], force=True)


@pytest.mark.asyncio
async def test_intraday_only_tickers_are_ignored(watchlist_store, quant_store):
    watchlist_store.add_ticker("NVDA", "NVIDIA Corporation")  # INTRADAY, default horizon

    with _mock_reingest() as m:
        await reconcile_missing_long_term_factors(
            watchlist_store, quant_store, asyncio.Event(), head_start_seconds=0.0,
        )

    m.assert_not_called()


@pytest.mark.asyncio
async def test_dual_horizon_tickers_are_included(watchlist_store, quant_store):
    watchlist_store.add_ticker("AMD", "Advanced Micro Devices", strategy_horizon="DUAL_HORIZON")

    with _mock_reingest() as m:
        await reconcile_missing_long_term_factors(
            watchlist_store, quant_store, asyncio.Event(), head_start_seconds=0.0,
        )

    m.assert_awaited_once_with(["AMD"], force=True)


@pytest.mark.asyncio
async def test_empty_watchlist_does_nothing(watchlist_store, quant_store):
    with _mock_reingest() as m:
        await reconcile_missing_long_term_factors(
            watchlist_store, quant_store, asyncio.Event(), head_start_seconds=0.0,
        )

    m.assert_not_called()


@pytest.mark.asyncio
async def test_a_reingestion_failure_does_not_raise(watchlist_store, quant_store):
    watchlist_store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    boom = patch(
        "run_talonx.run_long_term_financials_ingestion", new_callable=AsyncMock, side_effect=RuntimeError("boom"),
    )
    with boom:
        await reconcile_missing_long_term_factors(
            watchlist_store, quant_store, asyncio.Event(), head_start_seconds=0.0,
        )  # must not raise


@pytest.mark.asyncio
async def test_stop_during_the_head_start_delay_skips_reconciliation_entirely(watchlist_store, quant_store):
    """If the app is shutting down before the head-start delay even
    elapses, this must not fire at all -- there's nothing to reconcile
    against a process that's already stopping."""
    watchlist_store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    stop_event = asyncio.Event()
    stop_event.set()  # already stopping before the call even starts waiting

    with _mock_reingest() as m:
        await reconcile_missing_long_term_factors(
            watchlist_store, quant_store, stop_event, head_start_seconds=60.0,
        )

    m.assert_not_called()


@pytest.mark.asyncio
async def test_stop_causes_prompt_exit_during_the_head_start_delay(watchlist_store, quant_store):
    stop_event = asyncio.Event()
    task = asyncio.create_task(
        reconcile_missing_long_term_factors(watchlist_store, quant_store, stop_event, head_start_seconds=60.0)
    )
    await asyncio.sleep(0)  # let it start waiting
    stop_event.set()
    await asyncio.wait_for(task, timeout=2.0)  # must exit well before the 60s head start


# --- Cooldown clearing (a stale cooldown key silently re-suppressing the
# forced republish -- found live: DELL/GOOGL/MSFT/PYPL's quant.db rows
# were lost separately from their original successful run, but that
# run's fundamental_cooldown Redis TTL kept ticking down independently) --

@pytest.mark.asyncio
async def test_missing_tickers_have_their_cooldown_cleared_before_the_forced_republish(watchlist_store, quant_store):
    watchlist_store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    watchlist_store.add_ticker("MSFT", "Microsoft Corporation", strategy_horizon="LONG_TERM")
    scanner = AsyncMock()

    with _mock_reingest():
        await reconcile_missing_long_term_factors(
            watchlist_store, quant_store, asyncio.Event(), scanner, head_start_seconds=0.0,
        )

    assert scanner.clear_cooldown.await_count == 2
    cleared = {call.args[0] for call in scanner.clear_cooldown.await_args_list}
    assert cleared == {"AAPL", "MSFT"}


@pytest.mark.asyncio
async def test_tickers_with_existing_factors_never_get_their_cooldown_touched(watchlist_store, quant_store):
    watchlist_store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")
    quant_store.save_latest_factors("AAPL", 2025, 0.21, 8, 0.05, 5.5, 1.2, NOW)
    scanner = AsyncMock()

    with _mock_reingest():
        await reconcile_missing_long_term_factors(
            watchlist_store, quant_store, asyncio.Event(), scanner, head_start_seconds=0.0,
        )

    scanner.clear_cooldown.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_fundamental_scanner_given_is_handled_gracefully(watchlist_store, quant_store):
    """The default (no scanner passed) must still work -- e.g. a
    --skip-quant run where there's no FundamentalScanner instance to
    clear cooldowns on in the first place."""
    watchlist_store.add_ticker("AAPL", "Apple Inc.", strategy_horizon="LONG_TERM")

    with _mock_reingest() as m:
        await reconcile_missing_long_term_factors(
            watchlist_store, quant_store, asyncio.Event(), head_start_seconds=0.0,
        )  # fundamental_scanner defaults to None -- must not raise

    m.assert_awaited_once_with(["AAPL"], force=True)
