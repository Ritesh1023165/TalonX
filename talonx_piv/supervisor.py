"""Task 78I Stage 2 -- unified PIV application supervisor.

Wraps the EXISTING `SessionRunner`/`DecisionEngine`/`PaperLifecycle`/
`Preflight`/`acquire_execution_ownership` machinery (`cli.py::runtime()`,
unchanged) -- this module does not duplicate SessionRunner's own per-tick
failure isolation or guaranteed EOD-trigger (see `session_runner.py`'s own
`run()`), it adds:

  - An explicit, ORDERED startup-safety sequence matching this task's own
    required order exactly: (1) verify configuration, (2) verify execution
    ownership, (3) establish/reconcile account and order state through the
    broker adapter, (4) establish data readiness, (5) confirm strategy
    approval and per-ticker PAPER settings. Steps run in order and STOP at
    the first failure -- a later step never masks an earlier one.
  - A component health registry (required vs optional, NOT_STARTED/
    HEALTHY/DEGRADED/FAILED, last-heartbeat) -- `overall()` is FAILED only
    if a REQUIRED component is FAILED; an optional component failing
    degrades the overall status without stopping required work.
  - A bounded restart/backoff wrapper around the core `SessionRunner.run()`
    call for a genuinely recoverable failure (a catastrophic exception that
    escaped every per-tick guard) -- since `run()` always triggers EOD
    before returning/raising (Task 72O), a "restart" here always begins
    from a clean, already-flattened state, never mid-position.
  - A persisted recovery-state file distinguishing this PROCESS's own
    `invocation_id` (one per process start/restart attempt) from the
    TRADING `session_id` (one per `SessionIdentity`, reused across restarts
    within the same trading day per `session_identity.py`'s existing
    contract) -- the existing `piv_events.jsonl` (via `EventBus`, already
    stamped with `session_id`/`trading_date_et` on every row) remains the
    one session-scoped log; this module does not introduce a second,
    parallel logger.

One authoritative ingestion/decision path only: this supervisor constructs
exactly ONE `DecisionEngine` (talonx_piv's own) and ONE `SessionRunner` --
never a second, competing consumer.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable
import uuid

from talonx_core import process_guard

from .broker import AlpacaPaperClient
from .config import PAPER_ENDPOINT, PivConfig
from .events import EventBus
from .isolation import validate_piv_isolation
from .lifecycle import PaperLifecycle


class ComponentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@dataclass
class ComponentHealth:
    name: str
    required: bool
    status: ComponentStatus = ComponentStatus.NOT_STARTED
    detail: str = ""
    last_heartbeat: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


class ComponentHealthRegistry:
    def __init__(self) -> None:
        self.components: dict[str, ComponentHealth] = {}

    def register(self, name: str, *, required: bool) -> None:
        self.components[name] = ComponentHealth(name=name, required=required)

    def heartbeat(self, name: str, status: ComponentStatus, detail: str = "") -> None:
        if name not in self.components:
            self.register(name, required=False)
        component = self.components[name]
        component.status = status
        component.detail = detail
        component.last_heartbeat = datetime.now(timezone.utc).isoformat()

    def overall(self) -> str:
        statuses = list(self.components.values())
        if not statuses:
            return "NOT_STARTED"
        if any(c.required and c.status == ComponentStatus.FAILED for c in statuses):
            return "FAILED"
        if any(c.status in (ComponentStatus.DEGRADED, ComponentStatus.FAILED) for c in statuses):
            return "DEGRADED"
        if any(c.status == ComponentStatus.NOT_STARTED for c in statuses):
            return "STARTING"
        return "HEALTHY"

    def to_dict(self) -> dict[str, Any]:
        return {"overall": self.overall(), "components": {name: c.to_dict() for name, c in self.components.items()}}


@dataclass(frozen=True)
class StartupStepResult:
    step: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StartupReport:
    steps: list[StartupStepResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.steps) and all(s.passed for s in self.steps)

    @property
    def first_failure(self) -> StartupStepResult | None:
        return next((s for s in self.steps if not s.passed), None)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "steps": [s.to_dict() for s in self.steps]}


def no_duplicate_full_app_or_piv_process(
    *, exclude_pid: int | None = None, config: PivConfig | None = None,
) -> tuple[bool, str]:
    """Role-aware gate; no config retains the legacy strict diagnostic."""
    if config is None:
        return process_guard.no_competing_talonx_process(exclude_pid=exclude_pid)
    isolated, detail = validate_piv_isolation(config)
    if not isolated:
        return False, f"PIV isolation validation failed: {detail}"
    return process_guard.no_competing_talonx_process(
        exclude_pid=exclude_pid, current_role=process_guard.PIV_ROLE,
        piv_isolation_verified=True,
    )


def run_startup_sequence(
    config: PivConfig, broker: AlpacaPaperClient, lifecycle: PaperLifecycle, bus: EventBus,
    *, skip_ownership: bool = False, skip_duplicate_process_check: bool = False,
) -> StartupReport:
    """Runs the 5 required startup-safety steps IN ORDER, stopping at the
    first failure (a later step's result never appears if an earlier one
    already failed -- this is enforced by `run_step`'s own early return).
    `skip_ownership`/`skip_duplicate_process_check` exist ONLY for
    read-only inspection/rehearsal call sites that explicitly do not intend
    to mutate the broker at all -- production (`cli.py`) never sets either."""
    report = StartupReport()

    def run_step(name: str, action) -> bool:
        try:
            passed, detail = action()
        except Exception as exc:  # noqa: BLE001 -- a step that raises is a FAILED step, never a crashed supervisor
            passed, detail = False, f"{type(exc).__name__}: {exc}"
        report.steps.append(StartupStepResult(name, bool(passed), detail))
        return bool(passed)

    def step0_duplicate_process() -> tuple[bool, str]:
        return no_duplicate_full_app_or_piv_process(config=config)
    if skip_duplicate_process_check:
        report.steps.append(StartupStepResult("no_duplicate_process", True, "SKIPPED (read-only/rehearsal mode)"))
    elif not run_step("no_duplicate_process", step0_duplicate_process):
        return report

    def step1_verify_config() -> tuple[bool, str]:
        if config.real_capital:
            return False, "real_capital=True -- refusing to start (production must never fall back to a real-money endpoint)"
        if config.broker_endpoint.rstrip("/") != PAPER_ENDPOINT:
            return False, f"broker_endpoint is not the immutable Alpaca paper endpoint: {config.broker_endpoint!r}"
        if not config.paper_trading:
            return False, "paper_trading=False -- unknown/non-PAPER account mode fails closed"
        return True, f"PAPER config verified: endpoint={config.broker_endpoint}"
    if not run_step("verify_configuration", step1_verify_config):
        return report

    def step2_ownership() -> tuple[bool, str]:
        broker.verify_paper_identity()
        from .cli import acquire_execution_ownership  # local import: avoids a cli<->supervisor import cycle
        acquire_execution_ownership(config, broker, bus)
        return True, f"execution ownership acquired for account ***{broker.identity.account_number_suffix}"
    if skip_ownership:
        report.steps.append(StartupStepResult("verify_execution_ownership", True, "SKIPPED (read-only/rehearsal mode -- no mutation intended)"))
    elif not run_step("verify_execution_ownership", step2_ownership):
        return report

    def step3_reconcile() -> tuple[bool, str]:
        if not broker.identity:
            broker.verify_paper_identity()
        result = lifecycle.reconcile()
        if result.get("unexpected_short_symbols"):
            return False, f"unexpected broker-side short detected: {result['unexpected_short_symbols']} -- blocks new entries until an operator investigates"
        return True, json.dumps(result, sort_keys=True)
    if not run_step("establish_and_reconcile_broker_state", step3_reconcile):
        return report

    def step4_data_readiness() -> tuple[bool, str]:
        # Data readiness is established LIVE, per-symbol, during the
        # session (SessionReadinessValidator, unchanged) -- this step only
        # confirms the mechanism is present and importable, matching the
        # existing PIV preflight's own "capability, not connectivity" checks
        # for anything that is inherently established at session-runtime.
        from .readiness import SessionReadinessValidator
        SessionReadinessValidator()
        return True, "SessionReadinessValidator wired -- readiness established per-tick during the live session"
    run_step("data_readiness_mechanism_available", step4_data_readiness)

    def step5_approval_and_paper_settings() -> tuple[bool, str]:
        enabled = [t for t in config.universe if lifecycle.paper_entry_settings.enabled_for(t)]
        return True, (
            "strategy_approval_status=UNVALIDATED for every real decision (no approval registry exists -- "
            f"see remaining_issues.md); PAPER-entry-enabled tickers: {enabled or 'NONE'}"
        )
    run_step("confirm_strategy_approval_and_paper_settings", step5_approval_and_paper_settings)

    return report


def invocation_id() -> str:
    return str(uuid.uuid4())


def persist_recovery_state(state_dir: Path, *, invocation_id: str, session_id: str, startup: StartupReport) -> None:
    """Distinguishes this PROCESS's own invocation_id from the trading
    session_id -- multiple invocation_ids (restarts) can legitimately share
    one session_id within the same trading day."""
    path = state_dir / "supervisor_recovery_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}
    invocations = existing.get("invocations", [])
    invocations.append({
        "invocation_id": invocation_id, "session_id": session_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "startup": startup.to_dict(),
    })
    path.write_text(json.dumps({
        "session_id": session_id, "latest_invocation_id": invocation_id, "invocations": invocations,
    }, indent=2, sort_keys=True), encoding="utf-8")


def load_recovery_state(state_dir: Path) -> dict[str, Any] | None:
    path = state_dir / "supervisor_recovery_state.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def persist_component_health(state_dir: Path, registry: ComponentHealthRegistry) -> None:
    path = state_dir / "component_health.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


class TerminalSupervisorFailure(RuntimeError):
    """Raised once bounded restart attempts are exhausted -- a genuinely
    terminal failure, distinct from a single recoverable exception."""


async def _periodic_supervisor_heartbeat(
    registry: ComponentHealthRegistry, component_name: str, interval_seconds: float,
    on_heartbeat: Callable[[], None] | None, sleep: Callable[[float], Awaitable[None]],
) -> None:
    """Task 87B (PIV component-health lag): keep component_health.json's
    last_heartbeat current WHILE run_once() is executing. Previously
    on_heartbeat fired only at loop entry / clean exit / exception, so a
    healthy long-running session left the file frozen at startup time
    (Task 86: ~4.5h stale) -- indistinguishable from a hung process."""
    while True:
        await sleep(interval_seconds)
        registry.heartbeat(component_name, ComponentStatus.HEALTHY, "supervised, running")
        if on_heartbeat is not None:
            on_heartbeat()


async def run_with_bounded_restart(
    run_once: Callable[[], Awaitable[None]], registry: ComponentHealthRegistry, *,
    component_name: str = "session_runner", max_restarts: int = 3, backoff_seconds: float = 30.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_heartbeat: Callable[[], None] | None = None,
    heartbeat_interval_seconds: float | None = None,
) -> int:
    """Wraps `run_once` (e.g. `lambda: run_session(runner, listener)`) in a
    bounded restart/backoff loop. `run_once` is expected to already
    guarantee EOD-safety before returning or raising (SessionRunner.run()
    does -- Task 72O), so a restart here always begins from an
    already-flattened, clean state, never mid-position. A CLEAN return
    (e.g. scheduled EOD completion, or a controlled shutdown) ends the loop
    immediately with 0 attempts consumed -- restarts are for a genuinely
    UNEXPECTED exception only. Returns the number of restart attempts that
    were actually needed (0 on a clean first run).

    Task 87B: a background heartbeat refreshes component_health.json every
    ``heartbeat_interval_seconds`` (default 30, or
    TALONX_PIV_SUPERVISOR_HEARTBEAT_SECONDS) for the duration of each
    run_once(), so the file proves current liveness rather than freezing
    at startup."""
    if heartbeat_interval_seconds is None:
        try:
            heartbeat_interval_seconds = float(os.environ.get("TALONX_PIV_SUPERVISOR_HEARTBEAT_SECONDS", "30"))
        except (TypeError, ValueError):
            heartbeat_interval_seconds = 30.0
    attempt = 0
    while True:
        registry.heartbeat(component_name, ComponentStatus.HEALTHY, f"attempt={attempt}")
        if on_heartbeat is not None:
            on_heartbeat()
        hb_task = None
        if heartbeat_interval_seconds and heartbeat_interval_seconds > 0:
            hb_task = asyncio.ensure_future(_periodic_supervisor_heartbeat(
                registry, component_name, heartbeat_interval_seconds, on_heartbeat, sleep,
            ))
        try:
            await run_once()
            registry.heartbeat(component_name, ComponentStatus.HEALTHY, f"clean exit after {attempt} restart(s)")
            if on_heartbeat is not None:
                on_heartbeat()
            return attempt
        except Exception as exc:  # noqa: BLE001 -- a genuinely unexpected failure that escaped every
            # per-tick guard inside run_once itself; EOD-safety is assumed already handled by run_once
            # (documented precondition -- see this function's own docstring).
            attempt += 1
            registry.heartbeat(component_name, ComponentStatus.FAILED, f"attempt {attempt}: {type(exc).__name__}: {exc}")
            if on_heartbeat is not None:
                on_heartbeat()
            if attempt > max_restarts:
                registry.heartbeat(component_name, ComponentStatus.FAILED, f"exhausted {max_restarts} restart(s) -- terminal failure")
                if on_heartbeat is not None:
                    on_heartbeat()
                raise TerminalSupervisorFailure(
                    f"{component_name} failed {attempt} time(s), exceeding max_restarts={max_restarts}: {exc}"
                ) from exc
            await sleep(backoff_seconds)
        finally:
            if hb_task is not None:
                hb_task.cancel()
                try:
                    await hb_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- cleanup must never raise
                    pass
