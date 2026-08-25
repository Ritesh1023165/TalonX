"""
research/scripts/task67a_build_data_inventory.py
----------------------------------------------------
Builds results/task67a_phenomenon_discovery/data_inventory.json: for
EVERY historical-OHLCV dataset directory actually present under
data/historical_1m/ in THIS worktree (c:\\workspace\\TalonX-alpha-
phenomenon-discovery), records provider/symbols/date range/trading
days/interval/timezone/RTH-extended coverage/row counts/data-quality
issues/a dataset fingerprint/prior usage.

IMPORTANT CONTEXT (see results/task67a_phenomenon_discovery/errors.jsonl):
this worktree's data/historical_1m/ does NOT contain the pre-existing
archives (task7b_alpaca_long_history, task37_..., task46_..., etc.) the
Task 67A briefing described from exploring the CANONICAL repo -- /data/
is gitignored, so `git worktree add` never copied it here. This script
therefore only inventories what is ACTUALLY present in this worktree:
the two directories Task 67A itself downloaded tonight
(task67a_development, task67a_benchmarks). This is not a bug in the
script; it is an honest reflection of this worktree's real state -- see
data_split_contract.md for the full reasoning.

Read-only over data/historical_1m/*; writes ONLY
results/task67a_phenomenon_discovery/data_inventory.json.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402

from talonx_backtest.data import check_data_quality, load_ohlcv_csv  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data/historical_1m"
OUT_PATH = ROOT / "results/task67a_phenomenon_discovery/data_inventory.json"

_ET = "America/New_York"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dataset_fingerprint(csv_paths: list[Path]) -> str:
    """sha256 over the concatenation of each file's OWN sha256 (not raw
    bytes directly, to keep this cheap for large datasets), in a
    deterministic (sorted by relative path) order -- changes if ANY file
    is added/removed/modified, regardless of processing order."""
    parts = []
    for p in sorted(csv_paths, key=lambda x: x.name):
        parts.append(f"{p.name}:{sha256_file(p)}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def expected_weekday_sessions(start: pd.Timestamp, end: pd.Timestamp) -> set:
    """Mon-Fri calendar dates in [start, end] (America/New_York calendar
    date). Deliberately does NOT account for US market holidays -- this
    repo has no trading-calendar source of truth anywhere (see
    talonx_backtest/data.py's _is_weekend docstring for the same
    admission) -- so a holiday will show up as a false-positive "missing
    session" below; documented, not silently hidden."""
    days = pd.date_range(start.normalize(), end.normalize(), freq="D", tz=start.tz)
    return {d.date().isoformat() for d in days if d.weekday() < 5}


def analyze_symbol_csv(path: Path) -> dict:
    df = load_ohlcv_csv(path, symbol=path.stem.upper(), tz="UTC")
    report = check_data_quality(df, symbol=path.stem.upper())

    et = df["timestamp"].dt.tz_convert(_ET)
    dates_present = set(et.dt.strftime("%Y-%m-%d"))
    minute_of_day = et.dt.hour * 60 + et.dt.minute
    rth_mask = (minute_of_day >= 570) & (minute_of_day < 960)  # 09:30-16:00 ET
    extended_mask = ~rth_mask

    return {
        "symbol": path.stem.upper(),
        "rows": report.rows,
        "first_timestamp": str(report.first_timestamp) if report.first_timestamp is not None else None,
        "last_timestamp": str(report.last_timestamp) if report.last_timestamp is not None else None,
        "inferred_bar_interval_seconds": report.inferred_bar_interval_seconds,
        "timezone_as_loaded": "UTC (normalized by talonx_backtest.data.load_ohlcv_csv)",
        "sessions_present_et_dates": len(dates_present),
        "rth_bars": int(rth_mask.sum()),
        "extended_hours_bars": int(extended_mask.sum()),
        "duplicate_timestamps": report.duplicate_timestamps,
        "out_of_order_timestamps": report.out_of_order_timestamps,
        "missing_bars_total": report.missing_bars,
        "missing_bars_expected_session_closed": report.expected_session_gap_bars,
        "missing_bars_unexpected_intra_session": report.unexpected_intra_session_gap_bars,
        "invalid_prices_le_zero": report.invalid_prices,
        "invalid_ohlc_relationship": report.invalid_ohlc_relationship,
        "negative_volume": report.negative_volume,
        "nan_values": report.nan_values,
        "infinite_values": report.infinite_values,
        "has_critical_corruption": report.has_critical_corruption,
        "is_clean": report.is_clean,
        "dates_present_et": sorted(dates_present),
    }


