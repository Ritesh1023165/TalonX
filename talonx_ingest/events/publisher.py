"""
talonx_ingest.events.publisher
----------------------------------
Thin async wrapper around Redis Pub/Sub for publishing the two event
contracts (MarketTickEvent, NewFilingIngestedEvent) to their channels.

Design choice: Redis publish failures are logged, not raised. Losing the
Redis connection should degrade ingestion to "not broadcasting live
events" -- it should NOT crash a filing ingestion run or a market data
stream that's otherwise working fine and successfully writing to
ChromaDB. Downstream consumers can always re-derive state from ChromaDB;
Pub/Sub is a real-time notification layer on top, not the source of
truth.

Reconnection (2026-08-18 correctness fix, code-review finding #3): the
original version left `_client=None` PERMANENTLY for the rest of the
process's lifetime after either an initial connect() failure or a
runtime publish/incr_metric exception -- there was no retry anywhere, so
a Redis outage lasting even a few seconds around process startup (or a
mid-session blip) silently disabled the live event bus for the process's
entire remaining lifetime, with no recovery even once Redis came back.
Both paths now start a single background reconnect loop (bounded
jittered backoff, same `jittered_backoff_seconds` helper/convention used
throughout this project) that keeps retrying until it reconnects or
close() is called -- never a busy loop, never silently permanent,
clear logs on both giving up on an attempt and on recovery.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from talonx_ingest.common.backoff import jittered_backoff_seconds
from talonx_ingest.config import RedisConfig, settings
from talonx_ingest.events.schemas import (
    MarketTickEvent,
    NewFilingIngestedEvent,
    NewFundamentalsIngestedEvent,
    NewsArticleIngestedEvent,
)

logger = logging.getLogger("talonx_ingest.events.publisher")

try:
    import redis.asyncio as redis_asyncio
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import TimeoutError as RedisTimeoutError
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None
    RedisConnectionError = ConnectionError  # narrow fallback so isinstance() below never NameErrors
    RedisTimeoutError = TimeoutError


class RedisEventPublisher:
    """
    Usage:
        publisher = RedisEventPublisher()
        await publisher.connect()
        await publisher.publish_market_tick(event)
        await publisher.publish_filing_ingested(event)
        await publisher.close()

    Or as an async context manager:
        async with RedisEventPublisher() as publisher:
            await publisher.publish_market_tick(event)
    """

    def __init__(self, config: RedisConfig | None = None):
        self.config = config or settings.redis
        self._client = None
        self._connect_failed_logged = False
        self._closing = False
        self._reconnect_task: asyncio.Task | None = None
        # 2026-08-18 /ping observability fix: in-process, always available
        # (no Redis needed to read them via these properties -- unlike the
        # Redis-backed metrics below, which can only be WRITTEN once
        # connectivity exists at all, see _reconnect_loop's own docstring).
        self._publish_failures = 0
        self._reconnect_attempts = 0
        self._reconnect_successes = 0

    @property
    def publish_failures(self) -> int:
        return self._publish_failures

    @property
    def reconnect_attempts(self) -> int:
        return self._reconnect_attempts

    @property
    def reconnect_successes(self) -> int:
        return self._reconnect_successes

    async def connect(self) -> bool:
        """
        Attempt to connect. Returns True if connected, False otherwise --
        callers should treat False as "publishing is a no-op for THIS
        MOMENT" (not necessarily the rest of the session -- see
        _start_reconnect_loop, kicked off below on failure).
        """
        if redis_asyncio is None:
            logger.warning(
                "The 'redis' package is not installed -- event publishing "
                "disabled. Install it with: pip install redis"
            )
            return False

        if await self._try_connect_once():
            return True
        self._start_reconnect_loop()
        return False

    async def _try_connect_once(self) -> bool:
        try:
            client = redis_asyncio.from_url(
                self.config.url,
                socket_connect_timeout=self.config.connect_timeout_seconds,
                socket_timeout=self.config.socket_timeout_seconds,
            )
            await client.ping()
            self._client = client
            logger.info("Connected to Redis at %s", self.config.url)
            return True
        except Exception as exc:  # noqa: BLE001 -- any connection failure is non-fatal
            logger.warning(
                "Could not connect to Redis at %s (%s) -- event publishing "
                "disabled until reconnected. Ingestion will continue normally; "
                "only the live Pub/Sub broadcast is affected.",
                self.config.url, exc,
            )
            self._client = None
            return False

    def _start_reconnect_loop(self) -> None:
        """Idempotent -- a second call while a reconnect attempt is
        already in flight is a no-op, never a duplicate/racing loop."""
        if self._closing or (self._reconnect_task is not None and not self._reconnect_task.done()):
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        attempt = 0
        while not self._closing and self._client is None:
            attempt += 1
            self._reconnect_attempts += 1
            wait = jittered_backoff_seconds(
                attempt, self.config.reconnect_backoff_base_seconds, self.config.reconnect_backoff_max_seconds,
            )
            await asyncio.sleep(wait)
            if self._closing:
                return
            if await self._try_connect_once():
                self._reconnect_successes += 1
                # Flushed here, not per-attempt above -- there is no
                # connected client to write through UNTIL this exact
                # instant (that's the whole reason a reconnect loop
                # exists), so the attempt count accumulated during the
                # outage is reported as a single delta the moment
                # connectivity returns. Never fired for the initial
                # connect() call's own first attempt (that path never
                # reaches _reconnect_loop at all -- see connect()), so
                # this never miscounts a normal startup connect as a
                # "reconnect".
                await self.incr_metric("ingest", "market_redis_reconnect_attempts", attempt)
                await self.incr_metric("ingest", "market_redis_reconnect_successes", 1)
                logger.info("Redis event publisher reconnected at %s (after %d attempt(s))", self.config.url, attempt)
                return
        # loop exits without reconnecting only if close() was called mid-retry -- not logged as a failure

    async def close(self) -> None:
        self._closing = True
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- shutdown must never raise
                pass
            self._reconnect_task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "RedisEventPublisher":
        await self.connect()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    async def publish_market_tick(self, event: MarketTickEvent) -> None:
        await self._publish(self.config.market_stream_channel, event.to_redis_payload())

    async def publish_filing_ingested(self, event: NewFilingIngestedEvent) -> None:
        await self._publish(self.config.filings_events_channel, event.to_redis_payload())

    async def publish_fundamentals_ingested(self, event: NewFundamentalsIngestedEvent) -> None:
        await self._publish(self.config.fundamentals_events_channel, event.to_redis_payload())

    async def publish_news_ingested(self, event: NewsArticleIngestedEvent) -> None:
        await self._publish(self.config.news_events_channel, event.to_redis_payload())

    async def write_ws_heartbeat(self, source: str) -> None:
        """
        `/ping`'s WebSocket-status source (talonx_dispatch) -- a plain
        Redis key (SET ... EX, not Pub/Sub), refreshed on every market
        event this process handles. A missing/expired key reads as
        "disconnected/unknown" to any reader, so this is opportunistic
        (best-effort, never raises) rather than a channel a subscriber
        must actively listen on.
        """
        if self._client is None:
            return
        payload = json.dumps({
            "source": source,
            "connected": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            await self._client.set(
                self.config.ws_heartbeat_key, payload, ex=self.config.ws_heartbeat_ttl_seconds
            )
        except Exception as exc:  # noqa: BLE001 -- a heartbeat write must never break ingestion
            logger.warning("Failed to write WS heartbeat to Redis: %s", exc)

    async def incr_metric(self, stage: str, counter: str, amount: int = 1) -> None:
        """Stage-Gate Metric Funnel (Phase 2 requirement doc): atomic,
        per-UTC-day Redis counters at `metrics:{YYYY-MM-DD}:{stage}:{counter}`,
        read by talonx_dispatch's Daily Funnel dashboard tab. Each module
        re-declares this same small helper locally rather than sharing
        one (talonx_quant/talonx_core/talonx_brain/talonx_dispatch each
        have their own copy) -- same "no internal library between
        modules" convention this project uses everywhere else. Never
        raises -- a metrics-write failure must not affect ingestion."""
        if self._client is None or amount <= 0:
            return
        key = f"metrics:{datetime.now(timezone.utc):%Y-%m-%d}:{stage}:{counter}"
        try:
            new_value = await self._client.incrby(key, amount)
            if new_value == amount:
                await self._client.expire(key, 2764800)  # 32 days
        except Exception as exc:  # noqa: BLE001 -- telemetry must never break ingestion
            logger.warning("Metric increment failed for %s: %s", key, exc)
            self._maybe_handle_disconnect(exc)

    async def _publish(self, channel: str, payload: str) -> None:
        if self._client is None:
            return  # publishing disabled (not connected) -- silent no-op by design
        try:
            await self._client.publish(channel, payload)
        except Exception as exc:  # noqa: BLE001 -- never let a publish failure propagate
            logger.warning("Failed to publish to Redis channel %s: %s", channel, exc)
            self._publish_failures += 1
            # Best-effort: uses the SAME (possibly now-broken) client this
            # publish just failed against, since _maybe_handle_disconnect
            # below hasn't torn it down yet -- if the failure was
            # connection-level, this write will typically also fail
            # (already silently caught inside incr_metric itself), losing
            # this one data point rather than crashing; acceptable, same
            # best-effort posture every metric write in this codebase
            # already has.
            await self.incr_metric("ingest", "market_redis_publish_failures", 1)
            self._maybe_handle_disconnect(exc)

    def _maybe_handle_disconnect(self, exc: Exception) -> None:
        """Only a genuine connection-level failure (not an arbitrary/
        unexpected error that might have nothing to do with connectivity)
        tears down `_client` and starts the reconnect loop -- a narrow,
        specific classification rather than reacting to every exception,
        so a one-off unrelated error doesn't discard an otherwise-healthy
        connection."""
        if isinstance(exc, (RedisConnectionError, RedisTimeoutError)) and self._client is not None:
            logger.warning("Redis connection appears lost -- will attempt to reconnect in the background.")
            self._client = None
            self._start_reconnect_loop()
