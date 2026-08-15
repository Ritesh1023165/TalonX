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
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from talonx_quant import consumer as consumer_module
from talonx_quant.config import QuantConfig
from talonx_quant.consumer import QuantScanner
from talonx_quant.schemas import (
    MarketTickEvent,
    QuantSignal,
    SignalDirection,
    SignalType,
    TickEventType,
    TickSource,
)
from talonx_quant.store import QuantStateStore


def _snapshot_stub() -> SimpleNamespace:
    """Stand-in for compute_indicators' real IndicatorSnapshot in the
    _handle_market_tick-level tests below -- carries the fields the
    min-volatility gate and entry-blackout gate read: atr/price well
    clear of QuantConfig's default min_atr_pct (0.25%), and bar_timestamp
    at 15:00 UTC (11:00 ET, matching _bar_message's fixed event
    timestamp) -- safely inside the regular active window, outside both
    the 09:30-09:45 and 15:30-16:00 ET blackouts, so neither gate trips
    in tests that aren't testing for it."""
    return SimpleNamespace(atr=10.0, price=100.0, bar_timestamp=datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc))


def _signal(
    ticker: str,
    volume_surge_ratio: float | None,
    signal_type=SignalType.MACD_BULLISH_CROSS,
    confluence_score: int | None = 3,
    risk_reward_ratio: float | None = 2.0,
    direction: SignalDirection = SignalDirection.BULLISH,
) -> QuantSignal:
    # Defaults (confluence_score=3, risk_reward_ratio=2.0) clear the
    # default config's confluence_score_min=2 / min_risk_reward_ratio=1.5
    # so cooldown/throttle-focused tests aren't accidentally tripped by
    # the newer confluence/RR filters -- tests that specifically exercise
    # those filters override these two params.
    return QuantSignal(
        ticker=ticker,
        signal_type=signal_type,
        direction=direction,
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


@pytest.fixture(autouse=True)
def _stub_preseed(monkeypatch):
    """Every test in this file is hermetic by default -- no test should
    make a real yfinance network call just because it happens to touch
    _load_buffers_from_store/_handle_market_tick/preseed_symbols. Tests
    that specifically exercise the pre-seed success path override these
    with their own monkeypatch."""
    monkeypatch.setattr(consumer_module.preseed, "fetch_1m_history", lambda symbol, period: [])
    monkeypatch.setattr(consumer_module.preseed, "fetch_15m_history", lambda symbol, period: [])


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
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)])
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
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)])
    scanner._client.exists.side_effect = _exists_side_effect(on_cooldown=True)

    await scanner._handle_message(_bar_message("AAPL"))

    scanner._client.publish.assert_not_awaited()
    scanner._client.set.assert_not_awaited()  # cooldown not re-armed while already locked
    assert scanner.signals_suppressed_cooldown == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_starts_cooldown_and_buffers_candidate_when_not_on_cooldown(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)])

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
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [low_confluence])

    await scanner._handle_message(_bar_message("AAPL"))

    scanner._client.set.assert_not_awaited()  # cooldown never armed for a filtered-out candidate
    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_suppressed_low_confluence == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_suppresses_low_risk_reward_signal(scanner, monkeypatch):
    low_rr = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=1.0)  # below min_risk_reward_ratio=1.5
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [low_rr])

    await scanner._handle_message(_bar_message("AAPL"))

    scanner._client.set.assert_not_awaited()
    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_suppressed_low_risk_reward == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_suppresses_signal_missing_risk_reward_ratio(scanner, monkeypatch):
    no_rr = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=None)  # ATR unavailable
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [no_rr])

    await scanner._handle_message(_bar_message("AAPL"))

    assert scanner.signals_suppressed_low_risk_reward == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_only_survivors_proceed_when_signals_are_mixed(scanner, monkeypatch):
    survivor = _signal("AAPL", 5.0, signal_type=SignalType.MACD_BULLISH_CROSS, confluence_score=3, risk_reward_ratio=2.0)
    filtered_by_rr = _signal("AAPL", 1.0, signal_type=SignalType.MA_GOLDEN_CROSS, confluence_score=3, risk_reward_ratio=0.5)
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [survivor, filtered_by_rr])

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
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)])
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
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [_signal("SMCI", 3.0)])
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


