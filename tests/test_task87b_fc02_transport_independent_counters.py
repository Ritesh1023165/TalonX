"""Task 87B FC_02 -- transport-independent Redis-failure accounting.

Proves a publish failure (and a publish DROPPED while disconnected) is
recorded in an in-process tally that does not ride the failing transport,
that the delta later reconciles to Redis exactly once (no double count),
and that UTC-day key semantics are preserved.

TEST_FIXTURE_ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from talonx_ingest.events.publisher import RedisEventPublisher

try:
    from redis.exceptions import ConnectionError as RedisConnectionError
except ImportError:  # pragma: no cover
    RedisConnectionError = ConnectionError


def _config():
    from talonx_ingest.config import RedisConfig
    return RedisConfig()


def _today_key() -> str:
    return f"metrics:{datetime.now(timezone.utc):%Y-%m-%d}:ingest:market_redis_publish_failures"


@pytest.mark.asyncio
async def test_publish_while_disconnected_is_counted_not_silently_dropped():
    pub = RedisEventPublisher(_config())
    pub._client = None  # disconnected
    await pub._publish("talonx:some:channel", "{}")
    await pub._publish("talonx:some:channel", "{}")
    assert pub.publish_failures == 2
    assert pub.dropped_while_disconnected == 2
    assert pub.local_counters()["publish_failures"] == 2


@pytest.mark.asyncio
async def test_publish_exception_does_not_write_failure_counter_over_broken_transport():
    pub = RedisEventPublisher(_config())
    broken = AsyncMock()
    broken.publish.side_effect = RedisConnectionError("connection lost")
    pub._client = broken
    await pub._publish("c", "{}")
    assert pub.publish_failures == 1
    # No attempt to incrby the failure counter over the just-failed client.
    failure_incrs = [c for c in broken.incrby.await_args_list if "market_redis_publish_failures" in c.args[0]]
    assert failure_incrs == []


@pytest.mark.asyncio
async def test_delta_reconciles_to_redis_exactly_once_on_reconnect():
    pub = RedisEventPublisher(_config())
    pub._client = None
    for _ in range(3):
        await pub._publish("c", "{}")
    assert pub.publish_failures == 3 and pub._publish_failures_flushed == 0

    healthy = AsyncMock()
    healthy.incrby = AsyncMock(return_value=3)
    pub._client = healthy
    await pub._flush_publish_failure_delta()

    calls = [c for c in healthy.incrby.await_args_list if c.args[0] == _today_key()]
    assert len(calls) == 1 and calls[0].args[1] == 3
    assert pub._publish_failures_flushed == 3

    # A second flush with no new failures is a no-op (no double count).
    healthy.incrby.reset_mock()
    await pub._flush_publish_failure_delta()
    assert healthy.incrby.await_count == 0


@pytest.mark.asyncio
async def test_flush_rolls_back_when_redis_incrby_fails_so_it_retries_later():
    pub = RedisEventPublisher(_config())
    pub._client = None
    await pub._publish("c", "{}")
    flaky = AsyncMock()
    flaky.incrby = AsyncMock(side_effect=RedisConnectionError("still flaky"))
    pub._client = flaky
    await pub._flush_publish_failure_delta()
    assert pub._publish_failures_flushed == 0  # not actually flushed -> will retry

    flaky.incrby = AsyncMock(return_value=1)
    await pub._flush_publish_failure_delta()
    assert pub._publish_failures_flushed == 1


@pytest.mark.asyncio
async def test_incr_metric_opportunistically_drains_backlog_over_healthy_client():
    pub = RedisEventPublisher(_config())
    pub._client = None
    await pub._publish("c", "{}")
    await pub._publish("c", "{}")

    healthy = AsyncMock()
    healthy.incrby = AsyncMock(return_value=5)
    pub._client = healthy
    await pub.incr_metric("ingest", "bars_read", 1)  # normal metric call

    keys = [c.args[0] for c in healthy.incrby.await_args_list]
    assert _today_key() in keys                       # backlog drained
    assert any(k.endswith(":ingest:bars_read") for k in keys)  # and the metric itself still written
    assert pub._publish_failures_flushed == 2


@pytest.mark.asyncio
async def test_successful_publish_still_never_touches_failure_counter():
    pub = RedisEventPublisher(_config())
    healthy = AsyncMock()
    pub._client = healthy
    await pub._publish("c", "{}")
    assert pub.publish_failures == 0
    assert [c for c in healthy.incrby.await_args_list if "market_redis_publish_failures" in str(c)] == []
