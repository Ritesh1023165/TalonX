"""Task75B PREFLIGHT -- RAW harness parity (read-only). Re-runs the FROZEN research/task75_v1/strategy.py::evaluate()
on the ARCHIVED Task74B/Task75A RAW DEVELOPMENT bytes (loaded exactly as research/scripts/task74b_run_discovery.py
did), verifies every archived dataset hash first, and reproduces the anchor: trades, gross mean and both clustered
bootstrap intervals with the ORIGINAL call (research.task71_lib.diagnostics.cell_summary -> bootstrap_ci_clustered,
n_resamples=2000, seed 670067, day_col=decision_day) plus the task-specified 10,000-resample variant.
Never downloads anything; never touches a validation/replication range (the guard checks every slice).
usage: python -m research.task75b_preflight.raw_parity [ARCHIVE_ROOT]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.task67a_lib.research_stats import DEFAULT_SEED, bootstrap_ci_clustered  # noqa: E402
from research.task71_lib.diagnostics import cell_summary  # noqa: E402
from research.task75_v1 import contracts as C  # noqa: E402
from research.task75_v1.strategy import evaluate  # noqa: E402
from research.task75b_preflight.holdout import HoldoutGuard  # noqa: E402
from talonx_backtest.data import load_ohlcv_csv, load_ohlcv_directory  # noqa: E402
from talonx_backtest.reproducibility import get_dataset_hash  # noqa: E402

ARCHIVE_DEFAULT = Path("C:/workspace/TalonX-alpha-phenomenon-discovery")
MANIFEST = ROOT / "results" / "task74_alpha_discovery_v2" / "development_data_manifest.json"
CELL = ROOT / "results" / "task74_alpha_discovery_v2" / "cluster_bootstrap.csv"
SPY_DIR_OVERRIDE = {"2026_q3_f6_era": "data/historical_1m/task67a_benchmarks"}
ANCHOR = {"n_trades": 1000, "gross_mean_pct": 0.6070373392207478}
FLOAT_TOL = 1e-12


def anchor_cis() -> dict:
    df = pd.read_csv(CELL)
    r = df[(df.family == "FAMILY_B_MULTIDAY") & (df.hypothesis == "REVERSAL") & (df.direction == "SHORT")
           & (df.threshold_band == "loose") & (df.horizon_label == "3D")].iloc[0]
    return {"symbol": [float(r.ci_low_by_symbol), float(r.ci_high_by_symbol)],
            "day": [float(r.ci_low_by_day), float(r.ci_high_by_day)], "n_trades": int(r.n_trades)}


def load_slice(archive: Path, label: str, data_dir: str) -> pd.DataFrame:
    d = archive / data_dir
    if label not in SPY_DIR_OVERRIDE:
        return load_ohlcv_directory(d, symbols=C.UNIVERSE + [C.MARKET_SYMBOL])
    stocks = load_ohlcv_directory(d, symbols=C.UNIVERSE)
    spy = load_ohlcv_csv(archive / SPY_DIR_OVERRIDE[label] / "SPY.csv", symbol="SPY")
    return pd.concat([stocks, spy], ignore_index=True)


def run_ledger(slices: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for label, bars in slices.items():
        led = evaluate(bars)
        led["slice"] = label
        frames.append(led)
    return pd.concat(frames, ignore_index=True)


def summarize(trades: pd.DataFrame) -> dict:
    s = cell_summary(trades, day_col="decision_day")                  # the ORIGINAL anchor call (2,000 resamples)
    v, sym, ent = (trades["gross_return_pct"].to_numpy(), trades["symbol"].to_numpy(),
                   trades["entry_day"].astype(str).to_numpy())
    b_sym = bootstrap_ci_clustered(v, sym, n_resamples=10_000, ci_level=0.95, seed=DEFAULT_SEED)
    b_day = bootstrap_ci_clustered(v, ent, n_resamples=10_000, ci_level=0.95, seed=DEFAULT_SEED)
    return {"n_trades": int(len(trades)), "n_symbols": int(trades.symbol.nunique()),
            "gross_mean_pct": float(trades["gross_return_pct"].mean()),
            "original_2000": {"symbol": [s["bootstrap_gross_by_symbol"]["ci_low"], s["bootstrap_gross_by_symbol"]["ci_high"]],
                              "day": [s["bootstrap_gross_by_day"]["ci_low"], s["bootstrap_gross_by_day"]["ci_high"]]},
            "spec_10000": {"symbol": [b_sym.ci_low, b_sym.ci_high], "entry_day": [b_day.ci_low, b_day.ci_high]},
            "decision_to_entry_day_bijective": bool(trades.groupby("decision_day")["entry_day"].nunique().max() == 1
                                                    and trades.groupby("entry_day")["decision_day"].nunique().max() == 1),
            "seed": DEFAULT_SEED}


def main(archive: Path = ARCHIVE_DEFAULT) -> dict:
    man = json.loads(MANIFEST.read_text())["slices"]
    guard = HoldoutGuard.load()
    hashes = {}
    for label, s in man.items():
        guard.check_range(s["start"], s["end"], layer="LOAD")
        h = get_dataset_hash(archive / s["data_dir"].replace("\\", "/"), C.UNIVERSE)
        hashes[label] = {"expected": s["dataset_hash_sha256"], "actual": h, "match": h == s["dataset_hash_sha256"]}
    if not all(x["match"] for x in hashes.values()):
        return {"RAW_PARITY": "FAIL", "reason": "ARCHIVED_DATASET_HASH_MISMATCH", "hashes": hashes}
    slices = {label: load_slice(archive, label, s["data_dir"].replace("\\", "/")) for label, s in man.items()}
    led = run_ledger(slices)
    trades = led[led["data_ready"] == True].copy()  # noqa: E712
    res = summarize(trades)
    anc = anchor_cis()
    orig = res["original_2000"]
    checks = {"n_trades": res["n_trades"] == ANCHOR["n_trades"] == anc["n_trades"],
              "gross": abs(res["gross_mean_pct"] - ANCHOR["gross_mean_pct"]) <= FLOAT_TOL,
              "symbol_ci": all(abs(a - b) <= FLOAT_TOL for a, b in zip(orig["symbol"], anc["symbol"])),
              "day_ci": all(abs(a - b) <= FLOAT_TOL for a, b in zip(orig["day"], anc["day"]))}
    out = {"RAW_PARITY": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "hashes": hashes,
           "anchor_recorded": {**ANCHOR, "symbol_ci": anc["symbol"], "day_ci": anc["day"],
                               "bootstrap_call": "cell_summary -> bootstrap_ci_clustered(n_resamples=2000, seed=670067)"},
           "reproduced": res, "float_tolerance": FLOAT_TOL, "archive_root": str(archive)}
    outdir = ROOT / "results" / "task75b_preflight"
    outdir.mkdir(parents=True, exist_ok=True)
    trades.to_csv(outdir / "raw_development_trades.csv", index=False)
    (outdir / "raw_parity.json").write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ARCHIVE_DEFAULT), indent=1, default=str))
