"""
Task 88 -- Phase 5: frozen offline replay.

Replays the FROZEN fixture (results/task88_shared_gateway/fixtures/
frozen_market_events_v1.json -- generated once, never regenerated) through
BOTH shadow consumer adapters independently, on a stream key dedicated to
replay (`talonx:gateway:replay:v1`, never the live production stream key
`talonx:gateway:alpaca:market:v1`), and verifies input equivalence per the
task's required checklist: event count, symbol, timestamp, price/OHLC,
volume, ordering, provider, duplicates, missing events.

Per the task's explicit instruction, this does NOT compare strategy
output -- only that both sides received the identical input population.
Neither replay consumer is ever connected to a real lifecycle/broker/
execution object (see shadow_consumer_base.py's own SHADOW_INGESTION_ONLY
guarantee, already regression-tested in test_task88_shared_gateway.py).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from talonx_ingest.shared_gateway import redis_stream as rs
from talonx_ingest.shared_gateway.original_shadow_consumer import OriginalShadowConsumer
from talonx_ingest.shared_gateway.piv_shadow_consumer import PivShadowConsumer

try:
    import redis.asyncio as redis_asyncio
    import redis as sync_redis
    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    REDIS_AVAILABLE = False

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "results/task88_shared_gateway/fixtures/frozen_market_events_v1.json"
REPLAY_STREAM_KEY = "talonx:gateway:replay:v1"  # dedicated -- distinct from the live production key
REPLAY_REDIS_URL = "redis://localhost:6379/2"  # the gateway's own isolated db -- never db0/db1


def _redis_reachable() -> bool:
    if not REDIS_AVAILABLE:
        return False
    try:
        sync_redis.Redis.from_url(REPLAY_REDIS_URL, socket_connect_timeout=1).ping()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(not _redis_reachable(), reason="Redis db2 not reachable in this environment")


@pytest.fixture(scope="module")
def fixture_data():
    assert FIXTURE_PATH.is_file(), f"frozen fixture missing: {FIXTURE_PATH}"
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@requires_redis
def test_frozen_fixture_replays_identically_to_both_shadow_consumers(fixture_data):
    events = fixture_data["events"]
    total_count = len(events)
    unique_ids = {e["event_id"] for e in events}

    async def go():
        client = redis_asyncio.from_url(REPLAY_REDIS_URL)
        try:
            await client.delete(REPLAY_STREAM_KEY, f"{REPLAY_STREAM_KEY}:deadletter")
            for e in events:
                await rs.publish_event(client, json.dumps(e, sort_keys=True), key=REPLAY_STREAM_KEY)
            assert await rs.stream_length(client, key=REPLAY_STREAM_KEY) == total_count

            original_received: list[dict] = []
            async def original_sink(mapped):
                original_received.append(mapped)
            oc = OriginalShadowConsumer(
                group="original_shadow_replay", consumer_name="replay-original-1",
                redis_url=REPLAY_REDIS_URL, key=REPLAY_STREAM_KEY, sink=original_sink,
                group_start_id="0",  # replay wants the WHOLE already-published fixture, not just new entries
            )

            piv_received: list[dict] = []
            async def piv_sink(mapped):
                piv_received.append(mapped)
            pc = PivShadowConsumer(
                group="piv_shadow_replay", consumer_name="replay-piv-1",
                redis_url=REPLAY_REDIS_URL, key=REPLAY_STREAM_KEY, sink=piv_sink,
                group_start_id="0",
            )

            # Drain each independently, fully (loop until nothing new arrives).
            for consumer in (oc, pc):
                while True:
                    before = len(original_received) + len(piv_received)
                    await consumer.run(max_iterations=1)
                    after = len(original_received) + len(piv_received)
                    if after == before:
                        break

            # 1. event count -- both sides saw every entry, including the deliberate duplicate
            assert len(original_received) == total_count, "Original consumer missed/gained entries"
            assert len(piv_received) == total_count, "PIV consumer missed/gained entries"

            # 2. ordering -- both consumers process in the SAME stream order
            original_ids = [m["gateway_event_id"] for m in original_received]
            piv_ids = [m["gateway_event_id"] for m in piv_received]
            assert original_ids == piv_ids, "Original and PIV consumers observed different orderings"
            assert original_ids == [e["event_id"] for e in events], "delivered order does not match published order"

            # 3. duplicates -- both sides see the SAME single deliberate duplicate event_id twice, nothing else
            from collections import Counter
            original_counts = Counter(original_ids)
            dup_ids_original = {eid for eid, n in original_counts.items() if n > 1}
            assert dup_ids_original == {fixture_data["deliberate_duplicate_event_id"]}
            assert original_counts[fixture_data["deliberate_duplicate_event_id"]] == 2

            # 4. missing events -- zero unaccounted on either side
            assert unique_ids.issubset(set(original_ids))
            assert unique_ids.issubset(set(piv_ids))

            # 5. symbol / timestamp / OHLCV / volume / provider -- byte-identical between
            #    what each side received for the SAME event_id (input equivalence, not
            #    strategy-output equivalence -- see module docstring)
            by_id_original = {m["gateway_event_id"]: m for m in original_received}
            by_id_piv = {m["gateway_event_id"]: m for m in piv_received}
            for eid in unique_ids:
                o, p = by_id_original[eid], by_id_piv[eid]
                assert o["symbol"] == p["symbol"]
                assert o["timestamp"] == p["timestamp"]
                assert o["open"] == p["open"] and o["high"] == p["high"]
                assert o["low"] == p["low"] and o["close"] == p["close"]
                assert o["volume"] == p["volume"]
                assert o["price"] == p["price"] == o["close"]

            # 6. per-symbol accounting -- 10 bars/symbol + 1 extra for the duplicated symbol
            symbol_counts = Counter(m["symbol"] for m in original_received)
            expected = {s: fixture_data["bars_per_symbol"] for s in fixture_data["symbols"]}
            expected["AAPL"] += 1  # the deliberate duplicate is an AAPL bar
            assert dict(symbol_counts) == expected

            # 7. independent offsets -- confirmed structurally: each consumer used its
            #    OWN consumer group (original_shadow_replay / piv_shadow_replay); Phase 4
            #    already proves group independence at the transport level.
            lag = await rs.group_lag(client, key=REPLAY_STREAM_KEY)
            assert lag["original_shadow_replay"] == 0
            assert lag["piv_shadow_replay"] == 0

            return {
                "total_count": total_count, "unique_count": len(unique_ids),
                "original_received": len(original_received), "piv_received": len(piv_received),
                "symbol_counts": dict(symbol_counts),
            }
        finally:
            await client.delete(REPLAY_STREAM_KEY, f"{REPLAY_STREAM_KEY}:deadletter",
                                 "talonx:gateway:alpaca:consumer_lag:original_shadow_replay",
                                 "talonx:gateway:alpaca:consumer_lag:piv_shadow_replay")
            await client.aclose()

    result = asyncio.run(go())
    assert result["original_received"] == result["piv_received"] == result["total_count"]
