"""READ-ONLY reconciliation of every registered V2@1 forward-tracker slot (evidence for 2026-10-12).

Uses talonx_paperperf.forward_status.completeness from THIS checkout against the data under ROOT. Reads only run
records, structured loop markers and output-file metadata (stat); never opens outputs. Prints sanitised JSON.

usage: python reconcile.py [DATA_ROOT] > RECONCILIATION.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

CODE = Path(__file__).resolve().parents[4]
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else CODE
sys.path.insert(0, str(CODE))
from talonx_paperperf import forward_status as FS  # noqa: E402

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    c = FS.completeness(ROOT, datetime.now(timezone.utc))
    print(json.dumps(c, indent=1, default=str))
