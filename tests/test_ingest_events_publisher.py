"""
tests/test_ingest_events_publisher.py
------------------------------------------
Tests talonx_ingest.events.publisher.RedisEventPublisher's two Phase 2
additions: write_ws_heartbeat (/ping's WS-status source) and incr_metric
(the Stage-Gate Metric Funnel's per-module counter helper). Both are
opportunistic, best-effort writes -- neither should ever raise, matching
every other publish call in this module.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from talonx_ingest.events.publisher import RedisEventPublisher


def _publisher(client) -> RedisEventPublisher:
    publisher = RedisEventPublisher()
    publisher._client = client
    return publisher


@pytest.mark.asyncio
async def test_write_ws_heartbeat_sets_key_with_ttl_and_source():
    client = AsyncMock()
    publisher = _publisher(client)

    await publisher.write_ws_heartbeat("websocket")

    args, kwargs = client.set.await_args
    assert args[0] == publisher.config.ws_heartbeat_key
    payload = json.loads(args[1])
    assert payload["source"] == "websocket"
    assert payload["connected"] is True
    assert kwargs["ex"] == publisher.config.ws_heartbeat_ttl_seconds


@pytest.mark.asyncio
async def test_write_ws_heartbeat_is_a_noop_when_not_connected():
    publisher = _publisher(None)

    await publisher.write_ws_heartbeat("polling")  # must not raise


@pytest.mark.asyncio
async def test_write_ws_heartbeat_swallows_redis_errors():
    client = AsyncMock()
    client.set.side_effect = ConnectionError("redis down")
    publisher = _publisher(client)

    await publisher.write_ws_heartbeat("websocket")  # must not raise


@pytest.mark.asyncio
async def test_incr_metric_uses_date_bucketed_key_and_sets_ttl_on_first_write():
    client = AsyncMock()
    client.incrby.return_value = 1
    publisher = _publisher(client)

    await publisher.incr_metric("ingest", "bars_read")

    key = client.incrby.await_args.args[0]
    assert key.startswith("metrics:")
    assert key.endswith(":ingest:bars_read")
    client.expire.assert_awaited_once_with(key, 2764800)


@pytest.mark.asyncio
async def test_incr_metric_does_not_reset_ttl_on_subsequent_writes():
    client = AsyncMock()
    client.incrby.return_value = 42
    publisher = _publisher(client)

    await publisher.incr_metric("ingest", "filings_parsed")

    client.expire.assert_not_awaited()


@pytest.mark.asyncio
async def test_incr_metric_is_a_noop_with_no_client_or_zero_amount():
    await _publisher(None).incr_metric("ingest", "bars_read")  # must not raise
    client = AsyncMock()
    await _publisher(client).incr_metric("ingest", "bars_read", amount=0)
    client.incrby.assert_not_awaited()


@pytest.mark.asyncio
async def test_incr_metric_swallows_redis_errors():
    client = AsyncMock()
    client.incrby.side_effect = ConnectionError("redis down")
    publisher = _publisher(client)

    await publisher.incr_metric("ingest", "bars_read")  # must not raise
