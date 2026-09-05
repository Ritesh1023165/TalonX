"""Task 83 §2 / Task 83-R1 §4 -- operational wrapper around
ComparisonCollector.

An async loop that:
  * subscribes READ-ONLY to the Original (DB 0) and PIV (DB 1) Pub/Sub
    channels, buffering messages in memory (never re-publishing them),
  * tracks per-pipeline transport health (attempted / connected /
    subscribed / last message / last error / reconnect count / state) and
  * periodically calls ``ComparisonCollector.collect_once`` with a
    THREAD-SAFE SNAPSHOT of that health plus the drained buffer.

A failed subscription is ``DISCONNECTED`` (not ``NOT_RUN``). One
pipeline's failure never changes the other's health or suppresses its
evidence. On reconnect the collector records recovery evidence and no
buffered message is lost. The buffer swap is race-safe: a message
arriving during a pass stays for the next pass.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from typing import Any

from datetime import datetime, timezone

from .collector import ComparisonCollector
from .config import CompareConfig
from .lock import CollectorLock, CollectorLockError
from .transport import TransportHealth, merged_snapshot

__all__ = ["CollectorService", "CollectorLock", "CollectorLockError"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _Buffer:
    """A tiny thread-safe message buffer. ``swap`` atomically takes
    everything currently queued and leaves a fresh empty list, so a
    producer appending concurrently writes into the NEW list and is
    retained for the next pass."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[dict[str, Any]] = []

    def append(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._items.append(item)

    def swap(self) -> list[dict[str, Any]]:
        with self._lock:
            taken, self._items = self._items, []
            return taken

    def prepend(self, items: list[dict[str, Any]]) -> None:
        with self._lock:
            self._items[:0] = items

    def __len__(self) -> int:  # pragma: no cover - debug aid
        with self._lock:
            return len(self._items)


class CollectorService:
    def __init__(
        self,
        config: CompareConfig | None = None,
        *,
        interval_seconds: float = 5.0,
        clock: Any | None = None,
    ) -> None:
        self.config = config or CompareConfig()
        self.interval = interval_seconds
        self._buffer_original = _Buffer()
        self._buffer_piv = _Buffer()
        self._stop = asyncio.Event()
        self.health_original = TransportHealth("ORIGINAL", stale_seconds=self.config.stale_seconds)
        self.health_piv = TransportHealth("PIV", stale_seconds=self.config.stale_seconds)
        if clock is not None:
            self.health_original._now = clock
            self.health_piv._now = clock
        self.collector = ComparisonCollector(self.config, clock=(clock or _utcnow))
        self._last_result = None

    # --- subscriptions (read-only) --------------------------------

    async def _subscribe(self, url: str, channels: list[str], buffer: _Buffer,
                         health: TransportHealth) -> None:
        import redis.asyncio as redis_asyncio

        first = True
        while not self._stop.is_set():
            health.mark_attempt()
            client = redis_asyncio.from_url(url)
            try:
                await client.ping()
                pubsub = client.pubsub()
                await pubsub.subscribe(*channels)
                health.mark_connected(tuple(channels))
                if not first:
                    # reconnect -- leave a breadcrumb the next collect pass
                    # turns into recovery evidence.
                    buffer.append({"channel": "__collector_meta__",
                                   "data": '{"event":"TRANSPORT_RECONNECT"}'})
                first = False
                try:
                    while not self._stop.is_set():
                        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                        if msg is None:
                            health.mark_heartbeat()
                            continue
                        ch = msg.get("channel")
                        if isinstance(ch, bytes):
                            ch = ch.decode()
                        data = msg.get("data")
                        if isinstance(data, bytes):
                            data = data.decode()
                        buffer.append({"channel": ch, "data": data})
                        health.mark_message()
                finally:
                    with contextlib.suppress(Exception):
                        await pubsub.unsubscribe(*channels)
                        await pubsub.aclose()
            except Exception as exc:  # noqa: BLE001 -- a transport failure is DISCONNECTED, not NOT_RUN
                health.mark_error(f"{type(exc).__name__}: {exc}")
                await asyncio.sleep(min(5.0, self.interval))
            finally:
                with contextlib.suppress(Exception):
                    await client.aclose()

    # --- collection loop ----------------------------------------

    def _snapshot(self) -> dict[str, Any]:
        return merged_snapshot(self.health_original, self.health_piv)

    async def _collect_loop(self) -> None:
        while not self._stop.is_set():
            original = self._buffer_original.swap()
            piv = self._buffer_piv.swap()
            snap = self._snapshot()
            try:
                self._last_result = await asyncio.to_thread(
                    self.collector.collect_once,
                    captured_original_messages=original or None,
                    captured_piv_messages=[m for m in piv if m["channel"] != "__collector_meta__"] or None,
                    transport_health=snap,
                )
            except CollectorLockError:
                # another collector write is in progress -- retained buffer
                # is not lost; retry next tick.
                self._buffer_original.prepend(original)
                self._buffer_piv.prepend(piv)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)

    # --- lifecycle --------------------------------------------

    async def run(self) -> None:
        original_channels = list(self.config.original_channels().values())
        piv_channels = list(self.config.piv_channels().values())
        tasks = [
            asyncio.create_task(self._subscribe(
                self.config.original_redis_url, original_channels,
                self._buffer_original, self.health_original)),
            asyncio.create_task(self._subscribe(
                self.config.piv_redis_url, piv_channels,
                self._buffer_piv, self.health_piv)),
            asyncio.create_task(self._collect_loop()),
        ]
        try:
            await self._stop.wait()
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self) -> None:
        self._stop.set()

    async def run_for(self, passes: int, *, tick: float = 0.02) -> Any:
        """Test helper: run subscriptions, drive ``passes`` collect ticks
        against whatever is buffered, then stop. Returns the last
        CollectResult."""
        original_channels = list(self.config.original_channels().values())
        piv_channels = list(self.config.piv_channels().values())
        subs = [
            asyncio.create_task(self._subscribe(
                self.config.original_redis_url, original_channels,
                self._buffer_original, self.health_original)),
            asyncio.create_task(self._subscribe(
                self.config.piv_redis_url, piv_channels,
                self._buffer_piv, self.health_piv)),
        ]
        try:
            for _ in range(passes):
                await asyncio.sleep(tick)
                original = self._buffer_original.swap()
                piv = self._buffer_piv.swap()
                self._last_result = await asyncio.to_thread(
                    self.collector.collect_once,
                    captured_original_messages=original or None,
                    captured_piv_messages=[m for m in piv if m["channel"] != "__collector_meta__"] or None,
                    transport_health=self._snapshot(),
                )
        finally:
            self._stop.set()
            for t in subs:
                t.cancel()
            await asyncio.gather(*subs, return_exceptions=True)
        return self._last_result
