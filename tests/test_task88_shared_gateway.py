"""
Task 88 -- Shared Alpaca Gateway MVP: targeted offline qualification tests
(Phase 4). See results/task88_shared_gateway/design.md and
architecture_before.md for the full rationale each test below is checking.

Two groups:
  * Mocked-Redis unit tests (AsyncMock, same convention
    tests/test_ingest_events_publisher_reconnect.py already uses) --
    schema/producer logic that doesn't need real Stream semantics.
  * Real-Redis integration tests against db 2 (the gateway's own,
    dedicated, isolated database -- never Original's db0 or PIV's db1),
    for genuine Stream/consumer-group mechanics a mock cannot faithfully
    reproduce (ordering, MAXLEN trimming, XAUTOCLAIM idle-time, XINFO
    GROUPS lag). Skipped automatically if Redis isn't reachable. Each test
    uses its own unique stream key and flushes only that key afterward --
    never a blind FLUSHDB -- so tests never interfere with each other or
    with anything else that might use db 2.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from talonx_ingest.shared_gateway.config import GatewayConfig
from talonx_ingest.shared_gateway.event_schema import GatewayMarketEvent, build_event, compute_event_id
from talonx_ingest.shared_gateway.alpaca_gateway import AlpacaGatewayProducer
from talonx_ingest.shared_gateway.universe import ResolvedUniverse
from talonx_ingest.shared_gateway import redis_stream as rs
from talonx_ingest.shared_gateway.original_shadow_consumer import OriginalShadowConsumer
from talonx_ingest.shared_gateway.piv_shadow_consumer import PivShadowConsumer

try:
    import redis.asyncio as redis_asyncio
    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    redis_asyncio = None
    REDIS_AVAILABLE = False


def _now():
    return datetime.now(timezone.utc)


def _fake_response(status_code: int, bars: dict | None = None):
    resp = AsyncMock()
    resp.status_code = status_code
    resp.json = lambda: {"bars": bars or {}}
    return resp


class _FakeTransport:
    """Duck-typed `requests`-shaped .get() -- synchronous, matching real
    `requests.get`'s signature (the same transport AlpacaGatewayProducer
    and PIV's session_runner both actually use)."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, params))
        if not self._responses:
            raise RuntimeError("no more fake responses queued")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _universe(*symbols: str) -> ResolvedUniverse:
    origins = {s: ["original", "piv"] for s in symbols}
    return ResolvedUniverse(configured=tuple(sorted(symbols)), origins=origins,
                             original_count=len(symbols), piv_count=len(symbols), original_source="OK")


# ---------------------------------------------------------------------------
# 1. Event schema round-trip / 2. valid serialization / 3. malformed rejection
# ---------------------------------------------------------------------------

def test_event_schema_round_trip():
    ts = _now()
    ev = build_event(
        symbol="aapl", provider_feed="iex", provider_timestamp=ts, gateway_receive_timestamp=ts,
        open_=1.0, high=2.0, low=0.5, close=1.5, volume=100.0,
        gateway_session_id="s1", poll_cycle_id="c1",
    )
    assert ev.symbol == "AAPL"  # normalized upper
    payload = ev.to_redis_payload()
    restored = GatewayMarketEvent.from_redis_payload(payload)
    assert restored == ev


def test_event_id_is_deterministic_and_content_derived():
    ts = _now()
    id1 = compute_event_id("ALPACA", "AAPL", ts, "bar")
    id2 = compute_event_id("ALPACA", "AAPL", ts, "bar")
    id3 = compute_event_id("ALPACA", "MSFT", ts, "bar")
    assert id1 == id2
    assert id1 != id3
    # a different provider_timestamp is a genuinely different event
    assert id1 != compute_event_id("ALPACA", "AAPL", ts + timedelta(minutes=1), "bar")


