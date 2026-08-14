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
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

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
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None


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

    async def connect(self) -> bool:
        """
        Attempt to connect. Returns True if connected, False otherwise --
        callers should treat False as "publishing is a no-op for this
        session" rather than an exception to handle everywhere.
        """
        if redis_asyncio is None:
            logger.warning(
                "The 'redis' package is not installed -- event publishing "
                "disabled. Install it with: pip install redis"
            )
            return False

        try:
            self._client = redis_asyncio.from_url(
                self.config.url,
                socket_connect_timeout=self.config.connect_timeout_seconds,
                socket_timeout=self.config.socket_timeout_seconds,
            )
            await self._client.ping()
            logger.info("Connected to Redis at %s", self.config.url)
            return True
        except Exception as exc:  # noqa: BLE001 -- any connection failure is non-fatal
            logger.warning(
                "Could not connect to Redis at %s (%s) -- event publishing "
                "disabled for this run. Ingestion will continue normally; "
                "only the live Pub/Sub broadcast is affected.",
                self.config.url, exc,
            )
            self._client = None
            return False

    async def close(self) -> None:
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

    async def _publish(self, channel: str, payload: str) -> None:
        if self._client is None:
            return  # publishing disabled (not connected) -- silent no-op by design
        try:
            await self._client.publish(channel, payload)
        except Exception as exc:  # noqa: BLE001 -- never let a publish failure propagate
            logger.warning("Failed to publish to Redis channel %s: %s", channel, exc)
