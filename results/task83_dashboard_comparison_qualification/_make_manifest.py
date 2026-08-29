"""Regenerate evidence_manifest.json for this task's results directory.

    .venv/Scripts/python.exe results/task83_dashboard_comparison_qualification/_make_manifest.py
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "evidence_manifest.json"


def main() -> None:
    entries = []
    for p in sorted(HERE.rglob("*")):
        if not p.is_file() or p.name in ("evidence_manifest.json", "_make_manifest.py"):
            continue
        entries.append({
            "file": p.relative_to(HERE).as_posix(),
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        })
    OUT.write_text(json.dumps({
        "task": "Task 83 Dashboard Separation, Daily Comparison Evidence and Offline Dual-Run Qualification",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": "sha256",
        "file_count": len(entries),
        "artifacts": entries,
    }, indent=2), encoding="utf-8")
    print(f"wrote {OUT} ({len(entries)} files)")


if __name__ == "__main__":
    main()
