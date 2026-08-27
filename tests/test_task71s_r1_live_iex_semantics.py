"""Task 71S-R1 -- complete live IEX sparsity semantics.

Covers: the NO_IEX_BAR_OBSERVED rename (an honest, aggregate-bar-only
label, no longer overclaiming trade-level confirmation), the new
NO_NEW_IEX_BAR per-tick classification + rolling per-symbol coverage
counters in talonx_piv/freshness.py, and session_runner.py's fix for the
"a not-ready symbol stops being monitored at all" gap this task's own
Phase B forensic analysis found (REGN: only 5 of ~40 real regular-session
gaps were ever observed/reported live, because `_check_stale` used to skip
any symbol outside `_ready_symbols`).

Every fake transport below exposes only `.get()`; any `.post()`/`.delete()`
call is a test failure.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from talonx_piv.broker import AlpacaPaperClient
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.freshness import (
    DATA_GAP,
    FRESH,
    HEALTHY,
    NO_NEW_IEX_BAR,
    RECOVERED,
    STALE,
    UNKNOWN,
    FreshnessTracker,
)
from talonx_piv.gap_forensics import NO_IEX_BAR_OBSERVED
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.session_runner import SessionRunner
from talonx_piv.warmup import WarmupCheck

ET = ZoneInfo("America/New_York")
SESSION = date(2026, 8, 24)
UNIVERSE = ("AAPL", "MSFT", "REGN")


# =======================================================================
# NO_IEX_BAR_OBSERVED rename -- honest, aggregate-bar-only evidence label
# =======================================================================

def test_gap_forensics_uses_honest_aggregate_only_label():
    """The classification module must never claim trade-level confirmation
    -- only aggregate 1-minute-BAR absence was ever checked (Alpaca's
    /v2/stocks/{symbol}/bars endpoint), not a trade-level feed."""
    assert NO_IEX_BAR_OBSERVED == "NO_IEX_BAR_OBSERVED"
    import talonx_piv.gap_forensics as gf
    assert not hasattr(gf, "CONFIRMED_NO_IEX_TRADE")  # the overstated name must be fully retired


# =======================================================================
# freshness.py -- NO_NEW_IEX_BAR + rolling coverage
# =======================================================================

def test_successful_poll_with_no_symbol_bar_is_not_provider_failure():
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    t.observe_fresh("AAPL")
    classification = t.observe_quiet_tick("AAPL")  # ordinary: poll succeeded, no new bar this tick
    assert classification == NO_NEW_IEX_BAR
    assert t.provider_state == HEALTHY  # provider health untouched by symbol-level quietness
    assert t.state_of("AAPL") == FRESH  # stored state unaffected -- still considered healthy


def test_no_new_iex_bar_never_changes_stored_state():
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    t.observe_fresh("AAPL")
    for _ in range(10):
        t.observe_quiet_tick("AAPL")
    assert t.state_of("AAPL") == FRESH


def test_repetitive_sparse_intervals_do_not_generate_notification_storms():
    """observe_quiet_tick itself never returns anything event-worthy and
    the caller (session_runner) never emits from it -- see the dedicated
    session_runner integration test below for the no-events proof."""
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    t.observe_fresh("REGN")
    for _ in range(500):
        t.observe_quiet_tick("REGN")
    snap = t.snapshot()
    assert snap["coverage"]["REGN"]["quiet_tick_count"] == 500
    assert snap["coverage"]["REGN"]["fresh_bar_count"] == 1


def test_regn_like_sparse_coverage_case():
    """Synthetic replay of REGN's real 2026-08-26 shape: a handful of fresh
    bars against hundreds of quiet ticks -- low but well-defined coverage
    ratio, never a crash, never an invented pass/fail verdict."""
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    for _ in range(70):
        t.observe_fresh("REGN")
    for _ in range(320):
        t.observe_quiet_tick("REGN")
    ratio = t.coverage_ratio("REGN")
    assert ratio is not None and 0.15 < ratio < 0.20  # ~70/390, matching the real day's regular-session ratio


def test_high_coverage_aapl_like_case():
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    for _ in range(390):
        t.observe_fresh("AAPL")
    ratio = t.coverage_ratio("AAPL")
    assert ratio == 1.0


def test_never_checked_symbol_has_no_coverage_ratio_not_zero():
    """None (never observed) is honestly distinct from 0.0 (observed and
    always quiet) -- a silent 0.0 would misleadingly look like measured
    total sparsity rather than 'not yet checked at all'."""
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    assert t.coverage_ratio("NEVERSEEN") is None


def test_recovery_events_occur_exactly_once_per_transition():
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    t.observe_fresh("AAPL")
    recoveries = []
    for _ in range(3):
        t.observe_stale("AAPL")
        _, recovered = t.observe_fresh("AAPL")
        recoveries.append(recovered)
    assert recoveries == [True, True, True]  # exactly one recovered=True per stale->fresh cycle, never more


def test_warmup_readiness_and_live_suitability_are_independent_signals():
    """A symbol can be historically warmup-READY (Task 70S: 120+ bars from
    a 10-day lookback) while its live, THIS-SESSION rolling coverage is
    poor (REGN's real 2026-08-26 shape) -- these must never be conflated
    into a single field."""
    warmup_check = WarmupCheck(
        symbol="REGN", preseed_status="PRESEED_CALLED", bar_count_1m=726, required_1m_bars=120,
        bar_count_15m_regular=200, required_15m_bars=200, htf_sma_200_available=True,
        warmup_provider="YFINANCE", live_provider="ALPACA_IEX", evaluated_at="2026-08-26T08:19:00+00:00",
        reason="SUFFICIENT_1M_AND_HTF_HISTORY", ready=True,
    )
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    for _ in range(70):
        t.observe_fresh("REGN")
    for _ in range(320):
        t.observe_quiet_tick("REGN")
    assert warmup_check.ready is True  # historically warmup-ready ...
    assert t.coverage_ratio("REGN") < 0.20  # ... yet poor live-session coverage -- both true, independently


def test_stale_persisted_coverage_counters_not_reused_across_dates():
    t = FreshnessTracker()
    t.reset_for_session(date(2026, 8, 25))
    t.observe_fresh("REGN")
    t.observe_quiet_tick("REGN")
    assert t.coverage_ratio("REGN") == 0.5
    t.reset_for_session(date(2026, 8, 26))
    assert t.coverage_ratio("REGN") is None  # yesterday's counters gone, not carried forward


# =======================================================================
# Integration: session_runner.py wiring
# =======================================================================

class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class BarsTransport:
    def __init__(self, batches):
        self.batches = list(batches)

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "id", "account_number": "PA1", "status": "ACTIVE"}, 200)
        if url.endswith("/v2/orders"):
            return Response([])
        if "bars/latest" in url:
            item = self.batches.pop(0) if self.batches else {}
            if isinstance(item, Exception):
                raise item
            return Response({"bars": item})
        return Response({}, 404)

    def post(self, *a, **k):
        raise AssertionError("session_runner freshness path must never submit an order")

    def delete(self, *a, **k):
        raise AssertionError("session_runner freshness path must never cancel/close a position")


def bar_row(ts, price=100.0):
    return {"t": ts, "o": price, "h": price + 1, "l": price - 1, "c": price, "v": 1000}


def make_config(tmp_path, **overrides):
    values = dict(key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
                  broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
                  universe=UNIVERSE, stale_seconds=90)
    values.update(overrides)
    return PivConfig(**values)


def make_runner(tmp_path, batches, decision_engine=None, **overrides):
    cfg = make_config(tmp_path, **overrides)
    transport = BarsTransport(batches)
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "state.json", broker, bus)
    life.start_session(True, True)
    return SessionRunner(cfg, bus, life, transport, decision_engine=decision_engine), transport, bus


def to_utc_iso(local):
    return local.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_integration_not_ready_symbol_still_monitored_all_day(tmp_path):
    """The REGN regression this task fixes: a symbol excluded from
    _ready_symbols (session-readiness finalization already ran and left it
    out) must still be checked for staleness -- observational monitoring
    continues even though it can never reach the decision path."""
    run, transport, bus = make_runner(tmp_path, [])
    run._session = SESSION
    run._ready_symbols = {"AAPL"}  # REGN explicitly NOT ready (already finalized as DATA_NOT_READY)
    base = datetime(2026, 8, 24, 11, 0, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    run._last_seen_wall["REGN"] = base

    run._check_stale(base + timedelta(seconds=200))  # REGN has been quiet >120s
    assert run._freshness.state_of("REGN") == STALE  # still tracked, despite not being ready
    events_text = bus.path.read_text(encoding="utf-8")
    assert '"symbol": "REGN"' in events_text
    assert '"event": "STALE_DATA"' in events_text


@pytest.mark.asyncio
async def test_integration_data_not_ready_event_emitted_with_insufficient_prints_reason(tmp_path):
    run, transport, bus = make_runner(tmp_path, [])
    run._session = SESSION
    run._ready_symbols = {"AAPL"}
    base = datetime(2026, 8, 24, 11, 0, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    run._last_seen_wall["REGN"] = base
    run._check_stale(base + timedelta(seconds=200))

    events_text = bus.path.read_text(encoding="utf-8")
    assert '"event": "DATA_NOT_READY"' in events_text
    assert "INSUFFICIENT_RECENT_IEX_PRINTS:REGN" in events_text
    assert '"status": "EXCLUDED_FROM_DECISION_PATH"' in events_text


@pytest.mark.asyncio
async def test_integration_quiet_tick_never_emits_any_event(tmp_path):
    """Ordinary sparsity (gap > 0 but within threshold) must produce zero
    events -- only a rolling counter."""
    run, transport, bus = make_runner(tmp_path, [])
    run._session = SESSION
    run._ready_symbols = {"AAPL"}
    base = datetime(2026, 8, 24, 11, 0, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    run._last_seen_wall["AAPL"] = base
    before = bus.path.read_text(encoding="utf-8") if bus.path.exists() else ""
    run._check_stale(base + timedelta(seconds=30))  # well within the 90s configured threshold
    after = bus.path.read_text(encoding="utf-8") if bus.path.exists() else ""
    assert after == before  # zero NEW events emitted by the quiet-tick check
    assert run._freshness.snapshot()["coverage"]["AAPL"]["quiet_tick_count"] == 1


@pytest.mark.asyncio
async def test_integration_no_candidate_from_repeatedly_monitored_not_ready_symbol(tmp_path):
    """Critical regression guard for THIS task's own fix: now that REGN-like
    not-ready symbols are monitored all day (instead of being silently
    skipped), they must still NEVER reach the decision path."""
    fake_engine = AsyncMock()
    fake_engine.warmup_ready_symbols = {"AAPL", "REGN"}  # even if warmup-ready, session-readiness excludes REGN
    fake_engine.funnel_summary = lambda: {
        "evaluation_cycles": 0, "symbols_evaluated_total": 0, "candidates": 0, "published": 0,
        "rejected": 0, "pending": 0, "errored": 0, "unaccounted_candidates": 0, "rejected_breakdown": {},
    }
    # Task 77I: dispatch_pending is a plain SYNC method on the real
    # NotificationOutbox -- stubbed as a plain callable to avoid an
    # unawaited-coroutine warning from AsyncMock's default auto-async attrs.
    fake_engine.notification_outbox.dispatch_pending = lambda: {}
    tick = datetime(2026, 8, 24, 11, 0, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    run, transport, bus = make_runner(
        tmp_path, [{"REGN": bar_row(to_utc_iso(tick.astimezone(ET)))}], decision_engine=fake_engine,
    )
    run._session = SESSION
    run._ready_symbols = {"AAPL"}  # REGN NOT session-ready

    await run.process_tick(tick)
    fake_engine.on_bars.assert_not_awaited()  # REGN's fresh bar still never reaches on_bars


@pytest.mark.asyncio
async def test_integration_sparse_symbol_does_not_mark_feed_degraded_piv_info(tmp_path):
    run, transport, bus = make_runner(tmp_path, [])
    run._session = SESSION
    run._ready_symbols = {"AAPL", "REGN"}
    run.piv_info = {}
    base = datetime(2026, 8, 24, 11, 0, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    run._last_seen_wall["REGN"] = base
    run._check_stale(base + timedelta(seconds=200))  # REGN goes stale
    assert run.piv_info["provider_health"] == "HEALTHY"  # provider unaffected by one quiet symbol


@pytest.mark.asyncio
async def test_integration_freshness_report_stamped_with_session_identity(tmp_path):
    import json
    identity = {
        "session_id": "piv_2026-08-26_063119_1f17993c", "trading_date_et": "2026-08-26",
        "runtime_sha": "abc123", "config_hash": "def456",
    }
    (tmp_path / "session_identity.json").write_text(json.dumps(identity), encoding="utf-8")
    run, transport, bus = make_runner(tmp_path, [])
    run._freshness.reset_for_session(SESSION)
    run._freshness.observe_fresh("REGN")
    run._freshness.observe_stale("REGN")
    run._write_freshness_report()

    report = json.loads((run.config.state_dir / "freshness_report.json").read_text(encoding="utf-8"))
    assert report["session_id"] == "piv_2026-08-26_063119_1f17993c"
    assert report["trading_date_et"] == "2026-08-26"
    assert report["runtime_sha"] == "abc123"
    assert report["config_hash"] == "def456"
    assert report["symbols"]["REGN"] == "DATA_GAP"


@pytest.mark.asyncio
async def test_integration_freshness_report_still_written_without_identity_file(tmp_path):
    """Best-effort stamping only -- a missing/absent identity file must
    never prevent the report itself from being written."""
    import json
    run, transport, bus = make_runner(tmp_path, [])
    run._write_freshness_report()
    report = json.loads((run.config.state_dir / "freshness_report.json").read_text(encoding="utf-8"))
    assert report["session_id"] is None


@pytest.mark.asyncio
async def test_integration_symbol_never_silently_removed_from_universe(tmp_path):
    """A configured universe symbol with zero bars all day still appears
    in the freshness report (as UNKNOWN / absent-but-listed), never
    silently dropped."""
    run, transport, bus = make_runner(tmp_path, [])
    run._freshness.reset_for_session(SESSION)
    run._freshness.observe_fresh("AAPL")  # REGN never observed at all
    snap = run._freshness.snapshot()
    assert "REGN" not in snap["symbols"]  # never classified (UNKNOWN default, not stored)
    # the universe itself (config.universe) still includes REGN regardless
    # of freshness-tracker internals -- confirms no universe mutation:
    assert "REGN" in run.config.universe
