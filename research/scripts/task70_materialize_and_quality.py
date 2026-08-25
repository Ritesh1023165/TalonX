"""
research/scripts/task70_materialize_and_quality.py
----------------------------------------------------
Task 70 Part 4 -- builds the data manifest + data-quality report for the
locked VALIDATION and REPLICATION historical windows (see
results/task70_f6_validation/holdout_selection_lock.json), reusing the
existing canonical mechanism (talonx_backtest.data.load_ohlcv_csv /
check_data_quality, talonx_backtest.reproducibility.get_dataset_hash)
unmodified. No interpolation, no forward-fill, no synthetic bars --
whatever check_data_quality reports is reported verbatim.

Does NOT touch F6_FADE_V1 or compute any strategy outcome -- data
integrity only.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402

from talonx_backtest.data import check_data_quality, load_ohlcv_csv  # noqa: E402
from talonx_backtest.reproducibility import get_dataset_hash  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX",
    "ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON",
    "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU", "NFLX", "PANW", "PEP",
    "QCOM", "REGN", "SBUX", "TXN", "VRTX",
]


def build_role_reports(role: str, data_dir: Path, requested_start: str, requested_end: str) -> tuple[dict, dict]:
    manifest = {
        "role": role, "data_dir": str(data_dir.relative_to(ROOT)),
        "requested_start": requested_start, "requested_end": requested_end,
        "universe": UNIVERSE, "provider": "alpaca", "feed": "account_default (omitted -- confirmed SIP per data_split_contract.json precedent)",
        "dataset_hash_sha256": get_dataset_hash(data_dir, UNIVERSE),
        "per_symbol": {},
    }
    quality = {"role": role, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "per_symbol": {}}
    now_utc = pd.Timestamp.now(tz="UTC")

    download_summary_path = data_dir / "download_summary.json"
    download_summary = json.loads(download_summary_path.read_text(encoding="utf-8")) if download_summary_path.exists() else {}
    per_symbol_summary = download_summary.get("symbols", {})

    for symbol in UNIVERSE:
        csv_path = data_dir / f"{symbol}.csv"
        if not csv_path.exists():
            manifest["per_symbol"][symbol] = {"status": "FAILED", "reason": "no CSV written"}
            quality["per_symbol"][symbol] = {"status": "FAILED"}
            continue
        df = load_ohlcv_csv(csv_path, symbol=symbol)
        report = check_data_quality(df, symbol=symbol)
        future_timestamps = int((df["timestamp"] > now_utc).sum())
        trading_sessions = int(df["timestamp"].dt.tz_convert("America/New_York").dt.date.nunique())

        dl = per_symbol_summary.get(symbol, {})
        manifest["per_symbol"][symbol] = {
            "status": dl.get("status", "UNKNOWN"),
            "requested_range": [requested_start, requested_end],
            "actual_range": [str(report.first_timestamp), str(report.last_timestamp)],
            "bars_returned": int(report.rows),
            "trading_sessions": trading_sessions,
        }
        quality["per_symbol"][symbol] = {
            "rows": int(report.rows),
            "duplicate_timestamps": int(report.duplicate_timestamps),
            "out_of_order_timestamps": int(report.out_of_order_timestamps),
            "missing_bars_total": int(report.missing_bars),
            "missing_bars_expected_session_gap": int(report.expected_session_gap_bars),
            "missing_bars_unexpected_intra_session_gap": int(report.unexpected_intra_session_gap_bars),
            "invalid_prices_le_zero": int(report.invalid_prices),
            "invalid_ohlc_relationship": int(report.invalid_ohlc_relationship),
            "negative_volume": int(report.negative_volume),
            "nan_values": int(report.nan_values),
            "infinite_values": int(report.infinite_values),
            "future_timestamps": future_timestamps,
            "is_clean": bool(report.is_clean),
            "has_critical_corruption": bool(report.has_critical_corruption),
        }

    statuses = {v["status"] for v in manifest["per_symbol"].values()}
    manifest["overall_status"] = "FULL" if statuses == {"FULL"} else sorted(statuses)
    quality["overall_clean"] = all(v.get("is_clean", False) for v in quality["per_symbol"].values())
    quality["overall_critical_corruption"] = any(v.get("has_critical_corruption", False) for v in quality["per_symbol"].values())
    return manifest, quality


def main() -> None:
    out_dir = ROOT / "results" / "task70_f6_validation"
    plan = [
        ("VALIDATION", ROOT / "data" / "historical_1m" / "task70_validation", "2024-02-01", "2024-03-15"),
        ("REPLICATION", ROOT / "data" / "historical_1m" / "task70_replication", "2024-09-03", "2024-10-18"),
    ]
    for role, data_dir, start, end in plan:
        manifest, quality = build_role_reports(role, data_dir, start, end)
        prefix = role.lower()
        (out_dir / f"{prefix}_data_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        (out_dir / f"{prefix}_data_quality.json").write_text(json.dumps(quality, indent=2, sort_keys=True), encoding="utf-8")
        print(f"{role}: overall_status={manifest['overall_status']} overall_clean={quality['overall_clean']} dataset_hash={manifest['dataset_hash_sha256']}")


if __name__ == "__main__":
    main()
