"""Task 118F Part 4 -- ONE exploratory volatility-return test.

PREDECLARED PROTOCOL (written before any result below is computed):
- Feature: 20-trading-day realized volatility (annualized %, std of daily
  log returns * sqrt(252) * 100) of the traded issuer's own price series,
  using ONLY bars strictly BEFORE that TRADE's own entry date (per-trade,
  not per-issuer-first-entry -- a repeat issuer's later trade uses ITS OWN
  pre-entry window). Source: the same frozen local daily-bar CSVs used
  throughout Task 118.
- Primary estimand: the linear association between this pre-entry
  volatility feature (continuous, untransformed) and the trade's own net
  return (20bps convention, already published per-trade figures) --
  reported as an OLS slope (return per +1 percentage-point of annualized
  volatility) with an issuer-block bootstrap CI (5000 reps, seed 118118,
  SAME seed family as every other Task 118D/E resampling).
- Dependence treatment: issuer-block bootstrap (resample whole issuers,
  refit OLS each resample) -- repeated-issuer trades are never treated as
  independent observations.
- A and B reported SEPARATELY as primary (avoiding a within-population
  claim from a between-population artifact); a pooled fit is reported
  only as a secondary, explicitly-labelled check.
- Missing data: a trade whose issuer lacks >=20 trading days of prior
  history is excluded and named, not imputed.
- Sensitivity: (a) drop-MSTR (A's largest single-issuer weight) with the
  full population retained as primary; (b) month-of-entry time-block
  bootstrap as an alternative dependence assumption (mirrors Task 118E's
  predeclared sensitivity).
- These are already-inspected data (the SAME A/B/C trades already
  published) -- every result below is EXPLORATORY, not a fresh holdout.
"""
from __future__ import annotations
import csv
import json
import math
import random
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO_DATA = Path("C:/workspace/TalonX/results")
OUT = Path(__file__).resolve().parent
REC = OUT / "reconciliation"
SEED = 118118
REPS = 5000
WINDOW_TD = 20

BAR_DIRS = [REPO_DATA / "task95g_broad_cross_sectional/_daily",
            REPO_DATA / "task107a_form4_feasibility/_prices"]


def load_closes(symbol: str) -> list[tuple[date, float]]:
    out: dict[date, float] = {}
    for d in BAR_DIRS:
        p = d / f"{symbol}.csv"
        if not p.exists():
            continue
        with open(p) as f:
            for row in csv.DictReader(f):
                try:
                    dt = date.fromisoformat(row["date"][:10])
                    out[dt] = float(row["close"])
                except (KeyError, ValueError):
                    continue
    return sorted(out.items())


_CLOSE_CACHE: dict[str, list[tuple[date, float]]] = {}


def pre_entry_vol_pct(symbol: str, entry: date) -> float | None:
    if symbol not in _CLOSE_CACHE:
        _CLOSE_CACHE[symbol] = load_closes(symbol)
    prior = [(d, c) for d, c in _CLOSE_CACHE[symbol] if d < entry]
    if len(prior) < WINDOW_TD + 1:
        return None
    window = prior[-(WINDOW_TD + 1):]
    rets = [math.log(window[i][1] / window[i - 1][1]) for i in range(1, len(window))
            if window[i - 1][1] > 0 and window[i][1] > 0]
    if len(rets) < WINDOW_TD - 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
    return math.sqrt(var) * math.sqrt(252) * 100.0


