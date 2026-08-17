"""
talonx_backtest.cli
------------------------
`python -m talonx_backtest` -- runs a backtest from the command line
over a CSV file or a directory of per-symbol CSVs, using the FROZEN
production QuantConfig (RSI/MACD/ATR/confluence/R:R/cooldown/throttle
thresholds are not exposed as CLI flags -- only backtest-mechanics
settings are: slippage, spread, same-bar resolution, EOD flatten).
Writes the full results/ set (trades.csv/json, summary.json/txt,
equity_curve.csv, rejected_signals.csv, data_quality.json,
results.html, and cost_sensitivity.csv when --cost-sensitivity is
passed) via talonx_backtest.reports.write_report.

Data-safety posture (spec section 5): critical corruption (NaN/
infinite values, non-positive prices, an impossible OHLC relationship,
negative volume, or an unusable/unparseable timestamp) ABORTS the run
with a non-zero exit code before any backtest logic runs at all -- see
data.abort_on_critical_corruption. Recoverable issues (duplicate/
out-of-order timestamps) only warn unless --auto-dedupe is passed.

Usage:
    python -m talonx_backtest --data data/AAPL_1m.csv --symbol AAPL --out results
    python -m talonx_backtest --data data/ --start 2024-01-01 --end 2026-07-31 --out results
    python -m talonx_backtest --data data/AAPL_1m.csv --symbol AAPL --cost-sensitivity --out results
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from talonx_backtest.analysis import DEFAULT_COST_SCENARIOS_BPS, cost_sensitivity_scenarios
from talonx_backtest.data import (
    DataValidationError,
    abort_on_critical_corruption,
    check_dataset_quality,
    load_ohlcv_csv,
    load_ohlcv_directory,
    sort_and_dedupe,
)
from talonx_backtest.engine import BacktestConfig, BacktestEngine
from talonx_backtest.execution import ExecutionConfig
from talonx_backtest.reports import result_summary_text, write_report
from talonx_quant.config import QuantConfig


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="talonx_backtest",
        description="Run a historical backtest of the frozen TalonX strategy over 1-minute OHLCV data.",
    )
    parser.add_argument("--data", required=True, help="Path to a single OHLCV CSV, or a directory of per-symbol CSVs.")
    parser.add_argument("--symbol", help="Symbol for --data when it's a single CSV with no `symbol` column.")
    parser.add_argument("--symbols", help="Comma-separated symbol filter (directory loads, or post-filtering a combined CSV).")
    parser.add_argument("--start", help="ISO date/datetime (UTC) -- only bars at/after this are included.")
    parser.add_argument("--end", help="ISO date/datetime (UTC) -- only bars at/before this are included.")
    parser.add_argument(
        "--tz", default="UTC",
        help="Timezone naive timestamps in the source data should be interpreted as, e.g. "
             "'America/New_York' for exchange-local timestamps (default: UTC). Already-tz-aware "
             "timestamps in the file are converted to UTC regardless of this flag.",
    )
    parser.add_argument("--out", default="results", help="Output directory for the report files (default: results).")
    parser.add_argument("--prefix", default="backtest", help="Filename prefix for report files (default: backtest).")
    parser.add_argument("--entry-slippage-bps", type=float, default=0.0)
    parser.add_argument("--exit-slippage-bps", type=float, default=0.0)
    parser.add_argument("--spread-bps", type=float, default=0.0)
    parser.add_argument("--same-bar-resolution", choices=["stop_first", "target_first"], default="stop_first")
    parser.add_argument("--no-eod-flatten", action="store_true", help="Disable the 15:50 ET daily flatten sweep.")
    parser.add_argument("--auto-dedupe", action="store_true", help="Sort/dedupe the input before running if duplicates are found (see data.sort_and_dedupe).")
    parser.add_argument(
        "--cost-sensitivity", action="store_true",
        help=f"Also run the same backtest across cost scenarios {list(DEFAULT_COST_SCENARIOS_BPS)} bps "
             f"(entry slippage = exit slippage = spread, per scenario) and write cost_sensitivity.csv. "
             f"Sensitivity analysis only -- never selects or recommends a scenario.",
    )
    parser.add_argument(
        "--no-progress", action="store_true",
        help="Disable the periodic 'X%% (bars done/total)' progress line printed during a run "
             "(on by default -- a run over months of data can take minutes with compute_indicators's "
             "per-bar recompute, and a silent process is easy to mistake for hung).",
    )
    parser.add_argument(
        "--progress-interval", type=float, default=2.0,
        help="Seconds between progress updates (default: 2.0). Ignored if --no-progress is set.",
    )
    return parser


def _print_progress(bars_done: int, bars_total: int) -> None:
    pct = (bars_done / bars_total * 100) if bars_total else 100.0
    print(f"  progress: {pct:5.1f}%  ({bars_done:,}/{bars_total:,} bars)", flush=True)


def _print_cost_sensitivity_progress(scenario_index: int, scenario_count: int, bps: int, bars_done: int, bars_total: int) -> None:
    pct = (bars_done / bars_total * 100) if bars_total else 100.0
    print(f"  progress: scenario {scenario_index}/{scenario_count} ({bps} bps)  {pct:5.1f}%  ({bars_done:,}/{bars_total:,} bars)", flush=True)


def _load_data(args: argparse.Namespace) -> pd.DataFrame:
    path = Path(args.data)
    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None

    if path.is_dir():
        df = load_ohlcv_directory(path, symbols=symbols, tz=args.tz)
    elif path.is_file():
        df = load_ohlcv_csv(path, symbol=args.symbol, tz=args.tz)
        if symbols is not None:
            df = df[df["symbol"].isin(symbols)].reset_index(drop=True)
    else:
        raise FileNotFoundError(f"--data path not found: {path}")

    if args.start:
        df = df[df["timestamp"] >= pd.Timestamp(args.start, tz="UTC")]
    if args.end:
        df = df[df["timestamp"] <= pd.Timestamp(args.end, tz="UTC")]
    return df.reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        df = _load_data(args)
    except DataValidationError as exc:
        print("ERROR\nBACKTEST ABORTED\n" + str(exc), file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if df.empty:
        print("error: no rows loaded after filtering -- check --data/--symbols/--start/--end", file=sys.stderr)
        return 1

    quality = check_dataset_quality(df)
    print("=" * 70)
    print("DATA QUALITY")
    print("=" * 70)
    for report in quality.values():
        print(report.summary())
        print()

    # Critical corruption (NaN/infinite values, non-positive prices, an
    # impossible OHLC relationship, negative volume) hard-aborts here,
    # BEFORE any backtest logic runs -- spec section 5. Never
    # auto-repaired; the caller must fix the source data.
    try:
        abort_on_critical_corruption(quality)
    except DataValidationError as exc:
        print("ERROR\nBACKTEST ABORTED\n" + str(exc), file=sys.stderr)
        return 2

    recoverable_symbols = [s for s, r in quality.items() if r.has_recoverable_issues]
    if recoverable_symbols:
        if args.auto_dedupe:
            print(f"--auto-dedupe: sorting/deduplicating {recoverable_symbols} before running\n")
            df = sort_and_dedupe(df)
            quality = check_dataset_quality(df)
        else:
            print(
                f"WARNING: recoverable data-quality issues found for {recoverable_symbols} "
                f"(duplicate/out-of-order timestamps) -- proceeding as-is. Pass --auto-dedupe to "
                f"sort/dedupe automatically. The dataset was NOT modified.\n",
                file=sys.stderr,
            )

    config = BacktestConfig(
        quant_config=QuantConfig(),  # frozen production defaults -- not overridable from the CLI
        execution=ExecutionConfig(
            entry_slippage_bps=args.entry_slippage_bps,
            exit_slippage_bps=args.exit_slippage_bps,
            spread_bps=args.spread_bps,
            same_bar_resolution=args.same_bar_resolution,
        ),
        eod_flatten_enabled=not args.no_eod_flatten,
    )
    progress_callback = None if args.no_progress else _print_progress

    # Computed here (rather than only right before write_report) so the
    # interim stdout summary below and the final persisted report agree
    # on the same dataset_hash for this run -- previously this was only
    # computed after write_report's own call site, so result_summary_text
    # here had no dataset_path/dataset_symbols to pass to build_metadata
    # and printed dataset_hash: None even though the CLI already knew
    # exactly which dataset was loaded.
    dataset_symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None

    print("=" * 70)
    print("BACKTEST RESULT")
    print("=" * 70)
    engine = BacktestEngine(config)
    result = engine.run(df, progress_callback=progress_callback, progress_interval_seconds=args.progress_interval)
    print(result_summary_text(result, input_timezone=args.tz, dataset_path=args.data, dataset_symbols=dataset_symbols))

    cost_sensitivity_rows = None
    if args.cost_sensitivity:
        print("=" * 70)
        print("COST SENSITIVITY (sensitivity analysis only -- no scenario is recommended)")
        print("=" * 70)
        cs_progress_callback = None if args.no_progress else _print_cost_sensitivity_progress
        cost_sensitivity_rows = cost_sensitivity_scenarios(
            df, config.quant_config, same_bar_resolution=args.same_bar_resolution,
            eod_flatten_enabled=config.eod_flatten_enabled, progress_callback=cs_progress_callback,
        )
        print(f"{'cost_bps':>10} {'trades':>8} {'win_rate':>10} {'PF':>8} {'expectancy_R':>14} {'max_DD_R':>10}")
        for row in cost_sensitivity_rows:
            win_rate = "n/a" if row["win_rate"] is None else f"{row['win_rate']:.1%}"
            pf = "n/a" if row["profit_factor"] is None else f"{row['profit_factor']:.2f}"
            expectancy = "n/a" if row["expectancy_r"] is None else f"{row['expectancy_r']:.3f}"
            max_dd = "n/a" if row["max_drawdown_r"] is None else f"{row['max_drawdown_r']:.2f}"
            print(f"{row['cost_bps']:>10} {row['trades']:>8} {win_rate:>10} {pf:>8} {expectancy:>14} {max_dd:>10}")
        print()

    paths = write_report(
        result, args.out, prefix=args.prefix, data_quality=quality,
        input_timezone=args.tz, cost_sensitivity=cost_sensitivity_rows,
        dataset_path=args.data, dataset_symbols=dataset_symbols,
    )
    print("Report files written:")
    for label, out_path in paths.items():
        print(f"  {label:20s} {out_path}")
    print(f"\nOpen {paths['results_html']} in a browser to view the full report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
