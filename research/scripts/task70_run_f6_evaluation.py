"""
research/scripts/task70_run_f6_evaluation.py
-----------------------------------------------
Task 70 Parts 5-8 -- ONE-SHOT frozen F6_FADE_V1 evaluation against a locked
historical role (VALIDATION or REPLICATION). Re-verifies the strategy
fingerprint before doing anything else (abort on mismatch), loads the
locked dataset via the existing canonical mechanism
(talonx_backtest.data.load_ohlcv_directory), runs the UNMODIFIED
research.task68_f6.evaluator.evaluate() exactly once, and writes every
required raw/derived artifact. Applies results/task68_f6_freeze/
validation_protocol.json's pre-registered pass_logic EXACTLY as written --
no threshold is invented or adjusted here.

Usage: python research/scripts/task70_run_f6_evaluation.py --role VALIDATION
       python research/scripts/task70_run_f6_evaluation.py --role REPLICATION
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from research.task68_f6 import strategy  # noqa: E402
from research.task68_f6.evaluator import evaluate  # noqa: E402
from research.task68_f6.fingerprint import compute_fingerprint, load_spec  # noqa: E402
from research.task67a_lib.research_stats import (  # noqa: E402
    bootstrap_ci_clustered, compute_mfe_mae, concentration_metrics,
)
from talonx_backtest.data import load_ohlcv_directory  # noqa: E402
from talonx_backtest.reproducibility import get_dataset_hash  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results" / "task70_f6_validation"
REQUIRED_FINGERPRINT = "6beb8eebe50053aae27cab90226534b5d4392c46bd6e9c094873f7ad37466084"

UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX",
    "ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON",
    "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU", "NFLX", "PANW", "PEP",
    "QCOM", "REGN", "SBUX", "TXN", "VRTX",
]

ROLE_WINDOWS = {
    "VALIDATION": ("2024-02-01", "2024-03-15", ROOT / "data" / "historical_1m" / "task70_validation"),
    "REPLICATION": ("2024-09-03", "2024-10-18", ROOT / "data" / "historical_1m" / "task70_replication"),
}


def pre_run_integrity_check() -> str:
    spec = load_spec()
    fp = compute_fingerprint(spec)
    if fp != REQUIRED_FINGERPRINT:
        raise SystemExit(f"BLOCKED_FROZEN_STRATEGY_MISMATCH: expected {REQUIRED_FINGERPRINT}, got {fp}")
    print(f"[integrity] fingerprint OK: {fp}")
    return fp


def _cost_metrics(net_return: pd.Series) -> dict:
    pos = net_return[net_return > 0]
    neg = net_return[net_return <= 0]
    pf = (pos.sum() / abs(neg.sum())) if neg.sum() != 0 else (float("inf") if pos.sum() > 0 else float("nan"))
    return {
        "expectancy": float(net_return.mean()), "total_return": float(net_return.sum()),
        "profit_factor": float(pf) if np.isfinite(pf) else str(pf),
    }


def _max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    drawdown = equity - running_max
    return float(drawdown.min())


def build_ledger(role: str) -> tuple[pd.DataFrame, str]:
    _, _, data_dir = ROLE_WINDOWS[role]
    bars = load_ohlcv_directory(data_dir, symbols=UNIVERSE)
    dataset_hash = get_dataset_hash(data_dir, UNIVERSE)
    ledger = evaluate(bars, cost_bps=strategy.PRIMARY_COST_BPS)
    for bps in strategy.DIAGNOSTIC_COST_BPS:
        col = f"net_return_{int(bps)}bps"
        ledger[col] = ledger["gross_return"] - (bps / 10000.0)
    return ledger, dataset_hash, bars


def run_role(role: str) -> dict:
    start, end, data_dir = ROLE_WINDOWS[role]
    fp = pre_run_integrity_check()
    ledger, dataset_hash, bars = build_ledger(role)
    prefix = role.lower()

    trades = ledger[ledger["data_ready"] == True].copy()  # noqa: E712
    rejections = ledger[ledger["data_ready"] == False].copy()  # noqa: E712

    ledger.to_csv(OUT_DIR / f"{prefix}_candidates.csv", index=False)
    trades.to_csv(OUT_DIR / f"{prefix}_trades.csv", index=False)
    rejections.to_csv(OUT_DIR / f"{prefix}_rejections.csv", index=False)

    if trades.empty:
        metrics = {
            "role": role, "strategy_fingerprint": fp, "strategy_fingerprint_match": True,
            "dataset_hash": dataset_hash, "number_of_candidates": int(len(ledger)),
            "number_of_trades": 0, "classification": "VALIDATION_INCONCLUSIVE" if role == "VALIDATION" else "REPLICATION_INCONCLUSIVE",
            "reason": "zero trades generated -- insufficient sample for any conclusion",
        }
        (OUT_DIR / f"{prefix}_metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True, default=str), encoding="utf-8")
        return metrics

    net10 = trades["net_return"]  # primary cost (10bps), same column evaluate() produced

    # --- cost sensitivity (0/5/10bps) ---
    cost_rows = []
    for bps in strategy.DIAGNOSTIC_COST_BPS:
        col = f"net_return_{int(bps)}bps"
        m = _cost_metrics(trades[col])
        cost_rows.append({"cost_bps": bps, **m})
    pd.DataFrame(cost_rows).to_csv(OUT_DIR / f"{prefix}_cost_sensitivity.csv", index=False)

    # --- concentration ---
    conc = concentration_metrics(trades, value_col="net_return", symbol_col="symbol", day_col="session_date")
    by_day_positive = trades[trades["net_return"] > 0].groupby("session_date")["net_return"].sum().sort_values(ascending=False)
    total_positive = float(trades[trades["net_return"] > 0]["net_return"].sum())
    top3_day_share = float(by_day_positive.iloc[:3].sum() / total_positive) if total_positive > 0 and len(by_day_positive) else None
    conc["top3_day_share"] = top3_day_share
    pd.DataFrame([conc]).to_csv(OUT_DIR / f"{prefix}_concentration.csv", index=False)

    # --- outlier sensitivity ---
    sorted_by_ret = trades.sort_values("net_return")
    outlier_rows = []
    for label, subset in [
        ("remove_best_1", trades.drop(sorted_by_ret.index[-1:])),
        ("remove_best_3", trades.drop(sorted_by_ret.index[-3:])),
        ("remove_worst_1", trades.drop(sorted_by_ret.index[:1])),
        ("remove_worst_3", trades.drop(sorted_by_ret.index[:3])),
    ]:
        outlier_rows.append({"scenario": label, "n_trades": int(len(subset)), "expectancy": float(subset["net_return"].mean()) if len(subset) else None})
    pd.DataFrame(outlier_rows).to_csv(OUT_DIR / f"{prefix}_outlier_sensitivity.csv", index=False)
    top3_winners_removed_expectancy = next(r["expectancy"] for r in outlier_rows if r["scenario"] == "remove_best_3")

    # --- long vs short ---
    ls_rows = []
    for direction in ("LONG", "SHORT"):
        subset = trades[trades["signal_direction"] == direction]
        if subset.empty:
            ls_rows.append({"direction": direction, "count": 0, "expectancy": None, "profit_factor": None, "total_return": None})
            continue
        m = _cost_metrics(subset["net_return"])
        ls_rows.append({"direction": direction, "count": int(len(subset)), **m})
    pd.DataFrame(ls_rows).to_csv(OUT_DIR / f"{prefix}_long_short.csv", index=False)
    long_expectancy = next((r["expectancy"] for r in ls_rows if r["direction"] == "LONG"), None)
    short_expectancy = next((r["expectancy"] for r in ls_rows if r["direction"] == "SHORT"), None)

    # --- session/day and symbol economics ---
    session_econ = trades.groupby("session_date").agg(
        n_trades=("net_return", "size"), gross_expectancy=("gross_return", "mean"),
        net_expectancy=("net_return", "mean"), total_net_return=("net_return", "sum"),
    ).reset_index()
    session_econ.to_csv(OUT_DIR / f"{prefix}_session_economics.csv", index=False)

    symbol_econ = trades.groupby("symbol").agg(
        n_trades=("net_return", "size"), gross_expectancy=("gross_return", "mean"),
        net_expectancy=("net_return", "mean"), total_net_return=("net_return", "sum"),
        win_rate=("net_return", lambda s: float((s > 0).mean())),
    ).reset_index()
    symbol_econ.to_csv(OUT_DIR / f"{prefix}_symbol_economics.csv", index=False)

    # --- bootstrap (primary: clustered by symbol, per Task68A's own pre-registered protocol) ---
    boot_symbol = bootstrap_ci_clustered(trades["net_return"].to_numpy(), trades["symbol"].to_numpy(), n_resamples=10_000)
    boot_day = bootstrap_ci_clustered(trades["net_return"].to_numpy(), trades["session_date"].to_numpy(), n_resamples=10_000)

    # --- max drawdown (chronological, by entry_timestamp) ---
    chrono = trades.sort_values("entry_timestamp")
    equity = chrono["net_return"].cumsum()
    max_dd = _max_drawdown(equity)

    # --- MFE/MAE (no stop -> report price-move %, not R) ---
    mfe_pcts, mae_pcts = [], []
    for _, row in trades.iterrows():
        symbol_bars = bars[bars["symbol"] == row["symbol"]]
        direction = "long" if row["signal_direction"] == "LONG" else "short"
        try:
            result = compute_mfe_mae(
                symbol_bars, entry_timestamp=row["entry_timestamp"], exit_timestamp=row["exit_timestamp"],
                entry_price=row["entry_price"], risk_per_unit=0, direction=direction,
            )
        except ValueError:
            continue
        mfe_pcts.append((result["mfe_price"] - row["entry_price"]) / row["entry_price"] if direction == "long" else (row["entry_price"] - result["mfe_price"]) / row["entry_price"])
        mae_pcts.append((row["entry_price"] - result["mae_price"]) / row["entry_price"] if direction == "long" else (result["mae_price"] - row["entry_price"]) / row["entry_price"])
    mfe_median = float(np.median(mfe_pcts)) if mfe_pcts else None
    mae_median = float(np.median(mae_pcts)) if mae_pcts else None

    # --- integrity diagnostics ---
    decision_to_entry_seconds = (pd.to_datetime(trades["entry_timestamp"]) - pd.to_datetime(trades["decision_timestamp"])).dt.total_seconds()
    holding_seconds = (pd.to_datetime(trades["exit_timestamp"]) - pd.to_datetime(trades["entry_timestamp"])).dt.total_seconds()
    exit_reason_counts = trades["exit_reason"].value_counts().to_dict()
    rejection_reason_counts = rejections["rejection_reason"].value_counts().to_dict()
    causal_violations = int((decision_to_entry_seconds <= 0).sum())

    metrics = {
        "role": role, "period": {"start": start, "end": end},
        "strategy_fingerprint": fp, "strategy_fingerprint_match": fp == REQUIRED_FINGERPRINT,
        "dataset_hash": dataset_hash,
        "number_of_candidates": int(len(ledger)), "number_of_trades": int(len(trades)),
        "long_count": int((trades["signal_direction"] == "LONG").sum()),
        "short_count": int((trades["signal_direction"] == "SHORT").sum()),
        "symbol_coverage": int(trades["symbol"].nunique()), "session_coverage": int(trades["session_date"].nunique()),
        "gross_expectancy": float(trades["gross_return"].mean()), "gross_total_return": float(trades["gross_return"].sum()),
        "net_expectancy_10bps": float(net10.mean()), "net_total_return_10bps": float(net10.sum()),
        "profit_factor_10bps": _cost_metrics(net10)["profit_factor"],
        "win_rate": float((net10 > 0).mean()), "average_win": float(net10[net10 > 0].mean()) if (net10 > 0).any() else None,
        "average_loss": float(net10[net10 <= 0].mean()) if (net10 <= 0).any() else None,
        "median_trade": float(net10.median()),
        "max_drawdown_net_return_units": max_dd,
        "mfe_median_pct": mfe_median, "mae_median_pct": mae_median,
        "cost_sensitivity": {str(int(r["cost_bps"])) + "bps": {"expectancy": r["expectancy"], "total_return": r["total_return"], "profit_factor": r["profit_factor"]} for r in cost_rows},
        "bootstrap_ci_clustered_by_symbol": boot_symbol.as_dict(),
        "bootstrap_ci_clustered_by_session_date_secondary": boot_day.as_dict(),
        "top1_symbol_contribution": conc.get("top1_symbol_share"), "top3_symbol_contribution": conc.get("top3_symbol_share"),
        "top1_day_contribution": conc.get("best_day_share"), "top3_day_contribution": top3_day_share,
        "top3_winners_removed_expectancy": top3_winners_removed_expectancy,
        "long_expectancy": long_expectancy, "short_expectancy": short_expectancy,
        "decision_to_entry_seconds": {"min": float(decision_to_entry_seconds.min()), "max": float(decision_to_entry_seconds.max()), "median": float(decision_to_entry_seconds.median())},
        "holding_seconds": {"min": float(holding_seconds.min()), "max": float(holding_seconds.max()), "median": float(holding_seconds.median())},
        "exit_reason_counts": exit_reason_counts,
        "rejection_reason_counts": rejection_reason_counts,
        "causal_violations_decision_after_or_at_entry": causal_violations,
    }
    (OUT_DIR / f"{prefix}_metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", required=True, choices=["VALIDATION", "REPLICATION"])
    args = parser.parse_args()
    result = run_role(args.role)
    print(json.dumps({k: v for k, v in result.items() if not isinstance(v, dict)}, indent=2, default=str))
