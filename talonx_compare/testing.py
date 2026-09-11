"""Deterministic in-memory fakes for offline Original/PIV rehearsal.

TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. Nothing here touches a real
network, a real Redis instance, or any production state directory. The
fake Redis models the one property that matters for isolation testing:
**Pub/Sub is server-wide and ignores the selected database**, so channel
name collisions are not saved by putting the two pipelines on different
DBs.
"""

from __future__ import annotations

from collections import defaultdict
import fnmatch
import json
from typing import Any, Callable


class _FakeServer:
    """One 'redis-server': many logical DBs for key/value, ONE Pub/Sub bus
    shared across all of them (matching real Redis semantics)."""

    def __init__(self) -> None:
        self.kv: dict[int, dict[str, bytes]] = defaultdict(dict)
        self.channels: dict[str, list["FakePubSub"]] = defaultdict(list)
        self.async_channels: dict[str, list[Any]] = defaultdict(list)
        self.publish_log: list[tuple[str, str]] = []


class FakePubSub:
    def __init__(self, server: _FakeServer) -> None:
        self._server = server
        self._subscribed: set[str] = set()
        self._queue: list[dict[str, Any]] = []

    def subscribe(self, *channels: str) -> None:
        for ch in channels:
            self._subscribed.add(ch)
            self._server.channels[ch].append(self)

    def unsubscribe(self, *channels: str) -> None:
        for ch in channels or list(self._subscribed):
            self._subscribed.discard(ch)
            if self in self._server.channels.get(ch, []):
                self._server.channels[ch].remove(self)

    def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 0.0) -> dict[str, Any] | None:
        if self._queue:
            return self._queue.pop(0)
        return None

    def _deliver(self, channel: str, data: str) -> None:
        self._queue.append({"type": "message", "channel": channel, "data": data})

    def close(self) -> None:
        self.unsubscribe()

    aclose = close


class FakeRedis:
    """Synchronous fake supporting the read surface the collector and the
    dashboard views use (``ping``/``scan_iter``/``mget``/``get``), plus
    ``publish``/``pubsub`` so a test can simulate live traffic. Records
    every mutating call so a test can assert the collector never made
    one."""

    def __init__(self, *, db: int = 0, server: _FakeServer | None = None, unreachable: bool = False) -> None:
        self._server = server or _FakeServer()
        self.db = db
        self.unreachable = unreachable
        self.write_calls: list[tuple[str, tuple, dict]] = []

    # -- connection --
    def ping(self) -> bool:
        if self.unreachable:
            raise ConnectionError("fake redis unreachable")
        return True

    def close(self) -> None:  # noqa: D401
        pass

    # -- key/value (DB-scoped) --
    def set(self, key: str, value: Any, **kw: Any) -> None:
        self.write_calls.append(("set", (key, value), kw))
        self._server.kv[self.db][key] = value if isinstance(value, bytes) else str(value).encode()

    def incr(self, key: str, amount: int = 1) -> int:
        self.write_calls.append(("incr", (key, amount), {}))
        cur = int(self._server.kv[self.db].get(key, b"0"))
        cur += amount
        self._server.kv[self.db][key] = str(cur).encode()
        return cur

    def delete(self, *keys: str) -> int:
        self.write_calls.append(("delete", keys, {}))
        n = 0
        for k in keys:
            n += int(self._server.kv[self.db].pop(k, None) is not None)
        return n

    def get(self, key: str) -> bytes | None:
        if self.unreachable:
            raise ConnectionError("fake redis unreachable")
        return self._server.kv[self.db].get(key)

    def mget(self, keys: list[str]) -> list[bytes | None]:
        if self.unreachable:
            raise ConnectionError("fake redis unreachable")
        return [self._server.kv[self.db].get(k) for k in keys]

    def scan_iter(self, match: str = "*", count: int = 100):
        if self.unreachable:
            raise ConnectionError("fake redis unreachable")
        for k in list(self._server.kv[self.db].keys()):
            if fnmatch.fnmatch(k, match):
                yield k

    # -- Pub/Sub (server-wide -- DB is irrelevant) --
    def publish(self, channel: str, message: str) -> int:
        self.write_calls.append(("publish", (channel, message), {}))
        self._server.publish_log.append((channel, message))
        subs = self._server.channels.get(channel, [])
        for sub in subs:
            sub._deliver(channel, message)
        return len(subs)

    def pubsub(self) -> FakePubSub:
        return FakePubSub(self._server)

    # -- helpers for tests --
    def seed_metric(self, date: str, module: str, counter: str, value: int) -> None:
        """Directly seed a ``metrics:{date}:{module}:{counter}`` counter
        (bypasses write_calls -- this is test scaffolding, not collector
        behaviour)."""
        self._server.kv[self.db][f"metrics:{date}:{module}:{counter}"] = str(value).encode()


