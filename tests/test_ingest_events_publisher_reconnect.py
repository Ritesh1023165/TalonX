"""
tests/test_ingest_events_publisher_reconnect.py
------------------------------------------------------
2026-08-18 live-incident correctness fix (code-review finding #3):
RedisEventPublisher previously left `_client=None` PERMANENTLY for the
rest of the process's lifetime after either an initial connect() failure
or a runtime publish/incr_metric connection exception -- no retry
anywhere. These tests prove both paths now recover:
  - initial connect() failure -> background reconnect loop -> publication
    resumes once Redis becomes reachable.
  - a runtime connection-level exception during _publish/incr_metric ->
    _client torn down -> background reconnect loop -> publication resumes.

redis.asyncio.from_url and the client instances it would return are
mocked -- these tests never touch a real Redis server, matching every
other test in this project's "mock the external service" convention.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from talonx_ingest.config import RedisConfig
from talonx_ingest.events.publisher import RedisEventPublisher
from talonx_ingest.events.schemas import MarketTickEvent, TickEventType


def _config(**overrides) -> RedisConfig:
    defaults = dict(reconnect_backoff_base_seconds=0.0, reconnect_backoff_max_seconds=0.0)
    defaults.update(overrides)
    return RedisConfig(**defaults)


def _tick() -> MarketTickEvent:
    from datetime import datetime, timezone
    return MarketTickEvent(
        symbol="AAPL", event_type=TickEventType.BAR, source="polling",
        timestamp=datetime.now(timezone.utc), open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0,
    )


async def _drain_reconnect_task(publisher: RedisEventPublisher) -> None:
    """Test helper: await whatever background reconnect task connect()/
    _maybe_handle_disconnect started, so assertions run only after it has
    actually finished (mirrors how a real event loop would eventually
    schedule it -- these tests just don't want to sleep for real)."""
    if publisher._reconnect_task is not None:
        await publisher._reconnect_task


@pytest.mark.asyncio
async def test_initial_connect_failure_starts_reconnect_loop_and_recovers():
    publisher = RedisEventPublisher(_config())

    failing_client = AsyncMock()
    failing_client.ping.side_effect = RedisConnectionError("refused")
    healthy_client = AsyncMock()
    healthy_client.ping.return_value = True

    call_sequence = iter([failing_client, healthy_client])
    with patch("talonx_ingest.events.publisher.redis_asyncio.from_url", side_effect=lambda *a, **k: next(call_sequence)):
        connected = await publisher.connect()
        assert connected is False
        assert publisher._client is None
        assert publisher.is_connected is False

        await _drain_reconnect_task(publisher)

    assert publisher.is_connected is True
    assert publisher._client is healthy_client

    # Publication now works without needing a second connect() call.
    await publisher.publish_market_tick(_tick())
    healthy_client.publish.assert_awaited_once()

    await publisher.close()


@pytest.mark.asyncio
async def test_runtime_connection_error_during_publish_triggers_reconnect_and_resumes():
    publisher = RedisEventPublisher(_config())
    broken_client = AsyncMock()
    broken_client.publish.side_effect = RedisConnectionError("connection lost")
    publisher._client = broken_client  # simulates an already-established, then-lost connection

    healthy_client = AsyncMock()
    healthy_client.ping.return_value = True

    with patch("talonx_ingest.events.publisher.redis_asyncio.from_url", return_value=healthy_client):
        await publisher.publish_market_tick(_tick())  # triggers the failure + starts reconnect
        assert publisher._client is None  # torn down immediately on the connection-level error

        await _drain_reconnect_task(publisher)

    assert publisher.is_connected is True

    await publisher.publish_market_tick(_tick())
    healthy_client.publish.assert_awaited_once()

    await publisher.close()


@pytest.mark.asyncio
async def test_runtime_connection_error_during_incr_metric_triggers_reconnect():
    publisher = RedisEventPublisher(_config())
    broken_client = AsyncMock()
    broken_client.incrby.side_effect = RedisConnectionError("connection lost")
    publisher._client = broken_client

    healthy_client = AsyncMock()
    healthy_client.ping.return_value = True

    with patch("talonx_ingest.events.publisher.redis_asyncio.from_url", return_value=healthy_client):
        await publisher.incr_metric("ingest", "bars_read")
        assert publisher._client is None

        await _drain_reconnect_task(publisher)

    assert publisher.is_connected is True
    await publisher.close()


@pytest.mark.asyncio
async def test_non_connection_error_does_not_tear_down_a_working_client():
    """A narrow, specific classification -- an unrelated/unexpected
    exception (not a redis ConnectionError/TimeoutError) must NOT discard
    an otherwise-healthy client or start a reconnect loop."""
    publisher = RedisEventPublisher(_config())
    client = AsyncMock()
    client.publish.side_effect = ValueError("unexpected, unrelated to connectivity")
    publisher._client = client

    await publisher.publish_market_tick(_tick())  # logged and swallowed, per existing "never propagate" contract

    assert publisher._client is client  # NOT torn down
    assert publisher._reconnect_task is None  # no reconnect loop started


@pytest.mark.asyncio
async def test_second_connect_failure_does_not_start_a_duplicate_reconnect_loop():
    publisher = RedisEventPublisher(_config())
    failing_client = AsyncMock()
    failing_client.ping.side_effect = RedisConnectionError("refused")

    with patch("talonx_ingest.events.publisher.redis_asyncio.from_url", return_value=failing_client):
        await publisher.connect()
        first_task = publisher._reconnect_task
        assert first_task is not None

        # A publish attempt while a reconnect is already in flight must not
        # spawn a second, racing reconnect loop.
        publisher._client = None
        publisher._maybe_handle_disconnect(RedisConnectionError("still down"))
        assert publisher._reconnect_task is first_task

    await publisher.close()


# --- 2026-08-18 /ping observability completion: market_redis_publish_
# failures / market_redis_reconnect_attempts / market_redis_reconnect_
# successes -- genuine counters at the real event points (a publish
# failure, a reconnect attempt, a reconnect success), NOT counting the
# initial connect() call's own first attempt as a "reconnect". ------------

@pytest.mark.asyncio
async def test_successful_publish_does_not_increment_publish_failures():
    publisher = RedisEventPublisher(_config())
    healthy_client = AsyncMock()
    publisher._client = healthy_client

    await publisher.publish_market_tick(_tick())

    assert publisher.publish_failures == 0
    failure_calls = [c for c in healthy_client.incrby.await_args_list if "market_redis_publish_failures" in c.args[0]]
    assert len(failure_calls) == 0


@pytest.mark.asyncio
async def test_publish_failure_increments_publish_failures_counter_and_property():
    publisher = RedisEventPublisher(_config())
    broken_client = AsyncMock()
    broken_client.publish.side_effect = RedisConnectionError("connection lost")
    publisher._client = broken_client

    await publisher.publish_market_tick(_tick())

    assert publisher.publish_failures == 1
    # Best-effort flush attempted through the same (now-broken) client --
    # the ConnectionError makes this write itself also fail silently
    # (already caught inside incr_metric), so no Redis-side assertion here,
    # only the always-available in-process property.


@pytest.mark.asyncio
async def test_reconnect_records_attempts_and_success_property_and_flushes_to_redis():
    publisher = RedisEventPublisher(_config())
    failing_client = AsyncMock()
    failing_client.ping.side_effect = [RedisConnectionError("refused"), RedisConnectionError("refused")]
    healthy_client = AsyncMock()
    healthy_client.ping.return_value = True

    call_sequence = iter([failing_client, failing_client, healthy_client])
    with patch("talonx_ingest.events.publisher.redis_asyncio.from_url", side_effect=lambda *a, **k: next(call_sequence)):
        connected = await publisher.connect()
        assert connected is False
        # The initial connect() failure itself must NOT count as a reconnect.
        assert publisher.reconnect_attempts == 0
        assert publisher.reconnect_successes == 0

        await _drain_reconnect_task(publisher)

    assert publisher.is_connected is True
    assert publisher.reconnect_attempts >= 1
    assert publisher.reconnect_successes == 1
    attempt_calls = [c for c in healthy_client.incrby.await_args_list if "market_redis_reconnect_attempts" in c.args[0]]
    success_calls = [c for c in healthy_client.incrby.await_args_list if "market_redis_reconnect_successes" in c.args[0]]
    assert len(attempt_calls) == 1
    assert len(success_calls) == 1
    assert success_calls[0].args[1] == 1

    await publisher.close()


@pytest.mark.asyncio
async def test_close_cancels_an_in_flight_reconnect_loop_cleanly():
    publisher = RedisEventPublisher(_config(reconnect_backoff_base_seconds=60.0, reconnect_backoff_max_seconds=60.0))
    failing_client = AsyncMock()
    failing_client.ping.side_effect = RedisConnectionError("refused")

    with patch("talonx_ingest.events.publisher.redis_asyncio.from_url", return_value=failing_client):
        await publisher.connect()
        assert publisher._reconnect_task is not None
        assert not publisher._reconnect_task.done()

        await publisher.close()  # must not hang or raise, even mid-backoff-sleep

    assert publisher._reconnect_task is None
    assert publisher._client is None
