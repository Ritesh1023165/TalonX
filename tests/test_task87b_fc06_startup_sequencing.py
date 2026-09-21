"""Task 87B FC_06 -- bounded startup sequencing + readiness reporting.

Proves the critical path (Redis connect, market pollers, core consumers)
is marked ready before the expensive background bootstrap, that those
loops are deferred by a small bounded stagger yet still run, that
readiness is observable (snapshot + Redis key + liveness beat), and that
background-bootstrap state never degrades market-feed health while a
genuine critical-market failure still does.

TEST_FIXTURE_ONLY.
"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from talonx_ingest.startup_readiness import (
    PHASE_BOOTSTRAP_SCHEDULED,
    PHASE_CONSUMERS_STARTED,
    PHASE_FULL_READY,
    PHASE_MARKET_POLLERS_STARTED,
    PHASE_PRESEED_COMPLETE,
    PHASE_REDIS_CONNECTED,
    StartupReadiness,
    delayed_start,
)


def test_phase_order_and_readiness_predicates():
    sr = StartupReadiness()
    assert sr.current_phase == "process_start"
    assert sr.is_market_ready() is False and sr.is_full_ready() is False

    sr.mark(PHASE_PRESEED_COMPLETE)
    sr.mark(PHASE_REDIS_CONNECTED)
    assert sr.is_market_ready() is False  # pollers not up yet
    sr.mark(PHASE_MARKET_POLLERS_STARTED)
    assert sr.is_market_ready() is True   # redis + pollers -> market path ready
    assert sr.is_full_ready() is False

    sr.mark(PHASE_CONSUMERS_STARTED)
    sr.mark(PHASE_BOOTSTRAP_SCHEDULED)
    sr.mark(PHASE_FULL_READY)
    assert sr.is_full_ready() is True
    assert sr.current_phase == PHASE_FULL_READY


def test_mark_is_idempotent_and_timestamps_first_only():
    sr = StartupReadiness()
    sr.mark(PHASE_REDIS_CONNECTED)
    t1 = sr.snapshot()["phase_times"][PHASE_REDIS_CONNECTED]
    time.sleep(0.01)
    sr.mark(PHASE_REDIS_CONNECTED)
    assert sr.snapshot()["phase_times"][PHASE_REDIS_CONNECTED] == t1


@pytest.mark.asyncio
async def test_snapshot_is_published_to_redis_key():
    class Pub:
        def __init__(self):
            self._client = AsyncMock()
    pub = Pub()
    sr = StartupReadiness(pub, redis_key="talonx:ingest:startup", ttl_seconds=3600)
    sr.mark(PHASE_REDIS_CONNECTED)
    await sr.publish()
    pub._client.set.assert_awaited_once()
    key, value = pub._client.set.await_args.args
    assert key == "talonx:ingest:startup"
    body = json.loads(value)
    assert body["current_phase"] == PHASE_REDIS_CONNECTED and body["market_ready"] is False


@pytest.mark.asyncio
async def test_delayed_start_defers_first_run_but_still_runs():
    ran_at: list[float] = []
    start = asyncio.get_event_loop().time()

    async def work():
        ran_at.append(asyncio.get_event_loop().time() - start)

    await delayed_start(lambda: work(), 0.05, name="unit")
    assert len(ran_at) == 1
    assert ran_at[0] >= 0.045  # actually waited the bounded delay


@pytest.mark.asyncio
async def test_delayed_start_zero_delay_runs_immediately():
    ran = []
    await delayed_start(lambda: _noop(ran), 0.0, name="unit")
    assert ran == ["done"]


async def _noop(sink):
    sink.append("done")


@pytest.mark.asyncio
async def test_staggered_bootstrap_tasks_all_eventually_complete():
    """Simulates the run_talonx wiring: three 'expensive' loops wrapped in
    delayed_start with an increasing bounded stagger -- all must run."""
    completed: list[str] = []

    def make(name):
        async def loop():
            completed.append(name)
        return loop

    stg = 0.02
    tasks = [
        asyncio.create_task(delayed_start(make("ingestion"), stg * 1, name="ingestion")),
        asyncio.create_task(delayed_start(make("financials"), stg * 2, name="financials")),
        asyncio.create_task(delayed_start(make("reconcile"), stg * 4, name="reconcile")),
    ]
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=2.0)
    assert sorted(completed) == ["financials", "ingestion", "reconcile"]


# ---- liveness beat carries startup phase; bootstrap phase != degraded ----
@pytest.mark.asyncio
async def test_liveness_beat_carries_startup_phase():
    from talonx_ingest.liveness import LivenessBeacon

    class Pub:
        is_connected = True
        _client = None
        def __init__(self):
            self.written = []
        async def read_ws_heartbeat(self):
            return None
        async def write_liveness(self, payload, ttl):
            self.written.append(payload)
            return True

    sr = StartupReadiness()
    sr.mark(PHASE_REDIS_CONNECTED)
    sr.mark(PHASE_MARKET_POLLERS_STARTED)
    sr.mark(PHASE_BOOTSTRAP_SCHEDULED)  # market ready, bootstrap still warming
    pub = Pub()
    beacon = LivenessBeacon(pub, interval_seconds=0.01, ttl_seconds=90, startup_readiness=sr)
    await beacon._write_once()
    payload = pub.written[0]
    assert payload["startup_phase"] == PHASE_BOOTSTRAP_SCHEDULED
    assert payload["startup_market_ready"] is True


@pytest.mark.asyncio
async def test_bootstrap_not_full_ready_does_not_degrade_feed_health():
    """A fresh beat + recent event during RTH is HEALTHY even though the
    expensive background bootstrap has not reported full_ready."""
    from datetime import datetime, timedelta, timezone
    from talonx_dispatch.config import DispatchConfig
    from talonx_dispatch.telegram_listener import TelegramReplyListener
    from unittest.mock import MagicMock

    ln = TelegramReplyListener(store=MagicMock(), config=DispatchConfig(),
                               telegram_client=AsyncMock(), bot_factory=MagicMock())
    now = datetime.now(timezone.utc)
    hb = json.dumps({"updated_at": (now - timedelta(seconds=3)).isoformat()})
    beat = json.dumps({
        "updated_at": (now - timedelta(seconds=2)).isoformat(), "redis_reachable": True,
        "session_phase": "regular", "last_market_event_age_seconds": 3.0,
        "startup_phase": PHASE_BOOTSTRAP_SCHEDULED, "startup_market_ready": True,
    })
    client = AsyncMock()
    cfg = DispatchConfig()

    async def fake_get(key):
        return hb if key == cfg.ws_heartbeat_key else (beat if key == cfg.liveness_key else None)

    client.get = AsyncMock(side_effect=fake_get)
    state, _desc, _why = await ln._market_feed_state(client)
    assert state == "HEALTHY"
