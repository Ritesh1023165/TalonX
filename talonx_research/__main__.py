"""
talonx_research CLI (Task 115.H).

  python -m talonx_research validate --strategy INSIDER_BUY_CLUSTER_V2@1 \
      --start 2024-09-01 --end 2026-09-01 --primary-cost-bps 20 \
      [--data-root C:/workspace/TalonX] [--out results/task115_validation_framework/<run>]

  python -m talonx_research registry [--registry PATH]      # list versions
  python -m talonx_research fingerprint                      # print V2 semantic fingerprint

Deterministic: same inputs -> byte-identical evidence directory.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def cmd_fingerprint(args) -> int:
    from talonx_research.versioning import v2_fingerprint
    print(v2_fingerprint())
    return 0


def cmd_registry(args) -> int:
    from talonx_research.versioning import StrategyRegistry, seed_known_versions
    reg = StrategyRegistry(args.registry or None)
    seed_known_versions(reg)
    for sv in reg.all():
        print(f"{sv.id:28} fp={sv.fingerprint}  state={sv.lifecycle_state:16} "
              f"promotion={sv.promotion_status}  validation={sv.validation_status}")
    return 0


def cmd_validate(args) -> int:
    from talonx_research import PRIMARY_COST_BPS
    from talonx_research.validation import run_validation
    strat = args.strategy
    out = Path(args.out) if args.out else (
        _ROOT / "results" / "task115_validation_framework"
        / f"validate_{strat.replace('@', '_')}_{args.start}_{args.end}")
    res = run_validation(
        strategy_id=strat, start=args.start, end=args.end,
        primary_cost_bps=args.primary_cost_bps or PRIMARY_COST_BPS,
        data_root=Path(args.data_root) if args.data_root else None,
        out_dir=out, registry_path=Path(args.registry) if args.registry else None,
        do_replay=not args.no_replay)
    print(Path(out / "terminal_summary.txt").read_text())
    return 0 if res["verdict"] != "VALIDATION_FAIL" else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser("talonx_research")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate"); v.set_defaults(fn=cmd_validate)
    v.add_argument("--strategy", required=True, help="e.g. INSIDER_BUY_CLUSTER_V2@1")
    v.add_argument("--start", required=True)
    v.add_argument("--end", required=True)
    v.add_argument("--primary-cost-bps", type=int, default=20)
    v.add_argument("--data-root", default="")
    v.add_argument("--out", default="")
    v.add_argument("--registry", default="")
    v.add_argument("--no-replay", action="store_true",
                   help="metrics-only (skip the chronological runtime replay)")

    r = sub.add_parser("registry"); r.set_defaults(fn=cmd_registry)
    r.add_argument("--registry", default="")

    f = sub.add_parser("fingerprint"); f.set_defaults(fn=cmd_fingerprint)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