# --- Trend gate / pre-market liquidity / news-catalyst filters -----------

def _premarket_signal(ticker: str = "AAPL", **overrides) -> QuantSignal:
    kwargs = dict(
        signal_type=SignalType.MACD_BULLISH_CROSS, direction=SignalDirection.BULLISH,
        message="test", price=100.0, volume_surge_ratio=5.0, confluence_score=3,
        risk_reward_ratio=2.0, session="pre_market",
        bar_timestamp=datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc),
    )
    kwargs.update(overrides)
    return QuantSignal(ticker=ticker, **kwargs)


@pytest.mark.asyncio
async def test_handle_message_suppresses_signal_failing_trend_gate(scanner, monkeypatch):
    below_trend = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=2.0)
    below_trend.trend_aligned = False  # pydantic model, plain attribute assignment
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [below_trend],
    )

    await scanner._handle_message(_bar_message("AAPL"))

    scanner._client.set.assert_not_awaited()
    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_suppressed_trend_gate == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_passes_signal_with_trend_aligned_true(scanner, monkeypatch):
    aligned = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=2.0)
    aligned.trend_aligned = True
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [aligned],
    )

    await scanner._handle_message(_bar_message("AAPL"))

    assert len(scanner._pending_candidates) == 1


@pytest.mark.asyncio
async def test_handle_message_suppresses_premarket_signal_without_liquidity_data(scanner, monkeypatch):
    # session="pre_market", no buffered bars and no cached quote --
    # fail-closed: dollar volume and spread can't be confirmed.
    candidate = _premarket_signal()
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )

    await scanner._handle_message(_bar_message("AAPL"))

    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_suppressed_premarket_liquidity == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_passes_premarket_signal_when_liquidity_and_news_clear(scanner, monkeypatch):
    candidate = _premarket_signal()
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )
    monkeypatch.setattr(scanner, "_clears_premarket_liquidity", lambda s: True)
    scanner._last_news_seen["AAPL"] = datetime.now(timezone.utc)

    await scanner._handle_message(_bar_message("AAPL"))

    assert scanner.signals_suppressed_premarket_liquidity == 0
    assert scanner.signals_suppressed_news_catalyst == 0
    assert len(scanner._pending_candidates) == 1


@pytest.mark.asyncio
async def test_handle_message_suppresses_premarket_signal_without_recent_news(scanner, monkeypatch):
    candidate = _premarket_signal()
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )
    monkeypatch.setattr(scanner, "_clears_premarket_liquidity", lambda s: True)
    # No entry in _last_news_seen at all -- fail-closed.

    await scanner._handle_message(_bar_message("AAPL"))

    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_suppressed_news_catalyst == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_suppresses_premarket_signal_with_stale_news(scanner, monkeypatch):
    from datetime import timedelta
    candidate = _premarket_signal()
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )
    monkeypatch.setattr(scanner, "_clears_premarket_liquidity", lambda s: True)
    scanner._last_news_seen["AAPL"] = datetime.now(timezone.utc) - timedelta(hours=5)  # > 4h lookback

    await scanner._handle_message(_bar_message("AAPL"))

    assert scanner.signals_suppressed_news_catalyst == 1


@pytest.mark.asyncio
async def test_regular_session_signal_is_not_subject_to_premarket_gates(scanner, monkeypatch):
    # session="regular" (the default _signal() bar_timestamp is 15:00 UTC
    # = 11:00 ET) -- no quote/news cached at all, must still pass.
    candidate = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=2.0)
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )

    await scanner._handle_message(_bar_message("AAPL"))

    assert scanner.signals_suppressed_premarket_liquidity == 0
    assert scanner.signals_suppressed_news_catalyst == 0
    assert len(scanner._pending_candidates) == 1


# --- QUOTE event handling (spread cache, no OHLCV buffer impact) ---------

@pytest.mark.asyncio
async def test_quote_event_updates_latest_quote_cache_without_touching_bar_buffer(scanner):
    payload = {
        "event_type": "quote", "symbol": "AAPL", "source": "websocket",
        "timestamp": "2026-08-07T08:00:00Z", "bid": 99.9, "ask": 100.1,
    }
    message = {"channel": b"talonx:market:stream", "data": json.dumps(payload)}

    await scanner._handle_message(message)

    assert "AAPL" in scanner._latest_quotes
    bid, ask, _ = scanner._latest_quotes["AAPL"]
    assert bid == pytest.approx(99.9)
    assert ask == pytest.approx(100.1)
    assert scanner.buffer.get_dataframe("AAPL") is None  # QUOTE never feeds the OHLCV buffer


