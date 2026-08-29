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
from .gemini_enrichment import GeminiEnrichmentOutbox
from .isolation import build_piv_quant_config
from .lifecycle import PaperLifecycle, paper_cleanup
from .notification_outbox import NotificationOutbox
from .observability import build_integrated_projection
from .preflight import Preflight
from .reporting import build_session_report
from .session_identity import (
    _SESSION_IDENTITY_REQUIRED_FIELDS, SessionIdentity, SessionRecoveryRequired,
    build_session_identity, resolve_session_identity, write_session_recovery_marker,
)
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


def build_gemini_chain_if_enabled(bus: EventBus):
    """Task 78I Stage 3: optional, off by default. Only attempted when
    TALONX_PIV_GEMINI_ENABLED is explicitly truthy -- a NEW capability must
    never silently start making real API calls just because talonx_brain
    happens to be importable/configured for the general app. Construction
    failure (missing API key, import error, etc.) degrades to None
    (enrichment simply resolves UNAVAILABLE for every request) -- it never
    blocks PAPER_SESSION_STARTED or any decision/broker path."""
    if os.environ.get("TALONX_PIV_GEMINI_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    try:
        from talonx_brain.llm import build_research_chain
        return build_research_chain()
    except Exception as exc:  # noqa: BLE001 -- optional component; never blocks startup.
        bus.emit(PivEvent.build(
            "BROKER_ERROR", reason=f"GEMINI_CHAIN_CONSTRUCTION_FAILED_{type(exc).__name__}", status="ENRICHMENT_DISABLED_DEGRADED",
        ))
        return None


def runtime(config: PivConfig, session_id: str | None = None, runtime_sha: str | None = None, config_hash: str | None = None):
    bus = EventBus(
        config.state_dir / "piv_events.jsonl",
        sender(config.telegram_token, config.telegram_chat_id) if config.telegram_enabled else None,
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
    # Task 79E: fail-closed/inactive-by-default -- absent or malformed
    # experimental_authorization.json (the normal, expected state for every
    # session until an operator explicitly authors one) means the loader
    # returns None, so the experimental path is completely unreachable (see
    # decision_engine.py's _experimental_permissions: None -> (False, False,
    # None) for every signal, identical to pre-Task79E behavior).
    #
    # Task 79E-R1: the PATH (never a pre-loaded object) is what gets passed
    # to both PaperLifecycle and DecisionEngine below -- each independently
    # reloads the file FRESH from disk on every permission check (see
    # lifecycle.py/decision_engine.py's own _current_experimental_
    # authorization), so an operator deleting, disabling, or editing the
    # file mid-session is observed on the very next order attempt, not only
    # after this process is restarted.
    experimental_authorization_path = config.state_dir / "experimental_authorization.json"
    lifecycle = PaperLifecycle(
        config.state_dir / "lifecycle_state.json", broker, bus, paper_entry_settings,
        experimental_authorization_path=experimental_authorization_path,
        runtime_sha=runtime_sha, config_hash=config_hash,
    )
    return bus, broker, lifecycle, experimental_authorization_path


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
    start.add_argument("--isolated-parallel", action="store_true", help="Required Task 82 marker: PIV bindings were validated for parallel operation beside Original.")
    kill = sub.add_parser("kill-switch"); kill.add_argument("--cancel-paper-orders", action="store_true")
    sub.add_parser("eod")
    supervise = sub.add_parser("supervise", help="Task 78I Stage 2: run the unified supervisor (ordered startup-safety sequence, component health tracking, bounded restart/backoff) around the same live session start already does.")
    supervise.add_argument("--approved-sha", required=True)
    supervise.add_argument("--confirm-paper-session-start", action="store_true")
    supervise.add_argument("--no-decision-path", action="store_true")
    supervise.add_argument("--confirm-piv-lifecycle-probe", action="store_true")
    supervise.add_argument("--no-telegram-inbound", action="store_true")
    supervise.add_argument("--isolated-parallel", action="store_true")
    supervise.add_argument("--max-restarts", type=int, default=3)
    supervise.add_argument("--backoff-seconds", type=float, default=30.0)
    return root


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parser().parse_args(argv)
    base = PivConfig()
    approved = getattr(args, "approved_sha", None) or base.approved_sha
    config = PivConfig(approved_sha=approved)
    # Task 79E-R2-2 Requirement 3: resumes the SAME session identity for a
    # genuinely still-live session (see resolve_session_identity's own
    # docstring for the exact, fail-closed criteria) -- a full process
    # restart no longer always mints a brand-new session_id.
    try:
        identity = resolve_session_identity(config)
    except SessionRecoveryRequired as exc:
        # Task 81 §3: bindings changed / identity corrupt / EOD incomplete
        # while exposure or submissions remain unresolved. Never mint a
        # replacement session or overwrite session_identity.json here.
        write_session_recovery_marker(config.state_dir, exc, command=args.command)
        print("PIV_BLOCKED_RECOVERY_REQUIRED", file=sys.stderr)
        print(f"  required action: {exc.required_action}", file=sys.stderr)
        for _reason in exc.reasons:
            print(f"  reason: {_reason}", file=sys.stderr)
        if args.command in ("start", "supervise"):
            return 2
        # Read-only / recovery commands (preflight, eod, kill-switch,
        # cleanup, report) may still run against the PRESERVED identity so
        # the operator can carry out the recovery transition.
        if isinstance(exc.preserved_identity, dict) and all(
            k in exc.preserved_identity for k in _SESSION_IDENTITY_REQUIRED_FIELDS
        ):
            identity = SessionIdentity(**{k: exc.preserved_identity[k] for k in _SESSION_IDENTITY_REQUIRED_FIELDS})
        elif args.command in ("preflight",):
            identity = build_session_identity(config)
        else:
            print("  no usable preserved session identity -- cannot proceed", file=sys.stderr)
            return 2
    if args.command in ("start", "supervise") and not args.isolated_parallel:
        print("PIV_BLOCKED: --isolated-parallel is required for runtime startup", file=sys.stderr)
        return 2
    bus, broker, lifecycle, experimental_authorization_path = runtime(
        config, session_id=identity.session_id, runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
    )
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
                redis_client = redis_asyncio.from_url(config.redis_url)
                # Task 77I: the three new durable ledgers -- real, state_dir-
                # backed instances only here (production). No caller in this
                # file ever sets strategy_approval_status_override (grep-
                # provable -- see test_task77i_decision_engine_wiring.py's
                # own confirmation of this), so every real decision resolves
                # strategy approval to UNVALIDATED.
                decision_ledger = DecisionLedger(config.state_dir / "decision_ledger.json")
                notification_outbox = NotificationOutbox(
                    config.state_dir / "notification_outbox.json",
                    sender(config.telegram_token, config.telegram_chat_id) if config.telegram_enabled else None,
                )
                shadow_ledger = ShadowLedger(config.state_dir / "shadow_ledger.json")
                gemini_enrichment = GeminiEnrichmentOutbox(config.state_dir / "gemini_enrichment.json")
                # Task 79E-R2 Requirement 3: "restore only against reconciled
                # exposure" -- the `supervise` command's own startup sequence
                # already reconciles broker state (open orders, positions,
                # unexpected shorts, and now also any UNCONFIRMED_TIMEOUT/
                # SUBMIT_FAILED_UNCERTAIN order) BEFORE ever constructing a
                # DecisionEngine (see supervisor.run_startup_sequence's
                # step3_reconcile). This plain `start` command previously had
                # no equivalent call, so DecisionEngine.__post_init__'s own
                # _rehydrate_positions could run against un-reconciled,
                # possibly-stale local state. Matches supervise's posture
                # exactly, ahead of DecisionEngine's own rehydration below.
                lifecycle.reconcile()
                decision_engine = DecisionEngine(
                    redis_client, bus, lifecycle, config=build_piv_quant_config(config), piv_config=config,
                    decision_ledger=decision_ledger, notification_outbox=notification_outbox, shadow_ledger=shadow_ledger,
                    gemini_enrichment=gemini_enrichment,
                    runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
                    experimental_authorization_path=experimental_authorization_path,
                )
            piv_info = build_piv_info(
                config.feed_mode, config.universe, session_id=identity.session_id,
                runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
            )
            gemini_chain = build_gemini_chain_if_enabled(bus) if decision_engine is not None else None
            runner = SessionRunner(
                config, bus, lifecycle, broker.transport, decision_engine=decision_engine,
                probe_enabled=args.confirm_piv_lifecycle_probe, piv_info=piv_info, gemini_chain=gemini_chain,
            )
            listener = None if args.no_telegram_inbound or not config.telegram_enabled else build_piv_telegram_listener(
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
                redis_client = redis_asyncio.from_url(config.redis_url)
                decision_ledger = DecisionLedger(config.state_dir / "decision_ledger.json")
                notification_outbox = NotificationOutbox(
                    config.state_dir / "notification_outbox.json",
                    sender(config.telegram_token, config.telegram_chat_id) if config.telegram_enabled else None,
                )
                shadow_ledger = ShadowLedger(config.state_dir / "shadow_ledger.json")
                gemini_enrichment = GeminiEnrichmentOutbox(config.state_dir / "gemini_enrichment.json")
                decision_engine = DecisionEngine(
                    redis_client, bus, lifecycle, config=build_piv_quant_config(config), piv_config=config,
                    decision_ledger=decision_ledger, notification_outbox=notification_outbox, shadow_ledger=shadow_ledger,
                    gemini_enrichment=gemini_enrichment,
                    runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
                    experimental_authorization_path=experimental_authorization_path,
                )
            piv_info = build_piv_info(
                config.feed_mode, config.universe, session_id=identity.session_id,
                runtime_sha=identity.runtime_sha, config_hash=identity.config_hash,
            )
            gemini_chain = build_gemini_chain_if_enabled(bus) if decision_engine is not None else None
            registry.register("gemini_enrichment", required=False)
            registry.heartbeat("gemini_enrichment", ComponentStatus.HEALTHY if gemini_chain is not None else ComponentStatus.DEGRADED, "configured" if gemini_chain is not None else "TALONX_PIV_GEMINI_ENABLED not set, or construction failed -- degraded, never blocking")
            runner = SessionRunner(
                config, bus, lifecycle, broker.transport, decision_engine=decision_engine,
                probe_enabled=args.confirm_piv_lifecycle_probe, piv_info=piv_info, gemini_chain=gemini_chain,
            )
            listener = None if args.no_telegram_inbound or not config.telegram_enabled else build_piv_telegram_listener(
                config.state_dir, redis_client=redis_client, started_at=datetime.now(timezone.utc),
                feed_mode=config.feed_mode, universe=config.universe, piv_info=piv_info,
            )
            registry.heartbeat("decision_engine", ComponentStatus.HEALTHY if decision_engine is not None else ComponentStatus.NOT_STARTED, "constructed" if decision_engine is not None else "decision path disabled")
            registry.heartbeat(
                "telegram_inbound", ComponentStatus.HEALTHY,
                "started" if listener is not None else "disabled by Task 82 isolation policy",
            )
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
            from .reporting import finalize_session_report
            outcome = run_eod_lifecycle(
                config, bus, lifecycle, live_session_id=live_session_id, trading_date_et=trading_date_et,
                runtime_sha=runtime_sha, config_hash=config_hash, trigger_reason="MANUAL_CLI_INVOCATION",
            )
            # Task 81 §4 (C4/C5/C6): one shared, read-only report finaliser --
            # scoped to the ORIGINAL live session, emitted for PASSED /
            # FAILED / INCONCLUSIVE alike, never re-triggering broker
            # cancel/close, report-generation status kept separate.
            report = finalize_session_report(
                config.state_dir, bus.path, config_feed_mode=config.feed_mode,
                live_session_id=live_session_id, trading_date_et=trading_date_et, eod_outcome=outcome,
            )
            result = dict(outcome.get("reconciliation") or {})
            result["feed_mode"] = config.feed_mode
            result["eod_status"] = outcome["status"]
            result["report_generation_status"] = report.get("report_generation_status")
            print(json.dumps(result, sort_keys=True))
            return outcome["exit_code"]
    except (PaperGuardError, OSError, RuntimeError) as exc:
        bus.emit(PivEvent.build("BROKER_ERROR", reason=str(exc), status="PIV_BLOCKED"))
        print("PIV_BLOCKED", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
