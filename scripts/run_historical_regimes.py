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


# Unified run/failure status (2026-08-17 consolidated-reporting fix):
# additive alongside the existing ran/failure_reason pair (kept
# unchanged, exactly as before, for backward compatibility with every
# existing caller/test) -- `status` just names the same underlying
# decision as one of six explicit strings instead of making a reader
# reconstruct it from ran + failure_reason + total_trades +
# small_sample_warning by hand.
STATUS_SUCCESS = "SUCCESS"
STATUS_SUCCESS_ZERO_TRADES = "SUCCESS_ZERO_TRADES"
STATUS_SUCCESS_SMALL_SAMPLE = "SUCCESS_SMALL_SAMPLE"
STATUS_FAILED_PROCESS = "FAILED_PROCESS"
STATUS_FAILED_MISSING_SUMMARY = "FAILED_MISSING_SUMMARY"
STATUS_FAILED_INVALID_SUMMARY = "FAILED_INVALID_SUMMARY"

_FAILURE_REASON_TO_STATUS = {
    "process_failed": STATUS_FAILED_PROCESS,
    "missing_summary": STATUS_FAILED_MISSING_SUMMARY,
}


def _status_for_success(total_trades: int, small_sample_warning: bool | None) -> str:
    """SUCCESS_ZERO_TRADES takes priority over small-sample: 0 trades is
    its own, more specific state (see reports.is_small_sample's own
    "zero trades already gets its own messaging" convention, reused
    here rather than reinvented) -- SUCCESS_SMALL_SAMPLE is only for a
    real but thin (1-29 trade) sample."""
    if total_trades == 0:
        return STATUS_SUCCESS_ZERO_TRADES
    if small_sample_warning:
        return STATUS_SUCCESS_SMALL_SAMPLE
    return STATUS_SUCCESS


def _failed_row(regime: Regime, exit_code: int, failure_reason: str) -> dict:
    """One shape for every kind of "this regime did not produce usable
    results" outcome -- see run_regime's docstring for the three
    distinct failure_reason values this can carry. cost_sensitivity/
    small_sample_warning are None here (not False/[]): there is no
    result to have an opinion about either field for, same "never
    fabricate" posture as the metric fields below."""
    status = _FAILURE_REASON_TO_STATUS.get(failure_reason, STATUS_FAILED_INVALID_SUMMARY)
    return {
        "regime": regime.name, "start": regime.start, "end": regime.end,
        "exit_code": exit_code, "ran": False, "failure_reason": failure_reason, "status": status,
        "total_trades": None, "win_rate": None, "profit_factor": None,
        "expectancy_r": None, "total_r": None, "max_drawdown_r": None,
        "sharpe_per_trade": None, "sortino_per_trade": None,
        "small_sample_warning": None, "cost_sensitivity": None, "cost_sensitivity_requested": None,
    }