@pytest.mark.asyncio
async def test_news_event_updates_last_seen_and_keeps_the_most_recent(scanner):
    older = {"ticker": "AAPL", "published_at": "2026-08-07T05:00:00Z"}
    newer = {"ticker": "AAPL", "published_at": "2026-08-07T07:00:00Z"}

    await scanner._handle_message({"channel": b"talonx:news:events", "data": json.dumps(newer)})
    await scanner._handle_message({"channel": b"talonx:news:events", "data": json.dumps(older)})

    assert scanner._last_news_seen["AAPL"] == datetime(2026, 8, 7, 7, 0, tzinfo=timezone.utc)


# --- Stage-Gate Metric Funnel (_incr_metric) ------------------------------

@pytest.mark.asyncio
async def test_incr_metric_uses_date_bucketed_key_and_sets_ttl_on_first_write():
    client = AsyncMock()
    client.incrby.return_value = 3  # first write this key -- new_value == amount

    await consumer_module._incr_metric(client, "quant", "published", amount=3)

    key = client.incrby.await_args.args[0]
    assert key.startswith("metrics:")
    assert key.endswith(":quant:published")
    client.expire.assert_awaited_once_with(key, 2764800)


@pytest.mark.asyncio
async def test_incr_metric_does_not_reset_ttl_on_subsequent_writes():
    client = AsyncMock()
    client.incrby.return_value = 7  # not the first write (new_value != amount)

    await consumer_module._incr_metric(client, "quant", "published", amount=1)

    client.expire.assert_not_awaited()


@pytest.mark.asyncio
async def test_incr_metric_is_a_noop_with_no_client_or_zero_amount():
    await consumer_module._incr_metric(None, "quant", "published", amount=1)  # must not raise
    client = AsyncMock()
    await consumer_module._incr_metric(client, "quant", "published", amount=0)
    client.incrby.assert_not_awaited()


@pytest.mark.asyncio
async def test_incr_metric_swallows_redis_errors():
    client = AsyncMock()
    client.incrby.side_effect = ConnectionError("redis down")

    await consumer_module._incr_metric(client, "quant", "published", amount=1)  # must not raise


# --- Buffer persistence (_checkpoint_all_buffers / _load_buffers_from_store) --

@pytest.mark.asyncio
async def test_checkpoint_all_buffers_writes_both_buffers_to_the_store(tmp_path):
    with QuantStateStore(tmp_path / "quant.db") as store:
        scanner = QuantScanner(QuantConfig(), store=store)
        scanner.buffer.add_bar("AAPL", datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc), 100.0, 101.0, 99.0, 100.5, 1000.0)
        scanner.buffer_htf.add_bar("AAPL", datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc), 100.0, 101.0, 99.0, 100.5, 1000.0)

        scanner._checkpoint_all_buffers()

        assert len(store.load_buffer("AAPL", "1m")) == 1
        assert len(store.load_buffer("AAPL", "15m")) == 1


def test_checkpoint_all_buffers_is_a_noop_with_no_store():
    scanner = QuantScanner(QuantConfig(), store=None)
    scanner.buffer.add_bar("AAPL", datetime.now(timezone.utc), 100.0, 101.0, 99.0, 100.5, 1000.0)

    scanner._checkpoint_all_buffers()  # must not raise


@pytest.mark.asyncio
async def test_load_buffers_from_store_reloads_a_recent_1m_checkpoint(tmp_path):
    now = datetime.now(timezone.utc)
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.checkpoint_buffer("AAPL", "1m", [
            {"timestamp": now - timedelta(minutes=2), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0},
        ])
        scanner = QuantScanner(
            QuantConfig(buffer_reload_max_gap_seconds=900.0, historical_preseed_enabled=False), store=store,
        )

        await scanner._load_buffers_from_store()

        assert scanner.buffer.bar_count("AAPL") == 1


