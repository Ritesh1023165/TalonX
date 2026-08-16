"""
scripts/run_historical_regimes.py
---------------------------------------
Runs the frozen TalonX strategy (via `python -m talonx_backtest`,
unmodified -- this script only orchestrates, it never touches
talonx_quant) across several pre-defined historical date ranges
("regimes"), each meant to stress the strategy under a different kind
of market behavior, then builds one consolidated comparison table
across them.

This is empirical measurement, NOT parameter search: it runs the SAME
frozen QuantConfig against different TIME WINDOWS of the SAME data, and
reports what happened in each -- it never picks a "best regime," never
tunes anything between runs, and there is no `--optimize` path anywhere
in this repo (see docs/backtesting.md's own "What this backtester does
NOT do" section).

Requires historical 1-minute OHLCV data already on disk -- see
scripts/download_historical_1m.py. If --data-dir has no data for a
regime's date range, that regime's row in the comparison table is
reported as `n/a` across the board, never fabricated.

Usage:
    python scripts/run_historical_regimes.py --data-dir data/historical_1m --symbols AAPL,MSFT,NVDA
    python scripts/run_historical_regimes.py --data-dir data/historical_1m --regimes bull_momentum_2024,range_chop_2025
    python scripts/run_historical_regimes.py --data-dir data/historical_1m --out-dir reports --no-cost-sensitivity
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Regime:
    name: str
    start: str
    end: str
    description: str


# Pre-configured regimes (spec section: Task C). Date ranges only --
# nothing about the strategy changes between them. Add/edit ranges here
# freely; this is pure configuration, not strategy logic.
REGIMES: dict[str, Regime] = {
    "bull_momentum_2024": Regime(
        "bull_momentum_2024", "2024-01-01", "2024-06-30",
        "H1 2024 -- broad bull/momentum regime.",
    ),
    "high_vol_pullback_2024": Regime(
        "high_vol_pullback_2024", "2024-07-15", "2024-09-30",
        "Aug 2024 tech/macro pullback -- higher-volatility drawdown regime.",
    ),
    "range_chop_2025": Regime(
        "range_chop_2025", "2025-01-01", "2025-12-31",
        "2025 -- range-bound/consolidation regime.",
    ),
    "full_period_2024_2026": Regime(
        "full_period_2024_2026", "2024-01-01", "2026-08-01",
        "Full available window, 2024-2026 -- whatever data is on disk.",
    ),
}


def _discover_symbols(data_dir: Path) -> list[str]:
    symbols: set[str] = set()
    for entry in sorted(data_dir.iterdir()):
        if entry.is_file() and entry.suffix.lower() == ".csv":
            symbols.add(entry.stem.upper())
        elif entry.is_dir():
            symbols.add(entry.name.upper())
    return sorted(symbols)


def run_regime(
    regime: Regime, data_dir: Path, symbols: list[str] | None, out_root: Path,
    cost_sensitivity: bool, tz: str,
) -> dict:
    """Invokes `python -m talonx_backtest` (a real subprocess -- full
    process isolation between regimes, not an in-process call) for one
    regime. Returns a small result dict either way; a failed/empty run
    is reported, never silently skipped from the comparison table."""
    out_dir = out_root / f"regime_{regime.name}"
    argv = [
        sys.executable, "-m", "talonx_backtest",
        "--data", str(data_dir),
        "--start", regime.start, "--end", regime.end,
        "--tz", tz,
        "--out", str(out_dir),
    ]
    if symbols:
        argv += ["--symbols", ",".join(symbols)]
    if cost_sensitivity:
        argv += ["--cost-sensitivity"]

    print(f"\n{'=' * 70}\nRegime: {regime.name} ({regime.start} -> {regime.end})\n  {regime.description}\n{'=' * 70}", flush=True)
    # Deliberately NOT capture_output=True: talonx_backtest's own progress
    # lines (see cli.py's --no-progress) and its data-quality/result
    # printout are only useful if they stream live -- capturing and
    # printing them only after the whole subprocess exits is exactly why
    # a long regime run used to look hung with zero output for minutes.
    # Nothing downstream reads result.stdout/stderr (only returncode and
    # the written backtest_summary.json matter), so letting the child
    # inherit this process's stdout/stderr directly is safe.
    result = subprocess.run(argv, cwd=_REPO_ROOT)

    summary_path = out_dir / "backtest_summary.json"
    if result.returncode != 0 or not summary_path.is_file():
        return {
            "regime": regime.name, "start": regime.start, "end": regime.end,
            "exit_code": result.returncode, "ran": False,
            "total_trades": None, "win_rate": None, "profit_factor": None,
            "expectancy_r": None, "max_drawdown_r": None,
            "sharpe_per_trade": None, "sortino_per_trade": None,
        }

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    net = summary.get("metrics", {}).get("net")
    if not net:
        return {
            "regime": regime.name, "start": regime.start, "end": regime.end,
            "exit_code": result.returncode, "ran": True,
            "total_trades": 0, "win_rate": None, "profit_factor": None,
            "expectancy_r": None, "max_drawdown_r": None,
            "sharpe_per_trade": None, "sortino_per_trade": None,
        }

    return {
        "regime": regime.name, "start": regime.start, "end": regime.end,
        "exit_code": result.returncode, "ran": True,
        "total_trades": net["total_trades"], "win_rate": net["win_rate"],
        "profit_factor": net["profit_factor"], "expectancy_r": net["expectancy_r"],
        "max_drawdown_r": net["max_drawdown_r"], "sharpe_per_trade": net["sharpe_per_trade"],
        "sortino_per_trade": net["sortino_per_trade"],
    }


def _fmt(value, digits: int = 3, pct: bool = False) -> str:
    if value is None:
        return "n/a"
    if pct:
        return f"{value * 100:.1f}%"
    if value == float("inf"):
        return "inf"
    return f"{value:.{digits}f}"


def build_markdown_table(rows: list[dict]) -> str:
    lines = [
        "# TalonX multi-regime backtest comparison",
        "",
        "**Empirical measurement only -- not a parameter search.** The SAME frozen "
        "strategy (unmodified QuantConfig) was run against different historical date "
        "ranges. No regime's result should be read as \"the strategy is tuned for this "
        "period\" -- none of these runs changed anything about the strategy.",
        "",
        "| Regime | Period | Trades | Win Rate | Profit Factor | Expectancy (R) | Max DD (R) | Sharpe | Sortino |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        period = f"{row['start']} -> {row['end']}"
        if not row["ran"]:
            lines.append(f"| {row['regime']} | {period} | FAILED (exit {row['exit_code']}) | - | - | - | - | - | - |")
            continue
        lines.append(
            f"| {row['regime']} | {period} | {row['total_trades']} | "
            f"{_fmt(row['win_rate'], pct=True)} | {_fmt(row['profit_factor'], 2)} | "
            f"{_fmt(row['expectancy_r'])} | {_fmt(row['max_drawdown_r'], 2)} | "
            f"{_fmt(row['sharpe_per_trade'], 2)} | {_fmt(row['sortino_per_trade'], 2)} |"
        )
    lines += [
        "",
        "Every number above is read directly from each regime's own "
        "`backtest_summary.json` (net-of-cost metrics) -- none is estimated or "
        "interpolated. A regime with 0 (or very few) trades produces `n/a`/0 values "
        "here honestly, not a fabricated placeholder; treat any regime's row with a "
        "small trade count as low-confidence (see docs/backtesting.md's statistical-"
        "confidence guidance).",
    ]
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_historical_regimes",
        description="Run the frozen TalonX strategy across pre-configured historical date-range regimes and compare results.",
    )
    parser.add_argument("--data-dir", default="data/historical_1m", help="Directory of historical OHLCV CSVs (see scripts/download_historical_1m.py). Default: data/historical_1m")
    parser.add_argument("--symbols", default=None, help="Comma-separated symbol filter (default: every symbol found in --data-dir).")
    parser.add_argument("--regimes", default=None, help=f"Comma-separated regime names to run (default: all). Available: {', '.join(REGIMES)}")
    parser.add_argument("--out-dir", default="reports", help="Root directory for per-regime report subdirectories and the comparison table (default: reports/).")
    parser.add_argument("--tz", default="UTC", help="Timezone for naive timestamps in the source data (default: UTC) -- passed through to each regime's --tz.")
    parser.add_argument("--no-cost-sensitivity", action="store_true", help="Skip --cost-sensitivity on each regime run (default: included).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        print(f"error: --data-dir not found: {data_dir}. Run scripts/download_historical_1m.py first.", file=sys.stderr)
        return 1

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else _discover_symbols(data_dir)
    if not symbols:
        print(f"error: no symbols found in {data_dir} and none given via --symbols.", file=sys.stderr)
        return 1

    regime_names = [r.strip() for r in args.regimes.split(",")] if args.regimes else list(REGIMES)
    unknown = [r for r in regime_names if r not in REGIMES]
    if unknown:
        print(f"error: unknown regime(s) {unknown}. Available: {', '.join(REGIMES)}", file=sys.stderr)
        return 1

    out_root = Path(args.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    rows = [
        run_regime(REGIMES[name], data_dir, symbols, out_root, not args.no_cost_sensitivity, args.tz)
        for name in regime_names
    ]

    markdown = build_markdown_table(rows)
    (out_root / "regime_comparison.md").write_text(markdown, encoding="utf-8")
    (out_root / "regime_comparison.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")

    print("\n" + markdown)
    print(f"\nWritten: {out_root / 'regime_comparison.md'}")
    print(f"Written: {out_root / 'regime_comparison.json'}")

    failures = [r for r in rows if not r["ran"]]
    return 1 if len(failures) == len(rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
