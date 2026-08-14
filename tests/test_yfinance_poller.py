"""
tests/test_yfinance_poller.py
------------------------------------
Tests talonx_ingest.market_data.yfinance_poll.YFinancePoller.stream's
degraded-cycle handling: a poll cycle where _fetch_snapshots returns
data for only a fraction of symbols (per-symbol failures are already
swallowed inside _fetch_snapshots itself, so this never raises) must be
treated as a real failure -- backed off and, after enough consecutive
degraded cycles, escalated into a yfinance session reset -- not silently
treated as a healthy cycle forever (the bug this module fixes: a stuck
yfinance session previously required a manual process restart).

_fetch_snapshots and _reset_yfinance_session are monkeypatched so these
tests never touch the network or real yfinance internals -- same
"exercise the orchestration logic, mock the external boundary" approach
test_quant_consumer.py/test_dispatch_consumer.py use.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_ingest.config import MarketDataConfig
from talonx_ingest.market_data import yfinance_poll as poll_module
from talonx_ingest.market_data.models import DataSource, MarketEvent, MarketEventType
from talonx_ingest.market_data.yfinance_poll import YFinancePoller


def _event(symbol: str) -> MarketEvent:
    from datetime import datetime, timezone
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
async def test_healthy_cycle_does_not_reset_session(poller, monkeypatch):
    symbols = ["AAPL", "MSFT", "NVDA"]
    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: [_event(s) for s in syms])
    reset_mock = MagicMock()
    monkeypatch.setattr(poll_module, "_reset_yfinance_session", reset_mock)
    on_event = AsyncMock()

    async def stop_after_one_cycle(seconds):
        poller.stop()

    monkeypatch.setattr(poller, "_sleep_or_stop", stop_after_one_cycle)

    await poller.stream(symbols, on_event)

    assert on_event.await_count == 3
    reset_mock.assert_not_called()


@pytest.mark.asyncio
async def test_degraded_cycle_is_not_silently_treated_as_healthy(poller, monkeypatch):
    # 3 symbols requested, only 1 comes back -- 67% failure, above the 50% threshold.
    symbols = ["AAPL", "MSFT", "NVDA"]
    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: [_event("AAPL")])
    monkeypatch.setattr(poller, "_sleep_or_stop", AsyncMock())

    async def fake_sleep(seconds):
        poller.stop()  # stop right after the first degraded-cycle backoff sleep

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    on_event = AsyncMock()

    await poller.stream(symbols, on_event)

    # Still emits whatever partial data it got, exactly once (one cycle ran)...
    on_event.assert_awaited_once()
    # ...but backs off via asyncio.sleep rather than going straight to the
    # normal poll-interval sleep (_sleep_or_stop was never reached because
    # the degraded-cycle branch `continue`s past it).
    poller._sleep_or_stop.assert_not_called()


@pytest.mark.asyncio
async def test_degraded_cycle_resets_session_after_threshold_consecutive_failures(monkeypatch):
    config = _config(yfinance_session_reset_after_failures=3)
    poller = YFinancePoller(config)
    monkeypatch.setattr(poll_module, "jittered_backoff_seconds", lambda *a, **k: 0.0)
    symbols = ["AAPL", "MSFT", "NVDA"]
    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: [])  # 100% failure every cycle
    reset_mock = MagicMock()
    monkeypatch.setattr(poll_module, "_reset_yfinance_session", reset_mock)

    call_count = {"n": 0}

    async def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 3:  # stop right after the 3rd degraded cycle resets
            poller.stop()

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    await poller.stream(symbols, AsyncMock())

    reset_mock.assert_called_once()


@pytest.mark.asyncio
async def test_hard_exception_also_counts_toward_session_reset(monkeypatch):
    config = _config(yfinance_session_reset_after_failures=2)
    poller = YFinancePoller(config)
    monkeypatch.setattr(poll_module, "jittered_backoff_seconds", lambda *a, **k: 0.0)
    symbols = ["AAPL"]

    def raise_error(syms):
        raise ConnectionError("network down")

    monkeypatch.setattr(poller, "_fetch_snapshots", raise_error)
    reset_mock = MagicMock()
    monkeypatch.setattr(poll_module, "_reset_yfinance_session", reset_mock)

    call_count = {"n": 0}

    async def fake_sleep(seconds):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            poller.stop()

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    await poller.stream(symbols, AsyncMock())

    reset_mock.assert_called_once()


@pytest.mark.asyncio
async def test_recovery_resets_consecutive_failure_count(monkeypatch):
    config = _config(yfinance_session_reset_after_failures=2)
    poller = YFinancePoller(config)
    monkeypatch.setattr(poll_module, "jittered_backoff_seconds", lambda *a, **k: 0.0)
    symbols = ["AAPL", "MSFT"]
    reset_mock = MagicMock()
    monkeypatch.setattr(poll_module, "_reset_yfinance_session", reset_mock)

    # Cycle 1: fails. Cycle 2: fully healthy (should reset the counter).
    # Cycle 3: fails again -- if the counter wasn't reset, this would be
    # "consecutive failure #2" and trigger a reset; it must NOT.
    responses = iter([[], [_event("AAPL"), _event("MSFT")], []])
    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: next(responses))

    call_count = {"n": 0}

    async def fake_sleep(seconds):
        call_count["n"] += 1

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    monkeypatch.setattr(poller, "_sleep_or_stop", AsyncMock(side_effect=lambda s: poller.stop()))

    await poller.stream(symbols, AsyncMock())

    reset_mock.assert_not_called()


@pytest.mark.asyncio
async def test_too_few_symbols_does_not_trigger_degraded_logic(monkeypatch):
    """A 2-symbol poll (e.g. an earnings fast-track edge case) returning
    zero events -- 100% failure -- isn't statistically meaningful enough
    to call it a 'degraded cycle': the len(symbols) >= 3 guard means this
    falls through to the normal healthy-cycle path (_sleep_or_stop),
    never touching the backoff/session-reset machinery."""
    config = _config()
    poller = YFinancePoller(config)
    symbols = ["AAPL", "MSFT"]
    monkeypatch.setattr(poller, "_fetch_snapshots", lambda syms: [])
    reset_mock = MagicMock()
    monkeypatch.setattr(poll_module, "_reset_yfinance_session", reset_mock)
    sleep_or_stop_mock = AsyncMock(side_effect=lambda s: poller.stop())
    monkeypatch.setattr(poller, "_sleep_or_stop", sleep_or_stop_mock)

    await poller.stream(symbols, AsyncMock())

    sleep_or_stop_mock.assert_awaited_once()
    reset_mock.assert_not_called()