@pytest.mark.asyncio
async def test_load_buffers_from_store_skips_a_stale_1m_checkpoint(tmp_path):
    now = datetime.now(timezone.utc)
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.checkpoint_buffer("AAPL", "1m", [
            {"timestamp": now - timedelta(hours=10), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0},
        ])
        scanner = QuantScanner(
            QuantConfig(buffer_reload_max_gap_seconds=900.0, historical_preseed_enabled=False), store=store,
        )

        await scanner._load_buffers_from_store()

        assert scanner.buffer.bar_count("AAPL") == 0  # too old -- discarded, not reloaded


@pytest.mark.asyncio
async def test_load_buffers_from_store_stale_1m_checkpoint_triggers_preseed(tmp_path, monkeypatch):
    """Requirement 4: a discarded (too-stale) 1-min checkpoint falls
    through to historical pre-seeding via yfinance rather than leaving
    the symbol to re-warm-up purely from live ticks."""
    now = datetime.now(timezone.utc)
    seed_bars = [
        {"timestamp": now - timedelta(minutes=i), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
         "volume": 1.0, "session": "regular"}
        for i in range(5)
    ]
    monkeypatch.setattr(consumer_module.preseed, "fetch_1m_history", lambda symbol, period: seed_bars)
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.checkpoint_buffer("AAPL", "1m", [
            {"timestamp": now - timedelta(hours=10), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0},
        ])
        scanner = QuantScanner(QuantConfig(buffer_reload_max_gap_seconds=900.0, min_bars_required=5), store=store)

        await scanner._load_buffers_from_store()

        assert scanner.buffer.bar_count("AAPL") == 5


@pytest.mark.asyncio
async def test_load_buffers_from_store_reloads_stale_15m_checkpoint_regardless_of_gap(tmp_path):
    """The HTF buffer has no gap gate -- surviving an overnight/multi-day
    gap is the whole point (200 bars needs ~50 continuous hours to warm
    up, which a daily restart could never accumulate otherwise)."""
    now = datetime.now(timezone.utc)
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.checkpoint_buffer("AAPL", "15m", [
            {"timestamp": now - timedelta(days=3), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0},
        ])
        scanner = QuantScanner(
            QuantConfig(buffer_reload_max_gap_seconds=900.0, historical_preseed_enabled=False), store=store,
        )

        await scanner._load_buffers_from_store()

        assert scanner.buffer_htf.bar_count("AAPL") == 1


@pytest.mark.asyncio
async def test_load_buffers_from_store_backfills_15m_checkpoint_older_than_backfill_gap(tmp_path, monkeypatch):
    """Requirement 4: on top of the unconditional reload, a 15-min
    checkpoint whose newest bar is older than htf_backfill_gap_seconds
    (e.g. after a weekend) also triggers a yfinance backfill."""
    now = datetime.now(timezone.utc)
    fresh_bars = [
        {"timestamp": now - timedelta(minutes=15 * i), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
         "volume": 1.0, "session": "regular"}
        for i in range(3)
    ]
    monkeypatch.setattr(consumer_module.preseed, "fetch_15m_history", lambda symbol, period: fresh_bars)
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.checkpoint_buffer("AAPL", "15m", [
            {"timestamp": now - timedelta(days=3), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0},
        ])
        scanner = QuantScanner(
            QuantConfig(buffer_reload_max_gap_seconds=900.0, htf_backfill_gap_seconds=86400.0), store=store,
        )

        await scanner._load_buffers_from_store()

        # 1 reloaded bar (unconditional reload) + 3 backfilled bars.
        assert scanner.buffer_htf.bar_count("AAPL") == 4


@pytest.mark.asyncio
async def test_load_buffers_from_store_is_a_noop_with_no_store():
    scanner = QuantScanner(QuantConfig(), store=None)

    await scanner._load_buffers_from_store()  # must not raise

    assert scanner.buffer.known_symbols() == []


