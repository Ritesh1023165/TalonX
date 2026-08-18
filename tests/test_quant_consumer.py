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
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from talonx_quant import consumer as consumer_module
from talonx_quant.config import QuantConfig
from talonx_quant.consumer import QuantScanner, _opportunity_score
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
    #
    # atr/pivot_resistance/pivot_support default to a valid, internally-
    # consistent geometry (same values _revalidatable_signal below uses)
    # so a candidate built here can actually clear Final Revalidation
    # Data Availability (2026-08-16 quant audit, round 4) in a
    # _flush_throttle_window-level test -- that still additionally
    # requires the ticker have a buffered close price (see _seed_close)
    # for _revalidate_candidate's `current_price` to resolve.
    return QuantSignal(
        ticker=ticker,
        signal_type=signal_type,
        direction=direction,
        message="test signal",
        price=100.0,
        volume_surge_ratio=volume_surge_ratio,
        confluence_score=confluence_score,
        risk_reward_ratio=risk_reward_ratio,
        atr=2.0,
        pivot_resistance=110.0,
        pivot_support=90.0,
        bar_timestamp=datetime(2026, 8, 7, 15, 0, tzinfo=timezone.utc),
    )


def _channel_publishes(scanner, channel: str) -> list:
    """Filters scanner._client.publish's recorded calls down to just the
    given channel -- since Rejection Trace Logging (req 7), the same
    mocked `publish` now ALSO receives one call per rejected candidate on
    config.rejected_candidates_channel, so a bare `publish.assert_not_awaited()`
    or a blanket await_count check on the signals_channel no longer holds;
    tests need to distinguish which channel a given publish call targeted."""
    return [call.args[1] for call in scanner._client.publish.await_args_list if call.args[0] == channel]


def _signal_publishes(scanner) -> list:
    return _channel_publishes(scanner, scanner.config.signals_channel)


def _rejection_publishes(scanner) -> list:
    return _channel_publishes(scanner, scanner.config.rejected_candidates_channel)


def _lock_set_calls(scanner, prefix: str) -> list:
    """Filters scanner._client.set's recorded calls down to keys starting
    with `prefix` -- since Bar-Level Ingestion Idempotency (2026-08-16
    quant audit), the SAME mocked `set` now ALSO receives one call per
    BAR tick for the dedup key (`processed_bar:...`), so a bare
    `set.assert_not_awaited()`/`assert_awaited_once()` no longer isolates
    cooldown/loss-lockout arming specifically."""
    return [call for call in scanner._client.set.await_args_list if call.args[0].startswith(prefix)]


def _cooldown_set_calls(scanner) -> list:
    return _lock_set_calls(scanner, "cooldown:")


def _lockout_set_calls(scanner) -> list:
    return _lock_set_calls(scanner, "loss_lockout:")


def _bar_message(symbol: str = "AAPL") -> dict:
    payload = {
        "event_type": "bar",
        "symbol": symbol,
        "source": "polling",
        "timestamp": "2026-08-07T15:00:00Z",
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0,
    }
    return {"channel": b"talonx:market:stream", "data": json.dumps(payload)}


def _priming_bar_payload(symbol: str = "AAPL") -> dict:
    """Closed-Bar Evaluation (2026-08-16 quant audit): _handle_market_tick
    now only evaluates indicators/signals on a bar's FIRST tick after it
    closes -- the previous minute's bucket, i.e. a SECOND tick in a NEW
    bucket for the same symbol. This is the priming (first) tick, one
    minute before _bar_message's fixed timestamp, so a subsequent
    _bar_message delivery is recognized as closing the bucket THIS tick
    opens. compute_indicators/evaluate_signals are never reached by this
    priming call alone (bar_just_closed is False on a symbol's very
    first tick), so it's safe to send even when those are monkeypatched
    for the real, following call."""
    return {
        "event_type": "bar", "symbol": symbol, "source": "polling",
        "timestamp": "2026-08-07T14:59:00Z", "close": 100.0, "volume": 500.0,
    }


def _priming_bar_message(symbol: str = "AAPL") -> dict:
    return {"channel": b"talonx:market:stream", "data": json.dumps(_priming_bar_payload(symbol))}


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


@pytest.fixture(autouse=True)
def _stub_uk_operating_window_open(monkeypatch):
    """UK Operating Window (2026-08-16 quant audit, round 5): consumer.py
    gates on is_operating_window_open() called with NO argument -- i.e.
    the REAL current wall-clock instant, by design (see that function's
    own docstring: it must reflect "right now," never a fixed bar
    timestamp). Left un-stubbed, every test in this file that reaches
    that gate would non-deterministically pass or fail depending on
    whatever the ACTUAL time happens to be when the suite runs (e.g.
    failing outright if run at 2am UK time or on a weekend). Defaults
    every test in this file to "the window is open" so existing
    session-agnostic tests stay deterministic; the small number of tests
    that specifically exercise the UK-session-closed gate override this
    locally with their own monkeypatch."""
    monkeypatch.setattr(consumer_module, "is_operating_window_open", lambda *args, **kwargs: True)


@pytest.fixture
def scanner() -> QuantScanner:
    s = QuantScanner(QuantConfig())
    s._client = AsyncMock()
    s._client.exists.side_effect = _exists_side_effect()
    return s


@pytest.fixture
def config() -> QuantConfig:
    return QuantConfig()


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

    await scanner._handle_market_tick(_priming_bar_payload("AAPL"))
    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))

    assert _signal_publishes(scanner) == []
    assert _cooldown_set_calls(scanner) == []
    assert _lockout_set_calls(scanner) == []  # neither lock re-armed
    assert scanner.signals_suppressed_loss_lockout == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_is_loss_locked_out_fails_closed_on_redis_error_by_default(scanner):
    """Fail-Closed Risk Management (2026-08-16 quant audit): a Redis
    error means this process can't actually confirm the ticker is safe
    to trade -- default policy is to treat that as BLOCKED, not clear."""
    scanner._client.exists.side_effect = ConnectionError("redis down")

    assert await scanner._is_loss_locked_out("AAPL") is True


@pytest.mark.asyncio
async def test_is_loss_locked_out_fails_open_when_explicitly_configured(scanner):
    scanner.config = replace(scanner.config, risk_check_fail_closed=False)
    scanner._client.exists.side_effect = ConnectionError("redis down")

    assert await scanner._is_loss_locked_out("AAPL") is False


@pytest.mark.asyncio
async def test_risk_check_failure_records_a_rejection_when_failing_closed(scanner, tmp_path):
    scanner.store = QuantStateStore(tmp_path / "quant.db")
    scanner._client.exists.side_effect = ConnectionError("redis down")

    await scanner._is_loss_locked_out("AAPL")

    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "RISK_STORE_UNAVAILABLE_FAIL_CLOSED"
    assert rejections[0]["gate"] == "risk_store_gate"


@pytest.mark.asyncio
async def test_risk_check_failure_does_not_record_a_rejection_when_failing_open(scanner):
    scanner.config = replace(scanner.config, risk_check_fail_closed=False)
    scanner._client.exists.side_effect = ConnectionError("redis down")

    await scanner._is_loss_locked_out("AAPL")

    assert _rejection_publishes(scanner) == []


# --- Fail-Closed Lock Persistence (2026-08-16 quant audit, round 3) -------
# A Redis SET failure while ARMING loss-lockout/cooldown (as opposed to a
# failure CHECKING one, covered above) used to only log a warning and let
# the lock silently never take effect -- these cover the in-memory
# fallback lock that now enforces it instead.

@pytest.mark.asyncio
async def test_start_loss_lockout_falls_back_to_in_memory_lock_on_redis_set_failure(scanner):
    scanner._client.set.side_effect = ConnectionError("redis down")

    await scanner._start_loss_lockout("AAPL")

    assert await scanner._is_loss_locked_out("AAPL") is True


@pytest.mark.asyncio
async def test_is_loss_locked_out_ignores_expired_in_memory_fallback_lock(scanner):
    scanner._loss_lockout_fallback["AAPL"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    assert await scanner._is_loss_locked_out("AAPL") is False
    assert "AAPL" not in scanner._loss_lockout_fallback  # pruned on read


@pytest.mark.asyncio
async def test_start_loss_lockout_clears_in_memory_fallback_on_successful_set(scanner):
    scanner._loss_lockout_fallback["AAPL"] = datetime.now(timezone.utc) + timedelta(seconds=60)

    await scanner._start_loss_lockout("AAPL")

    assert "AAPL" not in scanner._loss_lockout_fallback


# --- Cooldown -------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_message_suppresses_signals_when_ticker_on_cooldown(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)])
    scanner._client.exists.side_effect = _exists_side_effect(on_cooldown=True)

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _signal_publishes(scanner) == []
    assert _cooldown_set_calls(scanner) == []  # cooldown not re-armed while already locked
    assert scanner.signals_suppressed_cooldown == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_buffers_candidate_without_arming_cooldown_yet(scanner, monkeypatch):
    """Post-Publication Cooldown Trigger (2026-08-16 quant audit):
    surviving strategy.py's gates only queues the candidate for the next
    throttle flush -- it does NOT arm cooldown yet. Cooldown is armed
    only once the candidate actually publishes (see the flush-level test
    below)."""
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)])

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _cooldown_set_calls(scanner) == []
    # Not published yet -- candidates wait for the throttle window flush.
    assert _signal_publishes(scanner) == []
    assert len(scanner._pending_candidates) == 1


