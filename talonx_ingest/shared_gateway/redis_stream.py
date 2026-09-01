"""
talonx_ingest.shared_gateway.redis_stream
----------------------------------------------
Thin, testable wrapper around the Redis Stream primitives Task 88 needs:
XADD (bounded), consumer-group bootstrap, XREADGROUP, and the
claim/dead-letter machinery that gives each consumer group an independent,
restart-safe offset. No business logic lives here -- see alpaca_gateway.py
(producer) and *_shadow_consumer.py (consumers) for that.

Design reference: results/task88_shared_gateway/design.md §2.3.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("talonx_ingest.shared_gateway.redis_stream")

try:
    import redis.asyncio as redis_asyncio
    from redis.exceptions import ResponseError
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None
    ResponseError = Exception

STREAM_KEY = "talonx:gateway:alpaca:market:v1"
DEADLETTER_KEY = f"{STREAM_KEY}:deadletter"
STREAM_MAXLEN = 20_000
DEADLETTER_MAXLEN = 2_000
MAX_DELIVERY_ATTEMPTS = 5

ORIGINAL_SHADOW_GROUP = "original_shadow"
PIV_SHADOW_GROUP = "piv_shadow"


@dataclass(frozen=True)
class StreamEntry:
    """One deserialized Stream entry, with its Stream-assigned id -- the
    id (not the payload) is what XACK/XCLAIM operate on."""
    entry_id: str
    payload: str


async def ensure_group(
    client: Any, *, key: str = STREAM_KEY, group: str, start_id: str = "$",
) -> bool:
    """Idempotent consumer-group bootstrap. Creates the group at `start_id`
    with MKSTREAM so the group can be created even before the first event
    exists. A pre-existing group (BUSYGROUP) is left completely alone --
    this is what makes "gateway/consumer restart does not reset consumer
    offsets" true; `start_id` only matters the FIRST time a given group is
    ever created, never on a later restart.

    `start_id="$"` (the default, and what every production shadow consumer
    uses) means "stream end -- new entries only," never backfilling years
    of history for a live shadow consumer. `start_id="0"` means "from the
    very beginning" -- used ONLY by Phase 5's offline replay, which by
    definition wants every event in its frozen, already-fully-published
    fixture stream, never live production traffic.

    Returns True if the group was newly created, False if it already
    existed (both are success outcomes for the caller)."""
    try:
        await client.xgroup_create(key, group, id=start_id, mkstream=True)
        logger.info("Created consumer group %s on %s at start_id=%s", group, key, start_id)
        return True
    except ResponseError as exc:
        if "BUSYGROUP" in str(exc):
            return False
        raise


async def publish_event(client: Any, payload: str, *, key: str = STREAM_KEY) -> str:
    """XADD with approximate MAXLEN trimming (see design.md §2.3 for why
    `~` rather than exact trimming, and why 20000). Returns the assigned
    entry id. Raises on failure -- callers (alpaca_gateway.py) are
    responsible for counting/logging a publish failure; this function does
    not swallow errors, matching every other Redis write in this task
    being explicitly, honestly counted rather than silently absorbed."""
    return await client.xadd(key, {"payload": payload}, maxlen=STREAM_MAXLEN, approximate=True)


async def read_new(
    client: Any, *, key: str = STREAM_KEY, group: str, consumer: str,
    count: int = 100, block_ms: int = 1000,
) -> list[StreamEntry]:
    """XREADGROUP for entries this consumer has never seen (`>`). Blocks up
    to `block_ms` if the stream is empty -- returns an empty list on
    timeout, never raises for "nothing new"."""
    resp = await client.xreadgroup(
        group, consumer, {key: ">"}, count=count, block=block_ms,
    )
    return _flatten(resp)


async def claim_pending(
    client: Any, *, key: str = STREAM_KEY, group: str, consumer: str,
    min_idle_ms: int = 30_000, count: int = 100,
) -> list[StreamEntry]:
    """Recovers this consumer's own not-yet-acked entries after a restart
    (Gate B: restart-safe delivery) -- claims entries idle for at least
    `min_idle_ms` under THIS group, assigned to THIS consumer name, so a
    process that died mid-processing resumes those entries instead of
    losing them. Never touches another group's PEL (Gate C: consumer
    independence) -- XAUTOCLAIM/XCLAIM are always scoped to one group."""
    try:
        resp = await client.xautoclaim(key, group, consumer, min_idle_ms, start_id="0", count=count)
    except ResponseError as exc:
        if "NOGROUP" in str(exc):
            return []
        raise
    # redis-py returns (next_cursor, claimed_entries, deleted_ids) for XAUTOCLAIM
    claimed = resp[1] if isinstance(resp, (list, tuple)) and len(resp) >= 2 else []
    return [StreamEntry(entry_id=eid, payload=fields.get("payload") or fields.get(b"payload", b"").decode())
            for eid, fields in claimed]


async def ack(client: Any, entry_id: str, *, key: str = STREAM_KEY, group: str) -> None:
    await client.xack(key, group, entry_id)


async def delivery_count(client: Any, entry_id: str, *, key: str = STREAM_KEY, group: str) -> int:
    """How many times this entry has been delivered to `group` without an
    ACK -- drives the dead-letter threshold (MAX_DELIVERY_ATTEMPTS)."""
    pending = await client.xpending_range(key, group, min=entry_id, max=entry_id, count=1)
    if not pending:
        return 0
    return int(pending[0]["times_delivered"])


async def move_to_deadletter(client: Any, entry: StreamEntry, *, key: str = STREAM_KEY, group: str) -> None:
    """Copies a poison entry to the dead-letter stream (bounded, own
    MAXLEN) and ACKs it off the main stream's PEL so it stops being
    redelivered -- never silently dropped (Gate D: no unexplained gaps),
    always both counted (by the caller) and durably visible here.

    The dead-letter key is always derived from `key` (never the hardcoded
    production STREAM_KEY) so a caller pointed at a different stream --
    a test's isolated fixture key, or Phase 5's separate frozen replay
    stream -- gets its OWN dead-letter stream, never one shared with
    production."""
    deadletter_key = f"{key}:deadletter"
    await publish_event(client, entry.payload, key=deadletter_key)
    await ack(client, entry.entry_id, key=key, group=group)
    logger.warning("Moved entry %s to dead-letter after exceeding delivery attempts", entry.entry_id)


async def group_lag(client: Any, *, key: str = STREAM_KEY) -> dict[str, int | None]:
    """Per-group `lag` (entries added since the group's last-delivered-id)
    via XINFO GROUPS -- Redis 7.0+ computes this natively (this project's
    Redis image is 7.0.15, confirmed). Returns {} if the stream/groups
    don't exist yet (a fresh gateway that hasn't published anything)."""
    try:
        groups = await client.xinfo_groups(key)
    except ResponseError:
        return {}
    result: dict[str, int | None] = {}
    for g in groups:
        name = g.get("name") or g.get(b"name")
        if isinstance(name, bytes):
            name = name.decode()
        result[name] = g.get("lag", g.get(b"lag"))
    return result


async def stream_length(client: Any, *, key: str = STREAM_KEY) -> int:
    try:
        return await client.xlen(key)
    except ResponseError:
        return 0


def _flatten(resp: Any) -> list[StreamEntry]:
    """redis-py XREADGROUP shape: [(stream_key, [(entry_id, {field: value}), ...])]."""
    entries: list[StreamEntry] = []
    if not resp:
        return entries
    for _stream_key, records in resp:
        for entry_id, fields in records:
            payload = fields.get("payload")
            if payload is None:
                payload = fields.get(b"payload", b"")
                payload = payload.decode() if isinstance(payload, bytes) else payload
            entries.append(StreamEntry(entry_id=entry_id, payload=payload))
    return entries
