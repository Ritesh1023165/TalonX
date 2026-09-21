"""Read-only CLI for the comparison collector.

    python -m talonx_compare collect-once     # one passive pass over current state
    python -m talonx_compare status           # latest archived day + health
    python -m talonx_compare verify <date>    # re-hash and check an archived day
    python -m talonx_compare run              # the passive loop (not used by Task 83)

No subcommand mutates the Original or PIV pipelines. ``run`` only ever
SUBSCRIBES to their channels.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .archive import CompareArchive
from .collector import ComparisonCollector
from .config import CompareConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="talonx_compare", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect-once")
    sub.add_parser("status")
    v = sub.add_parser("verify")
    v.add_argument("date")
    r = sub.add_parser("run")
    r.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args(argv)

    cfg = CompareConfig()

    if args.cmd == "collect-once":
        result = ComparisonCollector(cfg).collect_once()
        print(json.dumps({
            "trading_date": result.trading_date,
            "manifest_written": result.manifest_written,
            "manifest_conflict": result.manifest_conflict,
            "original_appended": result.original_appended,
            "piv_appended": result.piv_appended,
            "duplicates_skipped": result.duplicates_skipped,
            "diagnostics": result.diagnostics,
            "divergences": result.divergences,
            "evidence_dir": result.evidence_dir,
            "skipped_reason": result.skipped_reason,
        }, indent=2, default=str))
        return 0

    if args.cmd == "status":
        print(json.dumps(CompareArchive(cfg).latest(), indent=2, default=str))
        return 0

    if args.cmd == "verify":
        payload = CompareArchive(cfg).day(args.date)
        print(json.dumps(payload.get("archive_integrity", {}), indent=2, default=str))
        return 0 if payload.get("archive_integrity", {}).get("file_hashes_ok") else 1

    if args.cmd == "run":
        from .runner import CollectorService

        service = CollectorService(cfg, interval_seconds=args.interval)
        try:
            asyncio.run(service.run())
        except KeyboardInterrupt:
            service.stop()
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
