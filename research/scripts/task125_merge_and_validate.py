"""
TASK 125 Part 4 -- merge acquired partitions into one per-symbol series
and run the declared data-validation checks BEFORE the evaluation
script touches this data. No return/trigger/P&L computed here.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

RESEARCH_ROOT = Path(__file__).resolve().parents[2]
OUT = RESEARCH_ROOT / "results" / "task125_intraday_extension"
RAW = OUT / "_raw"
MERGED = OUT / "_merged"
MERGED.mkdir(parents=True, exist_ok=True)

SYMBOLS_ORIGINAL_12 = ["AAPL", "AMAT", "AMD", "AVGO", "CSCO", "GOOGL", "INTC", "MSFT", "NVDA", "PYPL", "STX", "TSLA"]
SYMBOLS_ADDED = ["BABA", "SHOP", "SPCX"]
ALL_SYMBOLS = SYMBOLS_ORIGINAL_12 + SYMBOLS_ADDED

REGULAR_SESSION_OPEN_UTC = "14:30:00"
DECISION_CUTOFF_UTC = "20:50:00"
EXTREME_SINGLE_BAR_JUMP_ABS = 0.30  # flagged for review, distinct from the evaluation's own 0.50 return-exclusion guard


def merge_symbol(sym: str) -> dict:
    parts = sorted((RAW / sym).glob("*.csv"))
    frames = []
    for p in parts:
        df = pd.read_csv(p, parse_dates=["timestamp"])
        if len(df):
            frames.append(df)
    checks = {"symbol": sym, "n_partitions": len(parts), "n_partitions_with_data": len(frames)}
    if not frames:
        checks["status"] = "NO_DATA"
        return checks

    merged = pd.concat(frames, ignore_index=True)
    n_before = len(merged)
    merged["timestamp"] = pd.to_datetime(merged["timestamp"], utc=True)

    # duplicates across partition boundaries (pagination can repeat the
    # boundary bar) -- dedup deterministically, keep first
    n_dup = int(merged["timestamp"].duplicated().sum())
    merged = merged.drop_duplicates(subset="timestamp", keep="first")
    merged = merged.sort_values("timestamp").reset_index(drop=True)
    n_out_of_order_before_sort = 0  # sort is deterministic; this counts nothing further, sort already applied

    non_pos = ((merged[["open", "high", "low", "close"]] <= 0).any(axis=1)).sum()
    neg_vol = (merged["volume"] < 0).sum()
    merged = merged[(merged[["open", "high", "low", "close"]] > 0).all(axis=1) & (merged["volume"] >= 0)].reset_index(drop=True)

    # single-bar-to-bar jump flag (candidate split/data-error markers,
    # NOT the evaluation's own overnight-return exclusion guard --
    # informational, for the acceptance report only)
    px = merged["close"].to_numpy()
    jump = pd.Series(px).pct_change().abs().replace([float("inf"), -float("inf")], pd.NA)
    n_extreme_jumps = int((jump > EXTREME_SINGLE_BAR_JUMP_ABS).fillna(False).sum())
    jump_dates = merged.loc[jump[jump > EXTREME_SINGLE_BAR_JUMP_ABS].index, "timestamp"].dt.date.astype(str).tolist() if n_extreme_jumps else []

    out_path = MERGED / f"{sym}.csv"
    merged.to_csv(out_path, index=False)
    file_hash = hashlib.sha256(out_path.read_bytes()).hexdigest()

    session_dates = merged["timestamp"].dt.date.unique()
    reg = merged[(merged["timestamp"].dt.strftime("%H:%M:%S") >= REGULAR_SESSION_OPEN_UTC)
                & (merged["timestamp"].dt.strftime("%H:%M:%S") <= DECISION_CUTOFF_UTC)]
    sessions_with_reg_coverage = reg["timestamp"].dt.date.nunique()

    checks.update({
        "status": "DATA_PRESENT",
        "n_rows_before_dedup": n_before, "n_duplicate_timestamps_dropped": n_dup,
        "n_non_positive_price_rows_dropped": int(non_pos), "n_negative_volume_rows_dropped": int(neg_vol),
        "n_rows_final": len(merged),
        "first_ts": str(merged["timestamp"].iloc[0]), "last_ts": str(merged["timestamp"].iloc[-1]),
        "n_distinct_calendar_dates": int(len(session_dates)),
        "n_sessions_with_open_through_cutoff_coverage": int(sessions_with_reg_coverage),
        "n_single_bar_jumps_gt_30pct": n_extreme_jumps, "single_bar_jump_dates": jump_dates,
        "file": str(out_path), "file_sha256": file_hash,
        "monotonic_timestamps": bool(merged["timestamp"].is_monotonic_increasing),
    })
    return checks


def main() -> int:
    report = {"generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
             "feed": "sip", "adjustment": "raw", "source": "task125_acquire_intraday.py",
             "by_symbol": {}}
    for sym in ALL_SYMBOLS:
        report["by_symbol"][sym] = merge_symbol(sym)

    out_path = OUT / "data_acceptance.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))
    for sym, c in report["by_symbol"].items():
        if c["status"] == "DATA_PRESENT":
            print(f"{sym}: {c['n_rows_final']:>7} rows, {c['n_distinct_calendar_dates']:>4} dates, "
                 f"{c['n_sessions_with_open_through_cutoff_coverage']:>4} w/ open-cutoff coverage, "
                 f"jumps>30%={c['n_single_bar_jumps_gt_30pct']}")
        else:
            print(f"{sym}: {c['status']}")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