def load_trade_records(tag: str) -> list[dict]:
    """Per-trade record: symbol, entry_date, net_return_20bps (fraction),
    pre_entry_vol_pct. Uses the SAME episode->entry-date join as Task
    118D/E."""
    if tag == "A":
        con = sqlite3.connect(f"file:{OUT / 'replay_v2_lane.db'}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(f"file:{OUT / f'replay_v2_lane_{tag}.db'}?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("SELECT episode_id, symbol, eligible_entry_session FROM processed_episodes WHERE disposition='ENTERED'")
    entry_map = {eid: (sym, date.fromisoformat(sess)) for eid, sym, sess in cur.fetchall()}

    trades_path = REC / "trades.csv" if tag == "A" else REC / f"trades_{tag}.csv"
    rows = list(csv.DictReader(open(trades_path)))
    out = []
    missing = []
    for r in rows:
        eid = r["episode_id"]
        sym, entry_date = entry_map[eid]
        vol = pre_entry_vol_pct(sym, entry_date)
        net_ret = float(r["net_return_pct"]) / 100.0 if tag == "A" else float(r["net_return_20bps"])
        if vol is None:
            missing.append((sym, str(entry_date)))
            continue
        out.append({"episode_id": eid, "symbol": sym, "entry_date": str(entry_date),
                    "pre_entry_vol_pct": vol, "net_return_20bps": net_ret})
    return out, missing


def ols_slope(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Simple OLS y = a + b*x. Returns (intercept, slope)."""
    n = len(points)
    if n < 2:
        return (float("nan"), float("nan"))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    sxy = sum((x - xbar) * (y - ybar) for x, y in points)
    sxx = sum((x - xbar) ** 2 for x in xs)
    if sxx == 0:
        return (ybar, float("nan"))
    b = sxy / sxx
    a = ybar - b * xbar
    return (a, b)


def issuer_blocks(trades: list[dict]) -> dict[str, list[dict]]:
    d: defaultdict[str, list[dict]] = defaultdict(list)
    for t in trades:
        d[t["symbol"]].append(t)
    return dict(d)


def month_blocks(trades: list[dict]) -> dict[str, list[dict]]:
    d: defaultdict[str, list[dict]] = defaultdict(list)
    for t in trades:
        d[t["entry_date"][:7]].append(t)
    return dict(d)


def block_bootstrap_slope(blocks: dict[str, list[dict]], rng: random.Random) -> float:
    names = list(blocks.keys())
    n = len(names)
    draw = [names[rng.randrange(n)] for _ in range(n)]
    pts = [(t["pre_entry_vol_pct"], t["net_return_20bps"]) for name in draw for t in blocks[name]]
    return ols_slope(pts)[1]


def ci(vals, lo=2.5, hi=97.5):
    s = sorted(v for v in vals if v == v)  # drop NaN
    n = len(s)
    if n == 0:
        return (float("nan"), float("nan"))
    return s[int(n * lo / 100)], s[min(n - 1, int(n * hi / 100))]


def analyze(name: str, trades: list[dict], seed_offset: int) -> dict:
    pts = [(t["pre_entry_vol_pct"], t["net_return_20bps"]) for t in trades]
    a, b = ols_slope(pts)
    blocks_issuer = issuer_blocks(trades)
    blocks_month = month_blocks(trades)
    rng1 = random.Random(SEED + seed_offset)
    rng2 = random.Random(SEED + seed_offset + 1)
    slopes_issuer = [block_bootstrap_slope(blocks_issuer, rng1) for _ in range(REPS)]
    slopes_month = [block_bootstrap_slope(blocks_month, rng2) for _ in range(REPS)]
    return {
        "n_trades": len(trades), "n_issuer_blocks": len(blocks_issuer), "n_month_blocks": len(blocks_month),
        "intercept": a, "slope_point_estimate": b,
        "slope_ci95_issuer_block": list(ci(slopes_issuer)),
        "slope_ci95_month_block": list(ci(slopes_month)),
    }


def main() -> int:
    A, A_missing = load_trade_records("A")
    B, B_missing = load_trade_records("B")
    print(f"A: {len(A)} trades usable, {len(A_missing)} missing pre-entry history: {A_missing}")
    print(f"B: {len(B)} trades usable, {len(B_missing)} missing pre-entry history (count={len(B_missing)})")

    result = {
        "protocol": "see module docstring -- predeclared before computation",
        "feature": "20-trading-day pre-entry realized volatility, annualized %",
        "estimand": "OLS slope of net_return_20bps on pre_entry_vol_pct",
        "seed": SEED, "repetitions": REPS,
        "A_primary": analyze("A", A, 200),
        "B_primary": analyze("B", B, 300),
        "A_missing_history": A_missing,
        "B_missing_history_count": len(B_missing),
    }

    # pooled (secondary, explicitly labelled)
    pooled = A + B
    result["pooled_secondary_do_not_interpret_as_within_population"] = analyze("pooled", pooled, 400)

    # concentration sensitivity: drop MSTR from A, full population stays primary above
    A_no_mstr = [t for t in A if t["symbol"] != "MSTR"]
    result["A_sensitivity_drop_MSTR"] = analyze("A_no_MSTR", A_no_mstr, 500)

    (REC / "volatility_return_test.json").write_text(json.dumps(result, indent=2, default=str))
    with open(REC / "volatility_return_trades.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["episode_id", "symbol", "entry_date", "pre_entry_vol_pct", "net_return_20bps"])
        w.writeheader()
        for pop, rows in (("A", A), ("B", B)):
            for r in rows:
                w.writerow({**r, "symbol": f"{pop}:{r['symbol']}"})

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
