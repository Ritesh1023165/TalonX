"""Task 78I Stage 2 -- supervisor.py unit tests. TEST_FIXTURE_ONLY -- NOT
ALPHA EVIDENCE throughout."""
from __future__ import annotations

import pytest

from talonx_piv.broker import AlpacaPaperClient
from talonx_piv.config import PAPER_ENDPOINT, PivConfig
from talonx_piv.events import EventBus
from talonx_piv.execution_settings import PaperEntrySettings
from talonx_piv.lifecycle import PaperLifecycle
from talonx_piv.supervisor import (
    ComponentHealthRegistry, ComponentStatus, StartupReport, StartupStepResult,
    TerminalSupervisorFailure, run_startup_sequence, run_with_bounded_restart,
)


class Response:
    def __init__(self, body, status=200): self.body, self.status_code = body, status
    def json(self): return self.body
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f"HTTP {self.status_code}")


class FakeTransport:
    def __init__(self):
        self.orders = []

    def get(self, url, **kwargs):
        if url.endswith("/v2/account"):
            return Response({"id": "acct-sup", "account_number": "PA123456", "status": "ACTIVE"})
        if url.endswith("/v2/orders"):
            return Response([])
        if url.endswith("/v2/positions"):
            return Response([])
        return Response({}, 404)

    def post(self, url, **kwargs):
        return Response({"id": "o1", "status": "new"})

    def delete(self, url, **kwargs):
        return Response([])


def _stack(tmp_path, **overrides):
    values = dict(
        key_id="key", secret_key="secret", paper_trading=True, real_capital=False,
        broker_endpoint=PAPER_ENDPOINT, approved_sha="abc", state_dir=tmp_path,
    )
    values.update(overrides)
    cfg = PivConfig(**values)
    transport = FakeTransport()
    broker = AlpacaPaperClient(cfg, transport)
    bus = EventBus(tmp_path / "events.jsonl", feed_mode=cfg.feed_mode)
    lifecycle = PaperLifecycle(tmp_path / "state.json", broker, bus, PaperEntrySettings.for_test("AAPL"))
    return cfg, broker, lifecycle, bus


# ---------------------------------------------------------------------------
# ComponentHealthRegistry
# ---------------------------------------------------------------------------

def test_overall_healthy_when_all_components_healthy():
    registry = ComponentHealthRegistry()
    registry.register("a", required=True)
    registry.register("b", required=False)
    registry.heartbeat("a", ComponentStatus.HEALTHY)
    registry.heartbeat("b", ComponentStatus.HEALTHY)
    assert registry.overall() == "HEALTHY"


def test_optional_component_failure_degrades_not_fails():
    registry = ComponentHealthRegistry()
    registry.register("required_a", required=True)
    registry.register("optional_b", required=False)
    registry.heartbeat("required_a", ComponentStatus.HEALTHY)
    registry.heartbeat("optional_b", ComponentStatus.FAILED, "gemini timeout")
    assert registry.overall() == "DEGRADED"  # not FAILED -- optional-only failure


def test_required_component_failure_is_overall_failed():
    registry = ComponentHealthRegistry()
    registry.register("required_a", required=True)
    registry.heartbeat("required_a", ComponentStatus.FAILED, "broker unreachable")
    assert registry.overall() == "FAILED"


def test_not_started_component_reports_starting():
    registry = ComponentHealthRegistry()
    registry.register("a", required=True)
    assert registry.overall() == "STARTING"


# ---------------------------------------------------------------------------
# Startup sequence -- order and fail-stop
# ---------------------------------------------------------------------------

def test_startup_sequence_passes_with_valid_paper_config(tmp_path):
    cfg, broker, lifecycle, bus = _stack(tmp_path)
    report = run_startup_sequence(cfg, broker, lifecycle, bus, skip_ownership=True, skip_duplicate_process_check=True)
    assert report.passed
    step_names = [s.step for s in report.steps]
    assert step_names == [
        "no_duplicate_process", "verify_configuration", "verify_execution_ownership",
        "establish_and_reconcile_broker_state", "data_readiness_mechanism_available",
        "confirm_strategy_approval_and_paper_settings",
    ]