def make_pair(*, unreachable_original: bool = False, unreachable_piv: bool = False) -> tuple[FakeRedis, FakeRedis]:
    """A shared fake server exposed as an 'Original' handle on DB 0 and a
    'PIV' handle on DB 1 -- key space separated, Pub/Sub shared."""
    server = _FakeServer()
    return (
        FakeRedis(db=0, server=server, unreachable=unreachable_original),
        FakeRedis(db=1, server=server, unreachable=unreachable_piv),
    )


# --------------------------------------------------------------------------
# PIV state-dir fixture builder
# --------------------------------------------------------------------------

_DEF_SESSION = "piv_2026-08-28_100000_abcd1234"
_DEF_DATE = "2026-08-28"


def write_piv_state(
    state_dir,
    *,
    session_id: str = _DEF_SESSION,
    trading_date: str = _DEF_DATE,
    runtime_sha: str = "e153450",
    config_hash: str = "cfg0001",
    feed_mode: str = "RESEARCH_SIP",
    events: list[dict[str, Any]] | None = None,
    decisions: dict[str, dict] | None = None,
    shadow: dict[str, dict] | None = None,
    lifecycle: dict[str, Any] | None = None,
    freshness: dict[str, Any] | None = None,
    reconciliation: dict[str, Any] | None = None,
    readiness: dict[str, Any] | None = None,
    eod: dict[str, Any] | None = None,
    write_identity: bool = True,
) -> None:
    """Write a coherent PIV state directory. Every argument defaults to a
    minimal, internally-consistent value so a test overrides only what it
    is exercising."""
    from pathlib import Path

    sd = Path(state_dir)
    sd.mkdir(parents=True, exist_ok=True)

    if write_identity:
        (sd / "session_identity.json").write_text(json.dumps({
            "session_id": session_id, "trading_date_et": trading_date,
            "runtime_start_utc": f"{trading_date}T13:30:00+00:00",
            "runtime_sha": runtime_sha, "config_hash": config_hash, "feed_mode": feed_mode,
        }, indent=2), encoding="utf-8")

    if events is None:
        events = [
            {"event": "PAPER_SESSION_STARTED", "timestamp": f"{trading_date}T13:31:00+00:00",
             "session_id": session_id, "trading_date_et": trading_date},
            {"event": "SIGNAL", "timestamp": f"{trading_date}T14:05:00+00:00", "symbol": "AAPL",
             "session_id": session_id, "trading_date_et": trading_date, "source": "STRATEGY",
             "correlation_id": "d1"},
        ]
    with (sd / "piv_events.jsonl").open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, sort_keys=True) + "\n")

    (sd / "decision_ledger.json").write_text(json.dumps(decisions if decisions is not None else {
        "d1": {"session_id": session_id, "trading_date_et": trading_date, "symbol": "AAPL",
               "timestamp": f"{trading_date}T14:05:30+00:00", "recommendation": "HOLD",
               "reason_codes": ["STRATEGY_UNVALIDATED_NO_ACTIONABLE_BUY_PROMOTION"],
               "market_view": "BULLISH", "decision_execution_status": "NO_ACTION",
               "data_readiness": "COMPLETE"},
    }, indent=2), encoding="utf-8")

    (sd / "shadow_ledger.json").write_text(
        json.dumps(shadow if shadow is not None else {}, indent=2), encoding="utf-8")

    (sd / "lifecycle_state.json").write_text(json.dumps(lifecycle if lifecycle is not None else {
        "orders": {}, "positions": {}, "session_enabled": True, "kill_switch": False,
        "reconciliation_flags": {},
    }, indent=2), encoding="utf-8")

    if freshness is not None:
        (sd / "freshness_report.json").write_text(json.dumps(freshness, indent=2), encoding="utf-8")
    if reconciliation is not None:
        (sd / "latest_reconciliation.json").write_text(json.dumps(reconciliation, indent=2), encoding="utf-8")
    if readiness is not None:
        (sd / "session_readiness_state.json").write_text(json.dumps(readiness, indent=2), encoding="utf-8")
    if eod is not None:
        (sd / "eod_state.json").write_text(json.dumps(eod, indent=2), encoding="utf-8")


