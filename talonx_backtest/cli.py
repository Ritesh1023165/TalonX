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
results.html) via talonx_backtest.reports.write_report.

Usage:
    python -m talonx_backtest --data data/AAPL_1m.csv --symbol AAPL --out results
    python -m talonx_backtest --data data/ --start 2024-01-01 --end 2026-07-31 --out results
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from talonx_backtest.data import (
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
    parser.add_argument("--tz", default="UTC", help="Timezone naive timestamps in the source data should be interpreted as (default UTC).")
    parser.add_argument("--out", default="results", help="Output directory for the report files (default: results).")
    parser.add_argument("--prefix", default="backtest", help="Filename prefix for report files (default: backtest).")
    parser.add_argument("--entry-slippage-bps", type=float, default=0.0)
    parser.add_argument("--exit-slippage-bps", type=float, default=0.0)
    parser.add_argument("--spread-bps", type=float, default=0.0)
    parser.add_argument("--same-bar-resolution", choices=["stop_first", "target_first"], default="stop_first")
    parser.add_argument("--no-eod-flatten", action="store_true", help="Disable the 15:50 ET daily flatten sweep.")
    parser.add_argument("--auto-dedupe", action="store_true", help="Sort/dedupe the input before running if duplicates are found (see data.sort_and_dedupe).")
    return parser


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
    dirty_symbols = []
    for symbol, report in quality.items():
        print(report.summary())
        print()
        if not report.is_clean:
            dirty_symbols.append(symbol)

    if dirty_symbols:
        if args.auto_dedupe:
            print(f"--auto-dedupe: sorting/deduplicating {dirty_symbols} before running\n")
            df = sort_and_dedupe(df)
            quality = check_dataset_quality(df)
        else:
            print(
                f"WARNING: data-quality issues found for {dirty_symbols} -- proceeding as-is "
                f"(pass --auto-dedupe to sort/dedupe timestamp issues automatically; other "
                f"issues like invalid prices are never auto-repaired).\n",
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
    engine = BacktestEngine(config)
    result = engine.run(df)

    print("=" * 70)
    print("BACKTEST RESULT")
    print("=" * 70)
    print(result_summary_text(result))

    paths = write_report(result, args.out, prefix=args.prefix, data_quality=quality)
    print("Report files written:")
    for label, out_path in paths.items():
        print(f"  {label:20s} {out_path}")
    print(f"\nOpen {paths['results_html']} in a browser to view the full report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