def run_regime(
    regime: Regime, data_dir: Path, symbols: list[str] | None, out_root: Path,
    cost_sensitivity: bool, tz: str,
) -> dict:
    """Invokes `python -m talonx_backtest` (a real subprocess -- full
    process isolation between regimes, not an in-process call) for one
    regime. Returns a small result dict either way; a failed/empty run
    is reported, never silently skipped from the comparison table.

    "Failed" is not one undifferentiated state -- `failure_reason`
    distinguishes:
      - "process_failed": the subprocess itself exited non-zero (a real
        backtest error -- bad data, an unhandled exception, etc).
      - "missing_summary": the subprocess exited 0 but never wrote
        backtest_summary.json at all -- an infrastructure/wiring bug,
        not a backtest error, and worth telling apart from the above.
      - "invalid_summary": the file exists but isn't parseable JSON --
        previously this would have raised INSIDE run_regime and crashed
        the whole multi-regime run (every other regime's results lost
        with it); now it's caught and reported as this one regime's
        row, same as any other failure mode.

    small_sample_warning and cost_sensitivity are read straight from
    that regime's own backtest_summary.json (already computed by
    talonx_backtest -- see reports.is_small_sample and
    analysis.cost_sensitivity_scenarios) and passed through unchanged;
    nothing here recalculates either one.

    `status` is an additive, unified summary of the SAME decision
    ran/failure_reason/total_trades/small_sample_warning already encode
    -- one of SUCCESS / SUCCESS_ZERO_TRADES / SUCCESS_SMALL_SAMPLE /
    FAILED_PROCESS / FAILED_MISSING_SUMMARY / FAILED_INVALID_SUMMARY --
    so a reader doesn't have to reconstruct it from four separate
    fields. `cost_sensitivity_requested` records whether --cost-
    sensitivity was actually passed for THIS run, independent of
    whether `cost_sensitivity` ended up populated -- lets a caller
    distinguish "not requested" from "requested but absent from the
    summary" without re-deriving it from CLI args after the fact."""
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
    if result.returncode != 0:
        return _failed_row(regime, result.returncode, "process_failed")
    if not summary_path.is_file():
        return _failed_row(regime, result.returncode, "missing_summary")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _failed_row(regime, result.returncode, f"invalid_summary: {exc}")

    small_sample_warning = summary.get("small_sample_warning")
    # cost_sensitivity is read from backtest_summary.json's own embedded
    # copy, not by separately opening backtest_cost_sensitivity.csv --
    # both are written from the exact same in-memory rows (see
    # talonx_backtest/reports.py: write_report passes the identical
    # `cost_sensitivity` list into both result_summary_json, which embeds
    # it verbatim, and cost_sensitivity_to_csv) and the CSV is only ever
    # written when that list is non-empty, so "CSV present" and "JSON key
    # non-empty" are the same condition. Reading the JSON avoids a second
    # file open for data already loaded into `summary` above; nothing is
    # recalculated either way -- this is still the individual backtest's
    # own generated output, just its already-open serialization.
    cost_sensitivity_rows = summary.get("cost_sensitivity") or None

    net = summary.get("metrics", {}).get("net")
    if not net:
        return {
            "regime": regime.name, "start": regime.start, "end": regime.end,
            "exit_code": result.returncode, "ran": True, "failure_reason": None,
            "status": _status_for_success(0, small_sample_warning),
            "total_trades": 0, "win_rate": None, "profit_factor": None,
            "expectancy_r": None, "total_r": None, "max_drawdown_r": None,
            "sharpe_per_trade": None, "sortino_per_trade": None,
            "small_sample_warning": small_sample_warning, "cost_sensitivity": cost_sensitivity_rows,
            "cost_sensitivity_requested": cost_sensitivity,
        }

    return {
        "regime": regime.name, "start": regime.start, "end": regime.end,
        "exit_code": result.returncode, "ran": True, "failure_reason": None,
        "status": _status_for_success(net["total_trades"], small_sample_warning),
        "total_trades": net["total_trades"], "win_rate": net["win_rate"],
        "profit_factor": net["profit_factor"], "expectancy_r": net["expectancy_r"],
        "total_r": net.get("total_r"),  # .get(): older/hand-built summaries may predate this field
        "max_drawdown_r": net["max_drawdown_r"], "sharpe_per_trade": net["sharpe_per_trade"],
        "sortino_per_trade": net["sortino_per_trade"],
        "small_sample_warning": small_sample_warning, "cost_sensitivity": cost_sensitivity_rows,
        "cost_sensitivity_requested": cost_sensitivity,
    }


def _fmt(value, digits: int = 3, pct: bool = False) -> str:
    if value is None:
        return "n/a"
    if pct:
        return f"{value * 100:.1f}%"
    if value == float("inf"):
        return "inf"
    return f"{value:.{digits}f}"


def _cost_sensitivity_summary(cost_sensitivity: list[dict] | None) -> str:
    """One compact cell: expectancy_r at the lowest and highest cost
    scenario present (e.g. "-1.000 (0bps) -> -2.103 (20bps)") -- a
    quick read of magnitude, not a replacement for that regime's own
    full backtest_cost_sensitivity.csv (still written unchanged,
    exactly as before). "n/a" if --cost-sensitivity wasn't requested
    for this run (cost_sensitivity is None) or the list is otherwise
    empty -- never a fabricated range."""
    if not cost_sensitivity:
        return "n/a"
    first, last = cost_sensitivity[0], cost_sensitivity[-1]
    return (
        f"{_fmt(first.get('expectancy_r'))} ({first.get('cost_bps')}bps) -> "
        f"{_fmt(last.get('expectancy_r'))} ({last.get('cost_bps')}bps)"
    )


