"""Download and persist the single frozen Task 63 Alpaca package."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.download_historical_1m import main as download_main  # noqa: E402


FREEZE = ROOT / "results/task62_new_alpha_candidate/freeze_manifest.json"
DATA_DIR = ROOT / "data/historical_1m/task63_orpb_v1_validation"


def main() -> int:
    manifest = json.loads(FREEZE.read_text(encoding="utf-8"))
    windows = manifest["windows"]
    package = {
        "start": windows[0]["warmup_start"],
        "end": windows[-1]["evaluation_end"],
        "provider": manifest["provider"],
        "symbols": len(manifest["universe"]),
    }
    if package != {
        "start": "2025-01-24",
        "end": "2025-05-05",
        "provider": "Alpaca only",
        "symbols": 35,
    }:
        raise RuntimeError("Task 63 package differs from the committed freeze")
    load_dotenv(ROOT / ".env", override=False)
    return download_main([
        "--symbols", ",".join(manifest["universe"]),
        "--start-date", package["start"],
        "--end-date", package["end"],
        "--output-dir", str(DATA_DIR),
        "--provider", "alpaca",
        "--max-retries", "5",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
