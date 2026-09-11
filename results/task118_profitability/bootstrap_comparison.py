"""Task 118D Part 3 -- issuer-block bootstrap comparison, A vs B (primary,
two independent disjoint populations) and A vs C (secondary, C = A union B,
shared observations preserved via joint resampling, not treated as
independent). Estimand: per-trade net expectancy (20bps convention),
matching Task 118B's corrected protocol. Seed fixed for reproducibility.
"""
from __future__ import annotations
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parent
REC = OUT / "reconciliation"
SEED = 118118
REPS = 5000


def load_trades(tag: str) -> list[dict]:
    if tag == "A":
        rows = list(csv.DictReader(open(REC / "trades.csv")))
        return [{"symbol": r["symbol"], "net_return_20bps": float(r["net_return_pct"]) / 100.0}
                for r in rows]
    rows = list(csv.DictReader(open(REC / f"trades_{tag}.csv")))
    return [{"symbol": r["symbol"], "net_return_20bps": float(r["net_return_20bps"])}
            for r in rows]


def issuer_blocks(trades: list[dict]) -> dict[str, list[float]]:
    d: defaultdict[str, list[float]] = defaultdict(list)
    for t in trades:
        d[t["symbol"]].append(t["net_return_20bps"])
    return dict(d)


def block_bootstrap_mean(blocks: dict[str, list[float]], rng: random.Random) -> float:
    names = list(blocks.keys())
    n = len(names)
    draw = [names[rng.randrange(n)] for _ in range(n)]
    vals = [v for name in draw for v in blocks[name]]
    return sum(vals) / len(vals) if vals else float("nan")


def ci(vals: list[float], lo=2.5, hi=97.5) -> tuple[float, float]:
    s = sorted(vals)
    n = len(s)
    return s[int(n * lo / 100)], s[min(n - 1, int(n * hi / 100))]


def main() -> int:
    A = load_trades("A")
    B = load_trades("B")
    C = load_trades("C")

    blocksA = issuer_blocks(A)
    blocksB = issuer_blocks(B)
    blocksC = issuer_blocks(C)

    print(f"A: n_trades={len(A)} n_issuer_blocks={len(blocksA)} -> {sorted(blocksA)}")
    print(f"B: n_trades={len(B)} n_issuer_blocks={len(blocksB)}")
    print(f"C: n_trades={len(C)} n_issuer_blocks={len(blocksC)}")

    rngA = random.Random(SEED)
    rngB = random.Random(SEED + 1)
    meansA = [block_bootstrap_mean(blocksA, rngA) for _ in range(REPS)]
    meansB = [block_bootstrap_mean(blocksB, rngB) for _ in range(REPS)]
    diff_AB = [a - b for a, b in zip(meansA, meansB)]

    # ---- A vs C: joint resampling preserving the nesting (C = A union B) ----
    C_names = list(blocksC.keys())
    A_name_set = set(blocksA.keys())
    nC = len(C_names)
    rngC = random.Random(SEED + 2)
    meansC_joint = []
    meansA_within_C = []
    for _ in range(REPS):
        draw = [C_names[rngC.randrange(nC)] for _ in range(nC)]
        all_vals = [v for name in draw for v in blocksC[name]]
        meansC_joint.append(sum(all_vals) / len(all_vals) if all_vals else float("nan"))
        a_vals = [v for name in draw if name in A_name_set for v in blocksC[name]]
        meansA_within_C.append(sum(a_vals) / len(a_vals) if a_vals else float("nan"))
    valid = [(a, c) for a, c in zip(meansA_within_C, meansC_joint) if a == a]  # drop NaN (A undrawn)
    diff_AC = [a - c for a, c in valid]

    def summarize(name, vals):
        m = sum(vals) / len(vals)
        lo, hi = ci(vals)
        return {"mean": m, "ci95": [lo, hi], "n_reps": len(vals)}

    results = {
        "seed": SEED, "repetitions": REPS, "resampling_unit": "issuer (block bootstrap)",
        "estimand": "per-trade net expectancy, 20bps round-trip cost convention",
        "A": {"n_trades": len(A), "n_issuer_blocks": len(blocksA),
              "point_mean": sum(t["net_return_20bps"] for t in A) / len(A),
              "bootstrap": summarize("A", meansA)},
        "B": {"n_trades": len(B), "n_issuer_blocks": len(blocksB),
              "point_mean": sum(t["net_return_20bps"] for t in B) / len(B),
              "bootstrap": summarize("B", meansB)},
        "C": {"n_trades": len(C), "n_issuer_blocks": len(blocksC),
              "point_mean": sum(t["net_return_20bps"] for t in C) / len(C),
              "bootstrap": summarize("C", meansC_joint)},
        "diff_A_minus_B_independent_resampling": summarize("A-B", diff_AB),
        "diff_A_minus_C_joint_resampling_valid_reps": summarize("A-C", diff_AC),
        "caveat_A_low_block_count": (
            f"Population A has only {len(blocksA)} distinct issuer blocks (one, MSTR, "
            f"contributing 4/10 trades) -- a 6-block bootstrap has very few distinct "
            f"achievable resample configurations; treat A's own interval, and any "
            f"A-involving difference, as indicative only, not a well-powered inference."
        ),
    }
    (REC / "bootstrap_comparison.json").write_text(json.dumps(results, indent=2, default=str))
    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
