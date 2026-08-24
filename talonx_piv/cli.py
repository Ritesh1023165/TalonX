"""Task 64 paper-only operator commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*args, **kwargs): return False

from .broker import AlpacaPaperClient, PaperGuardError
from .config import PivConfig
from .decision_engine import DecisionEngine
from .events import EventBus, PivEvent
from .lifecycle import PaperLifecycle, paper_cleanup
from .preflight import Preflight
from .reporting import build_session_report
from .session_runner import SessionRunner
from .telegram import sender
from .telegram_inbound import build_piv_telegram_listener


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


def runtime(config: PivConfig):
    bus = EventBus(
        config.state_dir / "piv_events.jsonl", sender(config.telegram_token, config.telegram_chat_id),
        feed_mode=config.feed_mode,
    )
    broker = AlpacaPaperClient(config)
    lifecycle = PaperLifecycle(config.state_dir / "lifecycle_state.json", broker, bus)
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
    return root


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parser().parse_args(argv)
    base = PivConfig()
    approved = getattr(args, "approved_sha", None) or base.approved_sha
    config = PivConfig(approved_sha=approved)
    bus, broker, lifecycle = runtime(config)
    try:
        if args.command == "preflight":
            status, checks = Preflight(config, broker, bus).run()
            Preflight.write_report(config.state_dir / "latest_preflight.json", status, checks, config.feed_mode)
            print(status)
            return 0 if status == "PIV_READY" else 2
        if args.command == "cleanup":
            result = paper_cleanup(broker, bus, args.confirm_paper_cleanup)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["clean"] else 2
        if args.command == "start":
            bus.emit(PivEvent.build("STARTUP", status="PAPER MODE / NO REAL CAPITAL"))
            status, checks = Preflight(config, broker, bus).run()
            Preflight.write_report(config.state_dir / "latest_preflight.json", status, checks, config.feed_mode)
            lifecycle.start_session(status == "PIV_READY", args.confirm_paper_session_start)
            print("PAPER_SESSION_STARTED")
            if args.no_live_loop:
                return 0
            decision_engine = None
            if config.decision_path_enabled and not args.no_decision_path:
                import redis.asyncio as redis_asyncio
                redis_client = redis_asyncio.from_url(os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379"))
                decision_engine = DecisionEngine(redis_client, bus, lifecycle)
            runner = SessionRunner(
                config, bus, lifecycle, broker.transport, decision_engine=decision_engine,
                probe_enabled=args.confirm_piv_lifecycle_probe,
            )
            listener = None if args.no_telegram_inbound else build_piv_telegram_listener(config.state_dir)
            asyncio.run(run_session(runner, listener))
            return 0
        broker.verify_paper_identity()
        if args.command == "kill-switch":
            lifecycle.activate_kill_switch(args.cancel_paper_orders)
            print("KILL_SWITCH")
            return 0
        if args.command == "eod":
            result = lifecycle.eod_flatten()
            result["feed_mode"] = config.feed_mode
            (config.state_dir / "latest_reconciliation.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
            report = build_session_report(bus.path, result, config.feed_mode)
            (config.state_dir / "latest_session_report.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
            print(json.dumps(result, sort_keys=True))
            return 0 if result["matched"] and not result["broker_open_orders"] and not result["broker_positions"] else 2
    except (PaperGuardError, OSError, RuntimeError) as exc:
        bus.emit(PivEvent.build("BROKER_ERROR", reason=str(exc), status="PIV_BLOCKED"))
        print("PIV_BLOCKED", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
