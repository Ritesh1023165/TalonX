"""
TASK 130B Part 9 -- full corrected economics on the durable replay's
own closed trades. Reuses `compute_stats` (unmodified import from
task130a_identity_and_stats.py) unchanged -- same bootstraps, same
materiality threshold, same original trade-count-ranked AND
supplemental P&L-ranked concentration tests, same calendar half-year
stability breakdown.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_ROOT / "research" / "scripts"))

OUT = RESEARCH_ROOT / "results" / "task130b_durable_replay"


def main() -> int:
    from task130a_identity_and_stats import compute_stats

    closed = json.loads((OUT / "closed_trades.json").read_text())
    stats = compute_stats(closed)
    (OUT / "corrected_stats.json").write_text(json.dumps(stats, indent=2, default=str))
    print(json.dumps(stats, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
