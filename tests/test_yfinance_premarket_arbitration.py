"""
tests/test_yfinance_premarket_arbitration.py
--------------------------------------------------
2026-08-18 live-incident correctness fix (code-review findings #2/#4):
YFinancePoller.stream (the continuous, always-running poller behind
WatchlistDrivenMarketData/LongTermPriceRunner) used `fast_info`, which
does NOT reflect pre/post-market trading (see fetch_extended_hours_quote's
own docstring, and run_talonx.PreMarketPoller's, which exists specifically
because of this gap). Left unsuppressed, it kept republishing the STALE
prior regular-session price as a fresh-timestamped BAR event every poll
cycle throughout pre-market -- racing PreMarketPoller's genuine premarket
bars on the SAME talonx:market:stream channel for the SAME symbols.

The fix suppresses PUBLICATION (not fetching) during the premarket window:
_fetch_snapshots is still called every cycle so _incremental_volume's
per-symbol cumulative-volume tracking stays continuous (skipping the fetch
entirely would make the first regular-session poll after market open
compute a bogus volume delta against a stale pre-premarket baseline).

Same "monkeypatch _fetch_snapshots, exercise stream()'s orchestration"
approach test_yfinance_poller.py already uses.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_ingest.config import MarketDataConfig
from talonx_ingest.market_data import yfinance_poll as poll_module
from talonx_ingest.market_data.models import DataSource, MarketEvent, MarketEventType
from talonx_ingest.market_data.yfinance_poll import YFinancePoller


def _event(symbol: str) -> MarketEvent:
    return MarketEvent(
        symbol=symbol, event_type=MarketEventType.BAR, source=DataSource.POLLING,
        timestamp=datetime.now(timezone.utc), open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0, raw={},
    )


def _config(**overrides) -> MarketDataConfig:
    defaults = dict(
        yfinance_poll_interval_seconds=0.0, yfinance_backoff_base_seconds=0.0,
        yfinance_backoff_max_seconds=0.0, yfinance_degraded_cycle_failure_rate=0.5,
        yfinance_session_reset_after_failures=3,
    )
    defaults.update(overrides)
    return MarketDataConfig(**defaults)


@pytest.fixture
def poller(monkeypatch) -> YFinancePoller:
    p = YFinancePoller(_config())
    monkeypatch.setattr(poll_module, "jittered_backoff_seconds", lambda *a, **k: 0.0)
    return p


@pytest.mark.asyncio
async def test_stream_suppresses_publication_during_premarket_window(poller, monkeypatch):
    symbols = ["AAPL", "MSFT"]
    fetch_mock = MagicMock(return_value=[_event(s) for s in symbols])
    monkeypatch.setattr(poller, "_fetch_snapshots", fetch_mock)
    monkeypatch.setattr(poll_module, "is_premarket_window", lambda *a, **k: True)
    on_event = AsyncMock()

    async def stop_after_one_cycle(seconds):
        poller.stop()

    monkeypatch.setattr(poller, "_sleep_or_stop", stop_after_one_cycle)

    await poller.stream(symbols, on_event)

    # Fetching (and therefore _incremental_volume's bookkeeping) still ran...
    fetch_mock.assert_called_once_with(symbols)
    # ...but nothing was published to the event bus during premarket.
    on_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_stream_publishes_normally_outside_premarket_window(poller, monkeypatch):
    """Regression check: regular-session (and after-hours/closed)
    behavior is completely unchanged by this fix."""
    symbols = ["AAPL", "MSFT"]
    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: [_event(s) for s in syms])
    monkeypatch.setattr(poll_module, "is_premarket_window", lambda *a, **k: False)
    on_event = AsyncMock()

    async def stop_after_one_cycle(seconds):
        poller.stop()

    monkeypatch.setattr(poller, "_sleep_or_stop", stop_after_one_cycle)

    await poller.stream(symbols, on_event)

    assert on_event.await_count == 2


@pytest.mark.asyncio
async def test_stream_transitions_from_suppressed_to_publishing_across_the_premarket_boundary(poller, monkeypatch):
    """Simulates the window ending mid-session: cycle 1 (premarket)
    suppressed, cycle 2 (regular) publishes -- proves this is evaluated
    fresh every cycle, not cached/sticky from process start."""
    symbols = ["AAPL"]
    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: [_event(s) for s in syms])
    window_calls = iter([True, False])  # premarket, then regular
    monkeypatch.setattr(poll_module, "is_premarket_window", lambda *a, **k: next(window_calls))
    on_event = AsyncMock()

    call_count = {"n": 0}

    async def stop_after_two_cycles(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            poller.stop()

    monkeypatch.setattr(poller, "_sleep_or_stop", stop_after_two_cycles)

    await poller.stream(symbols, on_event)

    on_event.assert_awaited_once()  # only cycle 2 (regular) published