@pytest.mark.asyncio
async def test_flush_throttle_window_arms_cooldown_only_for_published_signals(scanner):
    """Post-Publication Cooldown Trigger: cooldown is armed in
    _publish_signal, so it's only set for a candidate that actually
    clears the throttle window's ranking (and revalidation) -- a
    candidate dropped by the throttle must not burn the cooldown slot."""
    scanner.config = replace(scanner.config, throttle_max_signals=1)
    published = _signal("PUBLISHED", 5.0, confluence_score=3, risk_reward_ratio=2.0)
    dropped_by_throttle = _signal("DROPPED", 0.1, confluence_score=0, risk_reward_ratio=1.5)
    _seed_close(scanner, "PUBLISHED", 100.0)  # so revalidation can confirm fresh geometry
    scanner._pending_candidates = [published, dropped_by_throttle]

    await scanner._flush_throttle_window()

    cooldown_tickers = {call.args[0] for call in _cooldown_set_calls(scanner)}
    assert cooldown_tickers == {"cooldown:PUBLISHED"}


@pytest.mark.asyncio
async def test_is_on_cooldown_fails_closed_on_redis_error_by_default(scanner):
    """Fail-Closed Risk Management (2026-08-16 quant audit): a Redis
    error means this process can't confirm the ticker is actually clear
    of cooldown -- default policy is BLOCKED, not clear."""
    scanner._client.exists.side_effect = ConnectionError("redis down")

    assert await scanner._is_on_cooldown("AAPL") is True


@pytest.mark.asyncio
async def test_is_on_cooldown_fails_open_when_explicitly_configured(scanner):
    scanner.config = replace(scanner.config, risk_check_fail_closed=False)
    scanner._client.exists.side_effect = ConnectionError("redis down")

    assert await scanner._is_on_cooldown("AAPL") is False


# --- Fail-Closed Lock Persistence, cooldown leg (2026-08-16 quant audit,
# round 3) -- see the loss-lockout block above for the mirrored coverage.

@pytest.mark.asyncio
async def test_start_cooldown_falls_back_to_in_memory_lock_on_redis_set_failure(scanner):
    scanner._client.set.side_effect = ConnectionError("redis down")

    await scanner._start_cooldown("AAPL")

    assert await scanner._is_on_cooldown("AAPL") is True


@pytest.mark.asyncio
async def test_is_on_cooldown_ignores_expired_in_memory_fallback_lock(scanner):
    scanner._cooldown_fallback["AAPL"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    assert await scanner._is_on_cooldown("AAPL") is False
    assert "AAPL" not in scanner._cooldown_fallback  # pruned on read


@pytest.mark.asyncio
async def test_start_cooldown_clears_in_memory_fallback_on_successful_set(scanner):
    scanner._cooldown_fallback["AAPL"] = datetime.now(timezone.utc) + timedelta(seconds=60)

    await scanner._start_cooldown("AAPL")

    assert "AAPL" not in scanner._cooldown_fallback


# --- GLOBAL_RISK_DEGRADED (2026-08-16 quant audit, round 4) ---------------
# Process-wide (not per-ticker) fail-closed state: a mandatory Redis
# persistence WRITE failure (loss-lockout or cooldown) must block ALL
# subsequent signal publication for EVERY ticker, cleared only once
# _reconcile_risk_state confirms Redis can actually PERSIST a write again
# (not merely respond to PING).

def _fake_redis_kv(client) -> dict:
    """Wires client.set/client.get to a real in-memory dict so
    _verify_redis_persistence's write-then-readback roundtrip actually
    round-trips, instead of AsyncMock's default (a MagicMock that isn't
    the written value)."""
    store: dict[str, str] = {}

    async def fake_set(key, value, ex=None, nx=None):
        store[key] = value
        return True

    async def fake_get(key):
        return store.get(key)

    client.set = AsyncMock(side_effect=fake_set)
    client.get = AsyncMock(side_effect=fake_get)
    return store


@pytest.mark.asyncio
async def test_loss_lockout_set_failure_enters_global_risk_degraded(scanner):
    scanner._client.set.side_effect = ConnectionError("redis down")

    await scanner._start_loss_lockout("AAPL")

    assert scanner.risk_degraded is True


@pytest.mark.asyncio
async def test_cooldown_set_failure_enters_global_risk_degraded(scanner):
    scanner._client.set.side_effect = ConnectionError("redis down")

    await scanner._start_cooldown("AAPL")

    assert scanner.risk_degraded is True


@pytest.mark.asyncio
async def test_loss_lockout_failure_blocks_publication_for_every_ticker_not_just_the_affected_one(scanner):
    """Requirement 2/15: a Redis loss-lock SET failure for ONE ticker
    (AAPL) must block publication for every OTHER ticker too (MSFT,
    NVDA) -- this is a risk-CONTROL failure, not a ticker-specific
    market condition."""
    scanner._client.set.side_effect = ConnectionError("redis down")
    await scanner._start_loss_lockout("AAPL")
    assert scanner.risk_degraded is True

    for ticker in ("AAPL", "MSFT", "NVDA"):
        await scanner._publish_signal(_signal(ticker, 3.0))

    assert _signal_publishes(scanner) == []
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    degraded_rejections = [r for r in rejections if r["reason"] == "GLOBAL_RISK_DEGRADED"]
    assert {r["ticker"] for r in degraded_rejections} == {"AAPL", "MSFT", "NVDA"}


@pytest.mark.asyncio
async def test_cooldown_set_failure_after_publish_degrades_and_blocks_subsequent_publication(scanner):
    """Requirement 6/15: the first signal's publish itself already
    succeeded (can't be undone) -- but once its cooldown persistence
    fails, every SUBSEQUENT publish attempt (any ticker) must be
    blocked, not merely warned about."""
    first = _signal("AAPL", 3.0)
    scanner._client.set.side_effect = ConnectionError("redis down")  # cooldown SET will fail

    await scanner._publish_signal(first)

    assert len(_signal_publishes(scanner)) == 1  # already-published signal can't be undone
    assert scanner.risk_degraded is True

    second = _signal("MSFT", 3.0)
    await scanner._publish_signal(second)

    assert len(_signal_publishes(scanner)) == 1  # second publish blocked


@pytest.mark.asyncio
async def test_handle_market_tick_suppresses_every_ticker_when_risk_degraded(scanner, monkeypatch):
    scanner._risk_degraded = True
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)],
    )

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _signal_publishes(scanner) == []
    assert scanner.signals_suppressed_risk_degraded == 1
    assert scanner._pending_candidates == []
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert any(r["reason"] == "GLOBAL_RISK_DEGRADED" for r in rejections)


@pytest.mark.asyncio
async def test_verify_redis_persistence_true_on_successful_roundtrip(scanner):
    _fake_redis_kv(scanner._client)

    assert await scanner._verify_redis_persistence() is True


@pytest.mark.asyncio
async def test_verify_redis_persistence_false_on_set_failure(scanner):
    scanner._client.set.side_effect = ConnectionError("redis down")

    assert await scanner._verify_redis_persistence() is False


@pytest.mark.asyncio
async def test_verify_redis_persistence_false_when_readback_does_not_match(scanner):
    """Requirement 8: connectivity alone (e.g. a read-only replica that
    still answers GET/PING but silently drops writes) must not count as
    verified -- only a confirmed write-then-readback roundtrip does."""
    scanner._client.set = AsyncMock(return_value=True)
    scanner._client.get = AsyncMock(return_value=None)  # write didn't actually stick

    assert await scanner._verify_redis_persistence() is False


@pytest.mark.asyncio
async def test_reconcile_risk_state_clears_degraded_on_successful_verify(scanner):
    scanner._risk_degraded = True
    _fake_redis_kv(scanner._client)

    await scanner._reconcile_risk_state()

    assert scanner.risk_degraded is False


@pytest.mark.asyncio
async def test_reconcile_risk_state_remains_degraded_when_mandatory_set_still_fails(scanner):
    """Requirement 15's 'recovery failure' scenario: Redis PING succeeds
    (this test never touches .ping at all -- _reconcile_risk_state
    doesn't call it, deliberately, see Requirement 8) but the mandatory
    SET still fails -- must remain degraded, not clear."""
    scanner._risk_degraded = True
    scanner._client.set.side_effect = ConnectionError("redis down")

    await scanner._reconcile_risk_state()

    assert scanner.risk_degraded is True


@pytest.mark.asyncio
async def test_reconcile_risk_state_enters_degraded_when_verify_fails_from_healthy(scanner):
    scanner._risk_degraded = False
    scanner._client.set.side_effect = ConnectionError("redis down")

    await scanner._reconcile_risk_state()

    assert scanner.risk_degraded is True


@pytest.mark.asyncio
async def test_full_recovery_cycle_clears_degraded_and_resumes_publication(scanner):
    """Requirement 15's 'recovery' scenario end to end: Redis fails ->
    degraded -> Redis recovers -> required risk state successfully
    persisted -> degraded cleared -> publication resumes."""
    scanner._client.set.side_effect = ConnectionError("redis down")
    await scanner._start_cooldown("AAPL")
    assert scanner.risk_degraded is True

    _fake_redis_kv(scanner._client)  # Redis recovers -- writes actually persist now
    await scanner._reconcile_risk_state()
    assert scanner.risk_degraded is False

    await scanner._publish_signal(_signal("MSFT", 3.0))
    assert len(_signal_publishes(scanner)) == 1


