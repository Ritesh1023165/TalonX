"""Task 72O Stage 1 -- automatic, idempotent EOD reconciliation lifecycle,
linked to the original live trading session identity.

All broker interaction here is via FakeBroker (no AlpacaPaperClient, no
requests, no real HTTP) -- this suite proves the lifecycle's own
state-machine/idempotency/event-ordering contract in isolation. A
FakeBroker method call is itself the proof of "no real broker/API
invocation": cancel_all_orders/close_all_positions/open_orders/positions
are plain Python method calls against an in-memory fake, never a network
request.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.eod_lifecycle import STATUS_FAILED, STATUS_INCONCLUSIVE, STATUS_PASSED, run_eod_lifecycle
from talonx_piv.lifecycle import PaperLifecycle


class FakeBroker:
    def __init__(self, open_orders=None, positions=None, cancel_raises=None, close_raises=None, positions_raises=None):
        self._open_orders = list(open_orders or [])
        self._positions = list(positions or [])
        self._cancel_raises = cancel_raises
        self._close_raises = close_raises
        self._positions_raises = positions_raises
        self.cancel_calls = 0
        self.close_calls = 0
        self.identity = object()  # PaperLifecycle never checks this directly

    def _require_verified(self) -> None:
        pass  # already "verified" -- this fake has no real identity handshake to perform

    def cancel_all_orders(self):
        self.cancel_calls += 1
        if self._cancel_raises:
            raise self._cancel_raises
        cancelled = list(self._open_orders)
        self._open_orders = []
        return cancelled

    def close_all_positions(self):
        self.close_calls += 1
        if self._close_raises:
            raise self._close_raises
        closed = list(self._positions)
        self._positions = []
        return closed

    def open_orders(self):
        return list(self._open_orders)

    def positions(self):
        if self._positions_raises:
            raise self._positions_raises
        return list(self._positions)


def make_lifecycle(tmp_path, broker, internal_positions_open=None):
    cfg = PivConfig(key_id="k", secret_key="s", paper_trading=True, real_capital=False,
                     broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path)
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "lifecycle_state.json", broker, bus)
    life.start_session(True, True)
    for symbol in (internal_positions_open or []):
        life.state.positions[f"pos_{symbol}"] = {"symbol": symbol, "status": "OPEN"}
    return cfg, bus, life


def events_text(bus) -> str:
    return bus.path.read_text(encoding="utf-8") if bus.path.exists() else ""


def event_sequence(bus) -> list[str]:
    return [json.loads(line)["event"] for line in events_text(bus).splitlines() if line.strip()]


COMMON = dict(live_session_id="piv_2026-08-26_063119_1f17993c", trading_date_et="2026-08-26",
              runtime_sha="abc123", config_hash="def456")


# ---------------------------------------------------------------------
# Core outcomes
# ---------------------------------------------------------------------

def test_zero_orders_zero_positions_passes(tmp_path):
    broker = FakeBroker()
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    assert result["status"] == STATUS_PASSED
    assert result["exit_code"] == 0
    assert broker.cancel_calls == 1 and broker.close_calls == 1
    seq = [e for e in event_sequence(bus) if e.startswith("EOD_") or e == "SESSION_COMPLETED"]
    assert seq == [
        "EOD_STARTED", "EOD_CANCEL_REQUESTED", "EOD_FLATTEN_REQUESTED",
        "EOD_RECONCILIATION_STARTED", "EOD_RECONCILIATION_PASSED", "SESSION_COMPLETED",
    ]


def test_existing_paper_orders_are_cancelled(tmp_path):
    broker = FakeBroker(open_orders=[{"id": "o1", "symbol": "AAPL"}])
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    assert result["status"] == STATUS_PASSED
    assert broker.cancel_calls == 1


def test_existing_paper_positions_are_closed(tmp_path):
    broker = FakeBroker(positions=[{"symbol": "AAPL", "qty": "1", "side": "long"}])
    cfg, bus, life = make_lifecycle(tmp_path, broker, internal_positions_open=["AAPL"])
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    assert result["status"] == STATUS_PASSED
    assert broker.close_calls == 1
    assert life.state.positions["pos_AAPL"]["status"] == "CLOSED"


def test_cancellation_failure_is_inconclusive_not_passed(tmp_path):
    broker = FakeBroker(cancel_raises=RuntimeError("cancel boom"))
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    assert result["status"] != STATUS_PASSED
    assert "SESSION_COMPLETED" not in event_sequence(bus)


def test_close_failure_is_inconclusive_not_passed(tmp_path):
    broker = FakeBroker(close_raises=RuntimeError("close boom"))
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    assert result["status"] != STATUS_PASSED
    assert "SESSION_COMPLETED" not in event_sequence(bus)


def test_reconciliation_mismatch_is_failed_not_passed(tmp_path):
    # Broker still reports an open position even after close_all_positions
    # "succeeded" (delayed broker-side convergence / genuine mismatch).
    broker = FakeBroker(positions=[{"symbol": "AAPL", "qty": "1", "side": "long"}])
    broker.close_all_positions = lambda: []  # "succeeds" but broker state doesn't actually clear yet
    cfg, bus, life = make_lifecycle(tmp_path, broker, internal_positions_open=["AAPL"])
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    assert result["status"] == STATUS_FAILED
    assert result["exit_code"] == 2
    assert "SESSION_COMPLETED" not in event_sequence(bus)
    assert "EOD_RECONCILIATION_FAILED" in event_sequence(bus)


def test_delayed_broker_convergence_then_idempotent_retry_passes(tmp_path):
    """First call: broker hasn't converged yet -> FAILED. A later retry
    (broker now converged) re-reads reconciliation and passes -- without
    re-issuing cancel/close (idempotent)."""
    broker = FakeBroker(positions=[{"symbol": "AAPL", "qty": "1", "side": "long"}])
    cfg, bus, life = make_lifecycle(tmp_path, broker, internal_positions_open=["AAPL"])
    def fake_close():
        broker.close_calls += 1
        return []  # "succeeds" but broker._positions deliberately left unchanged (not yet converged)
    broker.close_all_positions = fake_close
    first = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    assert first["status"] == STATUS_FAILED

    broker._positions = []  # broker converges before the retry
    second = run_eod_lifecycle(cfg, bus, life, trigger_reason="MANUAL_CLI_INVOCATION", **COMMON)
    assert second["status"] == STATUS_PASSED
    assert broker.cancel_calls == 1 and broker.close_calls == 1  # NOT re-issued on the retry


def test_reconciliation_broker_read_failure_is_inconclusive(tmp_path):
    broker = FakeBroker(positions_raises=RuntimeError("positions endpoint down"))
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    assert result["status"] == STATUS_INCONCLUSIVE
    assert "SESSION_COMPLETED" not in event_sequence(bus)


# ---------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------

def test_idempotent_retry_does_not_duplicate_close_requests(tmp_path):
    broker = FakeBroker()
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    run_eod_lifecycle(cfg, bus, life, trigger_reason="MANUAL_CLI_INVOCATION", **COMMON)
    assert broker.cancel_calls == 1
    assert broker.close_calls == 1


def test_completed_reconciliation_can_be_safely_reread(tmp_path):
    broker = FakeBroker()
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    first = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    second = run_eod_lifecycle(cfg, bus, life, trigger_reason="MANUAL_CLI_INVOCATION", **COMMON)
    assert first["status"] == second["status"] == STATUS_PASSED


def test_process_interruption_during_eod_then_resume(tmp_path):
    """Simulates: cancel/close already persisted (process died before
    reconciliation completed) -- a fresh call must not re-cancel/close,
    only complete reconciliation."""
    broker = FakeBroker()
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    state_path = cfg.state_dir / "eod_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "session_id": COMMON["live_session_id"], "trading_date_et": COMMON["trading_date_et"],
        "cancel_close_requested": True, "status": "PENDING",
    }), encoding="utf-8")
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="MANUAL_CLI_INVOCATION", **COMMON)
    assert result["status"] == STATUS_PASSED
    assert broker.cancel_calls == 0 and broker.close_calls == 0  # never re-issued


# ---------------------------------------------------------------------
# Session identity / linkage
# ---------------------------------------------------------------------

def test_original_live_session_linkage_and_separate_reconciliation_run_id(tmp_path):
    broker = FakeBroker()
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="MANUAL_CLI_INVOCATION", **COMMON)
    assert result["session_id"] == COMMON["live_session_id"]
    assert result["reconciliation_run_id"] != COMMON["live_session_id"]
    for line in events_text(bus).splitlines():
        d = json.loads(line)
        if d["event"].startswith("EOD_") or d["event"] == "SESSION_COMPLETED":
            assert d["session_id"] == COMMON["live_session_id"]  # every EOD_* event stamped with the LIVE session


def test_two_reconciliation_runs_get_different_run_ids(tmp_path):
    broker = FakeBroker()
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    r1 = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    r2 = run_eod_lifecycle(cfg, bus, life, trigger_reason="MANUAL_CLI_INVOCATION", **COMMON)
    assert r1["reconciliation_run_id"] != r2["reconciliation_run_id"]
    assert r1["session_id"] == r2["session_id"] == COMMON["live_session_id"]


def test_cross_date_state_rejected(tmp_path):
    """A PASSED terminal state from a DIFFERENT ET trading date must never
    be treated as if it already applies to today -- today's cancel/close
    must still be issued."""
    broker = FakeBroker()
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    state_path = cfg.state_dir / "eod_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "session_id": COMMON["live_session_id"], "trading_date_et": "2026-08-25",  # YESTERDAY
        "cancel_close_requested": True, "status": "PASSED",
    }), encoding="utf-8")
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    assert result["status"] == STATUS_PASSED
    assert broker.cancel_calls == 1 and broker.close_calls == 1  # today's own request WAS issued


def test_different_session_id_same_date_does_not_reuse_prior_cancel_close(tmp_path):
    broker = FakeBroker()
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    other = dict(COMMON, live_session_id="piv_2026-08-26_041902_1f17993c")  # a DIFFERENT (earlier, failed) session
    run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **other)
    assert broker.cancel_calls == 1
    run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    assert broker.cancel_calls == 2  # a genuinely different live session -- its own cancel/close is issued


# ---------------------------------------------------------------------
# SESSION_COMPLETED gating
# ---------------------------------------------------------------------

def test_session_completed_never_emitted_on_failed(tmp_path):
    # Task 81 §6 (E1): assert the actual state/outcome, not a `pass` stub.
    broker = FakeBroker(positions=[{"symbol": "AAPL", "qty": "1", "side": "long"}])
    broker.close_all_positions = lambda: []  # "accepted" but broker stays non-flat
    cfg, bus, life = make_lifecycle(tmp_path, broker, internal_positions_open=["AAPL"])
    result = run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    assert result["status"] == STATUS_FAILED
    seq = event_sequence(bus)
    assert "EOD_RECONCILIATION_FAILED" in seq
    assert "SESSION_COMPLETED" not in seq
    assert "EOD_RECONCILIATION_PASSED" not in seq
    # C7: an accepted-but-unconfirmed close does not mark the position closed.
    assert life.state.positions["pos_AAPL"]["status"] == "OPEN"


def test_session_completed_never_emitted_on_inconclusive(tmp_path):
    broker = FakeBroker(positions_raises=RuntimeError("boom"))
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)
    assert "SESSION_COMPLETED" not in event_sequence(bus)


# ---------------------------------------------------------------------
# No real broker/API invocation
# ---------------------------------------------------------------------

def test_no_network_transport_ever_constructed(tmp_path):
    """FakeBroker exposes no `.get`/`.post`/`.delete` HTTP surface at all --
    proves reconciliation and cancel/close are pure in-memory calls here."""
    broker = FakeBroker()
    assert not hasattr(broker, "get") and not hasattr(broker, "post") and not hasattr(broker, "delete")
    cfg, bus, life = make_lifecycle(tmp_path, broker)
    run_eod_lifecycle(cfg, bus, life, trigger_reason="SCHEDULED_COMPLETION", **COMMON)


# =======================================================================
# session_runner.py integration -- guaranteed supervisor path
# =======================================================================

from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from talonx_piv.broker import AlpacaPaperClient
from talonx_piv.session_runner import SessionRunner

ET = ZoneInfo("America/New_York")


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class NoOpTransport:
    """Handles account verification + returns empty for everything else --
    orders/positions/bars all resolve to empty/success, no real network."""

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "id", "account_number": "PA1", "status": "ACTIVE"}, 200)
        if url.endswith("/v2/orders"):
            return Response([])
        if url.endswith("/v2/positions"):
            return Response([])
        if "bars/latest" in url:
            return Response({"bars": {}})
        return Response({}, 404)

    def post(self, url, **kwargs):
        raise AssertionError("session_runner EOD path must never submit an order")

    def delete(self, url, **kwargs):
        return Response([])  # cancel/close -- always empty, never a real mutation target


def make_runner(tmp_path, universe=("AAPL",), **overrides):
    values = dict(key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
                  broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
                  universe=universe, stale_seconds=90)
    values.update(overrides)
    cfg = PivConfig(**values)
    transport = NoOpTransport()
    broker = AlpacaPaperClient(cfg, transport)
    broker.verify_paper_identity()
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    life = PaperLifecycle(tmp_path / "lifecycle_state.json", broker, bus)
    life.start_session(True, True)
    (tmp_path / "session_identity.json").write_text(json.dumps({
        "session_id": "piv_2026-08-24_093000_abcdef01", "trading_date_et": "2026-08-24",
        "runtime_sha": "shatest", "config_hash": "hashtest",
    }), encoding="utf-8")
    return SessionRunner(cfg, bus, life, transport), bus


@pytest.mark.asyncio
async def test_scheduled_completion_triggers_eod_lifecycle(tmp_path):
    runner, bus = make_runner(tmp_path)
    start = datetime(2026, 8, 24, 15, 50, tzinfo=ET).astimezone(ZoneInfo("UTC"))

    async def fast_sleep(_seconds):
        pass

    ticks = [start]

    def clock():
        return ticks[0]

    await runner.run(clock=clock, sleep=fast_sleep)
    assert "EOD_STARTED" in event_sequence(bus)
    assert "EOD_RECONCILIATION_PASSED" in event_sequence(bus) or "EOD_RECONCILIATION_FAILED" in event_sequence(bus)
    for line in events_text(bus).splitlines():
        d = json.loads(line)
        if d["event"].startswith("EOD_") or d["event"] == "SESSION_COMPLETED":
            assert d["session_id"] == "piv_2026-08-24_093000_abcdef01"  # ORIGINAL live session, not a fresh one


@pytest.mark.asyncio
async def test_controlled_shutdown_kill_switch_triggers_eod_lifecycle(tmp_path):
    runner, bus = make_runner(tmp_path)
    runner.lifecycle.state.kill_switch = True
    runner.lifecycle._save()

    async def fast_sleep(_seconds):
        pass

    tick = datetime(2026, 8, 24, 11, 0, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    await runner.run(clock=lambda: tick, sleep=fast_sleep)
    assert "EOD_STARTED" in event_sequence(bus)
    assert "KILL_SWITCH" in event_sequence(bus)


@pytest.mark.asyncio
async def test_unhandled_exception_still_triggers_eod_then_reraises(tmp_path):
    runner, bus = make_runner(tmp_path)

    async def boom(_now):
        raise ValueError("simulated catastrophic bug outside any per-tick guard")

    # Bypass the per-tick try/except by making process_premarket_tick's
    # OWN call site raise from somewhere the loop doesn't already guard --
    # simplest reliable trigger: make lifecycle.reload() itself raise.
    def reload_boom():
        raise ValueError("simulated catastrophic bug outside any per-tick guard")

    runner.lifecycle.reload = reload_boom

    async def fast_sleep(_seconds):
        pass

    tick = datetime(2026, 8, 24, 11, 0, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    with pytest.raises(ValueError):
        await runner.run(clock=lambda: tick, sleep=fast_sleep)
    assert "EOD_STARTED" in event_sequence(bus)  # cleanup still attempted despite the re-raised exception


@pytest.mark.asyncio
async def test_no_session_identity_file_skips_eod_without_guessing(tmp_path):
    runner, bus = make_runner(tmp_path)
    (tmp_path / "session_identity.json").unlink()

    async def fast_sleep(_seconds):
        pass

    tick = datetime(2026, 8, 24, 15, 50, tzinfo=ET).astimezone(ZoneInfo("UTC"))
    await runner.run(clock=lambda: tick, sleep=fast_sleep)
    assert "EOD_REQUIRES_KNOWN_LIVE_SESSION_IDENTITY" in events_text(bus)
    assert "SESSION_COMPLETED" not in event_sequence(bus)