def analyze_dataset_dir(directory: Path) -> dict:
    csv_paths = sorted(directory.glob("*.csv"))
    symbol_reports = [analyze_symbol_csv(p) for p in csv_paths]

    summary_path = directory / "download_summary.json"
    provider_info = None
    if summary_path.exists():
        provider_info = json.loads(summary_path.read_text(encoding="utf-8"))

    all_first = [pd.Timestamp(r["first_timestamp"]) for r in symbol_reports if r["first_timestamp"]]
    all_last = [pd.Timestamp(r["last_timestamp"]) for r in symbol_reports if r["last_timestamp"]]
    overall_start = min(all_first) if all_first else None
    overall_end = max(all_last) if all_last else None

    all_dates_union: set = set()
    for r in symbol_reports:
        all_dates_union |= set(r["dates_present_et"])

    missing_sessions_by_symbol = {}
    if overall_start is not None and overall_end is not None:
        expected = expected_weekday_sessions(
            overall_start.tz_convert(_ET), overall_end.tz_convert(_ET)
        )
        for r in symbol_reports:
            missing = sorted(expected - set(r["dates_present_et"]))
            if missing:
                missing_sessions_by_symbol[r["symbol"]] = missing

    total_rows = sum(r["rows"] for r in symbol_reports)
    total_duplicates = sum(r["duplicate_timestamps"] for r in symbol_reports)
    total_out_of_order = sum(r["out_of_order_timestamps"] for r in symbol_reports)
    total_missing_bars = sum(r["missing_bars_total"] for r in symbol_reports)
    total_missing_bars_expected = sum(r["missing_bars_expected_session_closed"] for r in symbol_reports)
    total_missing_bars_unexpected = sum(r["missing_bars_unexpected_intra_session"] for r in symbol_reports)
    total_nan = sum(r["nan_values"] for r in symbol_reports)
    total_inf = sum(r["infinite_values"] for r in symbol_reports)
    total_invalid_prices = sum(r["invalid_prices_le_zero"] for r in symbol_reports)
    total_invalid_ohlc = sum(r["invalid_ohlc_relationship"] for r in symbol_reports)
    total_negative_volume = sum(r["negative_volume"] for r in symbol_reports)

    intervals = {r["inferred_bar_interval_seconds"] for r in symbol_reports if r["inferred_bar_interval_seconds"]}

    return {
        "directory": str(directory.relative_to(ROOT)).replace("\\", "/"),
        "provider": provider_info.get("provider") if provider_info else "unknown (no download_summary.json sidecar found)",
        "download_summary_present": summary_path.exists(),
        "download_summary_requested_range": (
            {"start": provider_info.get("requested_start"), "end": provider_info.get("requested_end")}
            if provider_info else None
        ),
        "symbols": [r["symbol"] for r in symbol_reports],
        "symbol_count": len(symbol_reports),
        "date_range_actual": {
            "start": str(overall_start) if overall_start is not None else None,
            "end": str(overall_end) if overall_end is not None else None,
        },
        "trading_days_union_across_symbols": len(all_dates_union),
        "interval_seconds_inferred": sorted(intervals),
        "timezone": "UTC on disk (America/New_York used only for session/RTH classification)",
        "rth_extended_coverage": "Both RTH (09:30-16:00 ET) and extended-hours bars present (Alpaca's default bars endpoint, no session filter applied) -- see per-symbol rth_bars/extended_hours_bars below.",
        "totals": {
            "rows": total_rows,
            "duplicate_timestamps": total_duplicates,
            "out_of_order_timestamps": total_out_of_order,
            "missing_bars": total_missing_bars,
            "missing_bars_expected_session_closed": total_missing_bars_expected,
            "missing_bars_unexpected_intra_session": total_missing_bars_unexpected,
            "missing_bars_note": "The vast majority of 'missing_bars' is EXPECTED (overnight/weekend session closure, or a session's own pre-market/after-hours minutes this provider simply didn't emit a bar for) -- missing_bars_unexpected_intra_session is the number actually worth scrutinizing (a hole inside 09:30-16:00 ET on an actual trading day).",
            "nan_values": total_nan,
            "infinite_values": total_inf,
            "invalid_prices_le_zero": total_invalid_prices,
            "invalid_ohlc_relationship": total_invalid_ohlc,
            "negative_volume": total_negative_volume,
        },
        "missing_sessions_by_symbol": missing_sessions_by_symbol,
        "missing_sessions_caveat": "Computed as Mon-Fri calendar dates with zero bars present, NOT cross-checked against a real trading-holiday calendar (none exists in this repo -- see talonx_backtest/data.py's _is_weekend docstring). A handful of these are very likely legitimate US market holidays (e.g. 2026-05-25 Memorial Day, 2026-07-03 early close / 2026-07-04 Independence Day), not real data defects -- inspect the list before treating any entry as a genuine gap.",
        "per_symbol": symbol_reports,
        "dataset_fingerprint_sha256": dataset_fingerprint(csv_paths),
        "dataset_fingerprint_method": "sha256(join(sorted 'filename:sha256(file_bytes)' per CSV, newline-separated)) -- changes if any file is added, removed, or its content changes, independent of filesystem iteration order.",
    }


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    dataset_dirs = sorted([d for d in DATA_ROOT.iterdir() if d.is_dir()]) if DATA_ROOT.is_dir() else []
    datasets = {}
    for d in dataset_dirs:
        if not list(d.glob("*.csv")):
            continue
        print(f"Analyzing {d} ...")
        datasets[d.name] = analyze_dataset_dir(d)

    prior_usage = {
        "task67a_development": "None -- freshly downloaded tonight (2026-08-24) by Task 67A Stage 0 specifically for this task's DEVELOPMENT role. The UNDERLYING CALENDAR DATES (2026-05-15..2026-08-14) DO have prior exposure from earlier tasks (Task 7B's 10-symbol year; Task 56 H3_late for the 35-symbol universe) -- see results/task67a_phenomenon_discovery/exposure_boundary_audit.json and data_split_contract.md for the full reasoning on why this is acceptable for DEVELOPMENT specifically. This CSV file itself, however, is a brand-new download, not a copy of any prior artifact.",
        "task67a_benchmarks": "None -- freshly downloaded tonight (2026-08-24) by Task 67A Stage 0 for benchmark_inventory.json (SPY + sector ETFs). Same underlying-calendar-dates caveat as task67a_development applies. No prior task in this repo ever downloaded SPY or any sector ETF (confirmed: no SPY/XLK/XLY/etc. reference found anywhere in exposure_boundary_audit.json's research-ledger/script sweep).",
    }

    payload = {
        "task": "67A Stage 0 - data inventory",
        "generated_utc": pd.Timestamp.now("UTC").isoformat(),
        "critical_environment_note": (
            "data/historical_1m/ in this isolated worktree does NOT contain the pre-existing archives "
            "described in the Task 67A briefing (task7b_alpaca_long_history, task37_universe_windows, "
            "task46_validation_windows, task53_warmup_windows, task54_extended_windows, task56_holdout, "
            "task61r_fprc_v1_validation, task63_orpb_v1_validation) -- /data/ is gitignored (see .gitignore "
            "line 46: 'real market data, not something to version') and git worktree add does not copy "
            "untracked/gitignored content from the canonical worktree. See errors.jsonl for the full finding. "
            "This inventory therefore covers only what is ACTUALLY present in THIS worktree: the two "
            "directories Task 67A itself created tonight. It does not claim (and must not be read as claiming) "
            "that the canonical repo's historical archives don't exist ANYWHERE -- only that they are not "
            "present in this isolated worktree's data/historical_1m/."
        ),
        "dataset_directories_found": list(datasets.keys()),
        "datasets": datasets,
        "prior_usage": prior_usage,
    }

    OUT_PATH.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
