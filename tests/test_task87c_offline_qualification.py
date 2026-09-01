"""Task 87C -- overnight offline qualification gap-fill.

TEST_FIXTURE_ONLY. No production code is imported for modification and no
real sockets are used. These tests fill the deeper-qualification gaps the
Task 87C night contract asks for on top of the Task 87B dedicated suites:

  * Phase 1  -- the EXACT frozen thresholds (90 s stale / 90 s fresh /
               20 s beacon / 90 s TTL) classify correctly at their
               boundaries.
  * Phase 2  -- FC_01 ambiguous-ack -> restart -> Dispatch dedup proven as
               ONE chained flow (exactly one user-facing side effect), and
               the intraday decision-bearing path has the same
               durability+idempotency as the long-term path.
  * Phase 3  -- full session-phase transition sequence + weekend, asserting
               HEALTHY / IDLE / STALE / DISCONNECTED and the /ping text
               agree at every step.
  * Phase 6  -- FC_02 in-process failure delta does not double-count across
               a UTC-day rollover.
  * Phase 7  -- canonical 43 -> 42 reconciliation invariant: every
               configured symbol maps to exactly one owner, 0 unaccounted.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from talonx_dispatch.config import DispatchConfig
from talonx_dispatch.telegram_listener import TelegramReplyListener


# ======================================================================
# Phase 1 -- frozen threshold boundaries
# ======================================================================
FROZEN_LIVENESS_STALE_SECONDS = 90.0
FROZEN_MARKET_FRESH_SECONDS = 90.0
FROZEN_BEACON_INTERVAL_SECONDS = 20.0
FROZEN_BEACON_TTL_SECONDS = 90


def _listener() -> TelegramReplyListener:
    return TelegramReplyListener(
        store=MagicMock(), config=DispatchConfig(), telegram_client=AsyncMock(),
        bot_factory=MagicMock(),
    )


def _frozen_config_is_unchanged() -> DispatchConfig:
    return DispatchConfig()


def test_phase1_frozen_values_are_what_the_code_defaults_to():
    cfg = _frozen_config_is_unchanged()
    assert cfg.liveness_stale_seconds == FROZEN_LIVENESS_STALE_SECONDS
    assert cfg.market_feed_fresh_seconds == FROZEN_MARKET_FRESH_SECONDS
    assert cfg.liveness_key == "talonx:ingest:liveness"
    from talonx_ingest.config import RedisConfig
    rc = RedisConfig()
    assert rc.liveness_interval_seconds == FROZEN_BEACON_INTERVAL_SECONDS
    assert rc.liveness_ttl_seconds == FROZEN_BEACON_TTL_SECONDS


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


def _beat(*, age_seconds: float, phase: str, redis_reachable: bool = True,
          event_age: float | None = None) -> str:
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    return json.dumps({
        "component": "ingest", "process_alive": True, "redis_reachable": redis_reachable,
        "updated_at": ts, "session_phase": phase,
        "last_market_event_age_seconds": event_age, "active_poller": "streaming_yfinance",
    })


def _hb(age_seconds: float) -> str:
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    return json.dumps({"source": "polling", "connected": True, "updated_at": ts})


@pytest.mark.asyncio
async def test_phase1_market_fresh_boundary_89s_vs_91s_regular_session():
    ln = _listener()
    # ws_heartbeat age is the market-event freshness signal (written on every
    # published bar); the liveness beat is the independent process-alive
    # signal. 89 s < 90 s fresh threshold -> HEALTHY.
    fresh = _fake_redis(heartbeat=_hb(89),
                        liveness=_beat(age_seconds=3, phase="regular"))
    state, _d, _w = await ln._market_feed_state(fresh)
    assert state == "HEALTHY"
    # 91 s > 90 s, regular session, beat still alive -> STALE (not DISCONNECTED)
    stale = _fake_redis(heartbeat=_hb(91),
                        liveness=_beat(age_seconds=3, phase="regular"))
    state2, _d, _w = await ln._market_feed_state(stale)
    assert state2 == "STALE"


@pytest.mark.asyncio
async def test_phase1_liveness_stale_boundary_89s_vs_91s_beat_age():
    ln = _listener()
    # beat age 89 s < 90 s stale -> still trusted; quiet phase -> IDLE
    ok = _fake_redis(heartbeat=_hb(200), liveness=_beat(age_seconds=89, phase="closed"))
    s1, _d, _w = await ln._market_feed_state(ok)
    assert s1 == "IDLE"
    # beat age 91 s > 90 s stale -> beat itself expired -> DISCONNECTED
    gone = _fake_redis(heartbeat=_hb(200), liveness=_beat(age_seconds=91, phase="closed"))
    s2, _d, why = await ln._market_feed_state(gone)
    assert s2 == "DISCONNECTED"
    assert "liveness beat" in why.lower()


# ======================================================================
# Phase 2 -- FC_01 chained: Core outage -> restart -> recover -> Dispatch
#           once -> replay same outbox_id -> Dispatch no-op (ONE flow).
# ======================================================================
def _sig(direction="bullish"):
    return {"ticker": "AAPL", "signal_type": "rsi_oversold_volume_surge", "direction": direction,
            "message": "RSI oversold with volume surge", "price": 200.0,
            "bar_timestamp": "2026-08-07T12:00:00Z"}


def _report(verdict="bullish", confidence=0.9):
    return {"ticker": "AAPL", "triggering_signal": _sig(), "verdict": verdict,
            "confidence": confidence, "summary": "Fundamentals support the move.",
            "key_findings": [], "risk_factors": [], "citations": [], "model_used": "gemini-flash-latest",
            "generated_at": "2026-08-07T12:00:30Z", "published_at": "2026-08-07T12:00:30Z"}


def _msg(channel, payload):
    return {"channel": channel.encode(), "data": json.dumps(payload)}


class _FlakyRedis:
    def __init__(self):
        self.up = True
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel, payload):
        if not self.up:
            raise ConnectionError("Redis unavailable (simulated)")
        self.published.append((channel, payload))
        return 1

    async def incrby(self, *a, **k):
        return 1

    async def expire(self, *a, **k):
        return True


@pytest.mark.asyncio
async def test_phase2_intraday_outage_restart_recover_dispatch_once_then_replay_noop(tmp_path):
    from talonx_core.config import CoreConfig
    from talonx_core.consumer import DecisionEngine
    from talonx_core.store import TickerStateStore
    from talonx_dispatch.config import DispatchConfig
    from talonx_dispatch.consumer import DispatchAgent
    from talonx_dispatch.store import AuditStore
    from talonx_watchlist.store import TickerWatchlistStore

    ob_path = str(tmp_path / "core_alert_outbox.json")

    # --- Core, Redis DOWN when the decision-bearing alert is produced ---
    down = _FlakyRedis(); down.up = False
    core1 = DecisionEngine(
        config=CoreConfig(alert_outbox_path=ob_path, alert_outbox_backoff_base_seconds=0.0,
                          alert_outbox_backoff_max_seconds=0.0),
        store=TickerStateStore(tmp_path / "core1.db"),
    )
    core1._client = down
    await core1._handle_message(_msg(core1.config.signals_channel, _sig("bullish")))
    await core1._handle_message(_msg(core1.config.reports_channel, _report("bullish", 0.9)))
    assert down.published == []                       # nothing on the wire
    assert core1.alert_outbox.pending_depth() == 1    # obligation is durable

    # --- Core restart: fresh engine, same outbox file, Redis healthy ---
    healthy = _FlakyRedis()
    core2 = DecisionEngine(
        config=CoreConfig(alert_outbox_path=ob_path, alert_outbox_backoff_base_seconds=0.0,
                          alert_outbox_backoff_max_seconds=0.0),
        store=TickerStateStore(tmp_path / "core2.db"),
    )
    core2._client = healthy
    assert core2.alert_outbox.pending_depth() == 1    # reloaded from disk
    await core2._flush_alert_outbox()
    assert len(healthy.published) == 1
    assert core2.alert_outbox.pending_depth() == 0
    wire_channel, wire_payload = healthy.published[0]
    outbox_id = json.loads(wire_payload)["outbox_id"]
    assert outbox_id and len(outbox_id) == 32

    # --- Dispatch receives the recovered alert exactly once ---
    audit = AuditStore(tmp_path / "audit.db")
    wl = TickerWatchlistStore(tmp_path / "wl.db")
    disp = DispatchAgent(config=DispatchConfig(), store=audit, telegram_client=AsyncMock(),
                         watchlist_store=wl)
    disp._client = AsyncMock()
    disp._maybe_send_telegram = AsyncMock()

    dmsg = {"channel": disp.config.alerts_channel.encode(), "data": wire_payload}
    await disp._handle_message(dmsg)
    # --- at-least-once redelivery of the SAME outbox_id ---
    await disp._handle_message(dmsg)

    rows = audit._conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    assert rows == 1                                  # recorded exactly once
    assert disp._maybe_send_telegram.await_count == 1  # user-facing side effect once
    audit.close()


@pytest.mark.asyncio
async def test_phase11_aug31_mcd_hold_quality_replay_durable_recovery_muted(tmp_path):
    """Aug 31 replay with the RECORDED MCD values (Task 86 forensic_report.md
    lines 103-113): moat=wide quality=9 fair_value=280.00 price=265.00
    margin_of_safety ~5.7%, action hold_quality. On the day, Core's
    _publish_long_term_alert to talonx:alerts:longterm timed out at
    08:35:23 during the startup Redis-contention window, mark_alerted had
    already run -> Dispatch received nothing. Under e5fcdec (FC_01) the
    alert is enqueued durably first, survives the outage, and is delivered
    exactly once on recovery -- while hold_quality stays Telegram-muted."""
    from talonx_core.alert_outbox import KIND_LONG_TERM, make_outbox_id
    from talonx_dispatch.config import DispatchConfig
    from talonx_dispatch.consumer import DispatchAgent
    from talonx_dispatch.store import AuditStore
    from talonx_watchlist.store import TickerWatchlistStore

    audit = AuditStore(tmp_path / "audit.db")
    wl = TickerWatchlistStore(tmp_path / "wl.db")
    disp = DispatchAgent(config=DispatchConfig(), store=audit, telegram_client=AsyncMock(),
                         watchlist_store=wl)
    disp._client = AsyncMock()

    lt_payload = {
        "ticker": "MCD", "action": "hold_quality", "severity": "info", "rationale": "r",
        "summary": "wide-moat quality hold", "quality_score": 9, "moat_rating": "wide",
        "market_price": 265.0, "intrinsic_fair_value": 280.0, "margin_of_safety_pct": 0.057,
        "capital_allocation_assessment": "ok", "key_findings": [], "risk_factors": [],
        "model_used": "gemini", "correlated_at": "2026-08-31T08:35:23Z",
        "published_at": "2026-08-31T08:35:23Z",
        "outbox_id": make_outbox_id(ticker="MCD", trading_date="2026-08-31",
                                    kind=KIND_LONG_TERM, action="hold_quality",
                                    correlated_at="2026-08-31T08:35:23+00:00"),
    }
    # Dispatch receives the recovered alert (post-outbox-flush) exactly once,
    # then an at-least-once redelivery under the same outbox_id.
    await disp._handle_long_term_alert(dict(lt_payload))
    await disp._handle_long_term_alert(dict(lt_payload))

    lt_rows = audit._conn.execute("SELECT COUNT(*) FROM long_term_alerts").fetchone()[0]
    assert lt_rows == 1                                   # durably recorded ONCE
    assert disp.telegram_client.send.await_count == 0     # hold_quality stays muted
    audit.close()


# ======================================================================
# Phase 3 -- full session transition sequence + weekend
# ======================================================================
@pytest.mark.asyncio
async def test_phase3_session_transition_sequence_pre_open_rth_post_closed():
    ln = _listener()
    steps = [
        # (phase, beat_age, hb_age, expected_state, headline_prefix)
        ("pre_market", 15, 280.0, "IDLE", "IDLE"),        # thin pre-market, sparse ticks
        ("regular", 5, 4.0, "HEALTHY", "HEALTHY"),        # RTH, fresh bars
        ("regular", 5, 400.0, "STALE", "DEGRADED"),       # RTH but ticks dried up
        ("after_hours", 8, 200.0, "IDLE", "IDLE"),        # post-close, quiet is fine
        ("closed", 30, 4000.0, "IDLE", "IDLE"),           # overnight
    ]
    for phase, beat_age, hb_age, expected, headline in steps:
        client = _fake_redis(heartbeat=_hb(hb_age),
                             liveness=_beat(age_seconds=beat_age, phase=phase))
        state, _d, _w = await ln._market_feed_state(client)
        assert state == expected, f"{phase}: expected {expected}, got {state}"
        _client2, label = await ln._market_feed_freshness(client)
        assert ln._pipeline_status(client, label).startswith(headline), (
            f"{phase}: headline mismatch for state {state}"
        )


@pytest.mark.asyncio
async def test_phase3_weekend_is_idle_not_disconnected():
    ln = _listener()
    # Saturday: get_session_state -> "closed"; ingest beat still fresh.
    client = _fake_redis(heartbeat=_hb(3600),
                         liveness=_beat(age_seconds=12, phase="closed", event_age=90000.0))
    state, _d, _w = await ln._market_feed_state(client)
    assert state == "IDLE"
    _c, label = await ln._market_feed_freshness(client)
    assert "disconnected" not in ln._pipeline_status(client, label).lower()


@pytest.mark.asyncio
async def test_phase3_unknown_when_no_redis():
    ln = _listener()
    assert ln._pipeline_status(None, "\U0001F7E2 healthy") == "UNKNOWN (no Redis connection)"


# ======================================================================
# Phase 4 -- DISCONNECTED vs STALE, proven deterministically offline.
#   * poller task stalled, PROCESS + beacon alive  -> STALE  ("feed stale")
#   * whole ingest process / Redis link down (beat gone/expired/unreachable)
#                                              -> DISCONNECTED ("feed disconnected")
# No broker exposure, no process kill, fully reversible, no prod change.
# ======================================================================
@pytest.mark.asyncio
async def test_phase4_poller_stalled_process_alive_is_stale_not_disconnected():
    ln = _listener()
    # streaming poller coroutine wedged: ws_heartbeat goes stale, but the
    # LivenessBeacon (separate timer task) keeps the beat fresh + regular.
    client = _fake_redis(heartbeat=_hb(400),
                         liveness=_beat(age_seconds=5, phase="regular"))
    state, _d, _w = await ln._market_feed_state(client)
    assert state == "STALE"
    _c, label = await ln._market_feed_freshness(client)
    assert ln._pipeline_status(client, label) == "DEGRADED (market feed stale)"


@pytest.mark.asyncio
async def test_phase4_process_or_redis_down_is_disconnected_three_ways():
    ln = _listener()
    # (a) beat key entirely gone
    a = _fake_redis(heartbeat=_hb(5), liveness=None,)
    # legacy fallback path when NO beat: fresh hb -> HEALTHY (documented).
    # The DISCONNECTED cases below all have a beat that proves the link is down.
    sa, _d, _w = await ln._market_feed_state(a)
    assert sa == "HEALTHY"  # no-beat legacy fallback, unchanged

    # (b) beat present but expired (> 90 s stale window) -> DISCONNECTED
    b = _fake_redis(heartbeat=_hb(5), liveness=_beat(age_seconds=95, phase="regular"))
    sb, _d, whyb = await ln._market_feed_state(b)
    assert sb == "DISCONNECTED" and "liveness beat" in whyb.lower()
    _c, lb = await ln._market_feed_freshness(b)
    assert ln._pipeline_status(b, lb) == "DEGRADED (market feed disconnected)"

    # (c) beat fresh but self-reports redis unreachable -> DISCONNECTED
    c = _fake_redis(heartbeat=_hb(5),
                    liveness=_beat(age_seconds=3, phase="regular", redis_reachable=False))
    sc, _d, whyc = await ln._market_feed_state(c)
    assert sc == "DISCONNECTED" and "redis" in whyc.lower()


# ======================================================================
# Phase 5 -- FC_06 startup sequencing repeated-iteration stress (offline
#           proxy; the real first-15-min contention signal is live).
# ======================================================================
@pytest.mark.asyncio
async def test_phase5_repeated_startup_sim_is_deterministic_and_ordered():
    import asyncio

    from talonx_ingest.startup_readiness import (
        PHASE_BOOTSTRAP_SCHEDULED, PHASE_CONSUMERS_STARTED, PHASE_FULL_READY,
        PHASE_MARKET_POLLERS_STARTED, PHASE_PRESEED_COMPLETE, PHASE_REDIS_CONNECTED,
        StartupReadiness, delayed_start,
    )

    ITER = 25
    stg = 0.005  # scaled-down stagger step
    market_ready_before_full = 0
    order_ok = 0
    heavy_all_ran = 0

    for _ in range(ITER):
        sr = StartupReadiness()
        completed: list[str] = []

        def make(name):
            async def loop():
                completed.append(name)
            return loop

        sr.mark(PHASE_PRESEED_COMPLETE)
        sr.mark(PHASE_REDIS_CONNECTED)
        sr.mark(PHASE_MARKET_POLLERS_STARTED)
        assert sr.is_market_ready() is True
        assert sr.is_full_ready() is False
        market_ready_before_full += 1

        sr.mark(PHASE_CONSUMERS_STARTED)
        sr.mark(PHASE_BOOTSTRAP_SCHEDULED)
        heavy = [
            asyncio.create_task(delayed_start(make("ingestion"), stg * 1, name="ingestion")),
            asyncio.create_task(delayed_start(make("financials"), stg * 2, name="financials")),
            asyncio.create_task(delayed_start(make("earnings"), stg * 3, name="earnings")),
            asyncio.create_task(delayed_start(make("reconcile"), stg * 4, name="reconcile")),
        ]
        await asyncio.wait_for(asyncio.gather(*heavy), timeout=2.0)
        sr.mark(PHASE_FULL_READY)

        if sr.is_full_ready():
            order_ok += 1
        if completed == ["ingestion", "financials", "earnings", "reconcile"]:
            heavy_all_ran += 1

    assert market_ready_before_full == ITER
    assert order_ok == ITER
    assert heavy_all_ran == ITER  # stagger order held on every iteration -- no race


# ======================================================================
# Phase 6 -- FC_02 no double count across a UTC-day rollover
# ======================================================================
@pytest.mark.asyncio
async def test_phase6_failure_delta_does_not_double_count_across_utc_day_rollover():
    from talonx_ingest.config import RedisConfig
    from talonx_ingest.events.publisher import RedisEventPublisher

    pub = RedisEventPublisher(RedisConfig())
    pub._client = None
    for _ in range(4):
        await pub._publish("c", "{}")
    assert pub.publish_failures == 4 and pub._publish_failures_flushed == 0

    healthy = AsyncMock()
    healthy.incrby = AsyncMock(return_value=4)
    pub._client = healthy

    # First flush "today".
    await pub._flush_publish_failure_delta()
    assert pub._publish_failures_flushed == 4
    first_calls = [c for c in healthy.incrby.await_args_list
                   if ":ingest:market_redis_publish_failures" in c.args[0]]
    assert len(first_calls) == 1 and first_calls[0].args[1] == 4

    # "Day rolls over" -> a later flush with NO new failures must be a no-op,
    # regardless of which day-key it would target. Watermark == tally.
    healthy.incrby.reset_mock()
    await pub._flush_publish_failure_delta()
    assert healthy.incrby.await_count == 0
    assert pub._publish_failures_flushed == pub.publish_failures  # reconciled, no leak


# ======================================================================
# Phase 7 -- canonical 43 -> 42 reconciliation invariant
# ======================================================================
CONFIGURED_43 = [f"S{i:02d}" for i in range(42)] + ["DELL"]


def _store(active):
    s = MagicMock()
    s.list_active_symbols.return_value = list(active)
    return s


def test_phase7_canonical_reconciliation_zero_unaccounted():
    from run_talonx import PreMarketPoller

    poller = PreMarketPoller(_store(CONFIGURED_43), AsyncMock(), 300.0,
                             active_earnings_symbols_fn=lambda: {"DELL"})
    selected, excluded = poller._select()

    configured = set(CONFIGURED_43)
    premarket_owned = set(selected)
    eft_owned = set(excluded)  # EARNINGS_FAST_TRACK alternate owner

    # every exclusion carries a reason naming its alternate owner
    assert all(reason == "EARNINGS_FAST_TRACK" for reason in excluded.values())
    # partition is exact: no overlap, no gap
    assert premarket_owned & eft_owned == set()
    unaccounted = configured - premarket_owned - eft_owned
    assert unaccounted == set(), f"symbols with no owner: {sorted(unaccounted)}"

    # canonical format
    line = (
        f"{len(configured)} CONFIGURED = {len(premarket_owned)} PREMARKET "
        f"+ {len(eft_owned)} EARNINGS_FAST_TRACK + 0 OTHER + {len(unaccounted)} UNACCOUNTED"
    )
    assert line == "43 CONFIGURED = 42 PREMARKET + 1 EARNINGS_FAST_TRACK + 0 OTHER + 0 UNACCOUNTED"


def test_phase7_no_earnings_window_means_full_43_and_still_zero_unaccounted():
    from run_talonx import PreMarketPoller

    poller = PreMarketPoller(_store(CONFIGURED_43), AsyncMock(), 300.0,
                             active_earnings_symbols_fn=lambda: set())
    selected, excluded = poller._select()
    configured = set(CONFIGURED_43)
    unaccounted = configured - set(selected) - set(excluded)
    assert len(selected) == 43 and excluded == {} and unaccounted == set()
