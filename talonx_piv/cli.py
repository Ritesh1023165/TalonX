"""Task 64 paper-only operator commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*args, **kwargs): return False

from .broker import AlpacaPaperClient, PaperGuardError
from .config import PivConfig
from .decision_engine import DecisionEngine
from .decision_ledger import DecisionLedger
from .events import EventBus, PivEvent
from .execution_ownership import ExecutionOwnership, account_lock_key
from .execution_settings import load_paper_entry_settings
from .lifecycle import PaperLifecycle, paper_cleanup
from .notification_outbox import NotificationOutbox
from .observability import build_integrated_projection
from .preflight import Preflight
from .reporting import build_session_report
from .session_identity import build_session_identity
from .session_runner import SessionRunner
from .shadow_ledger import ShadowLedger
from .supervisor import (
    ComponentHealthRegistry, ComponentStatus, StartupReport, StartupStepResult, TerminalSupervisorFailure,
    invocation_id as new_invocation_id, persist_component_health, persist_recovery_state,
    run_startup_sequence, run_with_bounded_restart,
)
from .telegram import sender
from .telegram_inbound import build_piv_info, build_piv_telegram_listener


async def run_session(runner: SessionRunner, listener) -> None:
    """Runs SessionRunner.run() as the main task; the inbound Telegram
    listener (if any) runs concurrently as a background task, started
    first so /ping is answerable from the moment the session begins, and
    always stopped in `finally` regardless of how the main run ends --
    its own internal retry-forever loop (see TelegramReplyListener.run's
    except/backoff) means nothing it does can crash the session, but the
    reverse must also hold: a session crash/kill-switch stop must not
    leave the listener polling forever in the background."""
    listener_task = asyncio.create_task(listener.run()) if listener is not None else None
    try:
        await runner.run()
    finally:
        if listener_task is not None:
            listener.stop()
            await listener_task


def _execution_lock_dir() -> Path:
    """Task 78I Stage 1D: deliberately a FIXED, global location -- NEVER
    under config.state_dir -- so two application instances configured with
    DIFFERENT state_dir but the SAME underlying Alpaca paper account still
    collide on the same lock. Overridable via TALONX_PIV_LOCK_DIR for
    isolated tests/rehearsal only; production uses the default unchanged."""
    return Path(os.environ.get("TALONX_PIV_LOCK_DIR", str(Path.home() / ".talonx_piv" / "locks")))


def acquire_execution_ownership(config: PivConfig, broker: AlpacaPaperClient, bus: EventBus) -> ExecutionOwnership:
    """Must be called AFTER broker.verify_paper_identity() has succeeded.
    Raises PaperGuardError (never returns a not-acquired lock silently) if
    another live process already owns this account -- callers must treat
    this exactly like a preflight failure, never proceeding to any
    mutating operation."""
    if broker.identity is None:
        raise PaperGuardError("cannot acquire execution ownership before paper identity is verified")
    key = account_lock_key(config.broker_endpoint, broker.identity.account_id)
    lock = ExecutionOwnership(_execution_lock_dir(), key, owner_label=f"pid={os.getpid()} endpoint={config.broker_endpoint}")
    if not lock.acquire():
        bus.emit(PivEvent.build(
            "BROKER_ERROR", reason="EXECUTION_OWNERSHIP_ALREADY_HELD", status="PIV_BLOCKED",
        ))
        raise PaperGuardError(
            f"execution ownership for this PAPER account is already held by another live process "
            f"(lock={lock.lock_path}) -- refusing to start a second execution writer"
        )
    broker.execution_ownership = lock
    return lock


def runtime(config: PivConfig, session_id: str | None = None):
    bus = EventBus(
        config.state_dir / "piv_events.jsonl", sender(config.telegram_token, config.telegram_chat_id),
        feed_mode=config.feed_mode, session_id=session_id,
    )
    broker = AlpacaPaperClient(config)
    # Task 76S Stage 2/3: fail-closed by construction -- if
    # paper_entry_settings.json does not exist yet (e.g. immediately after
    # this task ships), load_paper_entry_settings returns an all-disabled
    # PaperEntrySettings, so NO ticker may open a new PAPER entry until an
    # operator explicitly populates that file. See execution_settings.py
    # and results/task76s_long_only_execution_contract/paper_setting_migration.md.
    paper_entry_settings = load_paper_entry_settings(config.state_dir / "paper_entry_settings.json")
    lifecycle = PaperLifecycle(config.state_dir / "lifecycle_state.json", broker, bus, paper_entry_settings)
    return bus, broker, lifecycle


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="TalonX PAPER PIV operator (no real capital)")
    sub = root.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight"); preflight.add_argument("--approved-sha", required=True)
    cleanup = sub.add_parser("cleanup"); cleanup.add_argument("--confirm-paper-cleanup", action="store_true")
    start = sub.add_parser("start"); start.add_argument("--approved-sha", required=True); start.add_argument("--confirm-paper-session-start", action="store_true")
    start.add_argument("--no-live-loop", action="store_true", help="Flip session_enabled and return immediately without running the live data/strategy loop (Task64 behavior).")
    start.add_argument("--no-decision-path", action="store_true", help="Run the live feed/readiness loop without the strategy decision path wired in (Task65 plumbing-only behavior).")
    start.add_argument("--confirm-piv-lifecycle-probe", action="store_true", help="Enable the operator-confirmed PIV_LIFECYCLE_PROBE fallback (only fires if no natural STRATEGY order lifecycle occurred by the predeclared cutoff).")
    start.add_argument("--no-telegram-inbound", action="store_true", help="Do not start the inbound Telegram /ping listener (use if a separate run_talonx.py process is already polling the SAME bot token -- only one poller per token is allowed).")
    kill = sub.add_parser("kill-switch"); kill.add_argument("--cancel-paper-orders", action="store_true")
    sub.add_parser("eod")
    supervise = sub.add_parser("supervise", help="Task 78I Stage 2: run the unified supervisor (ordered startup-safety sequence, component health tracking, bounded restart/backoff) around the same live session start already does.")
    supervise.add_argument("--approved-sha", required=True)
    supervise.add_argument("--confirm-paper-session-start", action="store_true")
    supervise.add_argument("--no-decision-path", action="store_true")
    supervise.add_argument("--confirm-piv-lifecycle-probe", action="store_true")
    supervise.add_argument("--no-telegram-inbound", action="store_true")
    supervise.add_argument("--max-restarts", type=int, default=3)
    supervise.add_argument("--backoff-seconds", type=float, default=30.0)
    return root


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parser().parse_args(argv)
    base = PivConfig()
    approved = getattr(args, "approved_sha", None) or base.approved_sha
    config = PivConfig(approved_sha=approved)
    identity = build_session_identity(config)
    bus, broker, lifecycle = runtime(config, session_id=identity.session_id)
    try:
        if args.command == "preflight":
            status, checks = Preflight(config, broker, bus).run()
            Preflight.write_report(config.state_dir / "latest_preflight.json", status, checks, config.feed_mode)
            print(status)
            return 0 if status == "PIV_READY" else 2
        if args.command == "cleanup":
            broker.verify_paper_identity()
            acquire_execution_ownership(config, broker, bus)
            result = paper_cleanup(broker, bus, args.confirm_paper_cleanup)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["clean"] else 2
        if args.command == "start":
            (config.state_dir).mkdir(parents=True, exist_ok=True)
            (config.state_dir / "session_identity.json").write_text(
                json.dumps(identity.to_dict(), indent=2, sort_keys=True), encoding="utf-8",
            )
            bus.emit(PivEvent.build("STARTUP", status="PAPER MODE / NO REAL CAPITAL"))
            status, checks = Preflight(config, broker, bus).run()
            Preflight.write_report(config.state_dir / "latest_preflight.json", status, checks, config.feed_mode)
            if status == "PIV_READY":
                # Task 78I Stage 1D: ownership is acquired AFTER preflight
                # (which itself calls verify_paper_identity()), BEFORE
                # start_session flips session_enabled=True -- a session that
                # cannot claim exclusive execution ownership must never be
                # allowed to begin accepting entries.
                acquire_execution_ownership(config, broker, bus)
            lifecycle.start_session(status == "PIV_READY", args.confirm_paper_session_start)
            print("PAPER_SESSION_STARTED")
            if args.no_live_loop:
                return 0
            decision_engine = None
            redis_client = None
            if config.decision_path_enabled and not args.no_decision_path:
                import redis.asyncio as redis_asyncio
                redis_client = redis_asyncio.from_url(os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379"))
                # Task 77I: the three new durable ledgers -- real, state_dir-
                # backed instances only here (production). No caller in this
                # file ever sets strategy_approval_status_override (grep-
                # provable -- see test_task77i_decision_engine_wiring.py's
                # own confirmation of this), so every real decision resolves
                # strategy approval to UNVALIDATED.
                decision_ledger = DecisionLedger(config.state_dir / "decision_ledger.json")
                notification_outbox = NotificationOutbox(
                    config.state_dir / "notification_outbox.json", sender(config.telegram_token, config.telegram_chat_id),
                )
                shadow_ledger = ShadowLedger(config.state_dir / "shadow_ledger.json")
                decision_engine = DecisionEngine(
                    redis_client, bus, lifecycle, piv_config=config,
                    decision_ledger=decision_ledger, notification_outbox=notification_outbox, shadow_ledger=shadow_ledger,
                    runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
                )
            piv_info = build_piv_info(
                config.feed_mode, config.universe, session_id=identity.session_id,
                runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
            )
            runner = SessionRunner(
                config, bus, lifecycle, broker.transport, decision_engine=decision_engine,
                probe_enabled=args.confirm_piv_lifecycle_probe, piv_info=piv_info,
            )
            listener = None if args.no_telegram_inbound else build_piv_telegram_listener(
                config.state_dir, redis_client=redis_client, started_at=datetime.now(timezone.utc),
                feed_mode=config.feed_mode, universe=config.universe, piv_info=piv_info,
            )
            asyncio.run(run_session(runner, listener))
            return 0
        if args.command == "supervise":
            (config.state_dir).mkdir(parents=True, exist_ok=True)
            (config.state_dir / "session_identity.json").write_text(
                json.dumps(identity.to_dict(), indent=2, sort_keys=True), encoding="utf-8",
            )
            bus.emit(PivEvent.build("STARTUP", status="PAPER MODE / NO REAL CAPITAL / SUPERVISED"))
            registry = ComponentHealthRegistry()
            registry.register("preflight", required=True)
            registry.register("execution_ownership", required=True)
            registry.register("session_runner", required=True)
            registry.register("decision_engine", required=config.decision_path_enabled and not args.no_decision_path)
            registry.register("telegram_inbound", required=False)
            this_invocation_id = new_invocation_id()

            status, checks = Preflight(config, broker, bus).run()
            Preflight.write_report(config.state_dir / "latest_preflight.json", status, checks, config.feed_mode)
            registry.heartbeat("preflight", ComponentStatus.HEALTHY if status == "PIV_READY" else ComponentStatus.FAILED, status)
            persist_component_health(config.state_dir, registry)
            if status != "PIV_READY":
                failed_preflight_report = StartupReport(steps=[StartupStepResult("preflight", False, status)])
                persist_recovery_state(config.state_dir, invocation_id=this_invocation_id, session_id=identity.session_id, startup=failed_preflight_report)
                print("PIV_BLOCKED", file=sys.stderr)
                return 2

            # Task 78I Stage 2: the ordered startup-safety sequence -- belt-
            # and-suspenders with Preflight above (which already covers git
            # SHA/tree/feed/telegram/universe/runtime-parity), filling in
            # what Preflight does NOT cover: ownership, broker-state
            # reconciliation BEFORE accepting entries, and an explicit
            # approval/PAPER-setting report.
            startup = run_startup_sequence(config, broker, lifecycle, bus, skip_duplicate_process_check=True)
            persist_recovery_state(config.state_dir, invocation_id=this_invocation_id, session_id=identity.session_id, startup=startup)
            if not startup.passed:
                registry.heartbeat("execution_ownership", ComponentStatus.FAILED, startup.first_failure.detail)
                persist_component_health(config.state_dir, registry)
                bus.emit(PivEvent.build("BROKER_ERROR", reason=f"SUPERVISOR_STARTUP_FAILED:{startup.first_failure.step}", status="PIV_BLOCKED"))
                print("PIV_BLOCKED", file=sys.stderr)
                return 2
            registry.heartbeat("execution_ownership", ComponentStatus.HEALTHY, "acquired and reconciled")
            persist_component_health(config.state_dir, registry)

            lifecycle.start_session(True, args.confirm_paper_session_start)
            print("PAPER_SESSION_STARTED (SUPERVISED)")

            decision_engine = None
            redis_client = None
            if config.decision_path_enabled and not args.no_decision_path:
                import redis.asyncio as redis_asyncio
                redis_client = redis_asyncio.from_url(os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379"))
                decision_ledger = DecisionLedger(config.state_dir / "decision_ledger.json")
                notification_outbox = NotificationOutbox(
                    config.state_dir / "notification_outbox.json", sender(config.telegram_token, config.telegram_chat_id),
                )
                shadow_ledger = ShadowLedger(config.state_dir / "shadow_ledger.json")
                decision_engine = DecisionEngine(
                    redis_client, bus, lifecycle, piv_config=config,
                    decision_ledger=decision_ledger, notification_outbox=notification_outbox, shadow_ledger=shadow_ledger,
                    runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
                )
            piv_info = build_piv_info(
                config.feed_mode, config.universe, session_id=identity.session_id,
                runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
            )
            runner = SessionRunner(
                config, bus, lifecycle, broker.transport, decision_engine=decision_engine,
                probe_enabled=args.confirm_piv_lifecycle_probe, piv_info=piv_info,
            )
            listener = None if args.no_telegram_inbound else build_piv_telegram_listener(
                config.state_dir, redis_client=redis_client, started_at=datetime.now(timezone.utc),
                feed_mode=config.feed_mode, universe=config.universe, piv_info=piv_info,
            )
            registry.heartbeat("decision_engine", ComponentStatus.HEALTHY if decision_engine is not None else ComponentStatus.NOT_STARTED, "constructed" if decision_engine is not None else "decision path disabled")
            registry.heartbeat("telegram_inbound", ComponentStatus.HEALTHY if listener is not None else ComponentStatus.DEGRADED, "started" if listener is not None else "disabled (--no-telegram-inbound)")
            persist_component_health(config.state_dir, registry)

            def _on_heartbeat() -> None:
                persist_component_health(config.state_dir, registry)

            try:
                asyncio.run(run_with_bounded_restart(
                    lambda: run_session(runner, listener), registry,
                    max_restarts=args.max_restarts, backoff_seconds=args.backoff_seconds, on_heartbeat=_on_heartbeat,
                ))
            except TerminalSupervisorFailure as exc:
                bus.emit(PivEvent.build("BROKER_ERROR", reason=f"SUPERVISOR_TERMINAL_FAILURE:{exc}", status="PIV_BLOCKED"))
                print("PIV_BLOCKED: supervisor exhausted bounded restarts", file=sys.stderr)
                return 2
            return 0
        broker.verify_paper_identity()
        acquire_execution_ownership(config, broker, bus)
        if args.command == "kill-switch":
            lifecycle.activate_kill_switch(args.cancel_paper_orders)
            print("KILL_SWITCH")
            return 0
        if args.command == "eod":
            # Task 72O Stage 1: manual `eod` recovery MUST identify the
            # live session it is reconciling -- it must never mint a
            # second, unrelated session_id for EOD events (the exact
            # 2026-08-26 bug this stage fixes). Refuses, with zero broker
            # calls, if no live session identity is known.
            identity_path = config.state_dir / "session_identity.json"
            if not identity_path.exists():
                bus.emit(PivEvent.build("BROKER_ERROR", reason="EOD_REQUIRES_KNOWN_LIVE_SESSION_IDENTITY", status="PIV_BLOCKED"))
                print("PIV_BLOCKED: no session_identity.json -- cannot identify the live session to reconcile", file=sys.stderr)
                return 2
            saved = json.loads(identity_path.read_text(encoding="utf-8"))
            live_session_id = saved.get("session_id")
            trading_date_et = saved.get("trading_date_et") or identity.trading_date_et
            runtime_sha = saved.get("runtime_sha") or identity.runtime_sha
            config_hash = saved.get("config_hash") or identity.config_hash
            if not live_session_id:
                bus.emit(PivEvent.build("BROKER_ERROR", reason="EOD_REQUIRES_KNOWN_LIVE_SESSION_IDENTITY", status="PIV_BLOCKED"))
                print("PIV_BLOCKED: session_identity.json is missing session_id", file=sys.stderr)
                return 2

            from .eod_lifecycle import run_eod_lifecycle
            outcome = run_eod_lifecycle(
                config, bus, lifecycle, live_session_id=live_session_id, trading_date_et=trading_date_et,
                runtime_sha=runtime_sha, config_hash=config_hash, trigger_reason="MANUAL_CLI_INVOCATION",
            )
            result = dict(outcome.get("reconciliation") or {})
            result["feed_mode"] = config.feed_mode
            result["eod_status"] = outcome["status"]
            result["live_session_id"] = outcome["session_id"]
            result["reconciliation_run_id"] = outcome["reconciliation_run_id"]
            (config.state_dir / "latest_reconciliation.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
            funnel_path = config.state_dir / "quant_funnel_report.json"
            quant_funnel = json.loads(funnel_path.read_text(encoding="utf-8")) if funnel_path.exists() else None
            integrated_projection = build_integrated_projection(
                config.state_dir, session_id=live_session_id, trading_date_et=trading_date_et,
            )
            report = build_session_report(
                bus.path, result, config.feed_mode,
                trading_date_et=trading_date_et, session_id=live_session_id, quant_funnel=quant_funnel,
                integrated_projection=integrated_projection,
            )
            (config.state_dir / "latest_session_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            print(json.dumps(result, sort_keys=True))
            return outcome["exit_code"]
    except (PaperGuardError, OSError, RuntimeError) as exc:
        bus.emit(PivEvent.build("BROKER_ERROR", reason=str(exc), status="PIV_BLOCKED"))
        print("PIV_BLOCKED", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