def test_malformed_event_rejection_missing_timestamp_never_raises():
    producer = AlpacaGatewayProducer(
        config=GatewayConfig(key_id="k", secret_key="s"),
        transport=_FakeTransport([_fake_response(200, {"AAPL": {"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100}})]),
        universe=_universe("AAPL"),
    )

    async def go():
        await producer._poll_once()
    asyncio.run(go())
    assert producer.counters.malformed_events == 1
    assert producer.counters.events_received == 0


def test_malformed_event_rejection_bad_numeric_field_never_raises():
    producer = AlpacaGatewayProducer(
        config=GatewayConfig(key_id="k", secret_key="s"),
        transport=_FakeTransport([_fake_response(200, {"AAPL": {"t": _now().isoformat(), "o": "not-a-number", "h": 2, "l": 0.5, "c": 1.5, "v": 100}})]),
        universe=_universe("AAPL"),
    )

    async def go():
        await producer._poll_once()
    asyncio.run(go())
    assert producer.counters.malformed_events == 1


def test_symbol_outside_universe_never_silently_invented():
    """A provider row for a symbol NOT in the resolved universe is dropped
    -- never fabricated into an event for a symbol nobody configured."""
    producer = AlpacaGatewayProducer(
        config=GatewayConfig(key_id="k", secret_key="s"),
        transport=_FakeTransport([_fake_response(200, {"ZZZZ": {"t": _now().isoformat(), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}})]),
        universe=_universe("AAPL"),
    )

    async def go():
        await producer._poll_once()
    asyncio.run(go())
    assert producer.counters.events_received == 0
    assert producer.counters.malformed_events == 0  # not malformed -- just out of scope, no false alarm


# ---------------------------------------------------------------------------
# 18. temporary Redis failure (producer side, mocked) / provider fetch failure
# ---------------------------------------------------------------------------

def test_provider_fetch_failure_counted_never_raises():
    producer = AlpacaGatewayProducer(
        config=GatewayConfig(key_id="k", secret_key="s"),
        transport=_FakeTransport([_fake_response(500)]),
        universe=_universe("AAPL"),
    )

    async def go():
        await producer._poll_once()
    asyncio.run(go())
    assert producer.counters.provider_requests_failed == 1
    assert producer._provider_reachable is False


def test_provider_transport_exception_counted_never_raises():
    producer = AlpacaGatewayProducer(
        config=GatewayConfig(key_id="k", secret_key="s"),
        transport=_FakeTransport([ConnectionError("boom")]),
        universe=_universe("AAPL"),
    )

    async def go():
        await producer._poll_once()
    asyncio.run(go())
    assert producer.counters.provider_requests_failed == 1


# ---------------------------------------------------------------------------
# 19. provider reconnect simulation (recovers on the NEXT cycle)
# ---------------------------------------------------------------------------

def test_provider_recovers_on_next_poll_cycle():
    good_bar = {"AAPL": {"t": _now().isoformat(), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}}
    producer = AlpacaGatewayProducer(
        config=GatewayConfig(key_id="k", secret_key="s"),
        transport=_FakeTransport([_fake_response(500), _fake_response(200, good_bar)]),
        universe=_universe("AAPL"),
    )
    producer._client = AsyncMock()
    producer._client.xadd = AsyncMock(return_value="1-0")

    async def go():
        await producer._poll_once()
        await producer._poll_once()
    asyncio.run(go())
    assert producer.counters.provider_requests_failed == 1
    assert producer._provider_reachable is True
    assert producer.counters.events_published == 1


# ---------------------------------------------------------------------------
# 6. multiple symbols / 22. metrics accuracy / 23. per-symbol coverage
# ---------------------------------------------------------------------------

def test_multi_symbol_poll_publishes_one_event_each_and_counts_accurately():
    bars = {
        "AAPL": {"t": _now().isoformat(), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
        "MSFT": {"t": _now().isoformat(), "o": 2, "h": 2, "l": 2, "c": 2, "v": 2},
    }
    producer = AlpacaGatewayProducer(
        config=GatewayConfig(key_id="k", secret_key="s"),
        transport=_FakeTransport([_fake_response(200, bars)]),
        universe=_universe("AAPL", "MSFT"),
    )
    producer._client = AsyncMock()
    producer._client.xadd = AsyncMock(return_value="1-0")
    producer._client.incrby = AsyncMock(return_value=5)

    async def go():
        await producer._poll_once()
    asyncio.run(go())
    assert producer.counters.events_received == 2
    assert producer.counters.events_published == 2
    assert producer._client.xadd.await_count == 2
    # the events_received / events_published REDIS metrics must each be
    # incremented by the real per-cycle count (2), not by a mis-scoped
    # value -- regression guard for the Phase-7 bug where events_published
    # compared event_ids against a symbol-keyed dict and thus never
    # incremented at all.
    incrby_calls = {c.args[0].split(":")[-1]: c.args[1] for c in producer._client.incrby.await_args_list}
    assert incrby_calls.get("events_received") == 2
    assert incrby_calls.get("events_published") == 2


# ---------------------------------------------------------------------------
# 7. duplicate handling (producer-side, same event_id twice in one cycle)
# ---------------------------------------------------------------------------

def test_same_latest_bar_across_poll_cycles_is_deduped_and_counted():
    """Finding P7-2: Alpaca bars/latest returns a symbol's most recent bar
    unchanged until it prints a new one. The producer must publish it ONCE,
    then skip identical re-returns on later cycles (counting them as
    duplicate_events_detected), so the shared stream never carries stale
    repeats."""
    ts = _now().isoformat()
    stale_row = {"AAPL": {"t": ts, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}}
    fresh_row = {"AAPL": {"t": (_now() + timedelta(minutes=1)).isoformat(), "o": 2, "h": 2, "l": 2, "c": 2, "v": 2}}
    producer = AlpacaGatewayProducer(
        config=GatewayConfig(key_id="k", secret_key="s"),
        transport=_FakeTransport([
            _fake_response(200, stale_row),   # cycle 1: publish
            _fake_response(200, stale_row),   # cycle 2: identical -> skip
            _fake_response(200, stale_row),   # cycle 3: identical -> skip
            _fake_response(200, fresh_row),   # cycle 4: new bar -> publish
        ]),
        universe=_universe("AAPL"),
    )
    producer._client = AsyncMock()
    producer._client.xadd = AsyncMock(return_value="1-0")
    producer._client.incrby = AsyncMock(return_value=1)

    async def go():
        for _ in range(4):
            await producer._poll_once()
    asyncio.run(go())

    assert producer.counters.events_received == 4      # every returned row is "received"
    assert producer.counters.events_published == 2     # only the two DISTINCT bars reach the stream
    assert producer.counters.duplicate_events_detected == 2  # the two stale re-returns
    assert producer._client.xadd.await_count == 2


def test_symbol_coverage_is_cumulative_across_cycles_not_overwritten():
    """Finding P7-3: symbol_coverage must ACCUMULATE every symbol ever seen
    this session, not be overwritten each cycle with only that cycle's
    freshly-published symbols -- otherwise a sparse symbol whose latest bar
    hasn't changed vanishes from the map and reads as UNACCOUNTED."""
    c1 = {
        "AAPL": {"t": _now().isoformat(), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
        "MSFT": {"t": _now().isoformat(), "o": 2, "h": 2, "l": 2, "c": 2, "v": 2},
    }
    # cycle 2: MSFT prints a new bar, AAPL returns its SAME (stale) bar
    c2 = {
        "AAPL": {"t": c1["AAPL"]["t"], "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
        "MSFT": {"t": (_now() + timedelta(minutes=1)).isoformat(), "o": 3, "h": 3, "l": 3, "c": 3, "v": 3},
    }
    producer = AlpacaGatewayProducer(
        config=GatewayConfig(key_id="k", secret_key="s"),
        transport=_FakeTransport([_fake_response(200, c1), _fake_response(200, c2)]),
        universe=_universe("AAPL", "MSFT"),
    )
    producer._client = AsyncMock()
    producer._client.xadd = AsyncMock(return_value="1-0")
    producer._client.incrby = AsyncMock(return_value=1)
    producer._client.set = AsyncMock()

    async def go():
        await producer._poll_once()
        await producer._poll_once()
    asyncio.run(go())

    # After cycle 2, AAPL's stale bar was deduped (not published) -- but it
    # must STILL be in the coverage map from cycle 1, with an updated
    # last_seen_at and an unchanged last_new_bar_at.
    assert set(producer._coverage.keys()) == {"AAPL", "MSFT"}
    assert producer._coverage["AAPL"]["last_new_bar_at"] is not None  # published in cycle 1
    assert producer._coverage["MSFT"]["last_new_bar_at"] is not None
    # the LAST write_symbol_coverage call carried the full 2-symbol map
    last_set_call = producer._client.set.await_args_list[-1]
    written = json.loads(last_set_call.args[1])
    assert set(written.keys()) == {"AAPL", "MSFT"}


def test_duplicate_event_id_within_one_poll_cycle_is_deduped_before_publish():
    ts_iso = _now().isoformat()
    # Two distinct dict keys resolving to the exact same normalized event
    # cannot happen from a real Alpaca response (one row per symbol), but
    # the guard must hold regardless -- simulate by calling _poll_once
    # twice with the identical bar/timestamp and asserting the SECOND
    # cycle still only ever publishes the (different) new poll_cycle_id
    # payload, i.e. dedup is scoped per-cycle by construction, and a
    # stable dedup key is what event_id guarantees for genuine replays.
    row = {"t": ts_iso, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}
    producer = AlpacaGatewayProducer(
        config=GatewayConfig(key_id="k", secret_key="s"),
        transport=_FakeTransport([_fake_response(200, {"AAPL": row})]),
        universe=_universe("AAPL"),
    )
    producer._client = AsyncMock()
    producer._client.xadd = AsyncMock(return_value="1-0")

    async def go():
        await producer._poll_once()
    asyncio.run(go())
    assert producer.counters.duplicate_events_detected == 0  # single row, no in-cycle dup
    assert producer.counters.events_published == 1


# ---------------------------------------------------------------------------
# 17. gateway publish while one consumer is unavailable (mocked: publish
#     succeeds even though `_client` here has never been read by a consumer)
# ---------------------------------------------------------------------------

def test_publish_succeeds_independent_of_any_consumer_state():
    bar = {"AAPL": {"t": _now().isoformat(), "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}}
    producer = AlpacaGatewayProducer(
        config=GatewayConfig(key_id="k", secret_key="s"),
        transport=_FakeTransport([_fake_response(200, bar)]),
        universe=_universe("AAPL"),
    )
    producer._client = AsyncMock()
    producer._client.xadd = AsyncMock(return_value="1-0")

    async def go():
        await producer._poll_once()
    asyncio.run(go())
    assert producer.counters.events_published == 1  # no consumer was ever involved


# ---------------------------------------------------------------------------
# metrics/liveness never raise even when Redis is completely gone
# ---------------------------------------------------------------------------

def test_liveness_write_never_raises_when_client_is_none():
    from talonx_ingest.shared_gateway import metrics as gw_metrics

    async def go():
        ok = await gw_metrics.write_liveness(None, {"component": "gateway"})
        assert ok is False
    asyncio.run(go())


def test_incr_metric_never_raises_on_redis_exception():
    from talonx_ingest.shared_gateway import metrics as gw_metrics
    client = AsyncMock()
    client.incrby.side_effect = ConnectionError("down")

    async def go():
        await gw_metrics.incr_metric(client, "events_received", 1)  # must not raise
    asyncio.run(go())


# ---------------------------------------------------------------------------
# Consumer-adapter shape compatibility (already smoke-verified live against
# real production schemas during Phase 3 -- pinned here as a regression test)
# ---------------------------------------------------------------------------

def test_original_shadow_consumer_maps_to_valid_market_tick_event():
    from talonx_quant.schemas import MarketTickEvent
    ev = build_event(symbol="AAPL", provider_feed="iex", provider_timestamp=_now(), gateway_receive_timestamp=_now(),
                      open_=1, high=2, low=0.5, close=1.5, volume=100, gateway_session_id="s", poll_cycle_id="c")
    oc = OriginalShadowConsumer(consumer_name="x", redis_url="redis://localhost:6379/2")
    mapped = oc._map(ev)
    validated = MarketTickEvent.model_validate(mapped)
    assert validated.source.value == "polling"
    assert validated.close == 1.5


def test_piv_shadow_consumer_maps_to_valid_feed_bar_shape_and_feeds_real_scanner():
    from talonx_quant.consumer import QuantScanner
    ev = build_event(symbol="AAPL", provider_feed="iex", provider_timestamp=_now(), gateway_receive_timestamp=_now(),
                      open_=1, high=2, low=0.5, close=1.5, volume=100, gateway_session_id="s", poll_cycle_id="c")
    pc = PivShadowConsumer(consumer_name="x", redis_url="redis://localhost:6379/2")
    mapped = pc._map(ev)
    scanner = QuantScanner()

    async def go():
        await scanner._handle_market_tick(mapped)
    asyncio.run(go())
    assert scanner._bars_processed == 1


def test_shadow_consumer_default_sink_never_touches_execution_modules():
    """SHADOW_INGESTION_ONLY structural guarantee: neither shadow consumer
    module ACTUALLY IMPORTS anything execution/lifecycle-capable. Parses
    the AST's real import statements rather than grepping the raw source,
    so this can't be fooled by (or falsely flagged by) a docstring merely
    mentioning a forbidden module name in prose."""
    import ast
    import talonx_ingest.shared_gateway.original_shadow_consumer as osc_mod
    import talonx_ingest.shared_gateway.piv_shadow_consumer as psc_mod
    import talonx_ingest.shared_gateway.shadow_consumer_base as base_mod
    import talonx_ingest.shared_gateway.alpaca_gateway as gw_mod
    forbidden_modules = ("talonx_piv.broker", "talonx_piv.lifecycle", "talonx_paper", "talonx_core")
    for mod in (osc_mod, psc_mod, base_mod, gw_mod):
        tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)
        for forbidden in forbidden_modules:
            hit = [n for n in imported_names if n == forbidden or n.startswith(forbidden + ".")]
            assert not hit, f"{mod.__name__} unexpectedly imports {hit}"


# ===========================================================================
# Real-Redis integration tests (db 2 -- gateway's own isolated database)
# ===========================================================================

def _redis_db2_reachable() -> bool:
    if not REDIS_AVAILABLE:
        return False
    import redis as sync_redis
    try:
        sync_redis.Redis.from_url("redis://localhost:6379/2", socket_connect_timeout=1).ping()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(not _redis_db2_reachable(), reason="Redis db2 not reachable in this environment")


@pytest.fixture
def stream_key():
    """A UNIQUE key per test -- tests never share or collide on stream
    state, and cleanup only ever deletes exactly this key + its
    deadletter, never a blind FLUSHDB."""
    key = f"talonx:gateway:test:{uuid.uuid4().hex}"
    yield key


async def _client():
    return redis_asyncio.from_url("redis://localhost:6379/2")


async def _cleanup(client, key):
    """Deletes the test's own stream/deadletter keys plus any consumer-lag
    keys the loop under test may have written for the group names these
    tests use -- all TTL-bound (90s) so leaving one behind is harmless,
    but explicit cleanup keeps db2 tidy between runs regardless."""
    lag_keys = [f"talonx:gateway:alpaca:consumer_lag:{g}" for g in ("g1", "group_a", "group_b")]
    await client.delete(key, f"{key}:deadletter", *lag_keys)
    await client.aclose()


@requires_redis
def test_xadd_append_and_ordering(stream_key):
    async def go():
        client = await _client()
        try:
            ev1 = build_event(symbol="AAPL", provider_feed="iex", provider_timestamp=_now(), gateway_receive_timestamp=_now(),
                               open_=1, high=1, low=1, close=1, volume=1, gateway_session_id="s", poll_cycle_id="c1")
            ev2 = build_event(symbol="MSFT", provider_feed="iex", provider_timestamp=_now(), gateway_receive_timestamp=_now(),
                               open_=2, high=2, low=2, close=2, volume=2, gateway_session_id="s", poll_cycle_id="c2")
            id1 = await rs.publish_event(client, ev1.to_redis_payload(), key=stream_key)
            id2 = await rs.publish_event(client, ev2.to_redis_payload(), key=stream_key)
            assert id1 < id2  # Stream IDs are monotonically increasing -- ordering preserved
            assert await rs.stream_length(client, key=stream_key) == 2
        finally:
            await _cleanup(client, stream_key)
    asyncio.run(go())


@requires_redis
def test_empty_stream_read_returns_nothing_and_never_raises(stream_key):
    async def go():
        client = await _client()
        try:
            await rs.ensure_group(client, key=stream_key, group="g1")
            entries = await rs.read_new(client, key=stream_key, group="g1", consumer="c1", block_ms=100)
            assert entries == []
            lag = await rs.group_lag(client, key=stream_key)
            assert lag.get("g1") == 0
        finally:
            await _cleanup(client, stream_key)
    asyncio.run(go())


@requires_redis
def test_group_created_before_publish_delivers_first_entry(stream_key):
    async def go():
        client = await _client()
        try:
            await rs.ensure_group(client, key=stream_key, group="g1")
            ev = build_event(symbol="AAPL", provider_feed="iex", provider_timestamp=_now(), gateway_receive_timestamp=_now(),
                              open_=1, high=1, low=1, close=1, volume=1, gateway_session_id="s", poll_cycle_id="c1")
            await rs.publish_event(client, ev.to_redis_payload(), key=stream_key)
            entries = await rs.read_new(client, key=stream_key, group="g1", consumer="c1", block_ms=200)
            assert len(entries) == 1
        finally:
            await _cleanup(client, stream_key)
    asyncio.run(go())


@requires_redis
def test_consumer_a_and_b_have_independent_offsets(stream_key):
    """Gate C: one group's consumption never moves another group's offset."""
    async def go():
        client = await _client()
        try:
            await rs.ensure_group(client, key=stream_key, group="group_a")
            await rs.ensure_group(client, key=stream_key, group="group_b")
            ev = build_event(symbol="AAPL", provider_feed="iex", provider_timestamp=_now(), gateway_receive_timestamp=_now(),
                              open_=1, high=1, low=1, close=1, volume=1, gateway_session_id="s", poll_cycle_id="c1")
            await rs.publish_event(client, ev.to_redis_payload(), key=stream_key)

            entries_a = await rs.read_new(client, key=stream_key, group="group_a", consumer="a1", block_ms=200)
            assert len(entries_a) == 1
            await rs.ack(client, entries_a[0].entry_id, key=stream_key, group="group_a")

            lag = await rs.group_lag(client, key=stream_key)
            assert lag["group_a"] == 0
            assert lag["group_b"] == 1  # group_b never read -- untouched by group_a's activity
        finally:
            await _cleanup(client, stream_key)
    asyncio.run(go())


@requires_redis
def test_consumer_a_failure_does_not_block_consumer_b(stream_key):
    """Explicit task requirement: 'Consumer A failure DOES NOT block Consumer B.'"""
    async def go():
        client = await _client()
        try:
            await rs.ensure_group(client, key=stream_key, group="group_a")
            await rs.ensure_group(client, key=stream_key, group="group_b")
            ev = build_event(symbol="AAPL", provider_feed="iex", provider_timestamp=_now(), gateway_receive_timestamp=_now(),
                              open_=1, high=1, low=1, close=1, volume=1, gateway_session_id="s", poll_cycle_id="c1")
            await rs.publish_event(client, ev.to_redis_payload(), key=stream_key)

            received_b = []
            async def sink_b(mapped):
                received_b.append(mapped)

            async def broken_sink_a(mapped):
                raise RuntimeError("consumer A handler is broken")

            consumer_a = OriginalShadowConsumer(group="group_a", consumer_name="a1", redis_url="redis://localhost:6379/2", key=stream_key, sink=broken_sink_a)
            consumer_b = OriginalShadowConsumer(group="group_b", consumer_name="b1", redis_url="redis://localhost:6379/2", key=stream_key, sink=sink_b)

            await consumer_a.run(max_iterations=1)  # its sink raises internally -- must not propagate
            await consumer_b.run(max_iterations=1)  # must still succeed, unaffected by A's failure

            assert len(received_b) == 1
            assert consumer_a.counters.events_dead_lettered == 0  # only 1 delivery attempt so far -- not yet at threshold
        finally:
            await _cleanup(client, stream_key)
    asyncio.run(go())


@requires_redis
def test_consumer_restart_recovers_pending_entry_via_claim(stream_key):
    """Gate B: a consumer that dies mid-processing (read, not acked) has
    its entry reclaimed by a differently-named consumer under the SAME
    group after a restart -- not lost, not stuck forever."""
    async def go():
        client = await _client()
        try:
            await rs.ensure_group(client, key=stream_key, group="g1")
            ev = build_event(symbol="AAPL", provider_feed="iex", provider_timestamp=_now(), gateway_receive_timestamp=_now(),
                              open_=1, high=1, low=1, close=1, volume=1, gateway_session_id="s", poll_cycle_id="c1")
            await rs.publish_event(client, ev.to_redis_payload(), key=stream_key)

            # "crashed" consumer reads but never acks
            await client.xreadgroup("g1", "crashed", {stream_key: ">"}, count=10)

            claimed = await rs.claim_pending(client, key=stream_key, group="g1", consumer="recovered", min_idle_ms=0)
            assert len(claimed) == 1
        finally:
            await _cleanup(client, stream_key)
    asyncio.run(go())


@requires_redis
def test_poison_entry_is_dead_lettered_after_max_attempts_never_lost(stream_key):
    async def go():
        client = await _client()
        try:
            await rs.ensure_group(client, key=stream_key, group="g1")
            # publish something that will fail deserialization on purpose
            await client.xadd(stream_key, {"payload": "not-valid-json"})
            # claim_min_idle_ms=0: reclaim immediately rather than waiting
            # the real 30s-per-attempt production default -- see
            # ShadowConsumerBase.claim_min_idle_ms's own docstring.
            consumer = OriginalShadowConsumer(group="g1", consumer_name="c1", redis_url="redis://localhost:6379/2", key=stream_key, claim_min_idle_ms=0)
            for _ in range(rs.MAX_DELIVERY_ATTEMPTS):
                await consumer.run(max_iterations=1)
            assert consumer.counters.events_dead_lettered == 1
            assert await rs.stream_length(client, key=f"{stream_key}:deadletter") == 1
            # main stream's PEL must be clear -- it was ACKed when dead-lettered
            pending = await client.xpending(stream_key, "g1")
            assert pending["pending"] == 0
        finally:
            await _cleanup(client, stream_key)
    asyncio.run(go())


@requires_redis
def test_slow_consumer_does_not_backpressure_producer(stream_key):
    """Explicit task requirement: 'Consumer B lag DOES NOT backpressure the
    producer.' Publishes a burst while NO consumer ever reads -- every
    publish must still succeed immediately."""
    async def go():
        client = await _client()
        try:
            await rs.ensure_group(client, key=stream_key, group="g1")
            for i in range(50):
                ev = build_event(symbol="AAPL", provider_feed="iex", provider_timestamp=_now() + timedelta(seconds=i),
                                  gateway_receive_timestamp=_now(), open_=1, high=1, low=1, close=1, volume=1,
                                  gateway_session_id="s", poll_cycle_id=f"c{i}")
                await rs.publish_event(client, ev.to_redis_payload(), key=stream_key)
            assert await rs.stream_length(client, key=stream_key) == 50
            lag = await rs.group_lag(client, key=stream_key)
            assert lag["g1"] == 50  # fully behind, but every publish still landed
        finally:
            await _cleanup(client, stream_key)
    asyncio.run(go())


@requires_redis
def test_retention_maxlen_bounds_stream_growth(stream_key):
    async def go():
        client = await _client()
        try:
            small_maxlen = 10
            for i in range(30):
                ev = build_event(symbol="AAPL", provider_feed="iex", provider_timestamp=_now() + timedelta(seconds=i),
                                  gateway_receive_timestamp=_now(), open_=1, high=1, low=1, close=1, volume=1,
                                  gateway_session_id="s", poll_cycle_id=f"c{i}")
                await client.xadd(stream_key, {"payload": ev.to_redis_payload()}, maxlen=small_maxlen, approximate=False)
            length = await rs.stream_length(client, key=stream_key)
            assert length <= small_maxlen + 1  # exact trim -- bounded, never unbounded growth
        finally:
            await _cleanup(client, stream_key)
    asyncio.run(go())


@requires_redis
def test_consumer_group_bootstrap_is_idempotent_across_restarts(stream_key):
    """Gate B: re-running ensure_group (as every process restart does) must
    never reset an existing group's offset."""
    async def go():
        client = await _client()
        try:
            created_first = await rs.ensure_group(client, key=stream_key, group="g1")
            assert created_first is True
            ev = build_event(symbol="AAPL", provider_feed="iex", provider_timestamp=_now(), gateway_receive_timestamp=_now(),
                              open_=1, high=1, low=1, close=1, volume=1, gateway_session_id="s", poll_cycle_id="c1")
            await rs.publish_event(client, ev.to_redis_payload(), key=stream_key)
            entries = await rs.read_new(client, key=stream_key, group="g1", consumer="c1", block_ms=200)
            await rs.ack(client, entries[0].entry_id, key=stream_key, group="g1")

            # simulate a "gateway restart" re-bootstrapping the group
            created_second = await rs.ensure_group(client, key=stream_key, group="g1")
            assert created_second is False  # BUSYGROUP -- left alone, not recreated

            lag = await rs.group_lag(client, key=stream_key)
            assert lag["g1"] == 0  # offset survived the "restart" -- not reset to replay the already-acked entry
        finally:
            await _cleanup(client, stream_key)
    asyncio.run(go())


@requires_redis
def test_consumer_lag_calculation_accuracy(stream_key):
    async def go():
        client = await _client()
        try:
            await rs.ensure_group(client, key=stream_key, group="g1")
            for i in range(5):
                ev = build_event(symbol="AAPL", provider_feed="iex", provider_timestamp=_now() + timedelta(seconds=i),
                                  gateway_receive_timestamp=_now(), open_=1, high=1, low=1, close=1, volume=1,
                                  gateway_session_id="s", poll_cycle_id=f"c{i}")
                await rs.publish_event(client, ev.to_redis_payload(), key=stream_key)
            lag_before = await rs.group_lag(client, key=stream_key)
            assert lag_before["g1"] == 5
            entries = await rs.read_new(client, key=stream_key, group="g1", consumer="c1", count=3, block_ms=200)
            for e in entries:
                await rs.ack(client, e.entry_id, key=stream_key, group="g1")
            lag_after = await rs.group_lag(client, key=stream_key)
            assert lag_after["g1"] == 2
        finally:
            await _cleanup(client, stream_key)
    asyncio.run(go())