@pytest.mark.asyncio
async def test_checkpoint_loop_retries_reconciliation_only_while_degraded(scanner):
    """Requirement 3: recovery retrying piggybacks on the ALREADY-
    EXISTING buffer-checkpoint loop rather than a new 24x7 daemon --
    this confirms _reconcile_risk_state is (and isn't) invoked from
    there at the right times, without actually running the loop's
    sleep."""
    scanner._reconcile_risk_state = AsyncMock()
    scanner.store = None  # _checkpoint_all_buffers is a no-op without a store

    scanner._risk_degraded = False
    scanner._checkpoint_all_buffers()
    if scanner._risk_degraded:
        await scanner._reconcile_risk_state()
    scanner._reconcile_risk_state.assert_not_awaited()

    scanner._risk_degraded = True
    scanner._checkpoint_all_buffers()
    if scanner._risk_degraded:
        await scanner._reconcile_risk_state()
    scanner._reconcile_risk_state.assert_awaited_once()


# --- UK Operating Window (2026-08-16 quant audit, round 5) ----------------
# "08:00-22:00 Monday-Friday is a trading-session rule, not an
# application-startup rule" -- TalonX may be started at any time; each
# candidate's UK-window check is evaluated fresh, independent of when the
# process launched. is_operating_window_open's own boundary/DST behavior
# is covered in test_quant_session.py; these confirm consumer.py's two
# gates (early per-tick, and the authoritative final-revalidation check).

@pytest.mark.asyncio
async def test_handle_market_tick_suppresses_every_ticker_when_uk_window_closed(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)],
    )
    monkeypatch.setattr(consumer_module, "is_operating_window_open", lambda *a, **k: False)

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _signal_publishes(scanner) == []
    assert scanner.signals_suppressed_uk_session_closed == 1
    assert scanner._pending_candidates == []
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert any(r["reason"] == "UK_SESSION_CLOSED" for r in rejections)


@pytest.mark.asyncio
async def test_handle_market_tick_does_not_touch_redis_locks_when_uk_window_closed(scanner, monkeypatch):
    """Requirement 15: session closure must not corrupt/modify any
    existing Redis risk state -- it only prevents new publication."""
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)],
    )
    monkeypatch.setattr(consumer_module, "is_operating_window_open", lambda *a, **k: False)

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _cooldown_set_calls(scanner) == []
    assert _lockout_set_calls(scanner) == []


@pytest.mark.asyncio
async def test_handle_market_tick_allows_publication_when_uk_window_open(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)],
    )
    # default autouse fixture already stubs is_operating_window_open -> True

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert len(scanner._pending_candidates) == 1
    assert scanner.signals_suppressed_uk_session_closed == 0


@pytest.mark.asyncio
async def test_revalidate_candidate_rejects_when_uk_window_closed(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "is_operating_window_open", lambda *a, **k: False)
    now = datetime.now(timezone.utc)
    signal = _revalidatable_signal()
    _seed_close(scanner, "AAPL", 100.0)  # fresh data IS available -- window itself is the reason to reject

    result = await scanner._revalidate_candidate(signal, now)

    assert result is None
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "UK_SESSION_CLOSED"


@pytest.mark.asyncio
async def test_candidate_generated_before_close_is_rejected_if_window_closes_before_final_publication(
    scanner, monkeypatch,
):
    """Requirement 14's exact boundary scenario: a candidate generated
    at (say) 21:59:50, while the window was still open, can still be
    sitting in the throttle buffer when the window closes at 22:00:00 --
    the early per-tick check alone (which only saw the window as OPEN at
    generation time) would miss this; final revalidation must catch it."""
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)],
    )
    window_calls = iter([True, False])  # open when generated (early gate), closed by final revalidation
    monkeypatch.setattr(consumer_module, "is_operating_window_open", lambda *a, **k: next(window_calls))

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))  # early gate: window open -> queued
    assert len(scanner._pending_candidates) == 1

    await scanner._flush_throttle_window()  # final revalidation: window now closed -> rejected

    assert _signal_publishes(scanner) == []
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert any(r["reason"] == "UK_SESSION_CLOSED" for r in rejections)


@pytest.mark.asyncio
async def test_freshly_constructed_scanner_blocks_publication_when_started_outside_window(monkeypatch):
    """Simulates TalonX being started at an arbitrary/outside-hours time
    (an unplanned restart, or a weekend startup) -- a brand-new
    QuantScanner has no special startup-time state of its own; it simply
    evaluates the CURRENT UK window fresh on its very first tick, exactly
    like every other tick."""
    scanner = QuantScanner(QuantConfig())
    scanner._client = AsyncMock()
    scanner._client.exists.side_effect = _exists_side_effect()
    monkeypatch.setattr(consumer_module.preseed, "fetch_1m_history", lambda symbol, period: [])
    monkeypatch.setattr(consumer_module.preseed, "fetch_15m_history", lambda symbol, period: [])
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)],
    )
    monkeypatch.setattr(consumer_module, "is_operating_window_open", lambda *a, **k: False)

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert scanner._pending_candidates == []
    assert scanner.signals_suppressed_uk_session_closed == 1


@pytest.mark.asyncio
async def test_freshly_constructed_scanner_allows_publication_when_started_mid_window(monkeypatch):
    """Mirrors the test above for a mid-session (re)start -- e.g. Monday
    14:00, or a restart at 15:00 after an unexpected shutdown at 14:00:
    trading resumes immediately, no wait until the next scheduled 08:00."""
    scanner = QuantScanner(QuantConfig())
    scanner._client = AsyncMock()
    scanner._client.exists.side_effect = _exists_side_effect()
    monkeypatch.setattr(consumer_module.preseed, "fetch_1m_history", lambda symbol, period: [])
    monkeypatch.setattr(consumer_module.preseed, "fetch_15m_history", lambda symbol, period: [])
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)],
    )
    monkeypatch.setattr(consumer_module, "is_operating_window_open", lambda *a, **k: True)

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert len(scanner._pending_candidates) == 1
    assert scanner.signals_suppressed_uk_session_closed == 0


# --- US Market Closed Session Rejection (2026-08-18 correctness fix, ------
# code-review finding #5) -- session=="closed" (outside 04:00-16:00 ET)
# previously had NO dedicated gate: every other check below is either
# unconditional or specifically keyed on "pre_market", so a closed-session
# candidate could reach evaluation/scoring/publication on the same footing
# as a genuine regular-session one. Deliberately a SEPARATE concept from
# the UK operating window above (is_operating_window_open) -- these tests
# use is_operating_window_open's default autouse True stub (see the
# scanner fixture) so only the US-session gate under test is exercised.

@pytest.mark.asyncio
async def test_handle_message_suppresses_all_signals_when_us_market_closed(scanner, monkeypatch):
    candidate = _premarket_signal(session="closed")
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _signal_publishes(scanner) == []
    assert scanner.signals_suppressed_us_session_closed == 1
    assert scanner._pending_candidates == []
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert any(r["reason"] == "US_MARKET_SESSION_CLOSED" for r in rejections)


@pytest.mark.asyncio
async def test_handle_message_allows_regular_session_signal_through_us_session_gate(scanner, monkeypatch):
    # session="regular" (the default _signal() bar_timestamp is 15:00 UTC = 11:00 ET)
    candidate = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=2.0)
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert scanner.signals_suppressed_us_session_closed == 0
    assert len(scanner._pending_candidates) == 1


@pytest.mark.asyncio
async def test_handle_message_allows_premarket_session_signal_through_us_session_gate(scanner, monkeypatch):
    """A pre_market candidate must NOT be caught by the closed-session
    gate -- it should proceed to the premarket-specific gates instead
    (provider-capability/liquidity/news), unaffected by this fix."""
    candidate = _premarket_signal()  # session="pre_market"
    scanner._latest_quotes["AAPL"] = (99.0, 100.0, datetime.now(timezone.utc))
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )
    monkeypatch.setattr(scanner, "_clears_premarket_liquidity", lambda s: True)
    scanner._last_news_seen["AAPL"] = datetime.now(timezone.utc)

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert scanner.signals_suppressed_us_session_closed == 0
    assert len(scanner._pending_candidates) == 1


# --- Restart semantics (2026-08-16 quant audit, round 4, Requirement 4/13) -
# TalonX is a host process (scripts/start_talonx.ps1, Task Scheduler),
# stopped and restarted daily -- these confirm a BRAND-NEW QuantScanner
# (no in-memory history at all, simulating a Monday-morning restart)
# still honours whatever Redis itself currently says about a per-ticker
# lock's TTL, since these checks always read Redis live, never a
# process-local cache.

@pytest.mark.asyncio
async def test_valid_ttl_lock_is_honoured_by_a_freshly_constructed_scanner():
    scanner = QuantScanner(QuantConfig())
    scanner._client = AsyncMock()
    scanner._client.exists.side_effect = _exists_side_effect(locked_out=True)

    assert await scanner._is_loss_locked_out("AAPL") is True


@pytest.mark.asyncio
async def test_expired_ttl_lock_is_not_resurrected_by_a_freshly_constructed_scanner():
    scanner = QuantScanner(QuantConfig())
    scanner._client = AsyncMock()
    scanner._client.exists.side_effect = _exists_side_effect(locked_out=False)

    assert await scanner._is_loss_locked_out("AAPL") is False


