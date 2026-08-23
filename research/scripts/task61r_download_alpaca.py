"""Download the single frozen Task 61R Alpaca package; no fallback provider."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.download_historical_1m import main as download_main  # noqa: E402


MANIFEST = ROOT / "results/task61r_fprc_v1_independent_validation_1/corrected_window_manifest.json"
DATA_DIR = ROOT / "data/historical_1m/task61r_fprc_v1_validation"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    package = manifest["download_package"]
    if package != {
        "end": "2025-08-14",
        "provider": "Alpaca",
        "start": "2025-05-06",
        "symbols": 35,
    }:
        raise RuntimeError("Task61R download package differs from committed freeze")
    universe = manifest["universe"]
    if len(universe) != 35:
        raise RuntimeError("Task61R requires exactly 35 frozen symbols")
    load_dotenv(ROOT / ".env", override=False)
    return download_main(
        [
            "--symbols", ",".join(universe),
            "--start-date", package["start"],
            "--end-date", package["end"],
            "--output-dir", str(DATA_DIR),
            "--provider", "alpaca",
            "--max-retries", "5",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