@pytest.mark.asyncio
async def test_load_buffers_from_store_handles_multiple_symbols_independently(tmp_path):
    now = datetime.now(timezone.utc)
    with QuantStateStore(tmp_path / "quant.db") as store:
        store.checkpoint_buffer("AAPL", "1m", [
            {"timestamp": now - timedelta(minutes=1), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
        ])
        store.checkpoint_buffer("MSFT", "1m", [
            {"timestamp": now - timedelta(hours=5), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
        ])
        scanner = QuantScanner(
            QuantConfig(buffer_reload_max_gap_seconds=900.0, historical_preseed_enabled=False), store=store,
        )

        await scanner._load_buffers_from_store()

        assert scanner.buffer.bar_count("AAPL") == 1  # fresh -- reloaded
        assert scanner.buffer.bar_count("MSFT") == 0  # stale -- skipped


@pytest.mark.asyncio
async def test_no_store_means_no_persistence_attempted(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)])
    scanner._client.exists.side_effect = _exists_side_effect(on_cooldown=True)

    # scanner fixture has store=None by default -- must not raise.
    await scanner._handle_message(_bar_message("AAPL"))
    assert scanner.signals_suppressed_cooldown == 1


# --- True Calendar-Aligned 1-Minute Candle Aggregation (Requirement 1) ----

def _bar_event(symbol: str, timestamp: datetime, close: float, volume: float = 100.0) -> MarketTickEvent:
    # open/high/low deliberately set to values FAR from `close` -- the
    # yfinance polling fallback's fast_info-derived open/day_high/day_low
    # are DAY-level, not minute-level, so _update_1m_buffer must ignore
    # them and build the candle purely from each tick's own price.
    return MarketTickEvent(
        event_type=TickEventType.BAR, symbol=symbol, source=TickSource.POLLING,
        timestamp=timestamp, open=9999.0, high=9999.0, low=1.0, close=close, volume=volume,
    )


def test_update_1m_buffer_merges_ticks_within_the_same_minute(scanner):
    base = datetime(2026, 8, 14, 15, 0, 5, tzinfo=timezone.utc)
    scanner._update_1m_buffer(_bar_event("AAPL", base, close=100.0, volume=10.0))
    scanner._update_1m_buffer(_bar_event("AAPL", base + timedelta(seconds=40), close=101.5, volume=20.0))

    assert scanner.buffer.bar_count("AAPL") == 1
    bar = scanner.buffer.get_bars("AAPL")[0]
    assert bar["open"] == 100.0  # first tick's price this minute
    assert bar["high"] == 101.5
    assert bar["low"] == 100.0
    assert bar["close"] == 101.5  # latest tick's price
    assert bar["volume"] == 30.0  # accumulated


def test_update_1m_buffer_ignores_the_events_own_ohlc_fields(scanner):
    # _bar_event sets open=9999/high=9999/low=1 -- none of that should
    # leak into the aggregated candle, only `close` (the tick's price).
    ts = datetime(2026, 8, 14, 15, 0, 5, tzinfo=timezone.utc)
    scanner._update_1m_buffer(_bar_event("AAPL", ts, close=100.0))

    bar = scanner.buffer.get_bars("AAPL")[0]
    assert bar["open"] == 100.0
    assert bar["high"] == 100.0
    assert bar["low"] == 100.0


def test_update_1m_buffer_finalizes_a_new_row_only_when_the_minute_rolls_over(scanner):
    base = datetime(2026, 8, 14, 15, 0, 5, tzinfo=timezone.utc)
    scanner._update_1m_buffer(_bar_event("AAPL", base, close=100.0))
    scanner._update_1m_buffer(_bar_event("AAPL", base + timedelta(seconds=40), close=101.0))
    scanner._update_1m_buffer(_bar_event("AAPL", base + timedelta(minutes=1), close=102.0))

    bars = scanner.buffer.get_bars("AAPL")
    assert len(bars) == 2  # only the minute boundary crossing added a new row
    assert bars[0]["close"] == 101.0  # locked in once the first minute closed out
    assert bars[1]["open"] == 102.0
    assert bars[1]["close"] == 102.0


def test_update_1m_buffer_drops_a_tick_with_no_close(scanner):
    ts = datetime(2026, 8, 14, 15, 0, 5, tzinfo=timezone.utc)
    event = MarketTickEvent(
        event_type=TickEventType.BAR, symbol="AAPL", source=TickSource.POLLING,
        timestamp=ts, close=None,
    )

    scanner._update_1m_buffer(event)  # must not raise

    assert scanner.buffer.bar_count("AAPL") == 0


@pytest.mark.asyncio
async def test_handle_market_tick_computes_indicators_on_every_tick_including_partial_bars(scanner, monkeypatch):
    """Every tick still triggers indicator computation/signal evaluation
    (the currently-forming minute's evolving price must be visible
    immediately) -- this is what keeps single-tick tests elsewhere in
    this file working unchanged despite the new aggregation layer."""
    calls = []
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: calls.append(1) or None)

    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))

    assert len(calls) == 1