@pytest.mark.asyncio
async def test_freshly_constructed_scanner_starts_reconciled_not_degraded():
    """A brand-new process has no reason to assume Redis is broken --
    GLOBAL_RISK_DEGRADED defaults False; production correctness comes
    from _connect_and_listen's _reconcile_risk_state call running BEFORE
    the message loop starts (see that method's own docstring), not from
    this default."""
    scanner = QuantScanner(QuantConfig())

    assert scanner.risk_degraded is False


# --- Confluence / risk-reward filters (run before the cooldown lock) ------

@pytest.mark.asyncio
async def test_handle_message_suppresses_low_confluence_signal(scanner, monkeypatch):
    low_confluence = _signal("AAPL", 3.0, confluence_score=1)  # below confluence_score_min=2
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [low_confluence])

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _cooldown_set_calls(scanner) == []  # cooldown never armed for a filtered-out candidate
    assert _signal_publishes(scanner) == []
    assert scanner.signals_suppressed_low_confluence == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_suppresses_low_risk_reward_signal(scanner, monkeypatch):
    low_rr = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=1.0)  # below min_risk_reward_ratio=1.5
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [low_rr])

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _cooldown_set_calls(scanner) == []
    assert _signal_publishes(scanner) == []
    assert scanner.signals_suppressed_low_risk_reward == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_suppresses_signal_missing_risk_reward_ratio(scanner, monkeypatch):
    no_rr = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=None)  # ATR unavailable
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [no_rr])

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert scanner.signals_suppressed_low_risk_reward == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_only_survivors_proceed_when_signals_are_mixed(scanner, monkeypatch):
    survivor = _signal("AAPL", 5.0, signal_type=SignalType.MACD_BULLISH_CROSS, confluence_score=3, risk_reward_ratio=2.0)
    filtered_by_rr = _signal("AAPL", 1.0, signal_type=SignalType.MA_GOLDEN_CROSS, confluence_score=3, risk_reward_ratio=0.5)
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [survivor, filtered_by_rr])

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    # At least one signal survived, so only it is queued for the next
    # throttle flush -- cooldown isn't armed yet (Post-Publication
    # Cooldown Trigger), only once it's actually published.
    assert _cooldown_set_calls(scanner) == []
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
    for ticker in ("LOW", "MID", "HIGH"):  # NORATIO is dropped by the throttle, never reaches revalidation
        _seed_close(scanner, ticker, 100.0)
    scanner._pending_candidates = [low, mid, no_ratio, high]  # 4 candidates, cap is 3; all tied on confluence

    await scanner._flush_throttle_window()

    published_payloads = _signal_publishes(scanner)
    assert len(published_payloads) == 3
    assert scanner.signals_suppressed_throttle == 1
    assert scanner.signals_published == 3
    assert scanner._pending_candidates == []
    # The lowest-conviction candidate (no volume_surge_ratio at all) is
    # the one that should've been dropped -- from the PUBLISHED signals,
    # though it still gets its own THROTTLE rejection trace event.
    assert "NORATIO" not in "".join(published_payloads)
    assert "NORATIO" in "".join(_rejection_publishes(scanner))


@pytest.mark.asyncio
async def test_flush_throttle_window_ranks_confluence_before_volume_surge(scanner):
    scanner.config = QuantConfig(throttle_max_signals=1)
    low_confluence_high_volume = _signal("LOWCONF", 10.0, confluence_score=1)
    high_confluence_low_volume = _signal("HIGHCONF", 0.5, confluence_score=3)
    _seed_close(scanner, "HIGHCONF", 100.0)  # the only one that should survive to revalidation
    scanner._pending_candidates = [low_confluence_high_volume, high_confluence_low_volume]

    await scanner._flush_throttle_window()

    published_payloads = _signal_publishes(scanner)
    assert len(published_payloads) == 1
    assert "HIGHCONF" in "".join(published_payloads)
    assert "LOWCONF" not in "".join(published_payloads)


@pytest.mark.asyncio
async def test_flush_throttle_window_publishes_all_when_under_the_cap(scanner):
    scanner.config = QuantConfig(throttle_max_signals=3)
    _seed_close(scanner, "A", 100.0)
    _seed_close(scanner, "B", 100.0)
    scanner._pending_candidates = [_signal("A", 1.0), _signal("B", 2.0)]

    await scanner._flush_throttle_window()

    assert len(_signal_publishes(scanner)) == 2
    assert scanner.signals_suppressed_throttle == 0


@pytest.mark.asyncio
async def test_flush_throttle_window_is_a_noop_when_nothing_pending(scanner):
    await scanner._flush_throttle_window()

    scanner._client.publish.assert_not_awaited()
    assert scanner.signals_published == 0


# --- Intra-Flush Cooldown Re-Check (2026-08-16 quant audit, P1) -----------
# strategy.py can legitimately emit MULTIPLE independent candidates for
# the SAME ticker off one closed bar (e.g. a MACD cross AND an RSI/volume
# setup), which can both land in the same throttle batch. Without a
# re-check immediately before each candidate proceeds, the FIRST to
# publish arms cooldown:{TICKER} too late to stop a SECOND same-ticker
# candidate already sitting in that same batch from also publishing --
# these prove the fix, exercising the real _flush_throttle_window path
# end to end (not just _is_on_cooldown/_start_cooldown in isolation), so
# they'd fail against the previous buggy implementation.

def _fake_cooldown_backing_store(client) -> dict:
    """Wires client.set/.exists to a REAL in-memory dict, unlike
    _exists_side_effect's fixed canned answer -- needed here so a
    _start_cooldown() call made by an EARLIER candidate in the same
    flush is actually visible to a LATER candidate's _is_on_cooldown()
    check within the same test, proving the fix re-reads current state
    rather than trusting whatever was true when the batch was queued."""
    keys: dict[str, str] = {}

    async def fake_set(key, value, ex=None, nx=None):
        if nx and key in keys:
            return None
        keys[key] = value
        return True

    async def fake_exists(key):
        return key in keys

    client.set = AsyncMock(side_effect=fake_set)
    client.exists = AsyncMock(side_effect=fake_exists)
    return keys


@pytest.mark.asyncio
async def test_flush_throttle_window_blocks_second_same_ticker_candidate_via_cooldown(scanner):
    """TEST 1 -- same ticker: exactly one AAPL signal published, the
    second rejected as COOLDOWN, and cooldown:AAPL exists afterward."""
    _fake_cooldown_backing_store(scanner._client)
    first = _signal("AAPL", 3.0, signal_type=SignalType.MACD_BULLISH_CROSS)
    second = _signal("AAPL", 3.0, signal_type=SignalType.RSI_OVERSOLD_VOLUME_SURGE)
    _seed_close(scanner, "AAPL", 100.0)
    scanner._pending_candidates = [first, second]

    await scanner._flush_throttle_window()

    published = _signal_publishes(scanner)
    assert len(published) == 1

    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    cooldown_rejections = [r for r in rejections if r["reason"] == "COOLDOWN"]
    assert len(cooldown_rejections) == 1
    assert cooldown_rejections[0]["ticker"] == "AAPL"

    assert await scanner._is_on_cooldown("AAPL") is True


@pytest.mark.asyncio
async def test_flush_throttle_window_cooldown_recheck_does_not_affect_other_tickers(scanner):
    """TEST 2 -- mixed tickers: AAPL #1 publishes, AAPL #2 is COOLDOWN-
    rejected, MSFT #1 publishes untouched."""
    _fake_cooldown_backing_store(scanner._client)
    aapl_1 = _signal("AAPL", 3.0, signal_type=SignalType.MACD_BULLISH_CROSS)
    aapl_2 = _signal("AAPL", 3.0, signal_type=SignalType.RSI_OVERSOLD_VOLUME_SURGE)
    msft_1 = _signal("MSFT", 3.0, signal_type=SignalType.MACD_BULLISH_CROSS)
    for ticker in ("AAPL", "MSFT"):
        _seed_close(scanner, ticker, 100.0)
    scanner._pending_candidates = [aapl_1, aapl_2, msft_1]

    await scanner._flush_throttle_window()

    published_signals = [json.loads(p) for p in _signal_publishes(scanner)]
    assert len(published_signals) == 2
    aapl_published = [s for s in published_signals if s["ticker"] == "AAPL"]
    msft_published = [s for s in published_signals if s["ticker"] == "MSFT"]
    assert len(aapl_published) == 1
    assert len(msft_published) == 1


@pytest.mark.asyncio
async def test_flush_throttle_window_does_not_arm_cooldown_from_a_failed_revalidation(scanner):
    """TEST 3 -- first candidate fails final revalidation (expired in
    the throttle queue): it's rejected for ITS OWN reason, cooldown is
    NOT armed by it (cooldown is intentionally post-PUBLICATION, not
    post-attempt), and the second, still-valid same-ticker candidate
    must still be allowed to publish."""
    _fake_cooldown_backing_store(scanner._client)
    stale = _signal("AAPL", 3.0, signal_type=SignalType.MACD_BULLISH_CROSS)
    stale.signal_generated_at = datetime.now(timezone.utc) - timedelta(seconds=60)  # > max_candidate_age_seconds
    fresh = _signal("AAPL", 3.0, signal_type=SignalType.RSI_OVERSOLD_VOLUME_SURGE)
    _seed_close(scanner, "AAPL", 100.0)
    scanner._pending_candidates = [stale, fresh]

    await scanner._flush_throttle_window()

    published_signals = [json.loads(p) for p in _signal_publishes(scanner)]
    assert len(published_signals) == 1
    assert published_signals[0]["signal_type"] == SignalType.RSI_OVERSOLD_VOLUME_SURGE.value

    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert any(r["reason"] == "EXPIRED_IN_THROTTLE_QUEUE" for r in rejections)
    assert not any(r["reason"] == "COOLDOWN" for r in rejections)  # fresh candidate was never blocked


