"""Task 118E Part 4 -- ONE predeclared time-dependence sensitivity check
on the A-vs-B comparison: resample by calendar MONTH-of-entry instead of
by issuer, to check whether temporal clustering (overlapping holding
periods, shared market-regime shocks) changes the conclusion from the
issuer-block bootstrap already published in TASK118D_SCOPE_COMPARISON.md.
Predeclared here, before inspection of its result, as a single fixed
method (month-of-entry block bootstrap, same seed/rep convention as the
issuer-block analysis) -- not chosen after seeing which method looks
better.
"""
from __future__ import annotations
import csv
import json
import random
import sqlite3
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent
REC = OUT / "reconciliation"
SEED = 118118
REPS = 5000


def load_entry_months(tag: str) -> dict[str, str]:
    con = sqlite3.connect(f"file:{OUT / f'replay_v2_lane_{tag}.db'}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("SELECT episode_id, eligible_entry_session FROM processed_episodes WHERE disposition='ENTERED'")
    return {eid: sess[:7] for eid, sess in cur.fetchall()}  # YYYY-MM


def load_trades_with_month(tag: str) -> list[dict]:
    if tag == "A":
        con = sqlite3.connect(f"file:{OUT / 'replay_v2_lane.db'}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("SELECT episode_id, eligible_entry_session FROM processed_episodes WHERE disposition='ENTERED'")
        months = {eid: sess[:7] for eid, sess in cur.fetchall()}
        rows = list(csv.DictReader(open(REC / "trades.csv")))
        return [{"episode_id": r["episode_id"], "month": months.get(r["episode_id"], "UNKNOWN"),
                "net_return_20bps": float(r["net_return_pct"]) / 100.0} for r in rows]
    months = load_entry_months(tag)
    rows = list(csv.DictReader(open(REC / f"trades_{tag}.csv")))
    return [{"episode_id": r["episode_id"], "month": months.get(r["episode_id"], "UNKNOWN"),
            "net_return_20bps": float(r["net_return_20bps"])} for r in rows]


def month_blocks(trades: list[dict]) -> dict[str, list[float]]:
    d: defaultdict[str, list[float]] = defaultdict(list)
    for t in trades:
        d[t["month"]].append(t["net_return_20bps"])
    return dict(d)


def block_bootstrap_mean(blocks: dict[str, list[float]], rng: random.Random) -> float:
    names = list(blocks.keys())
    n = len(names)
    draw = [names[rng.randrange(n)] for _ in range(n)]
    vals = [v for name in draw for v in blocks[name]]
    return sum(vals) / len(vals) if vals else float("nan")


def ci(vals, lo=2.5, hi=97.5):
    s = sorted(vals)
    n = len(s)
    return s[int(n * lo / 100)], s[min(n - 1, int(n * hi / 100))]


def main() -> int:
    A = load_trades_with_month("A")
    B = load_trades_with_month("B")
    assert all(t["month"] != "UNKNOWN" for t in A), "A: unmatched episode_id -> month lookup failed"
    assert all(t["month"] != "UNKNOWN" for t in B), "B: unmatched episode_id -> month lookup failed"

    blocksA = month_blocks(A)
    blocksB = month_blocks(B)
    print(f"A: {len(A)} trades across {len(blocksA)} distinct entry-months: {sorted(blocksA)}")
    print(f"B: {len(B)} trades across {len(blocksB)} distinct entry-months")

    rngA = random.Random(SEED + 100)
    rngB = random.Random(SEED + 101)
    meansA = [block_bootstrap_mean(blocksA, rngA) for _ in range(REPS)]
    meansB = [block_bootstrap_mean(blocksB, rngB) for _ in range(REPS)]
    diff = [a - b for a, b in zip(meansA, meansB)]

    result = {
        "method": "month-of-entry block bootstrap (predeclared sensitivity to the "
                  "issuer-block bootstrap in TASK118D_SCOPE_COMPARISON.md)",
        "seed": SEED, "repetitions": REPS,
        "A_time_blocks": len(blocksA), "B_time_blocks": len(blocksB),
        "A_ci95": list(ci(meansA)), "A_mean": sum(meansA)/len(meansA),
        "B_ci95": list(ci(meansB)), "B_mean": sum(meansB)/len(meansB),
        "diff_A_minus_B_ci95": list(ci(diff)), "diff_A_minus_B_mean": sum(diff)/len(diff),
    }
    (REC / "time_block_sensitivity.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