def _status_label(row: dict) -> str:
    """The Status column's cell text -- the unified `status` string, plus
    enough detail to act on for a FAILED row (exit code + failure_reason)
    without needing to cross-reference regime_comparison.json."""
    status = row.get("status") or ("SUCCESS" if row["ran"] else "FAILED")
    if row["ran"]:
        return status
    reason = row.get("failure_reason") or "unknown"
    return f"{status} (exit {row['exit_code']}, {reason})"


def build_markdown_table(rows: list[dict]) -> str:
    lines = [
        "# TalonX multi-regime backtest comparison",
        "",
        "**Empirical measurement only -- not a parameter search.** The SAME frozen "
        "strategy (unmodified QuantConfig) was run against different historical date "
        "ranges. No regime's result should be read as \"the strategy is tuned for this "
        "period\" -- none of these runs changed anything about the strategy.",
        "",
        "| Regime | Period | Status | Trades | Win Rate | Profit Factor | Expectancy (R) | Total R | Max DD (R) | Small Sample |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        period = f"{row['start']} -> {row['end']}"
        if not row["ran"]:
            lines.append(f"| {row['regime']} | {period} | {_status_label(row)} | - | - | - | - | - | - | - |")
            continue
        small_sample = row.get("small_sample_warning")
        small_sample_label = "n/a" if small_sample is None else ("yes" if small_sample else "no")
        lines.append(
            f"| {row['regime']} | {period} | {_status_label(row)} | {row['total_trades']} | "
            f"{_fmt(row['win_rate'], pct=True)} | {_fmt(row['profit_factor'], 2)} | "
            f"{_fmt(row['expectancy_r'])} | {_fmt(row.get('total_r'))} | {_fmt(row['max_drawdown_r'], 2)} | "
            f"{small_sample_label} |"
        )
    lines += [
        "",
        "Every number above is read directly from each regime's own "
        "`backtest_summary.json` (net-of-cost metrics) -- none is estimated or "
        "interpolated. A regime with 0 (or very few) trades produces `n/a`/0 values "
        "here honestly, not a fabricated placeholder; treat any `SUCCESS_SMALL_SAMPLE` "
        "row as low-confidence (see docs/backtesting.md's statistical-confidence "
        "guidance). Sharpe/Sortino per trade are omitted from this compact table but "
        "remain in `regime_comparison.json` for every regime.",
        "",
        *_cost_sensitivity_section(rows),
    ]
    return "\n".join(lines)


def _cost_sensitivity_section(rows: list[dict]) -> list[str]:
    """A dedicated '## Cost Sensitivity' section, one '### {regime}'
    subsection per regime, each with its OWN small table of every cost
    scenario present (0/5/10/20 bps or however many the regime's own
    backtest_cost_sensitivity.csv/backtest_summary.json actually
    contains -- never assumed to be exactly four). Every regime gets a
    subsection, even when there's nothing to show -- explicitly stating
    WHY (not requested vs. requested-but-absent vs. the regime never
    ran at all) rather than silently disappearing from this section,
    which would be indistinguishable from "cost sensitivity happened to
    be empty" at a glance."""
    lines = ["## Cost Sensitivity", ""]
    for row in rows:
        lines.append(f"### {row['regime']}")
        lines.append("")
        cost_rows = row.get("cost_sensitivity")
        if cost_rows:
            lines.append("| Cost (bps) | Trades | Expectancy (R) | Profit Factor | Max DD (R) |")
            lines.append("|---|---|---|---|---|")
            for c in cost_rows:
                lines.append(
                    f"| {c.get('cost_bps', 'n/a')} | {c.get('trades', 'n/a')} | "
                    f"{_fmt(c.get('expectancy_r'))} | {_fmt(c.get('profit_factor'), 2)} | "
                    f"{_fmt(c.get('max_drawdown_r'), 2)} |"
                )
        elif not row["ran"]:
            lines.append(
                "Not available -- this regime did not produce a usable result "
                "(see the comparison table above for the failure reason)."
            )
        elif row.get("cost_sensitivity_requested") is False:
            lines.append("Cost sensitivity was not requested for this run (`--no-cost-sensitivity`).")
        else:
            lines.append(
                "Cost sensitivity was requested for this run, but is absent from this "
                "regime's `backtest_summary.json` -- check its own "
                "`backtest_cost_sensitivity.csv` directly."
            )
        lines.append("")
    return lines


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
