"""Task71 Part2 -- builds development_data_manifest.json across all 4
broadened DEVELOPMENT slices, reusing talonx_backtest.data quality checks
(same mechanism as Task70's own materialization)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from talonx_backtest.data import check_data_quality, load_ohlcv_csv  # noqa: E402
from talonx_backtest.reproducibility import get_dataset_hash  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX",
    "ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON",
    "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU", "NFLX", "PANW", "PEP",
    "QCOM", "REGN", "SBUX", "TXN", "VRTX",
]
SLICES = [
    ("2026_q3_f6_era", ROOT / "data" / "historical_1m" / "task67a_development", "2026-05-15", "2026-08-14"),
    ("2025_q1_orpb_era", ROOT / "data" / "historical_1m" / "task71_development_2025q1", "2025-02-03", "2025-03-14"),
    ("2025_q3_fprc_era", ROOT / "data" / "historical_1m" / "task71_development_2025q3", "2025-06-02", "2025-07-11"),
    ("2025_q4_task46_56_era", ROOT / "data" / "historical_1m" / "task71_development_2025q4", "2025-10-27", "2025-12-05"),
]


def main() -> None:
    manifest = {"role": "DEVELOPMENT_BROADENED", "slices": {}}
    total_bars, total_clean = 0, True
    for label, data_dir, start, end in SLICES:
        dataset_hash = get_dataset_hash(data_dir, UNIVERSE)
        per_symbol = {}
        for symbol in UNIVERSE:
            csv_path = data_dir / f"{symbol}.csv"
            df = load_ohlcv_csv(csv_path, symbol=symbol)
            report = check_data_quality(df, symbol=symbol)
            per_symbol[symbol] = {
                "rows": int(report.rows), "is_clean": bool(report.is_clean),
                "has_critical_corruption": bool(report.has_critical_corruption),
                "first_timestamp": str(report.first_timestamp), "last_timestamp": str(report.last_timestamp),
                "trading_sessions": int(df["timestamp"].dt.tz_convert("America/New_York").dt.date.nunique()),
            }
            total_bars += report.rows
            total_clean = total_clean and report.is_clean
        manifest["slices"][label] = {
            "data_dir": str(data_dir.relative_to(ROOT)), "requested_start": start, "requested_end": end,
            "dataset_hash_sha256": dataset_hash, "total_bars": sum(v["rows"] for v in per_symbol.values()),
            "all_clean": all(v["is_clean"] for v in per_symbol.values()),
            "per_symbol": per_symbol,
        }
    manifest["total_bars_all_slices"] = total_bars
    manifest["all_slices_clean"] = total_clean
    manifest["universe_symbols"] = len(UNIVERSE)
    (ROOT / "results" / "task71_structural_discovery" / "development_data_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8",
    )
    print(f"total_bars={total_bars} all_clean={total_clean}")


if __name__ == "__main__":
    main()
