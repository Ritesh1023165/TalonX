"""
talonx_ingest.shared_gateway.alpaca_gateway
--------------------------------------------------
AlpacaGatewayProducer -- the ONE process/connection that owns Alpaca
market-data acquisition for Task 88. Polls the same batched
`/v2/stocks/bars/latest` endpoint PIV's session_runner.py already
validated live (see results/task88_shared_gateway/design.md §2.0 for why
REST-poll was chosen over a hand-rolled WebSocket client), normalizes each
bar into a GatewayMarketEvent, and XADDs it onto the shared Redis Stream.

SHADOW_INGESTION_ONLY: this module never imports talonx_piv.broker,
talonx_piv.lifecycle, talonx_paper, or talonx_core -- it cannot place an
order or send an alert even by accident, because it never has a reference
to anything that can.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from talonx_ingest.common.backoff import jittered_backoff_seconds

from . import metrics
from .config import FEED_MODE_PARAM, GatewayConfig
from .event_schema import build_event
from .redis_stream import (
    ORIGINAL_SHADOW_GROUP,
    PIV_SHADOW_GROUP,
    ensure_group,
    publish_event,
)
from .universe import ResolvedUniverse, resolve_universe

logger = logging.getLogger("talonx_ingest.shared_gateway.alpaca_gateway")

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None


@dataclass
class GatewayCounters:
    """In-process, transport-independent tallies -- always readable even
    with Redis down, same "local_counters" posture as
    talonx_ingest.events.publisher.RedisEventPublisher."""
    events_received: int = 0
    events_published: int = 0
    stream_publish_failures: int = 0
    malformed_events: int = 0
    duplicate_events_detected: int = 0
    redis_reconnect_attempts: int = 0
    redis_reconnect_successes: int = 0
    provider_requests_failed: int = 0
    poll_cycles: int = 0

    def as_dict(self) -> dict:
        return {
            "events_received": self.events_received,
            "events_published": self.events_published,
            "stream_publish_failures": self.stream_publish_failures,
            "malformed_events": self.malformed_events,
            "duplicate_events_detected": self.duplicate_events_detected,
            "redis_reconnect_attempts": self.redis_reconnect_attempts,
            "redis_reconnect_successes": self.redis_reconnect_successes,
            "provider_requests_failed": self.provider_requests_failed,
            "poll_cycles": self.poll_cycles,
        }


@dataclass
class AlpacaGatewayProducer:
    config: GatewayConfig
    transport: object  # duck-typed `requests`-shaped .get(url, headers=, params=, timeout=) -- injectable for tests
    universe: ResolvedUniverse | None = None
    counters: GatewayCounters = field(default_factory=GatewayCounters)
    gateway_session_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    _client: object = field(default=None, init=False, repr=False)
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    _last_provider_event_at: dict[str, datetime] = field(default_factory=dict, init=False, repr=False)
    # Cross-cycle dedup: Alpaca's /v2/stocks/bars/latest always returns a
    # symbol's MOST RECENT 1-min bar, which is unchanged until that symbol
    # prints a new one -- sparse (esp. IEX) names would otherwise get the
    # identical bar XADDed every 60s poll. This maps symbol -> the last
    # event_id actually published for it; an unchanged event_id is skipped
    # from the stream and counted as duplicate_events_detected. (PIV's own
    # session_runner.fetch_bars_latest has the same upstream behaviour and
    # handles it the same way -- monotonic per-symbol timestamp guard.)
    _last_published_event_id: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    # Cumulative per-session coverage: symbol -> {last_seen_at, last_new_bar_at,
    # last_provider_timestamp, source}. Accumulates for EVERY symbol we
    # receive any bar for (new or a deduped repeat), so a symbol that has
    # gone quiet still shows its last-seen stamp rather than vanishing from
    # the map -- same "flush the whole accumulated map each beat" shape as
    # talonx_ingest.events.publisher's FC_08 symbol_coverage. An observer
    # computes staleness from last_seen_at; UNACCOUNTED = configured minus
    # keys here.
    _coverage: dict[str, dict] = field(default_factory=dict, init=False, repr=False)
    _last_publish_at: datetime | None = field(default=None, init=False, repr=False)
    _provider_reachable: bool = field(default=True, init=False, repr=False)
    _last_poll_http_status: int | None = field(default=None, init=False, repr=False)

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def local_counters(self) -> dict:
        return self.counters.as_dict()

    async def _connect(self) -> None:
        if redis_asyncio is None:
            raise ImportError("The 'redis' package is required. Install it with: pip install redis")
        attempt = 0
        while not self._stop_event.is_set():
            try:
                client = redis_asyncio.from_url(
                    self.config.redis_url,
                    socket_connect_timeout=self.config.connect_timeout_seconds,
                    socket_timeout=self.config.socket_timeout_seconds,
                )
                await client.ping()
                self._client = client
                await ensure_group(client, group=ORIGINAL_SHADOW_GROUP)
                await ensure_group(client, group=PIV_SHADOW_GROUP)
                if attempt > 0:
                    self.counters.redis_reconnect_successes += 1
                logger.info("Gateway connected to Redis at %s", self.config.redis_url)
                return
            except Exception as exc:  # noqa: BLE001 -- any connection failure is retried below
                attempt += 1
                self.counters.redis_reconnect_attempts += 1
                wait = jittered_backoff_seconds(
                    attempt, self.config.reconnect_backoff_base_seconds, self.config.reconnect_backoff_max_seconds,
                )
                logger.warning("Gateway Redis connect failed (%s); retrying in %.1fs (attempt %d)", exc, wait, attempt)
                await asyncio.sleep(wait)

    def _fetch_bars_latest(self, symbols: list[str]) -> tuple[dict, int | None]:
        """Same endpoint/params/headers PIV's session_runner.fetch_bars_latest
        already uses live -- deliberately not reimplemented differently.
        Returns (bars_dict, http_status). Never raises -- a fetch failure is
        classified by the caller from the returned (empty, status)."""
        feed = FEED_MODE_PARAM.get(self.config.feed_mode, "iex")
        headers = {"APCA-API-KEY-ID": self.config.key_id, "APCA-API-SECRET-KEY": self.config.secret_key}
        try:
            response = self.transport.get(
                f"{self.config.data_endpoint}/v2/stocks/bars/latest",
                headers=headers, params={"symbols": ",".join(symbols), "feed": feed},
                timeout=self.config.http_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 -- classified as a provider-fetch failure below
            logger.warning("Gateway Alpaca fetch failed: %s", exc)
            return {}, None
        if response.status_code != 200:
            return {}, response.status_code
        return (response.json() or {}).get("bars") or {}, response.status_code

    async def _poll_once(self) -> None:
        poll_cycle_id = str(uuid.uuid4())
        symbols = list(self.universe.configured)
        bars, status = self._fetch_bars_latest(symbols)
        self._last_poll_http_status = status
        self._provider_reachable = status == 200
        if status != 200:
            self.counters.provider_requests_failed += 1
            await metrics.incr_metric(self._client, "provider_requests_failed", 1)
            return

        seen_this_cycle: set[str] = set()
        received_this_cycle = 0
        published_this_cycle = 0
        duplicates_this_cycle = 0
        malformed_this_cycle = 0
        for symbol, row in bars.items():
            symbol = symbol.upper()
            if symbol not in self.universe.origins:
                continue  # not part of the resolved universe -- never silently invented
            if row is None:
                continue
            raw_ts = row.get("t")
            if not raw_ts:
                self.counters.malformed_events += 1
                malformed_this_cycle += 1
                logger.warning("Gateway dropping malformed bar for %s: missing timestamp", symbol)
                continue
            try:
                provider_timestamp = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                event = build_event(
                    symbol=symbol, provider_feed=FEED_MODE_PARAM.get(self.config.feed_mode, "iex"),
                    provider_timestamp=provider_timestamp,
                    gateway_receive_timestamp=datetime.now(timezone.utc),
                    open_=float(row["o"]), high=float(row["h"]), low=float(row["l"]),
                    close=float(row["c"]), volume=float(row["v"]),
                    gateway_session_id=self.gateway_session_id, poll_cycle_id=poll_cycle_id,
                )
            except (KeyError, TypeError, ValueError) as exc:
                self.counters.malformed_events += 1
                malformed_this_cycle += 1
                logger.warning("Gateway dropping malformed bar for %s: %s", symbol, exc)
                continue

            self.counters.events_received += 1
            received_this_cycle += 1
            now_iso = datetime.now(timezone.utc).isoformat()
            # Coverage accumulates for EVERY received bar -- new or deduped
            # repeat -- so a symbol never disappears from the map just
            # because its latest bar hasn't changed. last_new_bar_at is
            # only bumped on a genuinely new bar below.
            cov = self._coverage.setdefault(symbol, {"source": "gateway", "last_new_bar_at": None})
            cov["last_seen_at"] = now_iso
            cov["last_provider_timestamp"] = provider_timestamp.isoformat()

            # in-cycle dup (defensive -- one row per symbol from a real
            # response, but an API retry could duplicate) ...
            if event.event_id in seen_this_cycle:
                self.counters.duplicate_events_detected += 1
                duplicates_this_cycle += 1
                continue
            seen_this_cycle.add(event.event_id)
            # ... and cross-cycle dup: the same latest bar re-returned on a
            # later poll because the symbol has not printed a new one yet.
            if self._last_published_event_id.get(symbol) == event.event_id:
                self.counters.duplicate_events_detected += 1
                duplicates_this_cycle += 1
                continue

            if self._client is None:
                self.counters.stream_publish_failures += 1
                continue
            try:
                await publish_event(self._client, event.to_redis_payload())
                self.counters.events_published += 1
                published_this_cycle += 1
                self._last_published_event_id[symbol] = event.event_id
                self._last_publish_at = datetime.now(timezone.utc)
                self._last_provider_event_at[symbol] = provider_timestamp
                cov["last_new_bar_at"] = now_iso
            except Exception as exc:  # noqa: BLE001 -- a single publish failure must not abort the cycle
                self.counters.stream_publish_failures += 1
                logger.warning("Gateway failed to publish event for %s: %s", symbol, exc)
                self._client = None  # force reconnect on the next tick

        if self._coverage:
            await metrics.write_symbol_coverage(self._client, self._coverage)
        await metrics.incr_metric(self._client, "events_received", received_this_cycle)
        await metrics.incr_metric(self._client, "events_published", published_this_cycle)
        await metrics.incr_metric(self._client, "duplicate_events_detected", duplicates_this_cycle)
        await metrics.incr_metric(self._client, "malformed_events", malformed_this_cycle)
        await metrics.incr_metric(self._client, "poll_cycles", 1)
        self.counters.poll_cycles += 1

    async def _write_liveness_once(self) -> None:
        configured = list(self.universe.configured) if self.universe else []
        covered = sorted(self._coverage.keys())
        unaccounted = sorted(set(configured) - set(covered))
        payload = {
            "component": "gateway",
            "process_alive": True,
            "redis_reachable": self.is_connected,
            "provider_reachable": self._provider_reachable,
            "last_poll_http_status": self._last_poll_http_status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_publish_at": self._last_publish_at.isoformat() if self._last_publish_at else None,
            "configured_symbols": configured,
            "configured_count": len(configured),
            "covered_count": len(covered),
            "unaccounted_symbols": unaccounted,
            "gateway_session_id": self.gateway_session_id,
            "counters": self.local_counters(),
        }
        await metrics.write_liveness(self._client, payload)

    async def run(self) -> None:
        if self.universe is None:
            self.universe = resolve_universe(self.config.original_watchlist_db_path)
        await self._connect()
        logger.info(
            "Shared Alpaca Gateway started: session=%s universe=%d symbols feed=%s poll=%.0fs (SHADOW_INGESTION_ONLY)",
            self.gateway_session_id, len(self.universe.configured), self.config.feed_mode, self.config.poll_interval_seconds,
        )
        last_liveness = 0.0
        loop = asyncio.get_running_loop()
        while not self._stop_event.is_set():
            if self._client is None:
                await self._connect()
            try:
                await self._poll_once()
            except Exception as exc:  # noqa: BLE001 -- one bad cycle must not kill an hours-long gateway process
                logger.warning("Gateway poll cycle failed (will retry next cycle): %s", exc)
            now = loop.time()
            if now - last_liveness >= self.config.liveness_interval_seconds:
                await self._write_liveness_once()
                last_liveness = now
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.config.poll_interval_seconds)
            except asyncio.TimeoutError:
                pass
        if self._client is not None:
            await self._client.aclose()
