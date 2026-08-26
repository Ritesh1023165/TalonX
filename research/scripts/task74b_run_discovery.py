"""Task74B -- runs Families A/B against the existing broadened DEVELOPMENT
pool (4 regime slices, reused unchanged from Task71), computes every
required diagnostic, writes all artifacts under
results/task74_alpha_discovery_v2/. DEVELOPMENT-only: every slice's date
range is checked against research.task74_alpha_discovery_v2.holdout_guard
before loading (blocks all of 2024). Family C is feasibility-only and
contributes zero outcome cells (see universe_expansion_feasibility.json).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from research.task67a_lib.research_stats import compute_mfe_mae  # noqa: E402
from research.task71_lib.diagnostics import cell_summary, cost_sensitivity_table, net_return  # noqa: E402
from research.task71_lib.features import add_session_columns  # noqa: E402
from research.task74_alpha_discovery_v2 import family_a_catalyst, family_b_multiday  # noqa: E402
from research.task74_alpha_discovery_v2.holdout_guard import DevelopmentOnlyGuard  # noqa: E402
from talonx_backtest.data import check_data_quality, load_ohlcv_csv, load_ohlcv_directory  # noqa: E402
from talonx_backtest.reproducibility import get_dataset_hash  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "task74_alpha_discovery_v2"
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX",
    "ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON",
    "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU", "NFLX", "PANW", "PEP",
    "QCOM", "REGN", "SBUX", "TXN", "VRTX",
]
UNIVERSE_PLUS_SPY = UNIVERSE + ["SPY"]
SLICES = [
    ("2026_q3_f6_era", ROOT / "data" / "historical_1m" / "task67a_development", "2026-05-15", "2026-08-14"),
    ("2025_q1_orpb_era", ROOT / "data" / "historical_1m" / "task71_development_2025q1", "2025-02-03", "2025-03-14"),
    ("2025_q3_fprc_era", ROOT / "data" / "historical_1m" / "task71_development_2025q3", "2025-06-02", "2025-07-11"),
    ("2025_q4_task46_56_era", ROOT / "data" / "historical_1m" / "task71_development_2025q4", "2025-10-27", "2025-12-05"),
]
# The 2026 summer slice (task67a_development) predates Family-C-era SPY
# downloads -- SPY for that exact date range lives in a separate directory
# (task67a_benchmarks), matching Task71's family_c_residual_momentum.py
# precedent of merging it in from there.
SPY_DIR_OVERRIDE = {"2026_q3_f6_era": ROOT / "data" / "historical_1m" / "task67a_benchmarks"}
guard = DevelopmentOnlyGuard()
for _, _, start, end in SLICES:
    guard.check(start, end)

CELL_COLS = ["family", "hypothesis", "direction", "threshold_band", "horizon_label"]


def build_manifest() -> None:
    manifest = {"role": "DEVELOPMENT (reused unchanged from Task71)", "slices": {}}
    total_bars, all_clean = 0, True
    quality = {}
    for label, data_dir, start, end in SLICES:
        spy_override = SPY_DIR_OVERRIDE.get(label)
        dataset_hash = get_dataset_hash(data_dir, UNIVERSE)
        per_symbol = {}
        for symbol in UNIVERSE:
            df = load_ohlcv_csv(data_dir / f"{symbol}.csv", symbol=symbol)
            report = check_data_quality(df, symbol=symbol)
            per_symbol[symbol] = {"rows": int(report.rows), "is_clean": bool(report.is_clean)}
        spy_dir = spy_override if spy_override is not None else data_dir
        spy_df = load_ohlcv_csv(spy_dir / "SPY.csv", symbol="SPY")
        spy_report = check_data_quality(spy_df, symbol="SPY")
        per_symbol["SPY"] = {"rows": int(spy_report.rows), "is_clean": bool(spy_report.is_clean),
                              "source_dir_override": str(spy_dir.relative_to(ROOT)) if spy_override is not None else None}
        slice_bars = sum(v["rows"] for v in per_symbol.values())
        slice_clean = all(v["is_clean"] for v in per_symbol.values())
        manifest["slices"][label] = {
            "data_dir": str(data_dir.relative_to(ROOT)), "start": start, "end": end,
            "dataset_hash_sha256": dataset_hash, "total_bars": slice_bars, "all_clean": slice_clean,
        }
        total_bars += slice_bars
        all_clean = all_clean and slice_clean
        quality[label] = {"bars": slice_bars, "clean": slice_clean}
    manifest["total_bars_all_slices"] = total_bars
    manifest["all_slices_clean"] = all_clean
    manifest["universe_symbols"] = len(UNIVERSE)
    (OUT / "development_data_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    (OUT / "development_data_quality.json").write_text(json.dumps(quality, indent=2, default=str))
    print(f"total_bars={total_bars} all_clean={all_clean}")


def load_slice(label: str, data_dir: Path) -> pd.DataFrame:
    spy_override = SPY_DIR_OVERRIDE.get(label)
    if spy_override is None:
        return load_ohlcv_directory(data_dir, symbols=UNIVERSE_PLUS_SPY)
    stocks = load_ohlcv_directory(data_dir, symbols=UNIVERSE)
    spy = load_ohlcv_csv(spy_override / "SPY.csv", symbol="SPY")
    return pd.concat([stocks, spy], ignore_index=True)


def run_family(module, name: str, slice_bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames = []
    for label, bars in slice_bars.items():
        ledger = module.evaluate(bars)
        ledger["regime_slice"] = label
        ledger["family"] = name
        frames.append(ledger)
    return pd.concat(frames, ignore_index=True)


def early_mid_late(ledger: pd.DataFrame, day_col: str) -> pd.Series:
    days_sorted = sorted(ledger[day_col].dropna().unique())
    if not days_sorted:
        return pd.Series(dtype=object)
    thirds = np.array_split(days_sorted, 3)
    mapping = {}
    for label, block in zip(("EARLY", "MIDDLE", "LATE"), thirds):
        for d in block:
            mapping[d] = label
    return ledger[day_col].map(mapping)


def flat_summary(row_keys: dict, summary: dict) -> dict:
    row = dict(row_keys)
    row.update({k: v for k, v in summary.items() if not isinstance(v, (dict, list))})
    row["bootstrap_ci_low_by_symbol"] = summary.get("bootstrap_gross_by_symbol", {}).get("ci_low")
    row["bootstrap_ci_high_by_symbol"] = summary.get("bootstrap_gross_by_symbol", {}).get("ci_high")
    row["bootstrap_ci_low_by_day"] = summary.get("bootstrap_gross_by_day", {}).get("ci_low")
    row["bootstrap_ci_high_by_day"] = summary.get("bootstrap_gross_by_day", {}).get("ci_high")
    return row


def outlier_sensitivity_for_cell(group: pd.DataFrame, day_col: str) -> dict:
    g = group.sort_values("gross_return_pct")
    n = len(g)
    out = {"n_trades": n}
    for k in (1, 3, 5):
        remaining = g.iloc[:-k] if n > k else g.iloc[0:0]
        out[f"remove_best{k}_net10bps_pct"] = float(net_return(remaining["gross_return_pct"], 10).mean()) if len(remaining) else None
        remaining_w = g.iloc[k:] if n > k else g.iloc[0:0]
        out[f"remove_worst{k}_net10bps_pct"] = float(net_return(remaining_w["gross_return_pct"], 10).mean()) if len(remaining_w) else None
    by_day = group.groupby(day_col)["gross_return_pct"].sum().sort_values(ascending=False)
    if len(by_day) >= 1:
        rem = group[group[day_col] != by_day.index[0]]
        out["remove_best_day_net10bps_pct"] = float(net_return(rem["gross_return_pct"], 10).mean()) if len(rem) else None
    if len(by_day) >= 3:
        top3_days = set(by_day.index[:3])
        rem = group[~group[day_col].isin(top3_days)]
        out["remove_best3_days_net10bps_pct"] = float(net_return(rem["gross_return_pct"], 10).mean()) if len(rem) else None
    return out


def main() -> None:
    build_manifest()

    print("Loading development slices...")
    slice_bars = {label: load_slice(label, data_dir) for label, data_dir, _, _ in SLICES}

    print("Running Family A (catalyst extreme-activity)...")
    ledger_a = run_family(family_a_catalyst, "FAMILY_A_CATALYST", slice_bars)
    print("Running Family B (multi-day cross-sectional)...")
    ledger_b = run_family(family_b_multiday, "FAMILY_B_MULTIDAY", slice_bars)
    ledger_a.to_csv(OUT / "family_a_raw_ledger.csv", index=False)
    ledger_b.to_csv(OUT / "family_b_raw_ledger.csv", index=False)

    cell_rows, cost_rows, friction_rows, regime_rows, seg_rows = [], [], [], [], []
    symbol_conc_rows, day_conc_rows, cluster_rows, outlier_rows = [], [], [], []

    for ledger, day_col in ((ledger_a, "trading_day"), (ledger_b, "decision_day")):
        trades = ledger[ledger["data_ready"] == True].copy()  # noqa: E712
        if trades.empty:
            continue
        trades["_segment"] = early_mid_late(trades, day_col)

        for keys, group in trades.groupby(CELL_COLS, dropna=False):
            keys_d = dict(zip(CELL_COLS, keys))
            summary = cell_summary(group, day_col=day_col)
            cell_rows.append(flat_summary(keys_d, summary))

            table = cost_sensitivity_table(group)
            for _, r in table.iterrows():
                cost_rows.append({**keys_d, **r.to_dict()})
            gross_exp = float(group["gross_return_pct"].mean())
            for bps in (10, 15, 20):
                friction_rows.append({**keys_d, "assumed_round_trip_bps": bps, "gross_expectancy_pct": gross_exp,
                                       "friction_absorption_ratio": abs(gross_exp) / (bps / 100.0) if bps else None})

            for regime, rgroup in group.groupby("regime_slice"):
                rsummary = cell_summary(rgroup, day_col=day_col)
                regime_rows.append(flat_summary({**keys_d, "regime_slice": regime}, rsummary))

            for segment, sgroup in group.groupby("_segment", dropna=True):
                ssummary = cell_summary(sgroup, day_col=day_col)
                seg_rows.append(flat_summary({**keys_d, "segment": segment}, ssummary))

            symbol_conc_rows.append({**keys_d, "n_trades": summary.get("n_trades"),
                                      "top1_symbol_share": summary.get("top1_symbol_share"),
                                      "top3_symbol_share": summary.get("top3_symbol_share")})
            day_conc_rows.append({**keys_d, "n_trades": summary.get("n_trades"),
                                   "top1_day_share": summary.get("top1_day_share")})
            cluster_rows.append({**keys_d, "n_trades": summary.get("n_trades"),
                                  "ci_low_by_symbol": summary.get("bootstrap_gross_by_symbol", {}).get("ci_low"),
                                  "ci_high_by_symbol": summary.get("bootstrap_gross_by_symbol", {}).get("ci_high"),
                                  "ci_low_by_day": summary.get("bootstrap_gross_by_day", {}).get("ci_low"),
                                  "ci_high_by_day": summary.get("bootstrap_gross_by_day", {}).get("ci_high"),
                                  "weaker_interpretation": summary.get("weaker_cluster_interpretation")})
            outlier_rows.append({**keys_d, **outlier_sensitivity_for_cell(group, day_col)})

    pd.DataFrame(cell_rows).to_csv(OUT / "cell_results.csv", index=False)
    pd.DataFrame(cost_rows).to_csv(OUT / "cost_sensitivity.csv", index=False)
    pd.DataFrame(friction_rows).to_csv(OUT / "friction_absorption.csv", index=False)
    pd.DataFrame(regime_rows).to_csv(OUT / "regime_stability.csv", index=False)
    pd.DataFrame(seg_rows).to_csv(OUT / "time_segment_stability.csv", index=False)
    pd.DataFrame(symbol_conc_rows).to_csv(OUT / "symbol_concentration.csv", index=False)
    pd.DataFrame(day_conc_rows).to_csv(OUT / "day_concentration.csv", index=False)
    pd.DataFrame(cluster_rows).to_csv(OUT / "cluster_bootstrap.csv", index=False)
    pd.DataFrame(outlier_rows).to_csv(OUT / "outlier_sensitivity.csv", index=False)

    cell_df = pd.DataFrame(cell_rows)
    fam_rows = []
    for (fam, hyp), group in cell_df.groupby(["family", "hypothesis"]):
        best = group.loc[group["net_expectancy_10bps_pct"].idxmax()]
        fam_rows.append(best.to_dict())
    pd.DataFrame(fam_rows).to_csv(OUT / "family_summary.csv", index=False)

    # ---- risk_diagnostics.csv: MAE/MFE for the top-5 cells by net@10bps (mega-cap primary cost) ----
    top5 = cell_df.sort_values("net_expectancy_10bps_pct", ascending=False).head(5)
    reg_slice_bars = {label: add_session_columns(bars) for label, bars in slice_bars.items()}
    reg_slice_bars = {label: bars[bars["is_regular_session"]] for label, bars in reg_slice_bars.items()}
    risk_rows = []
    for _, cell in top5.iterrows():
        fam = cell["family"]
        ledger, day_col = (ledger_a, "trading_day") if fam == "FAMILY_A_CATALYST" else (ledger_b, "decision_day")
        trades = ledger[ledger["data_ready"] == True]
        mask = pd.Series(True, index=trades.index)
        for c in CELL_COLS:
            mask &= trades[c] == cell[c]
        cell_trades = trades[mask]
        for _, t in cell_trades.iterrows():
            bars_slice = reg_slice_bars[t["regime_slice"]]
            day_bars = bars_slice[bars_slice["symbol"] == t["symbol"]]
            try:
                mm = compute_mfe_mae(day_bars, entry_timestamp=t["entry_timestamp"], exit_timestamp=t["exit_timestamp"],
                                      entry_price=t["entry_price"], risk_per_unit=t["entry_price"] * 0.01,
                                      direction="long" if t["direction"] == "LONG" else "short")
            except ValueError:
                continue
            risk_rows.append({**{c: cell[c] for c in CELL_COLS}, "symbol": t["symbol"], day_col: t[day_col],
                               "mfe_R": mm["mfe_R"], "mae_R": mm["mae_R"]})
    pd.DataFrame(risk_rows).to_csv(OUT / "risk_diagnostics.csv", index=False)

    print("total_cells_computed:", len(cell_rows))


if __name__ == "__main__":
    main()
