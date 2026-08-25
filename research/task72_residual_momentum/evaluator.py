"""Task72 Part 12 -- full diagnostic bundle for one holdout run (VALIDATION
or REPLICATION), reusing Task71's already-tested statistical primitives
(research/task67a_lib/research_stats.py, research/task71_lib/diagnostics.py)
rather than reimplementing bootstrap/concentration/cost logic. Writes every
required artifact for a given `prefix` ("validation" or "replication") into
`out_dir` and returns the metrics dict used for PASS/FAIL/INCONCLUSIVE
classification.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.task67a_lib.research_stats import (
    bootstrap_ci_clustered, compute_mfe_mae, concentration_metrics,
)
from research.task71_lib.diagnostics import (
    COST_LEVELS_BPS, PRIMARY_COST_BPS, cost_sensitivity_table, friction_absorption_ratio, net_return, profit_factor,
)
from research.task72_residual_momentum import contracts as C


def _mfe_mae_for_trade(bars: pd.DataFrame, row: pd.Series) -> dict:
    day_bars = bars[(bars["symbol"] == row["symbol"]) & (bars["timestamp"] >= row["entry_timestamp"])
                     & (bars["timestamp"] <= row["exit_timestamp"])]
    if day_bars.empty:
        return {"mfe_price": None, "mae_price": None}
    risk_per_unit = row["entry_price"] - row["stop_price"]
    result = compute_mfe_mae(
        day_bars, entry_timestamp=row["entry_timestamp"], exit_timestamp=row["exit_timestamp"],
        entry_price=row["entry_price"], risk_per_unit=risk_per_unit, direction="long",
    )
    return result


def early_mid_late(trades: pd.DataFrame, day_col: str = "trading_day") -> pd.DataFrame:
    days = sorted(trades[day_col].unique())
    thirds = np.array_split(np.array(days), 3) if len(days) >= 3 else [np.array(days)]
    labels = ["EARLY", "MID", "LATE"][: len(thirds)]
    out = trades.copy()
    out["segment"] = None
    for label, chunk in zip(labels, thirds):
        out.loc[out[day_col].isin(chunk), "segment"] = label
    return out


def run_full_diagnostics(all_rows: pd.DataFrame, bars: pd.DataFrame, prefix: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    all_rows.to_csv(out_dir / f"{prefix}_candidates.csv", index=False)
    rejected = all_rows[~all_rows["data_ready"].astype(bool)]
    rejected.to_csv(out_dir / f"{prefix}_no_trade_or_rejections.csv", index=False)
    trades = all_rows[all_rows["data_ready"].astype(bool)].copy()
    trades.to_csv(out_dir / f"{prefix}_trades.csv", index=False)

    rejection_breakdown = rejected["rejection_reason"].value_counts().to_dict()

    n = len(trades)
    metrics: dict = {
        "prefix": prefix,
        "number_of_candidates": int(len(all_rows)),
        "number_of_trades": n,
        "missing_data_exclusions_total": int(len(rejected)),
        "missing_data_exclusions_breakdown": rejection_breakdown,
    }
    if n == 0:
        metrics["insufficient_n"] = True
        (out_dir / f"{prefix}_metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
        return metrics

    metrics["symbol_coverage"] = int(trades["symbol"].nunique())
    metrics["session_coverage"] = int(trades["trading_day"].nunique())

    cost_table = cost_sensitivity_table(trades, return_col="gross_return_pct")
    cost_table.to_csv(out_dir / f"{prefix}_cost_sensitivity.csv", index=False)
    net10 = net_return(trades["gross_return_pct"], PRIMARY_COST_BPS)

    metrics["gross_expectancy_pct"] = float(trades["gross_return_pct"].mean())
    for bps in COST_LEVELS_BPS:
        net_b = net_return(trades["gross_return_pct"], bps)
        metrics[f"net_expectancy_{bps}bps_pct"] = float(net_b.mean())
        metrics[f"profit_factor_{bps}bps"] = profit_factor(net_b)
    metrics["profit_factor"] = metrics["profit_factor_10bps"]
    metrics["net_expectancy_primary_cost"] = metrics["net_expectancy_10bps_pct"]
    metrics["win_rate"] = float((net10 > 0).mean())
    metrics["median_trade_pct"] = float(net10.median())
    wins, losses = net10[net10 > 0], net10[net10 <= 0]
    metrics["average_win_pct"] = float(wins.mean()) if len(wins) else None
    metrics["average_loss_pct"] = float(losses.mean()) if len(losses) else None
    metrics["total_return_pct_sum"] = float(net10.sum())
    metrics["friction_absorption_ratio_10bps"] = friction_absorption_ratio(metrics["gross_expectancy_pct"])

    cum = net10.cumsum()
    running_max = cum.cummax()
    drawdown = cum - running_max
    metrics["max_drawdown_pct"] = float(drawdown.min())

    stop_mask = trades["exit_reason"] == "STOP"
    time_mask = trades["exit_reason"] == "TIME_EXIT"
    metrics["stop_count"] = int(stop_mask.sum())
    metrics["time_exit_count"] = int(time_mask.sum())
    metrics["stop_rate"] = float(stop_mask.mean())
    metrics["expectancy_of_stop_exits_gross_pct"] = float(trades.loc[stop_mask, "gross_return_pct"].mean()) if stop_mask.any() else None
    metrics["expectancy_of_time_exits_gross_pct"] = float(trades.loc[time_mask, "gross_return_pct"].mean()) if time_mask.any() else None
    # Every STOP exit is by definition a truncated loser (the stop fired
    # instead of letting price run further against the position).
    metrics["large_losers_truncated_count"] = metrics["stop_count"]
    metrics["holding_minutes_median"] = float(trades["holding_minutes"].median())

    mfe_mae_rows = []
    for _, row in trades.iterrows():
        mm = _mfe_mae_for_trade(bars, row)
        mfe_mae_rows.append({"symbol": row["symbol"], "trading_day": row["trading_day"],
                              "exit_reason": row["exit_reason"], **mm})
    mfe_mae_df = pd.DataFrame(mfe_mae_rows)
    mfe_mae_df.to_csv(out_dir / f"{prefix}_stop_diagnostics.csv", index=False)
    if not mfe_mae_df.empty and mfe_mae_df["mfe_R"].notna().any():
        metrics["MFE_R_median"] = float(mfe_mae_df["mfe_R"].median())
        metrics["MAE_R_median"] = float(mfe_mae_df["mae_R"].median())
        time_exit_ids = trades.index[time_mask]
        time_exit_mfe = mfe_mae_df.loc[mfe_mae_df.index.isin(range(len(mfe_mae_df))) & (mfe_mae_df["exit_reason"] == "TIME_EXIT")]
        winning_time_exit_near_miss = time_exit_mfe[(time_exit_mfe["mae_R"].fillna(0) >= 0.9)]
        metrics["winning_time_exits_that_nearly_stopped_count"] = int(len(winning_time_exit_near_miss))

    trades["symbol_econ"] = trades.groupby("symbol")["symbol"].transform("count")
    by_symbol = trades.groupby("symbol").agg(
        n_trades=("symbol", "count"), gross_expectancy_pct=("gross_return_pct", "mean"),
        total_gross_pct=("gross_return_pct", "sum"),
    ).reset_index().sort_values("total_gross_pct", ascending=False)
    by_symbol.to_csv(out_dir / f"{prefix}_symbol_economics.csv", index=False)

    by_day = trades.groupby("trading_day").agg(
        n_trades=("trading_day", "count"), gross_expectancy_pct=("gross_return_pct", "mean"),
        total_gross_pct=("gross_return_pct", "sum"),
    ).reset_index().sort_values("total_gross_pct", ascending=False)
    by_day.to_csv(out_dir / f"{prefix}_day_economics.csv", index=False)

    conc = concentration_metrics(trades.assign(_ret=trades["gross_return_pct"]), value_col="_ret",
                                  symbol_col="symbol", day_col="trading_day")
    pd.DataFrame([conc]).to_csv(out_dir / f"{prefix}_concentration.csv", index=False)
    metrics["top1_symbol_contribution"] = conc.get("top1_symbol_share")
    metrics["top3_symbol_contribution"] = conc.get("top3_symbol_share")
    metrics["top1_day_contribution"] = conc.get("best_day_share")

    seg = early_mid_late(trades)
    seg_summary = seg.groupby("segment").agg(
        n_trades=("segment", "count"), gross_expectancy_pct=("gross_return_pct", "mean"),
        net_expectancy_10bps_pct=("gross_return_pct", lambda s: float(net_return(s, PRIMARY_COST_BPS).mean())),
    ).reset_index()
    seg_summary.to_csv(out_dir / f"{prefix}_segment_economics.csv", index=False)
    metrics["segment_signs"] = {row["segment"]: (row["gross_expectancy_pct"] > 0) for _, row in seg_summary.iterrows()}

    sorted_desc = trades.sort_values("gross_return_pct", ascending=False)
    top3_removed = sorted_desc.iloc[3:]
    worst3_removed = sorted_desc.iloc[:-3] if len(sorted_desc) > 3 else sorted_desc.iloc[0:0]
    top3_expectancy = float(net_return(top3_removed["gross_return_pct"], PRIMARY_COST_BPS).mean()) if len(top3_removed) else None
    worst3_expectancy = float(net_return(worst3_removed["gross_return_pct"], PRIMARY_COST_BPS).mean()) if len(worst3_removed) else None
    outlier_df = pd.DataFrame([
        {"check": "top3_winners_removed", "n_remaining": len(top3_removed), "net_expectancy_10bps_pct": top3_expectancy},
        {"check": "worst3_losers_removed", "n_remaining": len(worst3_removed), "net_expectancy_10bps_pct": worst3_expectancy},
    ])
    outlier_df.to_csv(out_dir / f"{prefix}_outlier_sensitivity.csv", index=False)
    metrics["top3_winners_removed_expectancy_10bps_pct"] = top3_expectancy
    metrics["worst3_losers_removed_expectancy_10bps_pct"] = worst3_expectancy

    boot_symbol = bootstrap_ci_clustered(trades["gross_return_pct"].to_numpy(), trades["symbol"].to_numpy(), n_resamples=5000)
    boot_day = bootstrap_ci_clustered(trades["gross_return_pct"].to_numpy(), trades["trading_day"].to_numpy(), n_resamples=5000)
    bootstrap_out = {"by_symbol": boot_symbol.as_dict(), "by_day": boot_day.as_dict()}
    (out_dir / f"{prefix}_bootstrap.json").write_text(json.dumps(bootstrap_out, indent=2, default=str))
    metrics["symbol_cluster_ci"] = [boot_symbol.ci_low, boot_symbol.ci_high]
    metrics["day_cluster_ci"] = [boot_day.ci_low, boot_day.ci_high]

    (out_dir / f"{prefix}_metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    return metrics
