"""Task72 Part 11/12 -- materialize-check + one-shot holdout evaluation for
a single locked role ("validation" or "replication"). Reverifies the
strategy fingerprint and the locked date range BEFORE loading any data;
computes a dataset hash and full data-quality report; then runs the
frozen strategy exactly once and writes every required diagnostic
artifact via research.task72_residual_momentum.evaluator.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402

from talonx_backtest.data import check_data_quality, load_ohlcv_csv  # noqa: E402
from talonx_backtest.reproducibility import get_dataset_hash  # noqa: E402

from research.task72_residual_momentum import contracts as C  # noqa: E402
from research.task72_residual_momentum.classify import classify  # noqa: E402
from research.task72_residual_momentum.evaluator import run_full_diagnostics  # noqa: E402
from research.task72_residual_momentum.fingerprint import compute_fingerprint  # noqa: E402
from research.task72_residual_momentum.holdout_guard import LockedRangeGuard  # noqa: E402
from research.task72_residual_momentum.strategy import evaluate  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_FINGERPRINT = "f3764b6794f2e00cc5262f73d241b5274ebf544dd65cc96e7a7ab175d7c6025a"
LOCKED_RANGES = [("2024-04-01", "2024-05-31"), ("2024-10-21", "2024-12-20")]
ALL_SYMBOLS = C.UNIVERSE + [C.MARKET_BENCHMARK_SYMBOL]

ROLES = {
    "validation": {"data_dir": ROOT / "data" / "historical_1m" / "task72_validation",
                   "start": "2024-04-01", "end": "2024-05-31", "prefix": "validation"},
    "replication": {"data_dir": ROOT / "data" / "historical_1m" / "task72_replication",
                    "start": "2024-10-21", "end": "2024-12-20", "prefix": "replication"},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["validation", "replication"], required=True)
    args = parser.parse_args()
    role = ROLES[args.role]

    fp = compute_fingerprint()
    if fp != REQUIRED_FINGERPRINT:
        raise SystemExit(f"FINGERPRINT MISMATCH: computed {fp} != locked {REQUIRED_FINGERPRINT} -- STOP.")

    guard = LockedRangeGuard(LOCKED_RANGES)
    guard.check(role["start"], role["end"])

    data_dir = role["data_dir"]
    dataset_hash = get_dataset_hash(data_dir, ALL_SYMBOLS)
    quality = {}
    frames = []
    for symbol in ALL_SYMBOLS:
        csv_path = data_dir / f"{symbol}.csv"
        df = load_ohlcv_csv(csv_path, symbol=symbol)
        report = check_data_quality(df, symbol=symbol)
        quality[symbol] = {
            "rows": int(report.rows), "is_clean": bool(report.is_clean),
            "has_critical_corruption": bool(report.has_critical_corruption),
            "first_timestamp": str(report.first_timestamp), "last_timestamp": str(report.last_timestamp),
        }
        frames.append(df)
    bars = pd.concat(frames, ignore_index=True)

    out_dir = ROOT / "results" / "task72_residual_momentum_freeze"
    manifest = {
        "role": args.role, "data_dir": str(data_dir.relative_to(ROOT)),
        "requested_start": role["start"], "requested_end": role["end"],
        "dataset_hash_sha256": dataset_hash,
        "total_bars": sum(v["rows"] for v in quality.values()),
        "all_clean": all(v["is_clean"] for v in quality.values()),
        "per_symbol": quality,
        "strategy_fingerprint_match": True,
    }
    (out_dir / f"{args.role}_data_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str))

    all_rows = evaluate(bars)
    metrics = run_full_diagnostics(all_rows, bars, role["prefix"], out_dir)
    metrics["strategy_fingerprint_match"] = True
    metrics["dataset_hash"] = dataset_hash
    result = classify(metrics)
    metrics["classification"] = result["classification"]
    metrics["criteria"] = result["criteria"]
    metrics["failed_criteria"] = result.get("failed_criteria")
    (out_dir / f"{role['prefix']}_metrics.json").write_text(json.dumps(metrics, indent=2, default=str))

    summary_lines = [
        f"# Task72/73 -- {args.role.upper()} summary\n",
        f"**Classification: {result['classification']}**\n",
        f"- Fingerprint match: {metrics['strategy_fingerprint_match']}",
        f"- Dataset hash: {dataset_hash}",
        f"- Trades: {metrics.get('number_of_trades')} | Symbols: {metrics.get('symbol_coverage')} | Days: {metrics.get('session_coverage')}",
        f"- Gross expectancy: {metrics.get('gross_expectancy_pct'):.4f}%" if metrics.get('gross_expectancy_pct') is not None else "- Gross expectancy: N/A",
        f"- Net expectancy 10bps: {metrics.get('net_expectancy_10bps_pct'):.4f}%" if metrics.get('net_expectancy_10bps_pct') is not None else "- Net expectancy 10bps: N/A",
        f"- Net expectancy 15bps: {metrics.get('net_expectancy_15bps_pct'):.4f}%" if metrics.get('net_expectancy_15bps_pct') is not None else "- Net expectancy 15bps: N/A",
        f"- Profit factor 10bps: {metrics.get('profit_factor_10bps')}",
        f"- Win rate: {metrics.get('win_rate')}",
        f"- Max drawdown: {metrics.get('max_drawdown_pct')}",
        f"- Stop rate: {metrics.get('stop_rate')} (stop={metrics.get('stop_count')}, time_exit={metrics.get('time_exit_count')})",
        f"- Symbol-cluster CI: {metrics.get('symbol_cluster_ci')}",
        f"- Day-cluster CI: {metrics.get('day_cluster_ci')}",
        f"- Top1 symbol contribution: {metrics.get('top1_symbol_contribution')}",
        f"- Top1 day contribution: {metrics.get('top1_day_contribution')}",
        f"- Top3 winners removed expectancy (10bps): {metrics.get('top3_winners_removed_expectancy_10bps_pct')}",
        "\n## Criteria\n",
    ]
    for k, v in result["criteria"].items():
        summary_lines.append(f"- {k}: {'PASS' if v else 'FAIL'}")
    (out_dir / f"{role['prefix']}_summary.md").write_text("\n".join(summary_lines))

    print(json.dumps({
        "role": args.role, "fingerprint_match": True, "dataset_hash": dataset_hash,
        "all_clean": manifest["all_clean"], "n_candidates": metrics.get("number_of_candidates"),
        "n_trades": metrics.get("number_of_trades"),
        "symbol_coverage": metrics.get("symbol_coverage"), "session_coverage": metrics.get("session_coverage"),
        "gross_expectancy_pct": metrics.get("gross_expectancy_pct"),
        "net_expectancy_10bps_pct": metrics.get("net_expectancy_10bps_pct"),
        "net_expectancy_15bps_pct": metrics.get("net_expectancy_15bps_pct"),
        "profit_factor_10bps": metrics.get("profit_factor_10bps"),
        "symbol_cluster_ci": metrics.get("symbol_cluster_ci"), "day_cluster_ci": metrics.get("day_cluster_ci"),
        "top1_symbol_contribution": metrics.get("top1_symbol_contribution"),
        "top1_day_contribution": metrics.get("top1_day_contribution"),
        "stop_rate": metrics.get("stop_rate"),
    }, indent=2, default=str))


if __name__ == "__main__":
    main()
