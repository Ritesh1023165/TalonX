"""Task 64 paper-only operator commands."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*args, **kwargs): return False

from .broker import AlpacaPaperClient, PaperGuardError
from .config import PivConfig
from .events import EventBus, PivEvent
from .lifecycle import PaperLifecycle, paper_cleanup
from .preflight import Preflight
from .reporting import build_session_report
from .session_runner import SessionRunner
from .telegram import sender


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
            SessionRunner(config, bus, lifecycle, broker.transport).run()
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
