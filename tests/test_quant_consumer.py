"""
tests/test_quant_consumer.py
----------------------------------
Tests talonx_quant.consumer.QuantScanner's two noise filters: per-ticker
Redis cooldown and the tumbling-window batch throttle. The Redis client
is mocked (AsyncMock) -- same "exercise the orchestration logic, mock the
external service" boundary the rest of this project's consumer tests use
(see test_dispatch_consumer.py, test_brain_consumer.py).

compute_indicators/evaluate_signals are monkeypatched for the
_handle_message-level cooldown test so it doesn't need 60 real bars of
history to produce a snapshot -- strategy.py's own logic (the edge-
triggering and hysteresis filters) is covered separately in
test_quant_strategy.py.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_quant import consumer as consumer_module
from talonx_quant.config import QuantConfig
from talonx_quant.consumer import QuantScanner
from talonx_quant.schemas import QuantSignal, SignalDirection, SignalType
from talonx_quant.store import QuantStateStore


def _signal(ticker: str, volume_surge_ratio: float | None, signal_type=SignalType.MACD_BULLISH_CROSS) -> QuantSignal:
    return QuantSignal(
        ticker=ticker,
        signal_type=signal_type,
        direction=SignalDirection.BULLISH,
        message="test signal",
        price=100.0,
        volume_surge_ratio=volume_surge_ratio,
        bar_timestamp=datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc),
    )


def _bar_message(symbol: str = "AAPL") -> dict:
    payload = {
        "event_type": "bar",
        "symbol": symbol,
        "source": "polling",
        "timestamp": "2026-08-07T15:00:00Z",
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0,
    }
    return {"channel": b"talonx:market:stream", "data": json.dumps(payload)}


@pytest.fixture
def scanner() -> QuantScanner:
    s = QuantScanner(QuantConfig())
    s._client = AsyncMock()
    return s


# --- Cooldown ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_message_suppresses_signals_when_ticker_on_cooldown(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: object())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config: [_signal("AAPL", 3.0)])
    scanner._client.exists.return_value = True  # already on cooldown

    await scanner._handle_message(_bar_message("AAPL"))

    scanner._client.publish.assert_not_awaited()
    scanner._client.set.assert_not_awaited()  # cooldown not re-armed while already locked
    assert scanner.signals_suppressed_cooldown == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_starts_cooldown_and_buffers_candidate_when_not_on_cooldown(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: object())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config: [_signal("AAPL", 3.0)])
    scanner._client.exists.return_value = False

    await scanner._handle_message(_bar_message("AAPL"))

    scanner._client.set.assert_awaited_once()
    args, kwargs = scanner._client.set.await_args
    assert args[0] == "cooldown:AAPL"
    assert kwargs["ex"] == int(scanner.config.cooldown_seconds)
    # Not published yet -- candidates wait for the throttle window flush.
    scanner._client.publish.assert_not_awaited()
    assert len(scanner._pending_candidates) == 1


@pytest.mark.asyncio
async def test_is_on_cooldown_treats_redis_error_as_not_on_cooldown(scanner):
    scanner._client.exists.side_effect = ConnectionError("redis down")

    assert await scanner._is_on_cooldown("AAPL") is False


# --- Batch throttle ----------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_throttle_window_releases_top_n_by_volume_surge_ratio(scanner):
    scanner.config = QuantConfig(throttle_max_signals=3)
    low = _signal("LOW", 1.5)
    mid = _signal("MID", 2.5)
    high = _signal("HIGH", 5.0)
    no_ratio = _signal("NORATIO", None)
    scanner._pending_candidates = [low, mid, no_ratio, high]  # 4 candidates, cap is 3

    await scanner._flush_throttle_window()

    published_payloads = [call.args[1] for call in scanner._client.publish.await_args_list]
    assert scanner._client.publish.await_count == 3
    assert scanner.signals_suppressed_throttle == 1
    assert scanner.signals_published == 3
    assert scanner._pending_candidates == []
    # The lowest-conviction candidate (no volume_surge_ratio at all) is
    # the one that should've been dropped.
    assert "NORATIO" not in "".join(published_payloads)


@pytest.mark.asyncio
async def test_flush_throttle_window_publishes_all_when_under_the_cap(scanner):
    scanner.config = QuantConfig(throttle_max_signals=3)
    scanner._pending_candidates = [_signal("A", 1.0), _signal("B", 2.0)]

    await scanner._flush_throttle_window()

    assert scanner._client.publish.await_count == 2
    assert scanner.signals_suppressed_throttle == 0


@pytest.mark.asyncio
async def test_flush_throttle_window_is_a_noop_when_nothing_pending(scanner):
    await scanner._flush_throttle_window()

    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_published == 0


# --- Suppression-count persistence (the EOD report's signal-funnel section) -

@pytest.mark.asyncio
async def test_cooldown_suppression_is_recorded_when_a_store_is_set(tmp_path, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: object())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config: [_signal("AAPL", 3.0)])
    with QuantStateStore(tmp_path / "quant.db") as store:
        scanner = QuantScanner(QuantConfig(), store=store)
        scanner._client = AsyncMock()
        scanner._client.exists.return_value = True  # already on cooldown

        await scanner._handle_message(_bar_message("AAPL"))

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = store.suppression_counts_for_date(today)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["reason"] == "COOLDOWN"
    assert rows[0]["count"] == 1


@pytest.mark.asyncio
async def test_throttle_suppression_is_recorded_per_ticker(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        scanner = QuantScanner(QuantConfig(throttle_max_signals=1), store=store)
        scanner._client = AsyncMock()
        # Two candidates for the SAME dropped ticker in one flush -- the
        # per-ticker count should be 2, not two separate rows.
        scanner._pending_candidates = [
            _signal("HIGH", 5.0), _signal("LOW", 1.0), _signal("LOW", 0.9),
        ]

        await scanner._flush_throttle_window()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = {r["ticker"]: r for r in store.suppression_counts_for_date(today)}
    assert rows["LOW"]["reason"] == "THROTTLE"
    assert rows["LOW"]["count"] == 2
    assert "HIGH" not in rows  # released, not dropped


@pytest.mark.asyncio
async def test_no_store_means_no_persistence_attempted(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: object())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config: [_signal("AAPL", 3.0)])
    scanner._client.exists.return_value = True

    # scanner fixture has store=None by default -- must not raise.
    await scanner._handle_message(_bar_message("AAPL"))
    assert scanner.signals_suppressed_cooldown == 1
