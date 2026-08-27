"""Task 71S -- PIV stabilization Phase 2: symbol-level and provider-level
data-freshness semantics, plus a read-only historical gap classifier.

Covers talonx_piv/freshness.py's state machine, talonx_piv/gap_forensics.py's
evidence-based classification, and their wiring into session_runner.py --
all without touching talonx_quant/{strategy,indicators,consumer,config}.py.
Every fake transport below exposes only `.get()`; any `.post()`/`.delete()`
call is a test failure (no order/broker-trading endpoint is ever reachable
from this task's code paths).
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
    DEGRADED,
    FRESH,
    HEALTHY,
    PROVIDER_UNAVAILABLE,
    RECOVERED,
    STALE,
    UNKNOWN,
    FreshnessTracker,
)
from talonx_piv.gap_forensics import (
    NO_IEX_BAR_OBSERVED,
    HISTORICAL_DATA_DISAGREEMENT,
    PROVIDER_WIDE_INTERRUPTION,
    SUBSCRIPTION_OR_PIPELINE_GAP,
    UNKNOWN as GAP_UNKNOWN,
    classify_missing_minute,
    classify_stale_event,
    classify_stale_events_batch,
    fetch_historical_minute_set,
)
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.session_runner import SessionRunner

ET = ZoneInfo("America/New_York")
SESSION = date(2026, 8, 24)
UNIVERSE = ("AAPL", "MSFT")


# =======================================================================
# talonx_piv/freshness.py -- pure state-machine unit tests
# =======================================================================

def test_fresh_bars_remain_fresh():
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    state, recovered = t.observe_fresh("AAPL")
    assert state == FRESH and recovered is False
    assert t.state_of("AAPL") == FRESH


def test_symbol_exceeds_threshold_becomes_stale():
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    t.observe_fresh("AAPL")
    state, newly_stale = t.observe_stale("AAPL")
    assert state == STALE and newly_stale is True
    assert t.state_of("AAPL") == STALE


def test_repeated_stale_checks_are_rate_limited_without_losing_the_state():
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    t.observe_fresh("AAPL")
    _, first = t.observe_stale("AAPL")
    _, second = t.observe_stale("AAPL")
    _, third = t.observe_stale("AAPL")
    assert (first, second, third) == (True, False, False)  # newly_stale only once
    assert t.state_of("AAPL") == STALE  # state itself is never lost/downgraded


def test_fresh_data_after_staleness_reports_recovered_then_settles_fresh():
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    t.observe_fresh("AAPL")
    t.observe_stale("AAPL")
    state, recovered = t.observe_fresh("AAPL")
    assert state == RECOVERED and recovered is True
    assert t.state_of("AAPL") == FRESH  # stored state settles immediately -- RECOVERED is a one-tick pulse


def test_never_observed_symbol_is_unknown():
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    assert t.state_of("NEVERSEEN") == UNKNOWN


def test_data_gap_at_session_end_for_unresolved_stale_symbol():
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    t.observe_fresh("AAPL")
    t.observe_stale("AAPL")
    t.observe_fresh("MSFT")  # MSFT stays healthy -- must not be swept into DATA_GAP
    gapped = t.mark_data_gap_at_session_end()
    assert gapped == ["AAPL"]
    assert t.state_of("AAPL") == DATA_GAP
    assert t.state_of("MSFT") == FRESH


def test_one_stale_symbol_does_not_mark_provider_unavailable():
    """Core Task 71S finding: many symbols independently going STALE on an
    ordinary day is not provider evidence -- only a directly observed
    fetch failure is."""
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    for i in range(20):
        t.observe_fresh(f"SYM{i}")
        t.observe_stale(f"SYM{i}")
    assert t.provider_state == HEALTHY


def test_provider_wide_interruption_marks_provider_health_correctly():
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    state1, transitioned1 = t.record_provider_fetch_result(False)
    assert state1 == DEGRADED and transitioned1 is True
    state2, transitioned2 = t.record_provider_fetch_result(False)
    assert state2 == PROVIDER_UNAVAILABLE and transitioned2 is True
    state3, transitioned3 = t.record_provider_fetch_result(True)
    assert state3 == HEALTHY and transitioned3 is True


def test_provider_single_isolated_failure_is_only_degraded_not_unavailable():
    t = FreshnessTracker()
    t.reset_for_session(SESSION)
    state, _ = t.record_provider_fetch_result(False)
    assert state == DEGRADED
    state, _ = t.record_provider_fetch_result(True)
    assert state == HEALTHY  # a single recovered fetch clears it -- never escalates from one failure alone


def test_stale_persisted_state_from_another_et_trading_date_is_not_reused():
    t = FreshnessTracker()
    t.reset_for_session(date(2026, 8, 25))
    t.observe_fresh("AAPL")
    t.observe_stale("AAPL")
    t.record_provider_fetch_result(False)
    t.record_provider_fetch_result(False)
    assert t.state_of("AAPL") == STALE
    assert t.provider_state == PROVIDER_UNAVAILABLE

    reset_happened = t.reset_for_session(date(2026, 8, 26))
    assert reset_happened is True
    assert t.state_of("AAPL") == UNKNOWN  # yesterday's STALE is gone, not carried forward
    assert t.provider_state == HEALTHY

    # idempotent: calling again for the SAME date is a no-op, not a re-reset
    t.observe_fresh("AAPL")
    reset_again = t.reset_for_session(date(2026, 8, 26))
    assert reset_again is False
    assert t.state_of("AAPL") == FRESH  # not wiped by the idempotent no-op


def test_freshness_tracker_never_touches_ohlcv_values():
    """Pure state/classification layer -- no bar data of any kind is ever
    accepted or returned by this module's API."""
    import inspect
    sig = inspect.signature(FreshnessTracker.observe_fresh)
    assert set(sig.parameters) == {"self", "symbol"}  # no open/high/low/close/volume parameter exists


