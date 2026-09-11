"""Boundary-only Alpaca availability audit for frozen ORPB_V1 dates.

This does not run the candidate, generate signals, or compute returns. It does
not persist market bars; only provider/date coverage metadata is recorded.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.download_historical_1m import download_symbol  # noqa: E402
from talonx_quant.orpb_v1 import ORPB_V1_UNIVERSE  # noqa: E402


OUT = ROOT / "results/task62_new_alpha_candidate/availability_audit.json"
BOUNDARIES = ("2025-01-24", "2025-05-05")


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    symbols: dict[str, dict[str, object]] = {}
    all_pass = True
    for ticker in ORPB_V1_UNIVERSE:
        checks: dict[str, object] = {}
        for boundary in BOUNDARIES:
            result = download_symbol(ticker, boundary, boundary, "alpaca", 5)
            passed = result.status == "FULL" and result.bars > 0
            checks[boundary] = {
                "status": result.status,
                "bars": result.bars,
                "actual_start": result.actual_start,
                "actual_end": result.actual_end,
                "available": passed,
            }
            all_pass = all_pass and passed
        symbols[ticker] = checks
    payload = {
        "task": 62,
        "purpose": "availability-only boundary audit; no signals, replay, or returns",
        "provider": "alpaca",
        "requested_package_start": BOUNDARIES[0],
        "requested_package_end": BOUNDARIES[1],
        "symbols": symbols,
        "symbols_passing_both_boundaries": sum(
            all(item[boundary]["available"] for boundary in BOUNDARIES)
            for item in symbols.values()
        ),
        "all_35_boundaries_available": all_pass,
        "validation_started": False,
        "bars_persisted": False,
        "candidate_imported_for_universe_only": True,
        "candidate_instantiated": False,
    }
    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "provider": "alpaca",
        "symbols_passing_both_boundaries": payload["symbols_passing_both_boundaries"],
        "all_35_boundaries_available": all_pass,
        "validation_started": False,
    }, indent=2))
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