@pytest.mark.asyncio
async def test_flush_throttle_window_cooldown_recheck_fails_closed_on_redis_error(scanner):
    """TEST 4 -- Redis failure: the new intra-flush check reuses
    _is_on_cooldown as-is, so a Redis error fails CLOSED (blocked) by
    default (config.risk_check_fail_closed) -- no new fail-open path."""
    scanner._client.exists.side_effect = ConnectionError("redis down")
    _seed_close(scanner, "AAPL", 100.0)
    scanner._pending_candidates = [_signal("AAPL", 3.0)]

    await scanner._flush_throttle_window()

    assert _signal_publishes(scanner) == []
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert any(r["reason"] == "RISK_STORE_UNAVAILABLE_FAIL_CLOSED" for r in rejections)


@pytest.mark.asyncio
async def test_flush_throttle_window_cooldown_recheck_respects_explicit_fail_open_config(scanner):
    """Confirms the ONLY way to get fail-open behavior here is the
    pre-existing, explicit TALONX_QUANT_RISK_FAIL_CLOSED=false opt-out
    -- the new check doesn't silently override that deliberate operator
    choice, in either direction."""
    scanner.config = replace(scanner.config, risk_check_fail_closed=False)
    scanner._client.exists.side_effect = ConnectionError("redis down")
    _seed_close(scanner, "AAPL", 100.0)
    scanner._pending_candidates = [_signal("AAPL", 3.0)]

    await scanner._flush_throttle_window()

    assert len(_signal_publishes(scanner)) == 1


@pytest.mark.asyncio
async def test_flush_throttle_window_skips_revalidation_when_already_on_cooldown(scanner):
    """TEST 5 -- existing cooldown before the flush even starts: rejected
    immediately as COOLDOWN, with NO revalidation (or publish) work done
    for it at all."""
    scanner._client.exists.side_effect = _exists_side_effect(on_cooldown=True)
    revalidate_spy = AsyncMock(wraps=scanner._revalidate_candidate)
    scanner._revalidate_candidate = revalidate_spy
    scanner._pending_candidates = [_signal("AAPL", 3.0)]

    await scanner._flush_throttle_window()

    assert _signal_publishes(scanner) == []
    revalidate_spy.assert_not_awaited()
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert any(r["reason"] == "COOLDOWN" and r["ticker"] == "AAPL" for r in rejections)


@pytest.mark.asyncio
async def test_flush_throttle_window_multiple_same_ticker_candidates_over_cap(scanner):
    """TEST 6 -- three AAPL candidates plus one MSFT candidate, throttle
    capacity generous enough to release all four: ranking/capacity
    itself is untouched (nothing dropped purely for THROTTLE capacity),
    but only ONE AAPL candidate can actually publish once cooldown is
    armed by the first."""
    _fake_cooldown_backing_store(scanner._client)
    scanner.config = replace(scanner.config, throttle_max_signals=4)
    aapl_1 = _signal("AAPL", 3.0, signal_type=SignalType.MACD_BULLISH_CROSS)
    aapl_2 = _signal("AAPL", 3.0, signal_type=SignalType.RSI_OVERSOLD_VOLUME_SURGE)
    aapl_3 = _signal("AAPL", 3.0, signal_type=SignalType.MA_GOLDEN_CROSS)
    msft_1 = _signal("MSFT", 3.0, signal_type=SignalType.MACD_BULLISH_CROSS)
    for ticker in ("AAPL", "MSFT"):
        _seed_close(scanner, ticker, 100.0)
    scanner._pending_candidates = [aapl_1, aapl_2, aapl_3, msft_1]

    await scanner._flush_throttle_window()

    published_signals = [json.loads(p) for p in _signal_publishes(scanner)]
    assert len(published_signals) == 2  # exactly one AAPL, one MSFT
    assert scanner.signals_suppressed_throttle == 0  # nothing dropped for lack of throttle capacity
    aapl_published = [s for s in published_signals if s["ticker"] == "AAPL"]
    msft_published = [s for s in published_signals if s["ticker"] == "MSFT"]
    assert len(aapl_published) == 1
    assert len(msft_published) == 1

    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    cooldown_rejections = [r for r in rejections if r["reason"] == "COOLDOWN"]
    assert len(cooldown_rejections) == 2  # the other two AAPL candidates


@pytest.mark.asyncio
async def test_flush_throttle_window_prefers_quality_over_a_raw_volume_pump(scanner):
    """2026-08-16 quant-audit regression: the exact scenario the
    Composite Opportunity Score was added to fix -- a "meme pump" with a
    huge raw volume surge but mediocre confluence/R:R must NOT
    automatically outrank a higher-conviction, better-risk-reward setup
    on a smaller relative surge, the way the old (confluence_score,
    volume_surge_ratio) tuple-sort's raw-ratio tiebreaker would have
    let it."""
    scanner.config = QuantConfig(throttle_max_signals=1)
    meme_pump = _signal(
        "MEME", volume_surge_ratio=25.0, confluence_score=2, risk_reward_ratio=1.6,
    )
    quality_setup = _signal(
        "QUALITY", volume_surge_ratio=3.0, confluence_score=3, risk_reward_ratio=4.5,
    )
    _seed_close(scanner, "QUALITY", 100.0)  # the one expected to win the throttle
    scanner._pending_candidates = [meme_pump, quality_setup]

    await scanner._flush_throttle_window()

    published_payloads = _signal_publishes(scanner)
    assert "QUALITY" in "".join(published_payloads)
    assert "MEME" not in "".join(published_payloads)


# --- Composite Opportunity Score (pure function) --------------------------

def test_opportunity_score_normalizes_confluence_to_zero_to_one(config):
    zero_signal = _signal("A", None, confluence_score=0, risk_reward_ratio=None)
    zero_signal.trend_aligned = False  # isolate confluence's own contribution
    max_signal = _signal("A", None, confluence_score=3, risk_reward_ratio=None)
    max_signal.trend_aligned = False

    zero = _opportunity_score(zero_signal, config)
    max_confluence = _opportunity_score(max_signal, config)

    assert max_confluence > zero
    assert max_confluence == pytest.approx(config.opportunity_score_confluence_weight)


def test_opportunity_score_caps_risk_reward_at_the_configured_ceiling(config):
    at_cap = _signal("A", None, confluence_score=0, risk_reward_ratio=config.opportunity_score_rr_cap)
    way_above_cap = _signal("A", None, confluence_score=0, risk_reward_ratio=config.opportunity_score_rr_cap * 10)

    assert _opportunity_score(at_cap, config) == pytest.approx(_opportunity_score(way_above_cap, config))


def test_opportunity_score_caps_volume_surge_at_the_configured_ceiling(config):
    at_cap = _signal("A", volume_surge_ratio=config.opportunity_score_volume_cap, confluence_score=0, risk_reward_ratio=None)
    way_above_cap = _signal(
        "A", volume_surge_ratio=config.opportunity_score_volume_cap * 10, confluence_score=0, risk_reward_ratio=None,
    )

    assert _opportunity_score(at_cap, config) == pytest.approx(_opportunity_score(way_above_cap, config))


def test_opportunity_score_trend_aligned_true_scores_higher_than_none(config):
    signal_true = _signal("A", None, confluence_score=0, risk_reward_ratio=None)
    signal_true.trend_aligned = True
    signal_none = _signal("A", None, confluence_score=0, risk_reward_ratio=None)
    signal_none.trend_aligned = None

    assert _opportunity_score(signal_true, config) > _opportunity_score(signal_none, config)


def test_opportunity_score_trend_aligned_none_scores_higher_than_false(config):
    # Defensive-only path -- a False candidate should never actually
    # reach the throttle window (the trend gate drops it upstream), but
    # the scoring itself must still rank it correctly if it somehow did.
    signal_none = _signal("A", None, confluence_score=0, risk_reward_ratio=None)
    signal_none.trend_aligned = None
    signal_false = _signal("A", None, confluence_score=0, risk_reward_ratio=None)
    signal_false.trend_aligned = False

    assert _opportunity_score(signal_none, config) > _opportunity_score(signal_false, config)


def test_opportunity_score_is_zero_for_a_maximally_uninteresting_candidate(config):
    signal = _signal("A", None, confluence_score=0, risk_reward_ratio=None)
    signal.trend_aligned = False

    assert _opportunity_score(signal, config) == pytest.approx(0.0)


def test_opportunity_score_is_the_sum_of_configured_weights_at_full_marks(config):
    signal = _signal("A", volume_surge_ratio=config.opportunity_score_volume_cap, confluence_score=3, risk_reward_ratio=config.opportunity_score_rr_cap)
    signal.trend_aligned = True

    expected = (
        config.opportunity_score_confluence_weight
        + config.opportunity_score_rr_weight
        + config.opportunity_score_volume_weight
        + config.opportunity_score_trend_weight
    )
    assert _opportunity_score(signal, config) == pytest.approx(expected)


# --- Dynamic R:R Revalidation (_revalidate_candidate) ----------------------

