"""
talonx_ingest.intelligence.service.service
==========================================
CLI entrypoint for the continuous SEC intelligence ingest service
(Phase 21).

    python -m talonx_ingest.intelligence.service scope
    python -m talonx_ingest.intelligence.service backfill [--symbols AAPL,MSFT]
    python -m talonx_ingest.intelligence.service poll [--duration 3600] [--max-cycles 5] [--with-backfill]
    python -m talonx_ingest.intelligence.service once [--symbols AAPL]
    python -m talonx_ingest.intelligence.service status
    python -m talonx_ingest.intelligence.service replay --cik 320193 --accession 0000320193-25-000079 --symbol AAPL

Never starts the quant loop / Original / PIV / any order path. Delivery is
dry-run (enqueue-only) by default; ``--send`` is refused unless Telegram is
configured AND ``--i-understand-external-send`` is also passed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone

from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.runner import IntelligenceService
from talonx_ingest.intelligence.service.singleton import SingletonLock

logger = logging.getLogger("talonx_ingest.intelligence.service")

_EXCLUSIVE_MODES = {"backfill", "poll", "once", "replay"}


def _build_config(args) -> ServiceConfig:
    cfg = ServiceConfig.from_env()
    over: dict = {}
    if args.ledger_path:
        over["ledger_path"] = args.ledger_path
    if args.state_dir:
        from pathlib import Path

        over["state_dir"] = Path(args.state_dir)
    if args.history_days is not None:
        over["history_days"] = args.history_days
    if getattr(args, "include_paused", False):
        over["include_paused"] = True
    if getattr(args, "send", False):
        over["dry_run_delivery"] = False
    return cfg.with_overrides(**over) if over else cfg


def _symbols(args) -> list[str] | None:
    raw = getattr(args, "symbols", None)
    if not raw:
        return None
    return [s.strip().upper() for s in raw.replace(";", ",").split(",") if s.strip()]


async def _run(args) -> int:
    cfg = _build_config(args)

    if getattr(args, "send", False) and not getattr(args, "i_understand_external_send", False):
        print("refusing --send without --i-understand-external-send", file=sys.stderr)
        return 2

    if args.mode == "status":
        svc = IntelligenceService(cfg)
        await svc.open(with_network=not args.offline)
        try:
            print(json.dumps(svc.status(), indent=2, default=str))
        finally:
            await svc.close()
        return 0

    if args.mode == "scope":
        svc = IntelligenceService(cfg)
        await svc.open(with_network=not args.offline)
        try:
            print(json.dumps(svc.scope.as_dict(), indent=2, default=str))
        finally:
            await svc.close()
        return 0

    if args.mode == "replay":
        from talonx_ingest.intelligence.service.replay import replay_filing

        trace = await replay_filing(
            cik=str(args.cik), accession=args.accession, symbol=args.symbol.upper(),
            ledger_path=cfg.ledger(), config=cfg,
        )
        print(json.dumps(trace, indent=2, default=str))
        return 0 if "error" not in trace else 1

    # -- exclusive long-running / mutating modes: take the singleton lock --
    lock = SingletonLock(cfg.lock_path())
    if not lock.acquire(force=args.force_lock):
        info = lock.read()
        print(
            f"another intelligence service holds the lock (pid={info.pid if info else '?'} "
            f"host={info.host if info else '?'}); use --force-lock to override",
            file=sys.stderr,
        )
        return 3

    svc = IntelligenceService(cfg)
    try:
        await svc.open(with_network=True)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, svc.request_stop)
            except (NotImplementedError, ValueError):
                signal.signal(sig, lambda *_a: svc.request_stop())

        if args.mode == "backfill":
            report = await svc.run_backfill(symbols=_symbols(args))
            print(json.dumps(report.as_dict(), indent=2, default=str))
        elif args.mode == "once":
            out = await svc.run_once(symbols=_symbols(args), backfill=not args.no_backfill)
            print(json.dumps(out, indent=2, default=str))
        elif args.mode == "poll":
            out = await svc.run_poll_loop(
                duration_seconds=args.duration,
                max_cycles=args.max_cycles,
                with_backfill=args.with_backfill,
            )
            print(json.dumps(out, indent=2, default=str))
        return 0
    finally:
        await svc.close()
        lock.release()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="talonx-intel-service", description=__doc__)
    p.add_argument("mode", choices=["scope", "backfill", "poll", "once", "status", "replay"])
    p.add_argument("--ledger-path", default=None)
    p.add_argument("--state-dir", default=None)
    p.add_argument("--history-days", type=int, default=None)
    p.add_argument("--symbols", default=None, help="comma-separated symbol subset")
    p.add_argument("--include-paused", action="store_true")
    p.add_argument("--offline", action="store_true",
                   help="status/scope only: use the cached CIK directory, no network")
    p.add_argument("--force-lock", action="store_true")
    p.add_argument("--json", action="store_true", help="(reserved) machine output")
    # poll
    p.add_argument("--duration", type=float, default=None, help="poll: seconds to run")
    p.add_argument("--max-cycles", type=int, default=None, help="poll: stop after N cycles")
    p.add_argument("--with-backfill", action="store_true",
                   help="poll: advance backfill one symbol per cycle (after the live cycle)")
    # once
    p.add_argument("--no-backfill", action="store_true", help="once: skip the backfill pass")
    # replay
    p.add_argument("--cik", default=None)
    p.add_argument("--accession", default=None)
    p.add_argument("--symbol", default=None)
    # delivery
    p.add_argument("--send", action="store_true",
                   help="actually drain the outbox to Telegram (refused without the ack flag)")
    p.add_argument("--i-understand-external-send", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args(argv)
    if args.mode == "replay" and not (args.cik and args.accession and args.symbol):
        print("replay requires --cik --accession --symbol", file=sys.stderr)
        return 2
    started = datetime.now(timezone.utc)
    try:
        rc = asyncio.run(_run(args))
    except KeyboardInterrupt:
        rc = 130
    logger.info("mode=%s finished rc=%d in %.1fs", args.mode, rc,
                (datetime.now(timezone.utc) - started).total_seconds())
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
