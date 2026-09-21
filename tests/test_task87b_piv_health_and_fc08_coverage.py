"""Task 87B -- PIV component-health lag fix + FC_08 minimal per-symbol
coverage observability.

PIV: run_with_bounded_restart now refreshes component_health.json on a
timer WHILE run_once() executes (was: only at loop entry / clean exit /
exception -> Task 86 found the file ~4.5h stale during a healthy run).

FC_08: RedisEventPublisher stamps a per-symbol last-event map in-process
(no per-event Redis write); the LivenessBeacon flushes it once per beat
to talonx:ingest:symbol_coverage so Task 87C can prove every configured
symbol is accounted for and spot one gone dark.

TEST_FIXTURE_ONLY.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from talonx_piv.supervisor import ComponentHealthRegistry, ComponentStatus, run_with_bounded_restart


# -------------------- PIV component-health lag --------------------
@pytest.mark.asyncio
async def test_component_health_is_refreshed_while_run_once_is_still_running():
    registry = ComponentHealthRegistry()
    registry.register("session_runner", required=True)
    persist_calls: list[float] = []

    def on_heartbeat():
        persist_calls.append(asyncio.get_event_loop().time())

    async def long_run_once():
        # a "session" that runs well past several heartbeat intervals
        await asyncio.sleep(0.25)

    async def fast_sleep(_seconds):
        # collapse the heartbeat interval so the test is quick
        await asyncio.sleep(0.02)

    attempts = await run_with_bounded_restart(
        long_run_once, registry, component_name="session_runner",
        on_heartbeat=on_heartbeat, heartbeat_interval_seconds=0.05, sleep=fast_sleep,
    )
    assert attempts == 0
    # entry + clean-exit + at least a couple of periodic refreshes in between
    assert len(persist_calls) >= 4
    hb = registry.to_dict()["components"]["session_runner"]
    assert hb["status"] == ComponentStatus.HEALTHY.value


@pytest.mark.asyncio
async def test_periodic_heartbeat_task_is_cancelled_on_clean_exit():
    registry = ComponentHealthRegistry()
    registry.register("session_runner", required=True)
    tasks_before = len(asyncio.all_tasks())

    async def quick():
        return None

    await run_with_bounded_restart(quick, registry, heartbeat_interval_seconds=0.01)
    await asyncio.sleep(0.05)
    # no leaked heartbeat task
    assert len(asyncio.all_tasks()) <= tasks_before + 1


@pytest.mark.asyncio
async def test_zero_interval_disables_periodic_heartbeat_backward_compatible():
    registry = ComponentHealthRegistry()
    registry.register("session_runner", required=True)
    calls = []

    async def run_once():
        await asyncio.sleep(0.05)

    await run_with_bounded_restart(
        run_once, registry, on_heartbeat=lambda: calls.append(1),
        heartbeat_interval_seconds=0,  # disabled
    )
    # only entry + clean-exit -> exactly the pre-Task-87B cadence
    assert len(calls) == 2


# -------------------- FC_08 minimal coverage --------------------
def test_publisher_stamps_per_symbol_last_event_in_process():
    from talonx_ingest.events.publisher import RedisEventPublisher
    from talonx_ingest.config import RedisConfig

    pub = RedisEventPublisher(RedisConfig())
    pub.note_symbol_event("aapl", "polling")
    pub.note_symbol_event("MSFT", "polling")
    cov = pub.symbol_coverage()
    assert set(cov) == {"AAPL", "MSFT"}
    assert cov["AAPL"]["source"] == "polling" and "at" in cov["AAPL"]


@pytest.mark.asyncio
async def test_liveness_beacon_flushes_symbol_coverage_once_per_beat():
    from talonx_ingest.liveness import LivenessBeacon

    class Pub:
        is_connected = True
        def __init__(self):
            self._cov = {"AAPL": {"at": "2026-08-31T14:00:00+00:00", "source": "polling"}}
            self.coverage_writes: list[dict] = []
            self.liveness_writes = 0
        async def read_ws_heartbeat(self):
            return None
        async def write_liveness(self, payload, ttl):
            self.liveness_writes += 1
            return True
        def symbol_coverage(self):
            return dict(self._cov)
        async def write_symbol_coverage(self, coverage, ttl):
            self.coverage_writes.append(coverage)
            return True

    pub = Pub()
    beacon = LivenessBeacon(pub, interval_seconds=0.01, ttl_seconds=90)
    await beacon._write_once()
    assert pub.liveness_writes == 1
    assert pub.coverage_writes == [{"AAPL": {"at": "2026-08-31T14:00:00+00:00", "source": "polling"}}]


@pytest.mark.asyncio
async def test_write_symbol_coverage_is_a_noop_when_disconnected():
    from talonx_ingest.events.publisher import RedisEventPublisher
    from talonx_ingest.config import RedisConfig

    pub = RedisEventPublisher(RedisConfig())
    pub._client = None
    assert await pub.write_symbol_coverage({"AAPL": {}}, 360) is False
    pub._client = AsyncMock()
    assert await pub.write_symbol_coverage({"AAPL": {}}, 360) is True
    key, _val = pub._client.set.await_args.args
    assert key == "talonx:ingest:symbol_coverage"