def _revalidatable_signal(
    ticker: str = "AAPL", price: float = 100.0, atr: float = 2.0,
    pivot_resistance: float = 110.0, pivot_support: float = 90.0,
    direction: SignalDirection = SignalDirection.BULLISH,
    signal_generated_at: datetime | None = None,
) -> QuantSignal:
    signal = _signal("AAPL" if ticker is None else ticker, 3.0, confluence_score=3, risk_reward_ratio=2.0, direction=direction)
    signal.price = price
    signal.atr = atr
    signal.pivot_resistance = pivot_resistance
    signal.pivot_support = pivot_support
    if signal_generated_at is not None:
        signal.signal_generated_at = signal_generated_at
    return signal


def _seed_close(scanner, ticker: str, close: float) -> None:
    scanner.buffer.add_bar(
        symbol=ticker, timestamp=datetime(2026, 8, 7, 15, 1, tzinfo=timezone.utc),
        open_=close, high=close, low=close, close=close, volume=1000.0,
    )


@pytest.mark.asyncio
async def test_revalidate_candidate_drops_when_expired(scanner):
    now = datetime.now(timezone.utc)
    stale = _revalidatable_signal(signal_generated_at=now - timedelta(seconds=31))

    result = await scanner._revalidate_candidate(stale, now)

    assert result is None
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "EXPIRED_IN_THROTTLE_QUEUE"


@pytest.mark.asyncio
async def test_revalidate_candidate_survives_just_under_the_age_limit(scanner):
    now = datetime.now(timezone.utc)
    fresh = _revalidatable_signal(signal_generated_at=now - timedelta(seconds=29))
    _seed_close(scanner, "AAPL", 100.0)

    result = await scanner._revalidate_candidate(fresh, now)

    assert result is not None
    assert result.signal_age_ms == pytest.approx(29000, abs=100)


@pytest.mark.asyncio
async def test_revalidate_candidate_drops_when_rr_degraded_by_price_drift(scanner):
    now = datetime.now(timezone.utc)
    # entry=100, atr=2 -> risk = 1.5*2 = 3; resistance=103 -> reward at
    # entry = 3, ratio = 1.0 (already below 1.5, but the ORIGINAL price
    # drifting up to 102 makes it materially worse: reward = 1, ratio = 0.33).
    signal = _revalidatable_signal(price=100.0, atr=2.0, pivot_resistance=106.0, pivot_support=90.0)
    _seed_close(scanner, "AAPL", 104.5)  # price drifted up close to resistance -- reward shrank

    result = await scanner._revalidate_candidate(signal, now)

    assert result is None
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "RR_DEGRADED_DURING_THROTTLE"


@pytest.mark.asyncio
async def test_revalidate_candidate_updates_price_and_rr_on_success(scanner):
    now = datetime.now(timezone.utc)
    signal = _revalidatable_signal(price=100.0, atr=2.0, pivot_resistance=110.0, pivot_support=90.0)
    _seed_close(scanner, "AAPL", 101.0)  # small, harmless drift

    result = await scanner._revalidate_candidate(signal, now)

    assert result is not None
    # reward = 110 - 101 = 9; risk = 1.5 * 2 = 3; ratio = 3.0
    assert result.price == pytest.approx(101.0)
    assert result.risk_reward_ratio == pytest.approx(3.0)
    assert result.signal_age_ms is not None
    # Canonical Trade Geometry (2026-08-16 quant audit, round 3): stop/
    # target must be re-derived against the SAME revalidated price the
    # ratio above was measured against -- not left pinned to the
    # original, stale entry price.
    assert result.stop_price == pytest.approx(101.0 - 3.0)  # price - atr_stop_multiplier(1.5)*atr(2.0)
    assert result.target_price == pytest.approx(110.0)  # pivot resistance, unchanged


@pytest.mark.asyncio
async def test_revalidate_candidate_bearish_uses_pivot_support(scanner):
    now = datetime.now(timezone.utc)
    signal = _revalidatable_signal(
        price=100.0, atr=2.0, pivot_resistance=115.0, pivot_support=94.0, direction=SignalDirection.BEARISH,
    )
    _seed_close(scanner, "AAPL", 99.0)

    result = await scanner._revalidate_candidate(signal, now)

    assert result is not None
    # reward = 99 - 94 = 5; risk = 1.5 * 2 = 3; ratio ~= 1.67
    assert result.risk_reward_ratio == pytest.approx(5.0 / 3.0)
    assert result.stop_price == pytest.approx(99.0 + 3.0)  # price + atr_stop_multiplier(1.5)*atr(2.0)
    assert result.target_price == pytest.approx(94.0)  # pivot support, unchanged


@pytest.mark.asyncio
async def test_revalidate_candidate_rejects_when_no_fresh_price_available(scanner):
    """Final Revalidation Data Availability (2026-08-16 quant audit,
    round 4, Requirement 10): a prior version of this method published
    the candidate as-generated (its original, now-unverified geometry)
    when no fresh buffered price was available. That's no longer
    acceptable -- final publication must be based on a VERIFIED current
    trade geometry, so the candidate is rejected instead."""
    now = datetime.now(timezone.utc)
    signal = _revalidatable_signal()  # no bar ever seeded for this ticker

    result = await scanner._revalidate_candidate(signal, now)

    assert result is None
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "FINAL_REVALIDATION_DATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_revalidate_candidate_rejects_when_atr_missing(scanner):
    now = datetime.now(timezone.utc)
    signal = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=2.0)
    signal.atr = None  # pydantic model, plain attribute assignment
    _seed_close(scanner, "AAPL", 105.0)

    result = await scanner._revalidate_candidate(signal, now)

    assert result is None
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "FINAL_REVALIDATION_DATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_revalidate_candidate_rejects_when_pivots_missing(scanner):
    now = datetime.now(timezone.utc)
    signal = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=2.0)
    signal.pivot_resistance = None
    signal.pivot_support = None
    _seed_close(scanner, "AAPL", 105.0)

    result = await scanner._revalidate_candidate(signal, now)

    assert result is None
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "FINAL_REVALIDATION_DATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_flush_throttle_window_publishes_the_revalidated_price(scanner):
    signal = _revalidatable_signal(price=100.0, atr=2.0, pivot_resistance=110.0, pivot_support=90.0)
    _seed_close(scanner, "AAPL", 103.0)
    scanner._pending_candidates = [signal]

    await scanner._flush_throttle_window()

    published = [json.loads(p) for p in _signal_publishes(scanner)]
    assert len(published) == 1
    assert published[0]["price"] == pytest.approx(103.0)


@pytest.mark.asyncio
async def test_flush_throttle_window_does_not_publish_an_expired_candidate(scanner):
    now = datetime.now(timezone.utc)
    signal = _revalidatable_signal(signal_generated_at=now - timedelta(seconds=60))
    scanner._pending_candidates = [signal]

    await scanner._flush_throttle_window()

    assert _signal_publishes(scanner) == []
    assert _cooldown_set_calls(scanner) == []


# --- Bar-Level Ingestion Idempotency (_is_new_bar_tick) ---------------------

@pytest.mark.asyncio
async def test_is_new_bar_tick_true_for_a_fresh_tick(scanner):
    event = MarketTickEvent(
        event_type=TickEventType.BAR, symbol="AAPL", source=TickSource.POLLING,
        timestamp=datetime(2026, 8, 7, 15, 0, 5, tzinfo=timezone.utc), close=100.0,
    )
    scanner._client.set.return_value = True  # Redis SETNX succeeded -- key didn't already exist

    assert await scanner._is_new_bar_tick(event) is True


@pytest.mark.asyncio
async def test_is_new_bar_tick_false_for_a_redis_confirmed_duplicate(scanner):
    event = MarketTickEvent(
        event_type=TickEventType.BAR, symbol="AAPL", source=TickSource.POLLING,
        timestamp=datetime(2026, 8, 7, 15, 0, 5, tzinfo=timezone.utc), close=100.0,
    )
    scanner._client.set.return_value = None  # Redis SETNX failed -- key already existed

    assert await scanner._is_new_bar_tick(event) is False


@pytest.mark.asyncio
async def test_is_new_bar_tick_uses_the_configured_dedup_ttl(scanner):
    event = MarketTickEvent(
        event_type=TickEventType.BAR, symbol="AAPL", source=TickSource.POLLING,
        timestamp=datetime(2026, 8, 7, 15, 0, 5, tzinfo=timezone.utc), close=100.0,
    )

    await scanner._is_new_bar_tick(event)

    args, kwargs = scanner._client.set.await_args
    assert args[0] == "processed_bar:AAPL:2026-08-07T15:00:05+00:00"
    assert kwargs["ex"] == int(scanner.config.bar_dedup_ttl_seconds)
    assert kwargs["nx"] is True


@pytest.mark.asyncio
async def test_is_new_bar_tick_falls_back_to_in_memory_dedup_on_redis_error(scanner):
    event = MarketTickEvent(
        event_type=TickEventType.BAR, symbol="AAPL", source=TickSource.POLLING,
        timestamp=datetime(2026, 8, 7, 15, 0, 5, tzinfo=timezone.utc), close=100.0,
    )
    scanner._client.set.side_effect = ConnectionError("redis down")

    first = await scanner._is_new_bar_tick(event)
    second = await scanner._is_new_bar_tick(event)  # exact same tick again

    assert first is True
    assert second is False  # caught by the in-memory fallback