class RecordingTelegram:
    """Stand-in for any Telegram sender. Counts calls; a PIV wiring that
    is correct never constructs, let alone calls, one of these."""

    def __init__(self) -> None:
        self.attempts = 0
        self.messages: list[str] = []

    def __call__(self, text: str) -> bool:
        self.attempts += 1
        self.messages.append(text)
        return True


# --------------------------------------------------------------------------
# Async fake Redis for driving the REAL CollectorService (Task 83-R1 §7)
# --------------------------------------------------------------------------

class AsyncFakePubSub:
    def __init__(self, server: "_FakeServer", *, fail_after: int | None = None) -> None:
        self._server = server
        self._subscribed: set[str] = set()
        self._queue: list[dict[str, Any]] = []
        self._fail_after = fail_after
        self._gets = 0

    async def subscribe(self, *channels: str) -> None:
        for ch in channels:
            self._subscribed.add(ch)
            self._server.async_channels[ch].append(self)

    async def unsubscribe(self, *channels: str) -> None:
        for ch in channels or list(self._subscribed):
            self._subscribed.discard(ch)
            subs = self._server.async_channels.get(ch, [])
            if self in subs:
                subs.remove(self)

    async def get_message(self, ignore_subscribe_messages: bool = True, timeout: float = 0.0):
        import asyncio

        self._gets += 1
        if self._fail_after is not None and self._gets > self._fail_after:
            raise ConnectionError("simulated PubSub drop")
        if self._queue:
            return self._queue.pop(0)
        # honour the poll timeout (bounded) so the subscribe loop yields
        # to the event loop instead of hot-spinning -- matches real redis.
        await asyncio.sleep(min(timeout, 0.01) if timeout else 0.005)
        return None

    def _deliver(self, channel: str, data: str) -> None:
        self._queue.append({"type": "message", "channel": channel, "data": data})

    async def aclose(self) -> None:
        await self.unsubscribe()

    close = aclose


class AsyncFakeRedis:
    """Minimal async client matching what CollectorService._subscribe uses:
    ``ping`` / ``pubsub`` / ``aclose``. ``unreachable`` makes ``ping``
    raise (subscription -> DISCONNECTED, never NOT_RUN)."""

    def __init__(self, server: "_FakeServer", *, unreachable: bool = False,
                 fail_ping_times: int = 0, pubsub_fail_after: int | None = None) -> None:
        self._server = server
        self.unreachable = unreachable
        self._fail_ping_times = fail_ping_times
        self._pings = 0
        self._pubsub_fail_after = pubsub_fail_after

    async def ping(self) -> bool:
        self._pings += 1
        if self.unreachable or self._pings <= self._fail_ping_times:
            raise ConnectionError("simulated redis unreachable")
        return True

    def pubsub(self) -> AsyncFakePubSub:
        return AsyncFakePubSub(self._server, fail_after=self._pubsub_fail_after)

    async def aclose(self) -> None:
        pass

    # sync publish helper for tests to inject "live" traffic
    def publish_sync(self, channel: str, data: str) -> None:
        self._server.publish_log.append((channel, data))
        for sub in list(self._server.async_channels.get(channel, [])):
            sub._deliver(channel, data)


def install_async_fakes(monkeypatch, *, original: "AsyncFakeRedis", piv: "AsyncFakeRedis") -> None:
    """Patch ``redis.asyncio.from_url`` so the Original URL yields
    ``original`` and the PIV URL yields ``piv``. Server-wide Pub/Sub is
    modelled: both share one bus."""
    import redis.asyncio as _ra

    def _from_url(url, *a, **k):
        return piv if url.rstrip("/").endswith("/1") else original

    monkeypatch.setattr(_ra, "from_url", _from_url)


def new_async_server():
    return _FakeServer()
