"""
talonx_ingest.shared_gateway.shadow_consumer_base
--------------------------------------------------------
Shared read-only consumer-group loop for Task 88's two shadow consumers
(original_shadow_consumer.py, piv_shadow_consumer.py). Deliberately mirrors
talonx_compare/runner.py's own "subscribe read-only, buffer, never
re-publish, independent per-pipeline health, reconnect without message
loss" pattern -- see results/task88_shared_gateway/architecture_before.md
§15, which identifies talonx_compare as the exact existing precedent for
this shape.

SHADOW_INGESTION_ONLY by construction: `sink` is caller-injected and this
base class does not import, construct, or reference any lifecycle/broker/
execution class. The production entrypoint (lifecycle.py) only ever wires
a counting sink; only the OFFLINE REPLAY phase (Phase 5, a separate,
explicitly-labelled script) wires a real, freestanding QuantScanner
instance -- never the live, running Original/PIV process.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from talonx_ingest.common.backoff import jittered_backoff_seconds

from . import metrics
from .event_schema import GatewayMarketEvent
from .redis_stream import (
    MAX_DELIVERY_ATTEMPTS,
    STREAM_KEY,
    StreamEntry,
    ack,
    claim_pending,
    delivery_count,
    ensure_group,
    group_lag,
    move_to_deadletter,
    read_new,
)

logger = logging.getLogger("talonx_ingest.shared_gateway.shadow_consumer_base")

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None

# A pure counter -- the DEFAULT sink for every production wiring path.
# Never touches a real strategy/execution object.
Sink = Callable[[dict], Awaitable[None]]


async def _noop_sink(_mapped: dict) -> None:
    return None


@dataclass
class ShadowConsumerCounters:
    events_consumed: int = 0
    events_deserialize_failed: int = 0
    events_dead_lettered: int = 0
    reconnect_attempts: int = 0
    reconnect_successes: int = 0

    def as_dict(self) -> dict:
        return {
            "events_consumed": self.events_consumed,
            "events_deserialize_failed": self.events_deserialize_failed,
            "events_dead_lettered": self.events_dead_lettered,
            "reconnect_attempts": self.reconnect_attempts,
            "reconnect_successes": self.reconnect_successes,
        }


@dataclass(kw_only=True)
class ShadowConsumerBase:
    """Subclass and implement `_map(event) -> dict` to translate a
    GatewayMarketEvent into your side's own established shape (Original's
    MarketTickEvent-equivalent dict, or PIV's feed_bar dict) -- neither
    existing shape is modified; this only ever produces a new dict matching
    it. `redis_url` MUST be the gateway's db (2), never db 0 or db 1."""

    group: str
    consumer_name: str
    redis_url: str
    # The Stream key this consumer reads. Defaults to the production
    # gateway stream; a test's isolated fixture key or Phase 5's separate
    # frozen replay stream override this explicitly -- never the hardcoded
    # production constant leaking into non-production wiring.
    key: str = STREAM_KEY
    sink: Sink = _noop_sink
    counters: ShadowConsumerCounters = field(default_factory=ShadowConsumerCounters)
    reconnect_backoff_base_seconds: float = 1.0
    reconnect_backoff_max_seconds: float = 30.0
    connect_timeout_seconds: float = 5.0
    socket_timeout_seconds: float = 5.0
    # How long an entry must sit un-acked before THIS consumer's own next
    # loop iteration will self-reclaim it via XAUTOCLAIM and retry (the
    # mechanism that eventually drives a poison entry to MAX_DELIVERY_
    # ATTEMPTS and dead-letters it, even with only one consumer process in
    # the group -- see run()). 30s in production; tests override this to
    # observe the dead-letter path without a real 5x30s wait.
    claim_min_idle_ms: int = 30_000
    # "$" (default) for every live/production consumer -- see
    # redis_stream.ensure_group's own docstring. Only Phase 5's offline
    # replay overrides this to "0" to consume its already-fully-published
    # frozen fixture stream from the beginning.
    group_start_id: str = "$"

    _client: object = field(default=None, init=False, repr=False)
    _stop_event_set: bool = field(default=False, init=False, repr=False)

    def stop(self) -> None:
        self._stop_event_set = True

    def _map(self, event: GatewayMarketEvent) -> dict:  # pragma: no cover - overridden by subclasses
        raise NotImplementedError

    async def _connect(self) -> None:
        if redis_asyncio is None:
            raise ImportError("The 'redis' package is required. Install it with: pip install redis")
        attempt = 0
        while not self._stop_event_set:
            try:
                client = redis_asyncio.from_url(
                    self.redis_url, socket_connect_timeout=self.connect_timeout_seconds,
                    socket_timeout=self.socket_timeout_seconds,
                )
                await client.ping()
                self._client = client
                await ensure_group(client, key=self.key, group=self.group, start_id=self.group_start_id)
                if attempt > 0:
                    self.counters.reconnect_successes += 1
                logger.info("Shadow consumer %s connected to %s", self.group, self.redis_url)
                return
            except Exception as exc:  # noqa: BLE001 -- retried below
                attempt += 1
                self.counters.reconnect_attempts += 1
                wait = jittered_backoff_seconds(attempt, self.reconnect_backoff_base_seconds, self.reconnect_backoff_max_seconds)
                logger.warning("Shadow consumer %s Redis connect failed (%s); retrying in %.1fs", self.group, exc, wait)
                import asyncio
                await asyncio.sleep(wait)

    async def _handle_entry(self, entry: StreamEntry) -> None:
        try:
            event = GatewayMarketEvent.from_redis_payload(entry.payload)
        except Exception as exc:  # noqa: BLE001 -- a malformed entry is dead-lettered, never crashes the loop
            self.counters.events_deserialize_failed += 1
            count = await delivery_count(self._client, entry.entry_id, key=self.key, group=self.group)
            logger.warning("Shadow consumer %s failed to deserialize entry %s (%s): %s", self.group, entry.entry_id, exc, count)
            if count >= MAX_DELIVERY_ATTEMPTS:
                await move_to_deadletter(self._client, entry, key=self.key, group=self.group)
                self.counters.events_dead_lettered += 1
            return
        try:
            mapped = self._map(event)
            await self.sink(mapped)
            await ack(self._client, entry.entry_id, key=self.key, group=self.group)
            self.counters.events_consumed += 1
        except Exception as exc:  # noqa: BLE001 -- handler failure -- leave un-acked for redelivery/dead-letter
            count = await delivery_count(self._client, entry.entry_id, key=self.key, group=self.group)
            logger.warning("Shadow consumer %s handler failed for entry %s (%s), delivery_count=%d", self.group, entry.entry_id, exc, count)
            if count >= MAX_DELIVERY_ATTEMPTS:
                await move_to_deadletter(self._client, entry, key=self.key, group=self.group)
                self.counters.events_dead_lettered += 1

    async def run(self, *, max_iterations: int | None = None) -> None:
        """max_iterations is test-only -- production callers omit it and
        run until stop() is called."""
        await self._connect()
        iterations = 0
        while not self._stop_event_set:
            if self._client is None:
                await self._connect()
            try:
                recovered = await claim_pending(
                    self._client, key=self.key, group=self.group, consumer=self.consumer_name,
                    min_idle_ms=self.claim_min_idle_ms,
                )
                for entry in recovered:
                    await self._handle_entry(entry)
                fresh = await read_new(self._client, key=self.key, group=self.group, consumer=self.consumer_name)
                for entry in fresh:
                    await self._handle_entry(entry)
                lag_map = await group_lag(self._client, key=self.key)
                await metrics.write_consumer_lag(self._client, self.group, lag_map.get(self.group))
            except Exception as exc:  # noqa: BLE001 -- one bad cycle must not kill the consumer loop
                logger.warning("Shadow consumer %s loop error (will reconnect): %s", self.group, exc)
                self._client = None
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
        if self._client is not None:
            await self._client.aclose()
