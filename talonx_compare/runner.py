"""Task 83 §2 -- operational wrapper around ComparisonCollector.

A tiny async loop that:
  - subscribes READ-ONLY to the Original (DB 0) and PIV (DB 1) Pub/Sub
    channels, buffering messages in memory (never re-publishing them),
  - periodically calls ``ComparisonCollector.collect_once`` to fold the
    buffer plus the PIV state files into date-partitioned evidence.

Single-instance: a collector-owned lock file under the collector state
dir (NEVER an Original/PIV lock). Not started by this task -- provided so
the offline rehearsal and a future operator can run it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
import time
from typing import Any

from .collector import ComparisonCollector
from .config import CompareConfig


class CollectorLockError(RuntimeError):
    pass


class CollectorLock:
    """Advisory single-instance lock: collector-owned, best-effort, and
    released on clean exit or when its recorded PID is gone. Abrupt
    termination therefore never leaves an Original/PIV lock held (this
    lock is not one of theirs) and a stale collector lock self-heals."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._held = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                rec = json.loads(self.path.read_text(encoding="utf-8"))
                pid = int(rec.get("pid", -1))
            except (OSError, ValueError, json.JSONDecodeError):
                pid = -1
            if pid > 0 and _pid_alive(pid):
                raise CollectorLockError(f"another collector holds {self.path} (pid {pid})")
        self.path.write_text(json.dumps({"pid": os.getpid(), "acquired_at": time.time()}),
                             encoding="utf-8")
        self._held = True

    def release(self) -> None:
        if self._held:
            with contextlib.suppress(OSError):
                self.path.unlink()
            self._held = False

    def __enter__(self) -> "CollectorLock":
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        try:
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # type: ignore[attr-defined]
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
                return True
        except Exception:  # noqa: BLE001
            return False
        return False
    return True


class CollectorService:
    def __init__(self, config: CompareConfig | None = None, *, interval_seconds: float = 5.0) -> None:
        self.config = config or CompareConfig()
        self.interval = interval_seconds
        self._buffer_original: list[dict[str, Any]] = []
        self._buffer_piv: list[dict[str, Any]] = []
        self._stop = asyncio.Event()

    async def _subscribe(self, url: str, channels: list[str], buffer: list[dict[str, Any]]) -> None:
        import redis.asyncio as redis_asyncio

        while not self._stop.is_set():
            client = redis_asyncio.from_url(url)
            try:
                await client.ping()
                pubsub = client.pubsub()
                await pubsub.subscribe(*channels)
                try:
                    while not self._stop.is_set():
                        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                        if msg is not None:
                            ch = msg.get("channel")
                            if isinstance(ch, bytes):
                                ch = ch.decode()
                            data = msg.get("data")
                            if isinstance(data, bytes):
                                data = data.decode()
                            buffer.append({"channel": ch, "data": data})
                finally:
                    with contextlib.suppress(Exception):
                        await pubsub.unsubscribe(*channels)
                        await pubsub.aclose()
            except Exception:  # noqa: BLE001 -- a transport failure is recorded as DISCONNECTED next pass
                await asyncio.sleep(min(30.0, self.interval))
            finally:
                with contextlib.suppress(Exception):
                    await client.aclose()

    async def _collect_loop(self) -> None:
        collector = ComparisonCollector(self.config)
        while not self._stop.is_set():
            original = self._buffer_original[:]
            piv = self._buffer_piv[:]
            del self._buffer_original[: len(original)]
            del self._buffer_piv[: len(piv)]
            await asyncio.to_thread(
                collector.collect_once,
                captured_original_messages=original or None,
                captured_piv_messages=piv or None,
            )
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)

    async def run(self) -> None:
        with CollectorLock(self.config.lock_path):
            original_channels = list(self.config.original_channels().values())
            piv_channels = list(self.config.piv_channels().values())
            tasks = [
                asyncio.create_task(self._subscribe(
                    self.config.original_redis_url, original_channels, self._buffer_original)),
                asyncio.create_task(self._subscribe(
                    self.config.piv_redis_url, piv_channels, self._buffer_piv)),
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
