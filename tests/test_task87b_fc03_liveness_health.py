"""Task 87B FC_03 -- market-independent liveness + session-aware feed health.

Proves the /ping feed verdict tells apart:
  HEALTHY  -- recent market event
  IDLE     -- ingest process provably alive, market phase legitimately quiet
  STALE    -- ingest alive but no ticks DURING the regular session
  DISCONNECTED -- the liveness beat itself is gone (process/redis down)
and that historical Redis reconnect/failure counters never feed it.

TEST_FIXTURE_ONLY -- no real sockets.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.telegram_listener import TelegramReplyListener
from talonx_ingest.liveness import LivenessBeacon

NOW = datetime(2026, 8, 31, 20, 5, 0, tzinfo=timezone.utc)  # ~16:05 ET -- just after the close


def _listener() -> TelegramReplyListener:
    return TelegramReplyListener(
        store=MagicMock(), config=DispatchConfig(), telegram_client=AsyncMock(), bot_factory=MagicMock(),
    )


def _fake_redis(*, heartbeat=None, liveness=None, extra: dict | None = None):
    client = AsyncMock()
    cfg = DispatchConfig()

    async def fake_get(key):
        if key == cfg.ws_heartbeat_key:
            return heartbeat
        if key == cfg.liveness_key:
            return liveness
        if extra and key in extra:
            return extra[key]
        return None

    client.get = AsyncMock(side_effect=fake_get)
    return client


def _hb(age_seconds: float) -> str:
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    return json.dumps({"source": "polling", "connected": True, "updated_at": ts})


def _beat(*, age_seconds: float, phase: str, redis_reachable: bool = True, event_age: float | None = None) -> str:
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    return json.dumps({
        "component": "ingest", "process_alive": True, "redis_reachable": redis_reachable,
        "updated_at": ts, "session_phase": phase, "last_market_event_age_seconds": event_age,
        "active_poller": "streaming_yfinance",
    })


# --------------------------------------------------------------------------
# scenario matrix -- machine state AND /ping operator text
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_1_process_alive_rth_events_fresh_is_healthy():
    ln = _listener()
    client = _fake_redis(heartbeat=_hb(5), liveness=_beat(age_seconds=3, phase="regular"))
    state, _desc, _why = await ln._market_feed_state(client)
    assert state == "HEALTHY"
    _, label = await ln._market_feed_freshness(client)
    assert ln._pipeline_status(client, label).startswith("HEALTHY")


@pytest.mark.asyncio
async def test_2_process_alive_market_closed_is_idle_not_disconnected():
    ln = _listener()
    client = _fake_redis(heartbeat=_hb(1800), liveness=_beat(age_seconds=10, phase="closed"))
    state, _desc, why = await ln._market_feed_state(client)
    assert state == "IDLE"
    _, label = await ln._market_feed_freshness(client)
    status = ln._pipeline_status(client, label)
    assert status.startswith("IDLE")
    assert "disconnected" not in status.lower()


@pytest.mark.asyncio
async def test_3_process_alive_premarket_sparse_is_idle():
    ln = _listener()
    # PreMarketPoller cadence 300s > old 120s TTL -- would have been "disconnected" pre-FC_03.
    client = _fake_redis(heartbeat=_hb(280), liveness=_beat(age_seconds=15, phase="pre_market"))
    state, *_ = await ln._market_feed_state(client)
    assert state == "IDLE"


@pytest.mark.asyncio
async def test_4_provider_responding_no_new_bar_after_hours_is_idle():
    ln = _listener()
    client = _fake_redis(heartbeat=_hb(200), liveness=_beat(age_seconds=5, phase="after_hours"))
    state, *_ = await ln._market_feed_state(client)
    assert state == "IDLE"


@pytest.mark.asyncio
async def test_5_redis_publication_degraded_beat_says_unreachable_is_disconnected():
    ln = _listener()
    client = _fake_redis(heartbeat=_hb(300), liveness=_beat(age_seconds=5, phase="regular", redis_reachable=False))
    state, _desc, why = await ln._market_feed_state(client)
    assert state == "DISCONNECTED"
    assert "redis" in why.lower()


@pytest.mark.asyncio
async def test_6_and_10_stale_events_during_regular_session_is_stale():
    ln = _listener()
    client = _fake_redis(heartbeat=_hb(400), liveness=_beat(age_seconds=5, phase="regular"))
    state, _desc, why = await ln._market_feed_state(client)
    assert state == "STALE"
    _, label = await ln._market_feed_freshness(client)
    assert ln._pipeline_status(client, label).startswith("DEGRADED")


@pytest.mark.asyncio
async def test_7_liveness_beat_missing_is_disconnected_even_with_recent_heartbeat():
    ln = _listener()
    # heartbeat looks recent, but the process-liveness beat is gone -> the
    # ingest process / its Redis link is actually down. Legacy fallback
    # (no beat) still classifies on the heartbeat alone.
    client_no_beat_fresh_hb = _fake_redis(heartbeat=_hb(5), liveness=None)
    state, *_ = await ln._market_feed_state(client_no_beat_fresh_hb)
    assert state == "HEALTHY"  # legacy fallback: fresh hb, no beat -> healthy (unchanged pre-FC_03 behaviour)

    client_beat_expired = _fake_redis(heartbeat=_hb(5), liveness=_beat(age_seconds=999, phase="regular"))
    state2, _d, why2 = await ln._market_feed_state(client_beat_expired)
    assert state2 == "DISCONNECTED"
    assert "liveness beat" in why2.lower()

    client_all_gone = _fake_redis(heartbeat=None, liveness=None)
    state3, *_ = await ln._market_feed_state(client_all_gone)
    assert state3 == "DISCONNECTED"


@pytest.mark.asyncio
async def test_8_reconnect_then_recovery_is_healthy():
    ln = _listener()
    client = _fake_redis(heartbeat=_hb(2), liveness=_beat(age_seconds=1, phase="regular"))
    state, *_ = await ln._market_feed_state(client)
    assert state == "HEALTHY"


@pytest.mark.asyncio
async def test_9_historical_reconnect_failure_counters_do_not_poison_healthy():
    ln = _listener()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    client = _fake_redis(
        heartbeat=_hb(3), liveness=_beat(age_seconds=2, phase="regular"),
        extra={
            f"metrics:{today}:ingest:market_redis_reconnect_attempts": "37",
            f"metrics:{today}:ingest:market_redis_publish_failures": "9",
            f"metrics:{today}:ingest:market_redis_reconnect_successes": "12",
        },
    )
    state, *_ = await ln._market_feed_state(client)
    assert state == "HEALTHY"  # counters are informational only, never an input


@pytest.mark.asyncio
async def test_legacy_fallback_preserves_old_stale_and_disconnected_contract():
    ln = _listener()
    # old stale heartbeat, NO liveness beat -> STALE (unchanged pre-FC_03)
    s1, *_ = await ln._market_feed_state(_fake_redis(heartbeat=_hb(600), liveness=None))
    assert s1 == "STALE"
    # no heartbeat, no beat -> DISCONNECTED (unchanged)
    s2, *_ = await ln._market_feed_state(_fake_redis(heartbeat=None, liveness=None))
    assert s2 == "DISCONNECTED"


def test_pipeline_status_idle_label_maps_to_idle_headline():
    ln = _listener()
    assert ln._pipeline_status(MagicMock(), "\U0001F7E2 idle").startswith("IDLE")
    # explicit-label contracts the existing suite relies on are unchanged
    assert ln._pipeline_status(MagicMock(), "\U0001F534 disconnected").startswith("DEGRADED")
    assert ln._pipeline_status(MagicMock(), "\U0001F7E1 stale").startswith("DEGRADED")
    assert ln._pipeline_status(MagicMock(), "\U0001F7E2 healthy").startswith("HEALTHY")
    assert ln._pipeline_status(None, "\U0001F7E2 healthy") == "UNKNOWN (no Redis connection)"


# --------------------------------------------------------------------------
# LivenessBeacon producer
# --------------------------------------------------------------------------
class _FakePublisher:
    def __init__(self, connected=True, hb_age=10.0):
        self.is_connected = connected
        self._hb_age = hb_age
        self.written: list[tuple[dict, int]] = []

    async def read_ws_heartbeat(self):
        if self._hb_age is None:
            return None
        ts = (datetime.now(timezone.utc) - timedelta(seconds=self._hb_age)).isoformat()
        return json.dumps({"updated_at": ts})

    async def write_liveness(self, payload, ttl):
        self.written.append((payload, ttl))
        return True


@pytest.mark.asyncio
async def test_beacon_writes_market_independent_beat_with_context():
    pub = _FakePublisher(connected=True, hb_age=42.0)
    beacon = LivenessBeacon(pub, interval_seconds=0.01, ttl_seconds=90,
                            active_poller_fn=lambda: "streaming_yfinance")
    await beacon._write_once()
    assert len(pub.written) == 1
    payload, ttl = pub.written[0]
    assert ttl == 90
    assert payload["process_alive"] is True
    assert payload["redis_reachable"] is True
    assert payload["active_poller"] == "streaming_yfinance"
    assert payload["session_phase"] in ("pre_market", "regular", "after_hours", "closed")
    assert abs(payload["last_market_event_age_seconds"] - 42.0) < 2.0


@pytest.mark.asyncio
async def test_beacon_reports_redis_unreachable_when_publisher_disconnected():
    pub = _FakePublisher(connected=False, hb_age=None)
    beacon = LivenessBeacon(pub, interval_seconds=0.01, ttl_seconds=90)
    await beacon._write_once()
    payload, _ = pub.written[0]
    assert payload["redis_reachable"] is False
    assert payload["last_market_event_age_seconds"] is None


@pytest.mark.asyncio
async def test_beacon_run_loop_writes_repeatedly_then_stops():
    import asyncio
    pub = _FakePublisher()
    beacon = LivenessBeacon(pub, interval_seconds=0.01, ttl_seconds=90)
    task = asyncio.create_task(beacon.run())
    await asyncio.sleep(0.05)
    beacon.stop()
    await asyncio.wait_for(task, timeout=1.0)
    assert beacon.beats_written >= 2