def test_real_capital_config_fails_verify_configuration_and_stops_there(tmp_path):
    cfg, broker, lifecycle, bus = _stack(tmp_path, real_capital=True)
    report = run_startup_sequence(cfg, broker, lifecycle, bus, skip_ownership=True, skip_duplicate_process_check=True)
    assert not report.passed
    assert report.first_failure.step == "verify_configuration"
    # Fail-stop: no later step (ownership, reconcile, etc.) ran at all.
    assert len(report.steps) == 2  # no_duplicate_process (skipped-true) + verify_configuration (failed)


def test_non_paper_broker_endpoint_fails_verify_configuration():
    from talonx_piv.config import PivConfig
    cfg = PivConfig(
        key_id="k", secret_key="s", paper_trading=True, real_capital=False,
        broker_endpoint="https://api.alpaca.markets", approved_sha="abc",
    )
    broker = AlpacaPaperClient(cfg, FakeTransport())
    bus = EventBus(cfg.state_dir / "events.jsonl", feed_mode=cfg.feed_mode)
    lifecycle = PaperLifecycle(cfg.state_dir / "state.json", broker, bus)
    report = run_startup_sequence(cfg, broker, lifecycle, bus, skip_ownership=True, skip_duplicate_process_check=True)
    assert not report.passed
    assert "broker_endpoint" in report.first_failure.detail


def test_unexpected_short_blocks_reconcile_step(tmp_path):
    cfg, broker, lifecycle, bus = _stack(tmp_path)

    class ShortTransport(FakeTransport):
        def get(self, url, **kwargs):
            if url.endswith("/v2/positions"):
                return Response([{"symbol": "AAPL", "side": "short", "qty": "-5"}])
            return super().get(url, **kwargs)

    broker.transport = ShortTransport()
    report = run_startup_sequence(cfg, broker, lifecycle, bus, skip_ownership=True, skip_duplicate_process_check=True)
    assert not report.passed
    assert report.first_failure.step == "establish_and_reconcile_broker_state"


def test_reports_unvalidated_strategy_status_never_fabricates_approval(tmp_path):
    cfg, broker, lifecycle, bus = _stack(tmp_path)
    report = run_startup_sequence(cfg, broker, lifecycle, bus, skip_ownership=True, skip_duplicate_process_check=True)
    approval_step = next(s for s in report.steps if s.step == "confirm_strategy_approval_and_paper_settings")
    assert "UNVALIDATED" in approval_step.detail


def test_paper_disabled_ticker_shown_as_not_enabled(tmp_path):
    cfg, broker, lifecycle, bus = _stack(tmp_path)
    lifecycle.paper_entry_settings = PaperEntrySettings.all_disabled()
    report = run_startup_sequence(cfg, broker, lifecycle, bus, skip_ownership=True, skip_duplicate_process_check=True)
    approval_step = next(s for s in report.steps if s.step == "confirm_strategy_approval_and_paper_settings")
    assert "NONE" in approval_step.detail


# ---------------------------------------------------------------------------
# Bounded restart/backoff
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clean_run_needs_zero_restarts():
    registry = ComponentHealthRegistry()

    async def run_once():
        return None

    attempts = await run_with_bounded_restart(run_once, registry, sleep=lambda s: _immediate())
    assert attempts == 0
    assert registry.overall() == "HEALTHY"


async def _immediate():
    return None


@pytest.mark.asyncio
async def test_recovers_after_a_transient_failure():
    registry = ComponentHealthRegistry()
    calls = {"n": 0}

    async def run_once():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated transient failure")
        return None

    attempts = await run_with_bounded_restart(run_once, registry, sleep=lambda s: _immediate(), max_restarts=3)
    assert attempts == 1
    assert calls["n"] == 2
    assert registry.overall() == "HEALTHY"


@pytest.mark.asyncio
async def test_exhausting_restarts_raises_terminal_failure():
    registry = ComponentHealthRegistry()
    registry.register("session_runner", required=True)

    async def run_once():
        raise RuntimeError("persistent failure")

    with pytest.raises(TerminalSupervisorFailure):
        await run_with_bounded_restart(run_once, registry, sleep=lambda s: _immediate(), max_restarts=2)
    assert registry.overall() == "FAILED"


@pytest.mark.asyncio
async def test_heartbeat_callback_invoked_on_every_transition():
    registry = ComponentHealthRegistry()
    calls = {"n": 0}

    async def run_once():
        return None

    def on_heartbeat():
        calls["n"] += 1

    await run_with_bounded_restart(run_once, registry, sleep=lambda s: _immediate(), on_heartbeat=on_heartbeat)
    assert calls["n"] == 2  # once before the attempt, once on clean exit