# =======================================================================
# talonx_piv/gap_forensics.py -- read-only historical classification
# =======================================================================

class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


class GetOnlyTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw.get("params")))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, *a, **k):
        raise AssertionError("gap_forensics must never submit an order")

    def delete(self, *a, **k):
        raise AssertionError("gap_forensics must never cancel/close a position")


def _hist_bars(*et_hhmm_labels, day="2026-08-26"):
    return {"bars": [
        {"t": f"{day}T{(datetime.strptime(label, '%H:%M') + timedelta(hours=4)).strftime('%H:%M')}:00Z",
         "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}
        for label in et_hhmm_labels
    ]}


def test_confirmed_no_trade_distinct_from_historical_disagreement():
    # neither of the two most-recent minutes has a historical bar -> confirmed
    hist = {"09:30", "09:37"}
    classification, _ = classify_stale_event("2026-08-26T13:33:00+00:00", hist)  # 09:33 ET
    assert classification == NO_IEX_BAR_OBSERVED

    # 09:32 ET (one minute before) DOES have a bar -> the live flag disagreed with history
    hist2 = {"09:30", "09:32"}
    classification2, evidence = classify_stale_event("2026-08-26T13:33:00+00:00", hist2)
    assert classification2 == HISTORICAL_DATA_DISAGREEMENT
    assert "09:32" in evidence


def test_missing_minute_classification_confirmed_vs_disagreement():
    assert classify_missing_minute("09:30", {"09:31", "09:32"}) == NO_IEX_BAR_OBSERVED
    assert classify_missing_minute("09:30", {"09:30", "09:31"}) == HISTORICAL_DATA_DISAGREEMENT


def test_unknown_missing_minute_remains_fail_closed_not_guessed():
    """No historical evidence available (fetch failed) -> UNKNOWN, never
    silently assumed to be a confirmed no-trade minute."""
    assert classify_missing_minute("09:30", None) == GAP_UNKNOWN
    classification, evidence = classify_stale_event("2026-08-26T13:33:00+00:00", None)
    assert classification == GAP_UNKNOWN
    assert "unavailable" in evidence


def test_fetch_historical_minute_set_success():
    transport = GetOnlyTransport([Resp(_hist_bars("09:30", "09:31"))])
    result = fetch_historical_minute_set(transport, "https://data.alpaca.markets", "k", "s", "AAPL", "start", "end")
    assert result == {"09:30", "09:31"}


def test_fetch_historical_minute_set_non_200_is_none_not_empty():
    transport = GetOnlyTransport([Resp({}, status=500)])
    result = fetch_historical_minute_set(transport, "https://data.alpaca.markets", "k", "s", "AAPL", "start", "end")
    assert result is None  # None (unavailable) is distinct from an empty-but-successful set()


def test_fetch_historical_minute_set_exception_is_none():
    transport = GetOnlyTransport([TimeoutError("boom")])
    result = fetch_historical_minute_set(transport, "https://data.alpaca.markets", "k", "s", "AAPL", "start", "end")
    assert result is None


def test_provider_wide_interruption_requires_many_symbols_same_minute():
    events = [{"symbol": f"SYM{i}", "timestamp": "2026-08-26T13:33:00+00:00"} for i in range(6)]
    hist_by_symbol = {f"SYM{i}": {"09:32"} for i in range(6)}  # all disagree at the SAME minute
    results = classify_stale_events_batch(events, hist_by_symbol, provider_wide_threshold=5)
    assert all(r.classification == PROVIDER_WIDE_INTERRUPTION for r in results)


def test_single_symbol_disagreement_is_pipeline_gap_not_provider_wide():
    events = [{"symbol": "AAPL", "timestamp": "2026-08-26T13:33:00+00:00"}]
    hist_by_symbol = {"AAPL": {"09:32"}}
    results = classify_stale_events_batch(events, hist_by_symbol, provider_wide_threshold=5)
    assert results[0].classification == SUBSCRIPTION_OR_PIPELINE_GAP


def test_real_2026_08_26_evidence_all_72_confirmed_no_trade():
    """Regression-locks this task's own forensic finding: replaying the
    exact classification methodology against the two most-recent minutes
    of a genuinely sparse historical set reproduces NO_IEX_BAR_OBSERVED,
    matching every one of the 72 real events analyzed for
    results/task71s_data_freshness_stabilization/stale_event_timeline.csv."""
    # REGN's own historical minute set around its first 2026-08-26 stale
    # event (09:32:10 ET) -- REGN's actual first print that day was 09:37.
    hist = {"09:37", "09:38"}
    classification, _ = classify_stale_event("2026-08-26T13:32:10.971281+00:00", hist)
    assert classification == NO_IEX_BAR_OBSERVED


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
            if isinstance(item, tuple):  # (body, status)
                return Response(*item)
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
async def test_integration_stale_then_recovered_emits_data_recovered(tmp_path):
    run, transport, bus = make_runner(tmp_path, [])
    run._session = SESSION
    run._ready_symbols = {"AAPL"}
    base = datetime(2026, 8, 24, 10, 1, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    run._last_seen_wall["AAPL"] = base
    run._check_stale(base + timedelta(seconds=200))  # goes STALE
    assert run._freshness.state_of("AAPL") == STALE

    # A fresh bar arrives via process_tick -> observe_fresh -> DATA_RECOVERED
    fresh_tick = base + timedelta(seconds=300)
    run.transport.batches.append({"AAPL": bar_row(to_utc_iso(fresh_tick.astimezone(ET)))})
    await run.process_tick(fresh_tick)

    events_text = bus.path.read_text(encoding="utf-8")
    assert '"event": "DATA_RECOVERED"' in events_text
    assert '"symbol": "AAPL"' in events_text
    assert run._freshness.state_of("AAPL") == FRESH


@pytest.mark.asyncio
async def test_integration_provider_fetch_failure_marks_provider_degraded_not_symbol_stale(tmp_path):
    run, transport, bus = make_runner(tmp_path, [TimeoutError("simulated network failure")])
    run._session = SESSION
    run._ready_symbols = {"AAPL"}
    tick = datetime(2026, 8, 24, 10, 1, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    await run.process_tick(tick)  # must not raise -- fetch_bars_latest fails closed to {}
    assert run._freshness.provider_state == "DEGRADED"
    events_text = bus.path.read_text(encoding="utf-8")
    assert '"event": "BROKER_ERROR"' in events_text
    assert "MARKET_DATA_FETCH_FAILED" in events_text


@pytest.mark.asyncio
async def test_integration_provider_recovers_after_healthy_fetch(tmp_path):
    tick1 = datetime(2026, 8, 24, 10, 1, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    tick2 = tick1 + timedelta(minutes=1)
    run, transport, bus = make_runner(tmp_path, [
        TimeoutError("simulated"),
        {"AAPL": bar_row(to_utc_iso(tick2.astimezone(ET)))},
    ])
    run._session = SESSION
    run._ready_symbols = {"AAPL"}
    await run.process_tick(tick1)
    assert run._freshness.provider_state == "DEGRADED"
    await run.process_tick(tick2)
    assert run._freshness.provider_state == "HEALTHY"
    events_text = bus.path.read_text(encoding="utf-8")
    assert '"event": "PROVIDER_RECOVERED"' in events_text


@pytest.mark.asyncio
async def test_integration_no_signal_from_stale_symbol(tmp_path):
    """No candidate/signal reaches on_bars for a symbol currently STALE,
    even if it were (hypothetically) present in decision_eligible."""
    fake_engine = AsyncMock()
    fake_engine.warmup_ready_symbols = {"AAPL"}
    fake_engine.funnel_summary = lambda: {
        "evaluation_cycles": 0, "symbols_evaluated_total": 0, "candidates": 0, "published": 0,
        "rejected": 0, "pending": 0, "errored": 0, "unaccounted_candidates": 0, "rejected_breakdown": {},
    }
    # Task 77I: dispatch_pending is a plain SYNC method on the real
    # NotificationOutbox -- stubbed as a plain callable to avoid an
    # unawaited-coroutine warning from AsyncMock's default auto-async attrs.
    fake_engine.notification_outbox.dispatch_pending = lambda: {}
    run, transport, bus = make_runner(tmp_path, [], decision_engine=fake_engine)
    run._session = SESSION
    run._ready_symbols = {"AAPL"}
    run._freshness.reset_for_session(SESSION)
    run._freshness.observe_fresh("AAPL")
    run._freshness.observe_stale("AAPL")  # AAPL is explicitly STALE right now

    tick = datetime(2026, 8, 24, 10, 1, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    await run.process_tick(tick)  # no new bar this tick (empty batch) -- AAPL stays out either way
    fake_engine.on_bars.assert_not_awaited()


@pytest.mark.asyncio
async def test_integration_recovery_permits_evaluation_once_restored(tmp_path):
    fake_engine = AsyncMock()
    fake_engine.warmup_ready_symbols = {"AAPL"}
    fake_engine.funnel_summary = lambda: {
        "evaluation_cycles": 0, "symbols_evaluated_total": 0, "candidates": 0, "published": 0,
        "rejected": 0, "pending": 0, "errored": 0, "unaccounted_candidates": 0, "rejected_breakdown": {},
    }
    # Task 77I: dispatch_pending is a plain SYNC method on the real
    # NotificationOutbox -- stubbed as a plain callable to avoid an
    # unawaited-coroutine warning from AsyncMock's default auto-async attrs.
    fake_engine.notification_outbox.dispatch_pending = lambda: {}
    tick = datetime(2026, 8, 24, 10, 1, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    run, transport, bus = make_runner(
        tmp_path, [{"AAPL": bar_row(to_utc_iso(tick.astimezone(ET)))}], decision_engine=fake_engine,
    )
    run._session = SESSION
    run._ready_symbols = {"AAPL"}
    run._freshness.reset_for_session(SESSION)
    run._freshness.observe_fresh("AAPL")
    run._freshness.observe_stale("AAPL")  # AAPL STARTS stale

    await run.process_tick(tick)  # a genuinely fresh bar arrives -> recovers -> now eligible
    fake_engine.on_bars.assert_awaited()
    called_bars = fake_engine.on_bars.await_args.args[0]
    assert "AAPL" in called_bars


@pytest.mark.asyncio
async def test_integration_duplicate_or_out_of_order_bar_does_not_trigger_recovery(tmp_path):
    """A bar with the SAME or an OLDER timestamp than the last-seen one is
    (already, pre-Task-71S) treated as not-new -- must not spuriously call
    observe_fresh / emit DATA_RECOVERED."""
    same_ts = datetime(2026, 8, 24, 10, 1, tzinfo=ET)
    run, transport, bus = make_runner(tmp_path, [{"AAPL": bar_row(to_utc_iso(same_ts))}])
    run._session = SESSION
    run._ready_symbols = {"AAPL"}
    run._last_bar_ts["AAPL"] = same_ts.astimezone(ZoneInfo("UTC"))  # already seen this exact bar
    run._freshness.reset_for_session(SESSION)
    run._freshness.observe_fresh("AAPL")
    run._freshness.observe_stale("AAPL")

    await run.process_tick(same_ts.astimezone(ZoneInfo("UTC")) + timedelta(seconds=1))
    assert run._freshness.state_of("AAPL") == STALE  # unchanged -- the duplicate bar did not recover it
    assert '"event": "DATA_RECOVERED"' not in bus.path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_integration_stale_persisted_state_from_another_date_not_reused(tmp_path):
    run, transport, bus = make_runner(tmp_path, [])
    run._session = date(2026, 8, 25)
    run._freshness.reset_for_session(date(2026, 8, 25))
    run._freshness.observe_fresh("AAPL")
    run._freshness.observe_stale("AAPL")
    assert run._freshness.state_of("AAPL") == STALE

    # A tick on a NEW ET trading date must reset freshness state too (same
    # convention as _last_seen_wall/_stale_flagged already being cleared).
    new_day_tick = datetime(2026, 8, 26, 9, 30, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    await run.process_tick(new_day_tick)
    assert run._freshness.state_of("AAPL") == "UNKNOWN"


@pytest.mark.asyncio
async def test_integration_session_end_writes_freshness_report_and_data_gap(tmp_path):
    run, transport, bus = make_runner(tmp_path, [])
    run._freshness.reset_for_session(SESSION)
    run._freshness.observe_fresh("AAPL")
    run._freshness.observe_stale("AAPL")
    run._write_freshness_report()
    assert run._freshness.state_of("AAPL") == DATA_GAP
    events_text = bus.path.read_text(encoding="utf-8")
    assert '"status": "DATA_GAP"' in events_text
    report_path = run.config.state_dir / "freshness_report.json"
    assert report_path.exists()
    import json
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["symbols"]["AAPL"] == "DATA_GAP"


@pytest.mark.asyncio
async def test_integration_premarket_tick_does_not_touch_freshness_or_orders(tmp_path):
    """Premarket radar is a wholly separate, observational-only path (see
    premarket_radar.py) -- it must never call fetch_bars_latest/freshness
    or reach an order endpoint."""
    run, transport, bus = make_runner(tmp_path, [])
    tick = datetime(2026, 8, 24, 6, 0, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    await run.process_premarket_tick(tick)
    assert run._freshness.state_of("AAPL") == "UNKNOWN"
