"""
Task 89 -- Phase 4: OFFLINE integrated dual-consumer rehearsal.

Replays the FROZEN Task 88 fixture (results/task88_shared_gateway/fixtures/
frozen_market_events_v1.json) through BOTH Task 88 shadow consumers wired
to REAL, ISOLATED QuantScanner instances (Original-role -> Redis db 3 /
`talonx:t89orig:*`; PIV-role -> Redis db 4 / `talonx:t89piv:*`). The
gateway Stream is a dedicated replay key on db 2. Redis db 0 (Original)
and db 1 (PIV) are never touched.

Mode: MARKET_DATA_PLUS_STRATEGY_EVAL, EXECUTION_WITHHELD. No DecisionEngine,
no PaperLifecycle, no broker object is constructed (see
tests/t89_integrated_harness.py). The 41-event fixture is far below
`min_bars_required` (120), so no strategy signal can fire -- this phase
qualifies the transport + consumer integration, not strategy output.

Covers the task's 12-point offline checklist:
  1  both consumers start from defined offsets
  2  both consume the identical fixture
  3  both reach lag zero
  4  event-id sets match for the common eligible population
  5  restarting Original does not affect PIV
  6  restarting PIV does not affect Original
  7  consumer A failure does not stop B
  8  duplicate replay does not create a duplicate downstream effect
  9  offset recovery after process restart
  10 malformed / dead-letter behaviour
  11 clean shutdown
  12 clean restart
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections import Counter
from pathlib import Path

import pytest

from talonx_ingest.shared_gateway import redis_stream as rs
from tests.t89_integrated_harness import (
    ALLOWED_ISOLATED_KEY_PREFIXES,
    ORIG_REDIS_URL,
    PIV_REDIS_URL,
    drain_both_until_idle,
    drain_until_idle,
    make_original_role,
    make_piv_role,
)

try:
    import redis.asyncio as redis_asyncio
    import redis as sync_redis
    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    REDIS_AVAILABLE = False

FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent
    / "results/task88_shared_gateway/fixtures/frozen_market_events_v1.json"
)
STREAM_REDIS_URL = "redis://localhost:6379/2"


def _redis_ok(url: str) -> bool:
    if not REDIS_AVAILABLE:
        return False
    try:
        sync_redis.Redis.from_url(url, socket_connect_timeout=1).ping()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(
    not (_redis_ok(STREAM_REDIS_URL) and _redis_ok(ORIG_REDIS_URL) and _redis_ok(PIV_REDIS_URL)),
    reason="Redis db2/db3/db4 not reachable in this environment",
)


@pytest.fixture(scope="module")
def fixture_data():
    assert FIXTURE_PATH.is_file(), f"frozen fixture missing: {FIXTURE_PATH}"
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _assert_isolated_dbs_safe_then_flush():
    """Guard: the isolated scanner DBs (3, 4) must contain ONLY keys this
    task's isolated scanners create. If anything else is there, the config
    is wrong (pointing at a real DB) -- fail instead of flushing."""
    for url in (ORIG_REDIS_URL, PIV_REDIS_URL):
        c = sync_redis.Redis.from_url(url)
        try:
            keys = [k.decode() if isinstance(k, bytes) else k for k in c.keys("*")]
            bad = [k for k in keys if not k.startswith(ALLOWED_ISOLATED_KEY_PREFIXES)]
            assert not bad, f"unexpected keys in isolated DB {url}: {bad[:10]}"
            c.flushdb()
        finally:
            c.close()


@pytest.fixture
def stream_key():
    key = f"talonx:gateway:t89replay:{uuid.uuid4().hex}"
    _assert_isolated_dbs_safe_then_flush()
    yield key
    c = sync_redis.Redis.from_url(STREAM_REDIS_URL)
    try:
        names = [key, f"{key}:deadletter"]
        names += [k for k in (k.decode() if isinstance(k, bytes) else k
                              for k in c.keys("talonx:gateway:alpaca:consumer_lag:*"))]
        if names:
            c.delete(*names)
    finally:
        c.close()
    _assert_isolated_dbs_safe_then_flush()


async def _publish_fixture(client, key, events):
    await client.delete(key, f"{key}:deadletter")
    for e in events:
        await rs.publish_event(client, json.dumps(e, sort_keys=True), key=key)
    assert await rs.stream_length(client, key=key) == len(events)


def _groups(tag):
    return f"original_shadow_{tag}", f"piv_shadow_{tag}"


# ---------------------------------------------------------------------------
# 1-4  common-input equivalence: both consume the identical fixture, both
#      reach lag 0, event-id sets match, per-side scanners agree on input
# ---------------------------------------------------------------------------
@requires_redis
def test_both_consumers_consume_identical_fixture_and_reach_lag_zero(fixture_data, stream_key):
    events = fixture_data["events"]
    total = len(events)
    unique_ids = {e["event_id"] for e in events}
    dup_id = fixture_data["deliberate_duplicate_event_id"]
    og, pg = _groups("t1")

    async def go():
        client = redis_asyncio.from_url(STREAM_REDIS_URL)
        orig = piv = None
        try:
            await _publish_fixture(client, stream_key, events)
            orig = await make_original_role(stream_key=stream_key, group=og,
                                            consumer_name="o1", group_start_id="0")
            piv = await make_piv_role(stream_key=stream_key, group=pg,
                                      consumer_name="p1", group_start_id="0")

            # 1. defined offsets: groups created at id 0 -> full backlog is their lag
            lag0 = await rs.group_lag(client, key=stream_key)
            assert lag0[og] == total and lag0[pg] == total

            await drain_both_until_idle(orig, piv)

            # 2. identical fixture: every entry delivered to both (incl. the 1 dup)
            assert orig.consumer.counters.events_consumed == total
            assert piv.consumer.counters.events_consumed == total
            assert orig.downstream_ticks == total and piv.downstream_ticks == total

            # 3. lag zero on both groups
            lag1 = await rs.group_lag(client, key=stream_key)
            assert lag1[og] == 0 and lag1[pg] == 0

            # 4. event-id sets match for the common eligible population
            orig_ids = [m["gateway_event_id"] for m in orig.received]
            piv_ids = [m["gateway_event_id"] for m in piv.received]
            assert orig_ids == piv_ids, "consumers observed different orderings"
            assert set(orig_ids) == unique_ids
            oc, pc = Counter(orig_ids), Counter(piv_ids)
            assert {k for k, n in oc.items() if n > 1} == {dup_id}
            assert oc[dup_id] == 2 and pc[dup_id] == 2

            # common-input invariant: identical normalized fields per event_id
            by_o = {m["gateway_event_id"]: m for m in orig.received}
            by_p = {m["gateway_event_id"]: m for m in piv.received}
            for eid in unique_ids:
                o, p = by_o[eid], by_p[eid]
                assert o["symbol"] == p["symbol"]
                assert o["timestamp"] == p["timestamp"]
                assert (o["open"], o["high"], o["low"], o["close"]) == (
                    p["open"], p["high"], p["low"], p["close"])
                assert o["volume"] == p["volume"]
                assert o["price"] == p["price"] == o["close"]

            # strategy withheld: 41 bars << min_bars_required, so no signal fired
            assert orig.scanner._bars_processed >= 1
            assert piv.scanner._bars_processed >= 1
        finally:
            if orig:
                await orig.aclose()
            if piv:
                await piv.aclose()
            await client.aclose()

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 8  duplicate replay does not create a duplicate downstream effect
# ---------------------------------------------------------------------------
@requires_redis
def test_duplicate_entry_is_deduped_by_scanner_not_double_counted(fixture_data, stream_key):
    events = fixture_data["events"]
    dup_id = fixture_data["deliberate_duplicate_event_id"]
    og, pg = _groups("t8")

    async def go():
        client = redis_asyncio.from_url(STREAM_REDIS_URL)
        orig = piv = None
        try:
            await _publish_fixture(client, stream_key, events)
            orig = await make_original_role(stream_key=stream_key, group=og,
                                            consumer_name="o1", group_start_id="0")
            piv = await make_piv_role(stream_key=stream_key, group=pg,
                                      consumer_name="p1", group_start_id="0")
            await drain_both_until_idle(orig, piv)

            # the duplicate stream entry IS delivered twice (transport-faithful)...
            assert Counter(m["gateway_event_id"] for m in orig.received)[dup_id] == 2
            # ...but the scanner's exact-timestamp idempotency drops the repeat:
            # bars_processed counts unique (ticker,timestamp) bars only.
            dup_symbol = next(e["symbol"] for e in events if e["event_id"] == dup_id)
            unique_bars = len({(e["symbol"], e["provider_timestamp"]) for e in events})
            assert orig.scanner._bars_processed == unique_bars
            assert piv.scanner._bars_processed == unique_bars
            # buffer for the duplicated symbol holds no double-counted bar
            assert orig.scanner.buffer.bar_count(dup_symbol) == sum(
                1 for e in events if e["symbol"] == dup_symbol
            ) - 1  # -1: the deliberate duplicate collapses
        finally:
            if orig:
                await orig.aclose()
            if piv:
                await piv.aclose()
            await client.aclose()

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 5 & 6  restart isolation: restarting one consumer does not move the other
# ---------------------------------------------------------------------------
@requires_redis
@pytest.mark.parametrize("restart", ["original", "piv"])
def test_restarting_one_consumer_does_not_affect_the_other(fixture_data, stream_key, restart):
    events = fixture_data["events"]
    total = len(events)
    og, pg = _groups(f"t56_{restart}")

    async def go():
        client = redis_asyncio.from_url(STREAM_REDIS_URL)
        try:
            await _publish_fixture(client, stream_key, events)
            orig = await make_original_role(stream_key=stream_key, group=og,
                                            consumer_name="o1", group_start_id="0",
                                            claim_min_idle_ms=0)
            piv = await make_piv_role(stream_key=stream_key, group=pg,
                                      consumer_name="p1", group_start_id="0",
                                      claim_min_idle_ms=0)

            # partial drain: a few iterations only
            for _ in range(3):
                await orig.consumer.run(max_iterations=1)
                await piv.consumer.run(max_iterations=1)

            keep, gone = (piv, orig) if restart == "original" else (orig, piv)
            keep_group = pg if restart == "original" else og
            gone_group = og if restart == "original" else pg
            keep_consumed_before = keep.consumer.counters.events_consumed
            keep_lag_before = (await rs.group_lag(client, key=stream_key))[keep_group]

            # "restart" the gone side: brand-new process/instance, SAME group + name
            await gone.aclose()
            gone2 = (
                await make_original_role(stream_key=stream_key, group=gone_group,
                                         consumer_name="o1", group_start_id="0", claim_min_idle_ms=0)
                if restart == "original"
                else await make_piv_role(stream_key=stream_key, group=gone_group,
                                         consumer_name="p1", group_start_id="0", claim_min_idle_ms=0)
            )

            # the kept side must not have moved as a result of the restart
            keep_lag_after = (await rs.group_lag(client, key=stream_key))[keep_group]
            assert keep.consumer.counters.events_consumed == keep_consumed_before
            assert keep_lag_after == keep_lag_before

            # both finish cleanly, no loss / no duplication beyond the fixture's own
            await drain_both_until_idle(keep, gone2)
            assert (await rs.group_lag(client, key=stream_key))[gone_group] == 0
            assert (await rs.group_lag(client, key=stream_key))[keep_group] == 0
            # kept side saw exactly the fixture population
            assert keep.consumer.counters.events_consumed == total

            await keep.aclose()
            await gone2.aclose()
        finally:
            await client.aclose()

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 7  consumer A failure does not stop consumer B (or the stream)
# ---------------------------------------------------------------------------
@requires_redis
def test_original_sink_failure_does_not_stop_piv_or_stream(fixture_data, stream_key):
    events = fixture_data["events"]
    total = len(events)
    poison = events[5]["event_id"]  # an arbitrary mid-stream event Original will choke on
    og, pg = _groups("t7")

    async def go():
        client = redis_asyncio.from_url(STREAM_REDIS_URL)
        orig = piv = None
        try:
            await _publish_fixture(client, stream_key, events)
            orig = await make_original_role(stream_key=stream_key, group=og, consumer_name="o1",
                                            group_start_id="0", claim_min_idle_ms=0,
                                            fail_on_event_id=poison)
            piv = await make_piv_role(stream_key=stream_key, group=pg, consumer_name="p1",
                                      group_start_id="0", claim_min_idle_ms=0)

            await drain_both_until_idle(orig, piv, max_rounds=400)

            # PIV is entirely unaffected: full fixture consumed, lag 0
            assert piv.consumer.counters.events_consumed == total
            assert piv.downstream_ticks == total
            assert (await rs.group_lag(client, key=stream_key))[pg] == 0

            # Original: the poison entry never acks -> retried -> dead-lettered
            # after MAX_DELIVERY_ATTEMPTS; every OTHER entry still processed.
            assert orig.sink_errors >= rs.MAX_DELIVERY_ATTEMPTS
            assert orig.consumer.counters.events_dead_lettered == 1
            assert orig.consumer.counters.events_consumed == total - 1
            dl_len = await client.xlen(f"{stream_key}:deadletter")
            assert dl_len == 1

            # the stream itself is untouched by either consumer's behaviour
            assert await rs.stream_length(client, key=stream_key) == total
        finally:
            if orig:
                await orig.aclose()
            if piv:
                await piv.aclose()
            await client.aclose()

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 9  offset recovery after a process restart (XAUTOCLAIM of pending)
# ---------------------------------------------------------------------------
@requires_redis
def test_offset_recovery_after_restart_loses_and_duplicates_nothing(fixture_data, stream_key):
    events = fixture_data["events"]
    total = len(events)
    og, pg = _groups("t9")

    async def go():
        client = redis_asyncio.from_url(STREAM_REDIS_URL)
        try:
            await _publish_fixture(client, stream_key, events)
            piv = await make_piv_role(stream_key=stream_key, group=pg, consumer_name="p1",
                                      group_start_id="0", claim_min_idle_ms=0)
            orig1 = await make_original_role(stream_key=stream_key, group=og, consumer_name="o1",
                                             group_start_id="0", claim_min_idle_ms=0)

            # Original reads a batch but we "kill" it before it can ack them all:
            # one raw XREADGROUP delivers up to 100 -> the whole fixture lands in
            # its PEL. Simulate death by never running _handle_entry on them.
            raw = await client.xreadgroup(og, "o1", {stream_key: ">"}, count=100)
            delivered = sum(len(recs) for _k, recs in raw)
            assert delivered == total  # all now pending, none acked

            await orig1.aclose()  # process dies

            # restart: same group + same consumer name, claim_min_idle_ms=0
            orig2 = await make_original_role(stream_key=stream_key, group=og, consumer_name="o1",
                                             group_start_id="0", claim_min_idle_ms=0)
            await drain_until_idle(orig2)

            # every pending entry recovered exactly once
            assert orig2.downstream_ticks == total
            assert Counter(m["gateway_event_id"] for m in orig2.received)[
                fixture_data["deliberate_duplicate_event_id"]] == 2  # fixture's own dup only
            assert (await rs.group_lag(client, key=stream_key))[og] == 0

            # PIV meanwhile is independent and complete
            await drain_until_idle(piv)
            assert piv.consumer.counters.events_consumed == total
            assert (await rs.group_lag(client, key=stream_key))[pg] == 0

            await orig2.aclose()
            await piv.aclose()
        finally:
            await client.aclose()

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 10  malformed / dead-letter behaviour
# ---------------------------------------------------------------------------
@requires_redis
def test_malformed_entry_is_dead_lettered_and_valid_entries_still_flow(fixture_data, stream_key):
    events = fixture_data["events"][:6]
    og, pg = _groups("t10")

    async def go():
        client = redis_asyncio.from_url(STREAM_REDIS_URL)
        orig = None
        try:
            await client.delete(stream_key, f"{stream_key}:deadletter")
            await rs.publish_event(client, json.dumps(events[0], sort_keys=True), key=stream_key)
            await rs.publish_event(client, "{not valid json at all", key=stream_key)
            for e in events[1:]:
                await rs.publish_event(client, json.dumps(e, sort_keys=True), key=stream_key)

            orig = await make_original_role(stream_key=stream_key, group=og, consumer_name="o1",
                                            group_start_id="0", claim_min_idle_ms=0)
            await drain_until_idle(orig)

            assert orig.consumer.counters.events_deserialize_failed >= 1
            assert orig.consumer.counters.events_dead_lettered == 1
            assert await client.xlen(f"{stream_key}:deadletter") == 1
            # all 6 well-formed entries still processed
            assert orig.consumer.counters.events_consumed == len(events)
            assert (await rs.group_lag(client, key=stream_key))[og] == 0
        finally:
            if orig:
                await orig.aclose()
            await client.aclose()

    asyncio.run(go())


# ---------------------------------------------------------------------------
# 11 & 12  clean shutdown, then clean restart resuming at the right offset
# ---------------------------------------------------------------------------
@requires_redis
def test_clean_shutdown_then_restart_resumes_without_reprocessing(fixture_data, stream_key):
    events = fixture_data["events"]
    total = len(events)
    og, pg = _groups("t1112")

    async def go():
        client = redis_asyncio.from_url(STREAM_REDIS_URL)
        try:
            await _publish_fixture(client, stream_key, events)
            piv = await make_piv_role(stream_key=stream_key, group=pg, consumer_name="p1",
                                      group_start_id="0", claim_min_idle_ms=0)
            orig1 = await make_original_role(stream_key=stream_key, group=og, consumer_name="o1",
                                             group_start_id="0", claim_min_idle_ms=0)

            await drain_until_idle(orig1)
            consumed_at_stop = orig1.consumer.counters.events_consumed
            assert consumed_at_stop == total

            # 11. clean shutdown: stop() then run() returns promptly, aclose() no error
            orig1.consumer.stop()
            await asyncio.wait_for(orig1.consumer.run(), timeout=5)
            await orig1.aclose()

            # 12. clean restart: same group -> BUSYGROUP no-op, resume at offset,
            # nothing reprocessed (lag was already 0, PEL empty).
            orig2 = await make_original_role(stream_key=stream_key, group=og, consumer_name="o1",
                                             group_start_id="0", claim_min_idle_ms=0)
            await drain_until_idle(orig2)
            assert orig2.consumer.counters.events_consumed == 0
            assert orig2.downstream_ticks == 0

            combined = orig1.received + orig2.received
            assert len(combined) == total
            assert Counter(m["gateway_event_id"] for m in combined)[
                fixture_data["deliberate_duplicate_event_id"]] == 2
            assert (await rs.group_lag(client, key=stream_key))[og] == 0

            await drain_until_idle(piv)
            assert piv.consumer.counters.events_consumed == total
            await orig2.aclose()
            await piv.aclose()
        finally:
            await client.aclose()

    asyncio.run(go())
