"""Task 66B-PREP operator commands for the NORMAL run_talonx.py
application's preflight -- read-only, mirrors talonx_piv/cli.py's
`preflight` subcommand shape but checks a different (wider) runtime and
never enables/starts anything itself.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*args, **kwargs): return False

from .comparator import build_comparator_report
from .preflight import FULL_APP_E2E_READY, FullAppPreflight

DEFAULT_REPORT_PATH = Path("results/task66b_prep/full_app_preflight.json")
DEFAULT_COMPARATOR_PATH = Path("results/task66b_prep/comparator_smoke_report.json")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="TalonX full-application (run_talonx.py) operator preflight -- read-only")
    sub = root.add_subparsers(dest="command", required=True)
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--expected-sha", default=None)
    preflight.add_argument("--out", default=str(DEFAULT_REPORT_PATH))
    comparator = sub.add_parser("comparator-smoke")
    comparator.add_argument("--piv-events", required=True)
    comparator.add_argument("--date", default=None, help="YYYY-MM-DD, defaults to today (UTC)")
    comparator.add_argument("--out", default=str(DEFAULT_COMPARATOR_PATH))
    return root


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parser().parse_args(argv)
    if args.command == "preflight":
        status, checks = FullAppPreflight(expected_sha=args.expected_sha).run()
        FullAppPreflight.write_report(Path(args.out), status, checks)
        print(status)
        return 0 if status == FULL_APP_E2E_READY else 2
    if args.command == "comparator-smoke":
        date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        report = build_comparator_report(Path(args.piv_events), date_str)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(report["classification_counts"], sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
