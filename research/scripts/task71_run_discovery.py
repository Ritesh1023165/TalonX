"""Task71 -- runs Families A-D against the broadened DEVELOPMENT pool (4
regime slices), computes all required diagnostics, writes every CSV/JSON
artifact under results/task71_structural_discovery/. DEVELOPMENT-only:
imports research.task71_lib.holdout_guard and checks every slice's date
range before loading it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from research.task71_lib import family_a_avwap, family_b_event_gap, family_c_residual_momentum, family_d_failed_break  # noqa: E402
from research.task71_lib.diagnostics import cell_summary, cost_sensitivity_table, net_return, profit_factor  # noqa: E402
from research.task71_lib.holdout_guard import DevelopmentOnlyGuard  # noqa: E402
from talonx_backtest.data import load_ohlcv_directory  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "task71_structural_discovery"
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX",
    "ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON",
    "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU", "NFLX", "PANW", "PEP",
    "QCOM", "REGN", "SBUX", "TXN", "VRTX",
]
SLICES = [
    ("2026_q3_f6_era", ROOT / "data" / "historical_1m" / "task67a_development", "2026-05-15", "2026-08-14"),
    ("2025_q1_orpb_era", ROOT / "data" / "historical_1m" / "task71_development_2025q1", "2025-02-03", "2025-03-14"),
    ("2025_q3_fprc_era", ROOT / "data" / "historical_1m" / "task71_development_2025q3", "2025-06-02", "2025-07-11"),
    ("2025_q4_task46_56_era", ROOT / "data" / "historical_1m" / "task71_development_2025q4", "2025-10-27", "2025-12-05"),
]
guard = DevelopmentOnlyGuard()
for _, _, start, end in SLICES:
    guard.check(start, end)


def load_slice(data_dir: Path, include_spy: bool) -> pd.DataFrame:
    symbols = UNIVERSE + (["SPY"] if include_spy else [])
    return load_ohlcv_directory(data_dir, symbols=symbols)


def run_family(module, include_spy: bool) -> pd.DataFrame:
    frames = []
    for label, data_dir, _, _ in SLICES:
        bars = load_slice(data_dir, include_spy=include_spy)
        ledger = module.evaluate(bars)
        ledger["regime_slice"] = label
        frames.append(ledger)
    return pd.concat(frames, ignore_index=True)


def early_mid_late(ledger: pd.DataFrame, day_col: str = "trading_day") -> pd.Series:
    days_sorted = sorted(ledger[day_col].dropna().unique())
    n = len(days_sorted)
    if n == 0:
        return pd.Series(dtype=object)
    thirds = np.array_split(days_sorted, 3)
    mapping = {}
    for label, block in zip(("EARLY", "MIDDLE", "LATE"), thirds):
        for d in block:
            mapping[d] = label
    return ledger[day_col].map(mapping)


def summarize_family(name: str, ledger: pd.DataFrame, group_cols: list[str], param_cols: list[str]) -> pd.DataFrame:
    """One row per (direction/param.../horizon) cell with full diagnostics."""
    trades = ledger[ledger["data_ready"] == True].copy()  # noqa: E712
    rows = []
    if trades.empty:
        return pd.DataFrame(rows)
    for keys, group in trades.groupby(group_cols, dropna=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        summary = cell_summary(group)
        row = dict(zip(group_cols, keys))
        row["family"] = name
        row.update({k: v for k, v in summary.items() if not isinstance(v, (dict, list))})
        row["bootstrap_ci_low_by_symbol"] = summary.get("bootstrap_gross_by_symbol", {}).get("ci_low")
        row["bootstrap_ci_high_by_symbol"] = summary.get("bootstrap_gross_by_symbol", {}).get("ci_high")
        row["bootstrap_ci_low_by_day"] = summary.get("bootstrap_gross_by_day", {}).get("ci_low")
        row["bootstrap_ci_high_by_day"] = summary.get("bootstrap_gross_by_day", {}).get("ci_high")
        rows.append(row)
    return pd.DataFrame(rows)


def rejection_counts(ledger: pd.DataFrame) -> dict:
    rejected = ledger[ledger["data_ready"] == False]  # noqa: E712
    return rejected["rejection_reason"].value_counts().to_dict()


def main() -> None:
    results = {}

    print("Running Family A (AVWAP)...")
    ledger_a = run_family(family_a_avwap, include_spy=False)
    ledger_a.to_csv(OUT / "family_a_raw_ledger.csv", index=False)
    summary_a = summarize_family("FAMILY_A_AVWAP", ledger_a, ["extension_side", "bet", "direction", "threshold_band", "horizon_label"], ["threshold_band"])
    summary_a.to_csv(OUT / "family_a_avwap_summary.csv", index=False)
    results["FAMILY_A_AVWAP"] = {"ledger": ledger_a, "summary": summary_a, "rejections": rejection_counts(ledger_a)}

    print("Running Family B (overnight gap)...")
    ledger_b = run_family(family_b_event_gap, include_spy=False)
    ledger_b.to_csv(OUT / "family_b_raw_ledger.csv", index=False)
    summary_b = summarize_family("FAMILY_B_GAP", ledger_b, ["direction", "gap_threshold_band", "horizon_label", "horizon_family"], ["gap_threshold_band"])
    summary_b.to_csv(OUT / "family_b_event_gap_summary.csv", index=False)
    results["FAMILY_B_GAP"] = {"ledger": ledger_b, "summary": summary_b, "rejections": rejection_counts(ledger_b)}

    print("Running Family C (residual momentum)...")
    ledger_c = run_family(family_c_residual_momentum, include_spy=True)
    ledger_c.to_csv(OUT / "family_c_raw_ledger.csv", index=False)
    summary_c = summarize_family("FAMILY_C_RESIDUAL", ledger_c, ["direction", "threshold_band", "horizon_label"], ["threshold_band"])
    summary_c.to_csv(OUT / "family_c_residual_momentum_summary.csv", index=False)
    results["FAMILY_C_RESIDUAL"] = {"ledger": ledger_c, "summary": summary_c, "rejections": rejection_counts(ledger_c)}

    print("Running Family D (failed structural break)...")
    ledger_d = run_family(family_d_failed_break, include_spy=False)
    ledger_d.to_csv(OUT / "family_d_raw_ledger.csv", index=False)
    summary_d = summarize_family("FAMILY_D_BREAK", ledger_d, ["side", "direction", "reclaim_window_band", "horizon_label"], ["reclaim_window_band"])
    summary_d.to_csv(OUT / "family_d_failed_break_summary.csv", index=False)
    results["FAMILY_D_BREAK"] = {"ledger": ledger_d, "summary": summary_d, "rejections": rejection_counts(ledger_d)}

    # ---- long/short diagnostics ----
    ls_rows = []
    for fam, data in results.items():
        trades = data["ledger"][data["ledger"]["data_ready"] == True]  # noqa: E712
        for direction, group in trades.groupby("direction"):
            summary = cell_summary(group)
            ls_rows.append({"family": fam, "direction": direction, **{k: v for k, v in summary.items() if not isinstance(v, (dict, list))}})
    pd.DataFrame(ls_rows).to_csv(OUT / "long_short_diagnostics.csv", index=False)

    # ---- horizon diagnostics ----
    hz_rows = []
    for fam, data in results.items():
        trades = data["ledger"][data["ledger"]["data_ready"] == True]  # noqa: E712
        if "horizon_label" not in trades.columns:
            continue
        for horizon, group in trades.groupby("horizon_label"):
            summary = cell_summary(group)
            hz_rows.append({"family": fam, "horizon_label": horizon, **{k: v for k, v in summary.items() if not isinstance(v, (dict, list))}})
    pd.DataFrame(hz_rows).to_csv(OUT / "horizon_diagnostics.csv", index=False)

    # ---- time stability (early/mid/late within each family+direction) ----
    ts_rows = []
    for fam, data in results.items():
        trades = data["ledger"][data["ledger"]["data_ready"] == True].copy()  # noqa: E712
        if trades.empty:
            continue
        trades["_segment"] = early_mid_late(trades)
        for (direction, segment), group in trades.groupby(["direction", "_segment"], dropna=False):
            summary = cell_summary(group)
            ts_rows.append({"family": fam, "direction": direction, "segment": segment, **{k: v for k, v in summary.items() if not isinstance(v, (dict, list))}})
    pd.DataFrame(ts_rows).to_csv(OUT / "time_stability.csv", index=False)

    # ---- regime diagnostics (per regime_slice) ----
    rg_rows = []
    for fam, data in results.items():
        trades = data["ledger"][data["ledger"]["data_ready"] == True]  # noqa: E712
        for (direction, regime), group in trades.groupby(["direction", "regime_slice"]):
            summary = cell_summary(group)
            rg_rows.append({"family": fam, "direction": direction, "regime_slice": regime, **{k: v for k, v in summary.items() if not isinstance(v, (dict, list))}})
    pd.DataFrame(rg_rows).to_csv(OUT / "regime_diagnostics.csv", index=False)

    # ---- concentration analysis (top1/top3 symbol+day per family/direction) ----
    conc_rows = []
    for fam, data in results.items():
        trades = data["ledger"][data["ledger"]["data_ready"] == True]  # noqa: E712
        for direction, group in trades.groupby("direction"):
            summary = cell_summary(group)
            conc_rows.append({
                "family": fam, "direction": direction, "n_trades": summary.get("n_trades"),
                "top1_symbol_share": summary.get("top1_symbol_share"), "top3_symbol_share": summary.get("top3_symbol_share"),
                "top1_day_share": summary.get("top1_day_share"),
            })
    pd.DataFrame(conc_rows).to_csv(OUT / "concentration_analysis.csv", index=False)

    # ---- dependence diagnostics (symbol-cluster vs day-cluster CI comparison) ----
    dep_rows = []
    for fam, data in results.items():
        trades = data["ledger"][data["ledger"]["data_ready"] == True]  # noqa: E712
        for direction, group in trades.groupby("direction"):
            summary = cell_summary(group)
            dep_rows.append({
                "family": fam, "direction": direction, "n_trades": summary.get("n_trades"),
                "ci_low_by_symbol": summary.get("bootstrap_gross_by_symbol", {}).get("ci_low"),
                "ci_high_by_symbol": summary.get("bootstrap_gross_by_symbol", {}).get("ci_high"),
                "ci_low_by_day": summary.get("bootstrap_gross_by_day", {}).get("ci_low"),
                "ci_high_by_day": summary.get("bootstrap_gross_by_day", {}).get("ci_high"),
                "weaker_interpretation": summary.get("weaker_cluster_interpretation"),
            })
    pd.DataFrame(dep_rows).to_csv(OUT / "dependence_diagnostics.csv", index=False)

    # ---- cost sensitivity + friction absorption (overall per family/direction) ----
    cost_rows, friction_rows = [], []
    for fam, data in results.items():
        trades = data["ledger"][data["ledger"]["data_ready"] == True]  # noqa: E712
        for direction, group in trades.groupby("direction"):
            table = cost_sensitivity_table(group)
            for _, r in table.iterrows():
                cost_rows.append({"family": fam, "direction": direction, **r.to_dict()})
            gross_exp = float(group["gross_return_pct"].mean())
            for bps in (10, 15, 20):
                friction_rows.append({
                    "family": fam, "direction": direction, "assumed_round_trip_bps": bps,
                    "gross_expectancy_pct": gross_exp,
                    "friction_absorption_ratio": abs(gross_exp) / (bps / 100.0) if bps else None,
                })
    pd.DataFrame(cost_rows).to_csv(OUT / "cost_sensitivity.csv", index=False)
    pd.DataFrame(friction_rows).to_csv(OUT / "friction_absorption.csv", index=False)

    # ---- parameter stability (response surface across the 2 predeclared bands) ----
    param_rows = []
    param_col_by_family = {
        "FAMILY_A_AVWAP": "threshold_band", "FAMILY_B_GAP": "gap_threshold_band",
        "FAMILY_C_RESIDUAL": "threshold_band", "FAMILY_D_BREAK": "reclaim_window_band",
    }
    for fam, data in results.items():
        trades = data["ledger"][data["ledger"]["data_ready"] == True]  # noqa: E712
        pcol = param_col_by_family[fam]
        for (direction, param_val), group in trades.groupby(["direction", pcol]):
            summary = cell_summary(group)
            param_rows.append({"family": fam, "direction": direction, "parameter": pcol, "value": param_val,
                                "n_trades": summary.get("n_trades"), "gross_expectancy_pct": summary.get("gross_expectancy_pct"),
                                "net_expectancy_10bps_pct": summary.get("net_expectancy_10bps_pct")})
    pd.DataFrame(param_rows).to_csv(OUT / "parameter_stability.csv", index=False)

    # ---- multiple testing summary ----
    total_cells = sum(len(data["summary"]) for data in results.values())
    mt_summary = {
        "predeclared_grid_cells": 72,
        "actual_cells_computed": total_cells,
        "cells_by_family": {fam: len(data["summary"]) for fam, data in results.items()},
        "method": "No dedicated max-statistic/permutation framework was built (none pre-existed and building one was out of scope for the time budget) -- per the task's own fallback instruction ('do not create a massive statistical framework if one is unavailable'), the control applied is: (1) a PREDECLARED, bounded grid (72 cells total, fixed before any outcome), (2) cluster-aware bootstrap CIs on every promising cell (not a naive i.i.d. CI), (3) an explicit total-hypothesis-count disclosure here, and (4) a qualitative downgrade of any isolated single-cell result not corroborated by neighboring parameter values or by more than one regime slice -- applied directly in candidate_ranking.md.",
        "isolated_marginal_findings_downgrade_rule": "Any cell reaching nominal significance (CI excluding zero) that is NOT corroborated by its neighboring threshold band AND by a majority of regime slices sharing the same sign is treated as likely noise, not evidence, regardless of its raw p-value/CI -- this rule is applied in candidate_ranking.md, not silently.",
    }
    (OUT / "multiple_testing_summary.json").write_text(json.dumps(mt_summary, indent=2), encoding="utf-8")

    print("total_cells_computed:", total_cells)
    for fam, data in results.items():
        print(fam, "rejections:", data["rejections"])


if __name__ == "__main__":
    main()