@pytest.mark.asyncio
async def test_is_new_bar_tick_falls_back_to_in_memory_dedup_with_no_client(scanner):
    scanner._client = None
    event = MarketTickEvent(
        event_type=TickEventType.BAR, symbol="AAPL", source=TickSource.POLLING,
        timestamp=datetime(2026, 8, 7, 15, 0, 5, tzinfo=timezone.utc), close=100.0,
    )

    first = await scanner._is_new_bar_tick(event)
    second = await scanner._is_new_bar_tick(event)

    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_handle_market_tick_drops_a_redelivered_duplicate_tick(scanner, monkeypatch):
    """Acceptance criterion: sending identical bar payloads twice results
    in only one entry added to RollingBarBuffer -- i.e. the SECOND,
    exact-duplicate delivery must not double-count volume into the
    still-forming bucket's running accumulation."""
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: None)
    # Redis SETNX: first delivery claims the dedup key (truthy), the
    # identical redelivery finds it already claimed (None).
    scanner._client.set.side_effect = [True, None]
    payload = json.loads(_bar_message("AAPL")["data"])  # close=100.5, volume=1000.0

    await scanner._handle_market_tick(payload)
    await scanner._handle_market_tick(dict(payload))  # exact duplicate redelivery

    df = scanner.buffer.get_dataframe("AAPL")
    assert len(df) == 1
    assert df["volume"].iloc[0] == pytest.approx(1000.0)  # NOT double-counted to 2000.0


@pytest.mark.asyncio
async def test_handle_market_tick_still_accumulates_a_distinct_later_tick(scanner, monkeypatch):
    """A second, genuinely DIFFERENT tick (different timestamp) landing
    in the same still-forming minute must still accumulate normally --
    dedup must not suppress legitimate accumulation."""
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: None)
    first = json.loads(_bar_message("AAPL")["data"])  # 2026-08-07T15:00:00Z, volume=1000.0
    second = dict(first, timestamp="2026-08-07T15:00:05Z", close=101.0, volume=500.0)

    await scanner._handle_market_tick(first)
    await scanner._handle_market_tick(second)

    df = scanner.buffer.get_dataframe("AAPL")
    assert len(df) == 1  # still one BAR (same bucket), but...
    assert df["volume"].iloc[0] == pytest.approx(1500.0)  # ...both ticks' volume accumulated
    assert df["close"].iloc[0] == pytest.approx(101.0)


@pytest.mark.asyncio
async def test_handle_market_tick_increments_duplicate_bar_metric(scanner, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: None)
    scanner._client.set.side_effect = [True, None]
    payload = json.loads(_bar_message("AAPL")["data"])

    await scanner._handle_market_tick(payload)
    await scanner._handle_market_tick(dict(payload))

    incr_calls = [c for c in scanner._client.incrby.await_args_list if "dropped_duplicate_bars" in c.args[0]]
    assert len(incr_calls) == 1


# --- Suppression-count persistence (the EOD report's signal-funnel section) -

@pytest.mark.asyncio
async def test_cooldown_suppression_is_recorded_when_a_store_is_set(tmp_path, monkeypatch):
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)])
    with QuantStateStore(tmp_path / "quant.db") as store:
        scanner = QuantScanner(QuantConfig(), store=store)
        scanner._client = AsyncMock()
        scanner._client.exists.side_effect = _exists_side_effect(on_cooldown=True)

        await scanner._handle_message(_priming_bar_message("AAPL"))
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

        await scanner._handle_message(_priming_bar_message("SMCI"))
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
        scanner._client.exists.side_effect = _exists_side_effect()  # not on cooldown
        _seed_close(scanner, "HIGH", 100.0)  # the one expected to win and publish
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

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _cooldown_set_calls(scanner) == []
    assert _signal_publishes(scanner) == []
    assert scanner.signals_suppressed_trend_gate == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_passes_signal_with_trend_aligned_true(scanner, monkeypatch):
    aligned = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=2.0)
    aligned.session = "regular"
    aligned.htf_sma_200 = 90.0  # gate applicable AND resolved -- not the unavailable case
    aligned.trend_aligned = True
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [aligned],
    )

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert len(scanner._pending_candidates) == 1
    assert scanner.signals_suppressed_htf_unavailable == 0


# --- HTF-Unavailable Trend Gate (2026-08-16 quant audit, round 3) ---------
# trend_aligned=None used to mean BOTH "gate doesn't apply" and "gate
# applies but the HTF buffer hasn't warmed up" -- these confirm the two
# are now distinguished (see _trend_gate_applicable).

@pytest.mark.asyncio
async def test_handle_message_suppresses_bullish_regular_session_signal_when_htf_unavailable(scanner, monkeypatch):
    candidate = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=2.0)
    candidate.session = "regular"
    # trend_aligned/htf_sma_200 both default to None -- gate applies
    # (bullish, regular session, enabled) but the buffer isn't ready.
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _signal_publishes(scanner) == []
    assert scanner.signals_suppressed_htf_unavailable == 1
    assert scanner.signals_suppressed_trend_gate == 0  # distinct gate, not double-counted
    assert scanner._pending_candidates == []
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "HTF_DATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_handle_message_passes_signal_when_trend_gate_disabled_and_htf_unavailable(scanner, monkeypatch):
    scanner.config = replace(scanner.config, trend_gate_enabled=False)
    candidate = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=2.0)
    candidate.session = "regular"
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert len(scanner._pending_candidates) == 1
    assert scanner.signals_suppressed_htf_unavailable == 0


@pytest.mark.asyncio
async def test_handle_message_suppresses_bearish_regular_session_signal_via_trend_aligned_none_unaffected(scanner, monkeypatch):
    """A BEARISH candidate is never subject to the trend gate at all --
    trend_aligned=None here means "not applicable", not "unavailable",
    even in a regular session with htf_sma_200 still None."""
    candidate = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=2.0, direction=SignalDirection.BEARISH)
    candidate.session = "regular"
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert len(scanner._pending_candidates) == 1
    assert scanner.signals_suppressed_htf_unavailable == 0


@pytest.mark.asyncio
async def test_handle_message_suppresses_premarket_signal_with_no_quote_capability(scanner, monkeypatch):
    # 2026-08-18 correctness fix (code-review finding #2): session=
    # "pre_market", no buffered bars and NO cached quote AT ALL -- e.g.
    # running on yfinance, which never emits QUOTE events (only
    # polygon_ws.py does; see talonx_ingest/market_data/yfinance_poll.py).
    # This is now PREMARKET_PROVIDER_UNSUPPORTED specifically (the
    # provider genuinely cannot supply the required quote capability),
    # distinct from PREMARKET_LIQUIDITY (a quote WAS available but failed
    # the freshness/spread/dollar-volume check -- see the sibling test
    # below). Renamed from
    # test_handle_message_suppresses_premarket_signal_without_liquidity_data,
    # which asserted the old, less specific classification this fix
    # replaces -- the gate itself is unchanged (still fail-closed,
    # candidate still rejected either way).
    candidate = _premarket_signal()
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _signal_publishes(scanner) == []
    assert scanner.signals_suppressed_premarket_provider_unsupported == 1
    assert scanner.signals_suppressed_premarket_liquidity == 0
    assert scanner._pending_candidates == []
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert any(r["reason"] == "PREMARKET_PROVIDER_UNSUPPORTED" for r in rejections)


@pytest.mark.asyncio
async def test_handle_message_suppresses_premarket_signal_with_quote_but_fails_liquidity(scanner, monkeypatch):
    """A quote IS available (e.g. a Polygon-configured deployment) but
    _clears_premarket_liquidity itself rejects it (stale/wide spread/low
    dollar volume) -- this is the genuine PREMARKET_LIQUIDITY case, still
    distinct from the no-quote-at-all case above."""
    candidate = _premarket_signal()
    scanner._latest_quotes["AAPL"] = (99.0, 100.0, datetime.now(timezone.utc))
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )
    monkeypatch.setattr(scanner, "_clears_premarket_liquidity", lambda s: False)

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _signal_publishes(scanner) == []
    assert scanner.signals_suppressed_premarket_provider_unsupported == 0
    assert scanner.signals_suppressed_premarket_liquidity == 1
    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert any(r["reason"] == "PREMARKET_LIQUIDITY" for r in rejections)


@pytest.mark.asyncio
async def test_handle_message_passes_premarket_signal_when_liquidity_and_news_clear(scanner, monkeypatch):
    candidate = _premarket_signal()
    # A quote must be present to clear the new provider-capability gate
    # (see test_handle_message_suppresses_premarket_signal_with_no_quote_capability
    # above) before _clears_premarket_liquidity (monkeypatched below) is
    # ever reached.
    scanner._latest_quotes["AAPL"] = (99.0, 100.0, datetime.now(timezone.utc))
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )
    monkeypatch.setattr(scanner, "_clears_premarket_liquidity", lambda s: True)
    scanner._last_news_seen["AAPL"] = datetime.now(timezone.utc)

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert scanner.signals_suppressed_premarket_provider_unsupported == 0
    assert scanner.signals_suppressed_premarket_liquidity == 0
    assert scanner.signals_suppressed_news_catalyst == 0
    assert len(scanner._pending_candidates) == 1


@pytest.mark.asyncio
async def test_handle_message_suppresses_premarket_signal_without_recent_news(scanner, monkeypatch):
    candidate = _premarket_signal()
    scanner._latest_quotes["AAPL"] = (99.0, 100.0, datetime.now(timezone.utc))
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )
    monkeypatch.setattr(scanner, "_clears_premarket_liquidity", lambda s: True)
    # No entry in _last_news_seen at all -- fail-closed.

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    assert _signal_publishes(scanner) == []
    assert scanner.signals_suppressed_news_catalyst == 1
    assert scanner._pending_candidates == []