# --- Session-aware HTF buffer (Requirement 3: RTH-only 200-SMA source) ---

def _htf_bar_event(symbol: str, timestamp: datetime, close: float) -> MarketTickEvent:
    return MarketTickEvent(
        event_type=TickEventType.BAR, symbol=symbol, source=TickSource.POLLING,
        timestamp=timestamp, open=close, high=close, low=close, close=close, volume=100.0,
    )


def test_update_htf_buffer_excludes_pre_market_bucket_when_rth_only_enabled():
    scanner = QuantScanner(QuantConfig(rth_only_htf_sma=True))
    # 09:00 UTC = 05:00 ET -- pre-market. Two ticks in this 15-min bucket,
    # then one in the NEXT bucket to trigger finalization of the first.
    bucket = datetime(2026, 8, 14, 9, 0, 0, tzinfo=timezone.utc)
    scanner._update_htf_buffer(_htf_bar_event("AAPL", bucket, 100.0))
    scanner._update_htf_buffer(_htf_bar_event("AAPL", bucket + timedelta(minutes=15), 101.0))

    assert scanner.buffer_htf.bar_count("AAPL") == 0  # the pre-market bucket was never finalized in


def test_update_htf_buffer_includes_regular_session_bucket():
    scanner = QuantScanner(QuantConfig(rth_only_htf_sma=True))
    # 14:00 UTC = 10:00 ET -- regular session.
    bucket = datetime(2026, 8, 14, 14, 0, 0, tzinfo=timezone.utc)
    scanner._update_htf_buffer(_htf_bar_event("AAPL", bucket, 100.0))
    scanner._update_htf_buffer(_htf_bar_event("AAPL", bucket + timedelta(minutes=15), 101.0))

    assert scanner.buffer_htf.bar_count("AAPL") == 1


def test_update_htf_buffer_includes_pre_market_when_rth_only_disabled():
    scanner = QuantScanner(QuantConfig(rth_only_htf_sma=False))
    bucket = datetime(2026, 8, 14, 9, 0, 0, tzinfo=timezone.utc)
    scanner._update_htf_buffer(_htf_bar_event("AAPL", bucket, 100.0))
    scanner._update_htf_buffer(_htf_bar_event("AAPL", bucket + timedelta(minutes=15), 101.0))

    assert scanner.buffer_htf.bar_count("AAPL") == 1


# --- Historical pre-seeding (Requirement 2) -------------------------------

def _seed_bar(minutes_ago: int, session: str = "regular") -> dict:
    now = datetime.now(timezone.utc)
    return {
        "timestamp": now - timedelta(minutes=minutes_ago), "open": 100.0, "high": 101.0,
        "low": 99.0, "close": 100.5, "volume": 1000.0, "session": session,
    }


@pytest.mark.asyncio
async def test_preseed_1m_if_needed_populates_buffer_from_yfinance(scanner, monkeypatch):
    bars = [_seed_bar(i) for i in range(150, 0, -1)]
    monkeypatch.setattr(consumer_module.preseed, "fetch_1m_history", lambda symbol, period: bars)

    await scanner._preseed_1m_if_needed("AAPL")

    assert scanner.buffer.bar_count("AAPL") == scanner.config.min_bars_required  # capped to the threshold


@pytest.mark.asyncio
async def test_preseed_1m_if_needed_skips_when_already_above_threshold(scanner, monkeypatch):
    monkeypatch.setattr(
        consumer_module.preseed, "fetch_1m_history", lambda symbol, period: pytest.fail("should not be called"),
    )
    for i in range(scanner.config.min_bars_required):
        scanner.buffer.add_bar("AAPL", datetime.now(timezone.utc) - timedelta(minutes=i), 1.0, 1.0, 1.0, 1.0, 1.0)

    await scanner._preseed_1m_if_needed("AAPL")  # must not call fetch_1m_history at all


@pytest.mark.asyncio
async def test_preseed_1m_if_needed_only_attempts_once_per_symbol(scanner, monkeypatch):
    call_count = {"n": 0}

    def _fetch(symbol, period):
        call_count["n"] += 1
        return []

    monkeypatch.setattr(consumer_module.preseed, "fetch_1m_history", _fetch)

    await scanner._preseed_1m_if_needed("AAPL")
    await scanner._preseed_1m_if_needed("AAPL")

    assert call_count["n"] == 1


