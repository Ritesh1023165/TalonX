"""Explicit deterministic Task 83-R2 scenarios 21-33 evidence generator.

Ordinary test execution never writes the committed matrix. This command runs
the complete production-loop rehearsal into a temporary CSV, validates the
exact row set and PASS verdicts, then atomically publishes the authoritative
matrix.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "results/task83_r1_production_collector_closure/expanded_rehearsal_matrix.csv"


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # Keep the candidate beside OUTPUT so publication is an atomic same-volume
    # replace. Pytest scratch data uses a fresh system temp directory, avoiding
    # reuse of any ACL-damaged directory left by an interrupted desktop run.
    candidate = OUTPUT.with_name(f".{OUTPUT.name}.{uuid4().hex}.tmp")
    with TemporaryDirectory(prefix="talonx_task83r2_rehearsal_") as temp_root:
        base_temp = Path(temp_root) / "pytest"
        command = [
            sys.executable, "-m", "pytest", "tests/test_task83_r1_production_loop.py",
            "-q", "--disable-warnings", f"--basetemp={base_temp}",
            f"--task83-r2-matrix-output={candidate}",
        ]
        result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        candidate.unlink(missing_ok=True)
        return result.returncode
    with candidate.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    scenarios = [int(row["scenario"]) for row in rows]
    if scenarios != list(range(21, 34)) or any(row["verdict"] != "PASS" for row in rows):
        candidate.unlink(missing_ok=True)
        raise SystemExit(f"qualification refused: scenarios={scenarios!r}")
    os.replace(candidate, OUTPUT)
    print(f"wrote {OUTPUT.relative_to(ROOT)}: 13/13 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
