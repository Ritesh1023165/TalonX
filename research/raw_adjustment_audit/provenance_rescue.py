"""B5c -- provenance rescue (READ-ONLY on the live worktree). Copies manifests / reports / logs (and small top-level
result tables) of the untracked Task93/95A/95B/95G results -- plus any dataset-builder code found -- into
research/provenance/task93_97/ on this branch, and writes a sha256 inventory of every DATA file left behind.
Nothing in C:/workspace/TalonX is moved, modified or deleted (files are only opened for reading).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

LIVE = Path("C:/workspace/TalonX/results")
ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "research" / "provenance" / "task93_97"
DIRS = ["task93_alpha_foundation", "task95a_regime_expansion", "task95b_swing_foundation",
        "task95g_broad_cross_sectional"]
EXTRA_CODE = [LIVE / "task97_catalyst_displacement" / "_build_task97_dataset.py"]
DATA_SUBDIRS = {"_canonical_data", "_expanded_data", "_raw_expanded", "_features_expanded", "_daily", "baseline_segmentA"}
DOC_EXT = {".md", ".json", ".log", ".txt", ".html", ".py"}
SMALL_TABLE_BYTES = 2_000_000


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> dict:
    copied, left = [], []
    for d in DIRS:
        for p in sorted((LIVE / d).rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(LIVE)
            in_data_dir = any(part in DATA_SUBDIRS for part in rel.parts[1:-1])
            top_level_table = len(rel.parts) == 2 and p.suffix in (".csv",) and p.stat().st_size <= SMALL_TABLE_BYTES
            if (p.suffix in DOC_EXT and not in_data_dir and p.suffix != ".pid") or top_level_table:
                out = DEST / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, out)                       # read-only copy; source untouched
                copied.append({"path": str(rel).replace("\\", "/"), "sha256": sha256(p), "bytes": p.stat().st_size})
            else:
                left.append({"path": str(rel).replace("\\", "/"), "sha256": sha256(p), "bytes": p.stat().st_size})
    for p in EXTRA_CODE:
        if p.exists():
            rel = p.relative_to(LIVE)
            out = DEST / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)
            copied.append({"path": str(rel).replace("\\", "/"), "sha256": sha256(p), "bytes": p.stat().st_size})
    inv = {"rescued_utc": datetime.now(timezone.utc).isoformat(), "source": str(LIVE),
           "acquisition_code": {"task93_canonical_v1": "NOT_FOUND in any worktree or remote branch",
                                "task95a": "NOT_FOUND", "task95b_daily_v1": "NOT_FOUND",
                                "task95g_sp500_daily_v1": "NOT_FOUND",
                                "task97": "FOUND results/task97_catalyst_displacement/_build_task97_dataset.py (copied)"},
           "copied": copied, "data_files_left_behind": left,
           "left_behind_total_bytes": sum(x["bytes"] for x in left)}
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "INVENTORY.json").write_text(json.dumps(inv, indent=1))
    return inv


if __name__ == "__main__":
    r = main()
    print(json.dumps({"copied": len(r["copied"]), "left_behind": len(r["data_files_left_behind"]),
                      "left_behind_GB": round(r["left_behind_total_bytes"] / 1e9, 2)}, indent=1))