@pytest.mark.asyncio
async def test_preseed_1m_if_needed_is_disabled_by_config(scanner, monkeypatch):
    scanner.config = QuantConfig(historical_preseed_enabled=False)
    monkeypatch.setattr(
        consumer_module.preseed, "fetch_1m_history", lambda symbol, period: pytest.fail("should not be called"),
    )

    await scanner._preseed_1m_if_needed("AAPL")  # must not call fetch_1m_history at all


@pytest.mark.asyncio
async def test_preseed_1m_if_needed_falls_back_soft_on_fetch_failure(scanner, monkeypatch):
    def _boom(symbol, period):
        raise RuntimeError("yfinance rate limited")

    monkeypatch.setattr(consumer_module.preseed, "fetch_1m_history", _boom)

    await scanner._preseed_1m_if_needed("AAPL")  # must not raise

    assert scanner.buffer.bar_count("AAPL") == 0


@pytest.mark.asyncio
async def test_preseed_htf_if_needed_filters_to_regular_session_bars_by_default(scanner, monkeypatch):
    mixed = [_seed_bar(i, session="pre_market") for i in range(10)] + [
        _seed_bar(i, session="regular") for i in range(210, 10, -1)
    ]
    monkeypatch.setattr(consumer_module.preseed, "fetch_15m_history", lambda symbol, period: mixed)

    await scanner._preseed_htf_if_needed("AAPL")

    bars = scanner.buffer_htf.get_bars("AAPL")
    assert bars  # something loaded
    assert all(b["session"] == "regular" for b in bars)


@pytest.mark.asyncio
async def test_preseed_htf_if_needed_keeps_pre_market_bars_when_rth_only_disabled(monkeypatch):
    scanner = QuantScanner(QuantConfig(rth_only_htf_sma=False))
    bars = [_seed_bar(i, session="pre_market") for i in range(5)]
    monkeypatch.setattr(consumer_module.preseed, "fetch_15m_history", lambda symbol, period: bars)

    await scanner._preseed_htf_if_needed("AAPL")

    assert scanner.buffer_htf.bar_count("AAPL") == 5


@pytest.mark.asyncio
async def test_preseed_htf_if_needed_force_bypasses_the_threshold_check(scanner, monkeypatch):
    for i in range(scanner.config.htf_sma_period):
        scanner.buffer_htf.add_bar(
            "AAPL", datetime.now(timezone.utc) - timedelta(minutes=15 * i), 1.0, 1.0, 1.0, 1.0, 1.0, session="regular",
        )
    call_count = {"n": 0}

    def _fetch(symbol, period):
        call_count["n"] += 1
        return []

    monkeypatch.setattr(consumer_module.preseed, "fetch_15m_history", _fetch)

    await scanner._preseed_htf_if_needed("AAPL", force=True)

    assert call_count["n"] == 1  # fetched despite already being at/above threshold


@pytest.mark.asyncio
async def test_preseed_checkpoints_immediately_when_a_store_is_set(tmp_path, monkeypatch):
    bars = [_seed_bar(i) for i in range(10, 0, -1)]
    monkeypatch.setattr(consumer_module.preseed, "fetch_1m_history", lambda symbol, period: bars)
    with QuantStateStore(tmp_path / "quant.db") as store:
        scanner = QuantScanner(QuantConfig(), store=store)  # 10 fetched bars stay well under min_bars_required=120

        await scanner._preseed_1m_if_needed("AAPL")

        # Doesn't wait for the periodic 60s checkpoint loop -- the whole
        # point is the ticker_funnel_report reads a checkpoint that's
        # already ready shortly after boot, not up to a minute later.
        assert len(store.load_buffer("AAPL", "1m")) == 10


@pytest.mark.asyncio
async def test_preseed_symbols_seeds_both_buffers_for_every_symbol(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module.preseed, "fetch_1m_history", lambda symbol, period: [_seed_bar(1)])
    monkeypatch.setattr(consumer_module.preseed, "fetch_15m_history", lambda symbol, period: [_seed_bar(1)])

    await scanner.preseed_symbols(["aapl", "msft"])

    assert scanner.buffer.bar_count("AAPL") == 1
    assert scanner.buffer.bar_count("MSFT") == 1
    assert scanner.buffer_htf.bar_count("AAPL") == 1
    assert scanner.buffer_htf.bar_count("MSFT") == 1