@pytest.mark.asyncio
async def test_handle_message_suppresses_premarket_signal_with_stale_news(scanner, monkeypatch):
    from datetime import timedelta
    candidate = _premarket_signal()
    scanner._latest_quotes["AAPL"] = (99.0, 100.0, datetime.now(timezone.utc))
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals",
        lambda ticker, snap, config, **kwargs: [candidate],
    )
    monkeypatch.setattr(scanner, "_clears_premarket_liquidity", lambda s: True)
    scanner._last_news_seen["AAPL"] = datetime.now(timezone.utc) - timedelta(hours=5)  # > 4h lookback

    await scanner._handle_message(_priming_bar_message("AAPL"))
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

    await scanner._handle_message(_priming_bar_message("AAPL"))
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
    await scanner._handle_message(_priming_bar_message("AAPL"))
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
async def test_handle_market_tick_does_not_evaluate_on_a_symbols_very_first_tick(scanner, monkeypatch):
    """Closed-Bar Evaluation (2026-08-16 quant audit): a symbol's very
    first tick only OPENS a bucket -- there is no prior closed bar yet,
    so compute_indicators must not be called at all."""
    calls = []
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: calls.append(1) or None)

    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))

    assert calls == []


@pytest.mark.asyncio
async def test_handle_market_tick_does_not_evaluate_while_a_bucket_is_still_forming(scanner, monkeypatch):
    """A second tick landing in the SAME bucket (same floored minute) as
    the first must not trigger evaluation either -- the bar hasn't
    closed, only accumulated another tick."""
    calls = []
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: calls.append(1) or None)

    first = json.loads(_bar_message("AAPL")["data"])
    still_forming = dict(first, close=101.0)  # same "2026-08-07T15:00:00Z" bucket, different price
    await scanner._handle_market_tick(first)
    await scanner._handle_market_tick(still_forming)

    assert calls == []


@pytest.mark.asyncio
async def test_handle_market_tick_evaluates_exactly_once_when_the_bucket_closes(scanner, monkeypatch):
    """Closed-Bar Evaluation: the FIRST tick of a NEW bucket for a symbol
    already being tracked triggers evaluation of the bar that just
    closed -- exactly once per closed bar, not once per tick."""
    calls = []
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: calls.append(1) or None)

    await scanner._handle_market_tick(_priming_bar_payload("AAPL"))  # opens the first bucket
    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))  # closes it, opens the next

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_handle_market_tick_evaluates_against_the_closed_bars_final_values(scanner, monkeypatch):
    """The dataframe passed to compute_indicators when a bar closes must
    reflect the CLOSED bar's own final OHLCV (the priming tick's bucket),
    not the tick that just started the NEXT (still-forming) bucket --
    the core Closed-Bar Evaluation correctness fix: evaluation must never
    see a partial, still-moving candle."""
    captured = []
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: captured.append(df) or None)

    await scanner._handle_market_tick(_priming_bar_payload("AAPL"))  # close=100.0, bucket 14:59
    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))  # close=100.5, bucket 15:00 (new)

    assert len(captured) == 1
    df = captured[0]
    last_row = df.iloc[-1]
    # The evaluated bar is the PRIMING one (14:59, close=100.0) -- NOT
    # the just-arrived 15:00 tick (close=100.5), which only opened the
    # next, still-forming bucket.
    assert last_row["close"] == pytest.approx(100.0)
    assert df.index[-1] == datetime(2026, 8, 7, 14, 59, tzinfo=timezone.utc)


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

    await scanner._handle_market_tick(_priming_bar_payload("AAPL"))
    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))

    # Gated BEFORE evaluate_signals is even called (skips momentum
    # evaluation entirely for a low-beta bar), and no SIGNAL published
    # (a bare rejection trace event still is -- see Rejection Trace
    # Logging tests below).
    assert evaluate_called["n"] == 0
    assert _signal_publishes(scanner) == []
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

    await scanner._handle_market_tick(_priming_bar_payload("AAPL"))
    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))

    assert _signal_publishes(scanner) == []
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

    await scanner._handle_market_tick(_priming_bar_payload("AAPL"))
    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))

    # The BULLISH candidate is dropped, but the BEARISH one survives this
    # gate and proceeds into the rest of the pipeline (queued for the
    # next throttle flush) -- an open position should still be able to
    # exit before EOD-flatten. Cooldown isn't armed yet at this point
    # (Post-Publication Cooldown Trigger) -- only once actually published.
    assert scanner.signals_suppressed_closing_blackout == 1
    assert _cooldown_set_calls(scanner) == []
    assert len(scanner._pending_candidates) == 1
    assert scanner._pending_candidates[0].direction == SignalDirection.BEARISH


@pytest.mark.asyncio
async def test_handle_market_tick_no_blackout_during_active_session(scanner, monkeypatch):
    # 11:00 ET = 15:00 UTC -- deep in the active window, outside both
    # blackout sub-windows.
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(
        consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [_signal("AAPL", 3.0)],
    )

    await scanner._handle_market_tick(_priming_bar_payload("AAPL"))
    await scanner._handle_market_tick(json.loads(_bar_message("AAPL")["data"]))

    assert scanner.signals_suppressed_opening_blackout == 0
    assert scanner.signals_suppressed_closing_blackout == 0


# --- Rejection Trace Logging ----------------------------------------------

@pytest.mark.asyncio
async def test_record_rejection_calls_store_and_publishes_one_event(scanner, tmp_path):
    scanner.store = QuantStateStore(tmp_path / "quant.db")
    when = datetime(2026, 8, 16, 15, 0, tzinfo=timezone.utc)

    await scanner._record_rejection("AAPL", "TREND_GATE", 1, when)

    counts = scanner.store.suppression_counts_for_date("2026-08-16")
    assert len(counts) == 1
    assert counts[0]["ticker"] == "AAPL"
    assert counts[0]["reason"] == "TREND_GATE"
    assert counts[0]["count"] == 1

    rejections = _rejection_publishes(scanner)
    assert len(rejections) == 1
    payload = json.loads(rejections[0])
    assert payload["ticker"] == "AAPL"
    assert payload["reason"] == "TREND_GATE"
    assert payload["gate"] == "trend_gate"  # acceptance criteria's own example gate name


@pytest.mark.asyncio
async def test_record_rejection_uses_rr_gate_name_for_low_risk_reward(scanner):
    await scanner._record_rejection("AAPL", "LOW_RISK_REWARD", 1, datetime.now(timezone.utc))

    payload = json.loads(_rejection_publishes(scanner)[0])
    assert payload["gate"] == "rr_gate"  # acceptance criteria's own example gate name


@pytest.mark.asyncio
async def test_record_rejection_publishes_one_event_per_candidate_with_full_detail(scanner):
    dropped = [
        _signal("AAPL", 3.0, signal_type=SignalType.MACD_BULLISH_CROSS, confluence_score=1),
        _signal("AAPL", 5.0, signal_type=SignalType.MA_GOLDEN_CROSS, confluence_score=0),
    ]

    await scanner._record_rejection("AAPL", "LOW_CONFLUENCE", 2, datetime.now(timezone.utc), dropped)

    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert len(rejections) == 2  # one per candidate, not one aggregated event
    signal_types = {r["signal_type"] for r in rejections}
    assert signal_types == {"macd_bullish_cross", "ma_golden_cross"}
    confluence_scores = {r["confluence_score"] for r in rejections}
    assert confluence_scores == {0, 1}


@pytest.mark.asyncio
async def test_record_rejection_publishes_bare_events_without_signal_detail(scanner):
    # LOW_VOLATILITY fires before any candidate signal is built --
    # `signals` is None, so `count` alone determines how many bare
    # (ticker/reason only) events are published.
    await scanner._record_rejection("AAPL", "LOW_VOLATILITY", 1, datetime.now(timezone.utc))

    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert len(rejections) == 1
    assert rejections[0]["signal_type"] is None
    assert rejections[0]["gate"] == "volatility_gate"


@pytest.mark.asyncio
async def test_record_rejection_skips_publish_when_client_is_none(scanner, tmp_path):
    scanner.store = QuantStateStore(tmp_path / "quant.db")
    scanner._client = None

    await scanner._record_rejection("AAPL", "TREND_GATE", 1, datetime.now(timezone.utc))  # must not raise

    counts = scanner.store.suppression_counts_for_date(datetime.now(timezone.utc).date().isoformat())
    assert len(counts) == 1  # local suppression-count persistence still happens


@pytest.mark.asyncio
async def test_record_rejection_tolerates_a_publish_failure(scanner):
    scanner._client.publish.side_effect = ConnectionError("redis down")

    await scanner._record_rejection("AAPL", "TREND_GATE", 1, datetime.now(timezone.utc))  # must not raise


@pytest.mark.asyncio
async def test_handle_message_low_risk_reward_rejection_uses_rr_gate(scanner, monkeypatch):
    low_rr = _signal("AAPL", 3.0, confluence_score=3, risk_reward_ratio=1.0)
    monkeypatch.setattr(consumer_module, "compute_indicators", lambda df, config: _snapshot_stub())
    monkeypatch.setattr(consumer_module, "evaluate_signals", lambda ticker, snap, config, **kwargs: [low_rr])

    await scanner._handle_message(_priming_bar_message("AAPL"))
    await scanner._handle_message(_bar_message("AAPL"))

    rejections = [json.loads(p) for p in _rejection_publishes(scanner)]
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "LOW_RISK_REWARD"
    assert rejections[0]["gate"] == "rr_gate"
