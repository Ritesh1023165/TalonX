"""
tests/test_quant_consumer.py
----------------------------------
Tests talonx_quant.consumer.QuantScanner's filter pipeline: post-loss
lockout, per-ticker Redis cooldown, confluence/risk-reward filtering, and
the tumbling-window batch throttle. The Redis client is mocked
(AsyncMock) -- same "exercise the orchestration logic, mock the external
service" boundary the rest of this project's consumer tests use (see
test_dispatch_consumer.py, test_brain_consumer.py).

compute_indicators/evaluate_signals are monkeypatched for the
_handle_market_tick-level tests so they don't need 120 real bars of
history to produce a snapshot -- strategy.py's own logic (the edge-
triggering, hysteresis, ATR-move, confluence, and risk/reward
calculations) is covered separately in test_quant_strategy.py.

_client.exists is mocked via a side_effect keyed on the Redis key prefix
(cooldown: vs loss_lockout:) rather than a single return_value, since a
handler now checks BOTH keys per tick -- a single blanket return_value
would make every test ambiguous about which lock actually fired.
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


def _signal(
    ticker: str,
    volume_surge_ratio: float | None,
    signal_type=SignalType.MACD_BULLISH_CROSS,
    confluence_score: int | None = 3,
    risk_reward_ratio: float | None = 2.0,
) -> QuantSignal:
    # Defaults (confluence_score=3, risk_reward_ratio=2.0) clear the
    # default config's confluence_score_min=2 / min_risk_reward_ratio=1.5
    # so cooldown/throttle-focused tests aren't accidentally tripped by
    # the newer confluence/RR filters -- tests that specifically exercise
    # those filters override these two params.
    return QuantSignal(
        ticker=ticker,
        signal_type=signal_type,
        direction=SignalDirection.BULLISH,
        message="test signal",
        price=100.0,
        volume_surge_ratio=volume_surge_ratio,
        confluence_score=confluence_score,
        risk_reward_ratio=risk_reward_ratio,
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


def _paper_trade_message(
    ticker: str = "AAPL", order_type: str = "SELL", realized_pnl_usd: float | None = -5.0
) -> dict:
    payload = {"ticker": ticker, "order_type": order_type, "realized_pnl_usd": realized_pnl_usd}
    return {"channel": b"talonx:paper:trades", "data": json.dumps(payload)}


def _exists_side_effect(on_cooldown: bool = False, locked_out: bool = False):
    async def _exists(key: str) -> bool:
        if key.startswith("cooldown:"):
            return on_cooldown
        if key.startswith("loss_lockout:"):
            return locked_out
        return False
    return _exists


@pytest.fixture
def scanner() -> QuantScanner:
    s = QuantScanner(QuantConfig())
    s._client = AsyncMock()
    s._client.exists.side_effect = _exists_side_effect()
    return s


# --- Channel routing ----------------------------------------------------

@pytest.mark.asyncio
async def test_handle_message_routes_market_channel_to_market_tick(scanner):
    scanner._handle_market_tick = AsyncMock()

    await scanner._handle_message(_bar_message("AAPL"))

    scanner._handle_market_tick.assert_awaited_once()
    assert scanner._handle_market_tick.await_args.args[0]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_handle_message_routes_paper_trades_channel_to_paper_trade(scanner):
    scanner._handle_paper_trade = AsyncMock()

    await scanner._handle_message(_paper_trade_message("AAPL"))

    scanner._handle_paper_trade.assert_awaited_once()
    assert scanner._handle_paper_trade.await_args.args[0]["ticker"] == "AAPL"


@pytest.mark.asyncio
async def test_handle_message_ignores_unexpected_channel(scanner):
    message = {"channel": b"talonx:something:else", "data": json.dumps({"foo": "bar"})}

    await scanner._handle_message(message)  # must not raise

    scanner._client.publish.assert_not_awaited()


# --- Post-loss lockout ---------------------------------------------------

@pytest.mark.asyncio
async def test_handle_paper_trade_starts_loss_lockout_on_losing_sell(scanner):
    await scanner._handle_paper_trade({"ticker": "SMCI", "order_type": "SELL", "realized_pnl_usd": -4.28})

    scanner._client.set.assert_awaited_once()
    args, kwargs = scanner._client.set.await_args
    assert args[0] == "loss_lockout:SMCI"
    assert kwargs["ex"] == int(scanner.config.loss_lockout_seconds)


@pytest.mark.asyncio
async def test_handle_paper_trade_ignores_winning_sell(scanner):
    await scanner._handle_paper_trade({"ticker": "AAPL", "order_type": "SELL", "realized_pnl_usd": 1.05})

    scanner._client.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_paper_trade_ignores_buy_orders(scanner):
    await scanner._handle_paper_trade({"ticker": "AAPL", "order_type": "BUY", "realized_pnl_usd": None})

    scanner._client.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_paper_trade_ignores_invalid_payload(scanner):
    await scanner._handle_paper_trade({"order_type": "SELL"})  # missing required ticker

    scanner._client.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_market_tick_suppresses_signals_when_locked_out(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: object())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config: [_signal("AAPL", 3.0)])
    scanner._client.exists.side_effect = _exists_side_effect(locked_out=True)

    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))

    scanner._client.publish.assert_not_awaited()
    scanner._client.set.assert_not_awaited()  # neither lock re-armed
    assert scanner.signals_suppressed_loss_lockout == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_is_loss_locked_out_treats_redis_error_as_not_locked_out(scanner):
    scanner._client.exists.side_effect = ConnectionError("redis down")

    assert await scanner._is_loss_locked_out("AAPL") is False


# --- Cooldown -------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_message_suppresses_signals_when_ticker_on_cooldown(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: object())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config: [_signal("AAPL", 3.0)])
    scanner._client.exists.side_effect = _exists_side_effect(on_cooldown=True)

    await scanner._handle_message(_bar_message("AAPL"))

    scanner._client.publish.assert_not_awaited()
    scanner._client.set.assert_not_awaited()  # cooldown not re-armed while already locked
    assert scanner.signals_suppressed_cooldown == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_starts_cooldown_and_buffers_candidate_when_not_on_cooldown(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: object())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config: [_signal("AAPL", 3.0)])

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


# --- Confluence / risk-reward filters (run before the cooldown lock) ------

@pytest.mark.asyncio
async def test_handle_message_suppresses_low_confluence_signal(scanner, monkeypatch):
    low_confluence = _signal("AAPL", 3.0, confluence_score=1)  # below confluence_score_min=2
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: object())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config: [low_confluence])

    await scanner._handle_message(_bar_message("AAPL"))

    scanner._client.set.assert_not_awaited()  # cooldown never armed for a filtered-out candidate
    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_suppressed_low_confluence == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_suppresses_low_risk_reward_signal(scanner, monkeypatch):
    low_rr = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=1.0)  # below min_risk_reward_ratio=1.5
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: object())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config: [low_rr])

    await scanner._handle_message(_bar_message("AAPL"))

    scanner._client.set.assert_not_awaited()
    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_suppressed_low_risk_reward == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_suppresses_signal_missing_risk_reward_ratio(scanner, monkeypatch):
    no_rr = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=None)  # ATR unavailable
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: object())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config: [no_rr])

    await scanner._handle_message(_bar_message("AAPL"))

    assert scanner.signals_suppressed_low_risk_reward == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_only_survivors_proceed_when_signals_are_mixed(scanner, monkeypatch):
    survivor = _signal("AAPL", 5.0, signal_type=SignalType.MACD_BULLISH_CROSS, confluence_score=3, risk_reward_ratio=2.0)
    filtered_by_rr = _signal("AAPL", 1.0, signal_type=SignalType.MA_GOLDEN_CROSS, confluence_score=3, risk_reward_ratio=0.5)
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: object())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config: [survivor, filtered_by_rr])

    await scanner._handle_message(_bar_message("AAPL"))

    # At least one signal survived, so the ticker's cooldown IS started
    # and only the survivor is queued.
    scanner._client.set.assert_awaited_once()
    assert len(scanner._pending_candidates) == 1
    assert scanner._pending_candidates[0].signal_type == SignalType.MACD_BULLISH_CROSS
    assert scanner.signals_suppressed_low_risk_reward == 1


# --- Batch throttle ----------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_throttle_window_releases_top_n_by_volume_surge_ratio(scanner):
    scanner.config = QuantConfig(throttle_max_signals=3)
    low = _signal("LOW", 1.5)
    mid = _signal("MID", 2.5)
    high = _signal("HIGH", 5.0)
    no_ratio = _signal("NORATIO", None)
    scanner._pending_candidates = [low, mid, no_ratio, high]  # 4 candidates, cap is 3; all tied on confluence

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
async def test_flush_throttle_window_ranks_confluence_before_volume_surge(scanner):
    scanner.config = QuantConfig(throttle_max_signals=1)
    low_confluence_high_volume = _signal("LOWCONF", 10.0, confluence_score=1)
    high_confluence_low_volume = _signal("HIGHCONF", 0.5, confluence_score=3)
    scanner._pending_candidates = [low_confluence_high_volume, high_confluence_low_volume]

    await scanner._flush_throttle_window()

    published_payloads = [call.args[1] for call in scanner._client.publish.await_args_list]
    assert scanner._client.publish.await_count == 1
    assert "HIGHCONF" in "".join(published_payloads)
    assert "LOWCONF" not in "".join(published_payloads)


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
        scanner._client.exists.side_effect = _exists_side_effect(on_cooldown=True)

        await scanner._handle_message(_bar_message("AAPL"))

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = store.suppression_counts_for_date(today)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["reason"] == "COOLDOWN"
    assert rows[0]["count"] == 1


@pytest.mark.asyncio
async def test_loss_lockout_suppression_is_recorded_when_a_store_is_set(tmp_path, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: object())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config: [_signal("SMCI", 3.0)])
    with QuantStateStore(tmp_path / "quant.db") as store:
        scanner = QuantScanner(QuantConfig(), store=store)
        scanner._client = AsyncMock()
        scanner._client.exists.side_effect = _exists_side_effect(locked_out=True)

        await scanner._handle_message(_bar_message("SMCI"))

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = store.suppression_counts_for_date(today)
    assert len(rows) == 1
    assert rows[0]["ticker"] == "SMCI"
    assert rows[0]["reason"] == "LOSS_LOCKOUT"
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
    scanner._client.exists.side_effect = _exists_side_effect(on_cooldown=True)

    # scanner fixture has store=None by default -- must not raise.
    await scanner._handle_message(_bar_message("AAPL"))
    assert scanner.signals_suppressed_cooldown == 1