# --- Minimum volatility gate (_fails_min_volatility) -----------------------

def test_fails_min_volatility_true_below_threshold():
    # ATR 0.20 on a $100 stock = 0.20% ATR, below the default 0.25% floor.
    snapshot = SimpleNamespace(atr=0.20, price=100.0)
    assert consumer_module._fails_min_volatility(snapshot, QuantConfig()) is True


def test_fails_min_volatility_false_above_threshold():
    # ATR 2.00 on a $100 stock = 2.00% ATR, well clear of the floor.
    snapshot = SimpleNamespace(atr=2.0, price=100.0)
    assert consumer_module._fails_min_volatility(snapshot, QuantConfig()) is False


def test_fails_min_volatility_does_not_fail_closed_on_missing_atr():
    # Warm-up (ATR not yet available) must NOT trip this gate -- every
    # RSI/MACD/MA check downstream already requires ATR, so an unwarmed
    # symbol produces zero signals regardless of this gate's answer.
    snapshot = SimpleNamespace(atr=None, price=100.0)
    assert consumer_module._fails_min_volatility(snapshot, QuantConfig()) is False


@pytest.mark.asyncio
async def test_handle_market_tick_suppresses_low_volatility_bar_before_evaluating(scanner, monkeypatch):
    low_vol_snapshot = SimpleNamespace(
        atr=0.10, price=100.0, bar_timestamp=datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: low_vol_snapshot)
    evaluate_called = {"n": 0}

    def _evaluate(ticker, snap, config, **kwargs):
        evaluate_called["n"] += 1
        return [_signal("AAPL", 3.0)]

    monkeypatch.setattr(consumer_module, "evaluate_signals", _evaluate)

    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))

    # Gated BEFORE evaluate_signals is even called (skips momentum
    # evaluation entirely for a low-beta bar), and nothing published.
    assert evaluate_called["n"] == 0
    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_suppressed_low_volatility == 1


# --- Entry blackout gate (get_entry_blackout) -------------------------------

@pytest.mark.asyncio
async def test_handle_market_tick_suppresses_all_signals_during_opening_blackout(scanner, monkeypatch):
    # 09:35 ET = 13:35 UTC -- inside the 09:30-09:45 opening blackout.
    opening_snapshot = SimpleNamespace(
        atr=10.0, price=100.0, bar_timestamp=datetime(2026, 8, 7, 13, 35, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: opening_snapshot)
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [
            _signal("AAPL", 3.0, direction=SignalDirection.BULLISH),
            _signal("AAPL", 3.0, direction=SignalDirection.BEARISH),
        ],
    )

    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))

    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_suppressed_opening_blackout == 2


@pytest.mark.asyncio
async def test_handle_market_tick_closing_blackout_drops_bullish_keeps_bearish(scanner, monkeypatch):
    # 15:45 ET = 19:45 UTC -- inside the 15:30-16:00 closing blackout.
    closing_snapshot = SimpleNamespace(
        atr=10.0, price=100.0, bar_timestamp=datetime(2026, 8, 7, 19, 45, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: closing_snapshot)
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [
            _signal("AAPL", 3.0, direction=SignalDirection.BULLISH),
            _signal("AAPL", 3.0, direction=SignalDirection.BEARISH),
        ],
    )

    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))

    # The BULLISH candidate is dropped, but the BEARISH one survives this
    # gate and proceeds into the rest of the pipeline (cooldown, etc.) --
    # an open position should still be able to exit before EOD-flatten.
    assert scanner.signals_suppressed_closing_blackout == 1
    scanner._client.set.assert_awaited()  # cooldown started for the surviving BEARISH candidate


@pytest.mark.asyncio
async def test_handle_market_tick_no_blackout_during_active_session(scanner, monkeypatch):
    # 11:00 ET = 15:00 UTC -- deep in the active window, outside both
    # blackout sub-windows.
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)],
    )

    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))

    assert scanner.signals_suppressed_opening_blackout == 0
    assert scanner.signals_suppressed_closing_blackout == 0
