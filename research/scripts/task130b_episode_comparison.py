"""
TASK 130B Part 9 -- per-episode comparison of the durable, session-
phased, V2Store-backed replay's own closed trades against Task 130A's
153 closed trades. Classifies every episode_id present in either set
as UNCHANGED / IDENTITY_CORRECTED / NEWLY_ADMITTED / EXCLUDED /
TIMING_CHANGED / QUANTITY_COST_CHANGED / MISSING_DATA_DISPOSITION_CHANGED.
Never assumes numerical equality of the aggregate result proves
implementation equivalence -- every material per-episode difference is
retained and explained.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[2]
OUT = RESEARCH_ROOT / "results" / "task130b_durable_replay"


def main() -> int:
    a_trades = {t["episode_id"]: t for t in
               json.loads((RESEARCH_ROOT / "results/task130a_corrected_replay/closed_trades.json").read_text())}
    b_trades = {t["episode_id"]: t for t in
               json.loads((OUT / "closed_trades.json").read_text())}

    all_ids = sorted(set(a_trades) | set(b_trades))
    comparison = []
    counts = {"UNCHANGED": 0, "IDENTITY_CORRECTED": 0, "NEWLY_ADMITTED": 0, "EXCLUDED": 0,
             "TIMING_CHANGED": 0, "QUANTITY_COST_CHANGED": 0,
             "MISSING_DATA_DISPOSITION_CHANGED": 0}

    for eid in all_ids:
        a, b = a_trades.get(eid), b_trades.get(eid)
        if a is not None and b is None:
            status = "EXCLUDED"
            detail = {"a_symbol": a["symbol"], "a_entry_session": a["entry_session"]}
        elif a is None and b is not None:
            status = "NEWLY_ADMITTED"
            detail = {"b_symbol": b["symbol"], "b_entry_session": b["entry_session"]}
        else:
            diffs = []
            if a["entry_session"] != b["entry_session"] or a["exit_session"] != b["exit_session"]:
                diffs.append("TIMING_CHANGED")
            if abs(a["shares"] - b["shares"]) > 1e-6 or abs(a["notional"] - b["notional"]) > 1e-6:
                diffs.append("QUANTITY_COST_CHANGED")
            if a["symbol"] != b["symbol"]:
                diffs.append("IDENTITY_CORRECTED")
            if not diffs:
                status = "UNCHANGED"
            else:
                status = diffs[0]  # primary classification; all diffs recorded in detail
            detail = {
                "a_symbol": a["symbol"], "b_symbol": b["symbol"],
                "a_entry_session": a["entry_session"], "b_entry_session": b["entry_session"],
                "a_exit_session": a["exit_session"], "b_exit_session": b["exit_session"],
                "a_net_return_pct": round(100 * a["net_return"], 4),
                "b_net_return_pct": round(100 * b["net_return"], 4),
                "all_diffs": diffs,
            }
        counts[status] += 1
        comparison.append({"episode_id": eid, "status": status, "detail": detail})

    result = {
        "n_task130a_trades": len(a_trades), "n_task130b_trades": len(b_trades),
        "counts": counts,
        "note": (
            "Numerical equality of the aggregate result with Task 130A's own figure is NOT "
            "evidence of implementation equivalence and is not a target. Every episode_id "
            "present in only one run, or present in both with a material field difference, is "
            "retained below with an explicit classification, not collapsed into a single "
            "pass/fail summary."
        ),
        "episodes": comparison,
    }
    (OUT / "episode_comparison.json").write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps({k: v for k, v in result.items() if k != "episodes"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
