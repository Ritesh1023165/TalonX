"""Task 83-R1 §6.9/§6.10 -- evidence manifest generator.

Hashes GIT-NORMALIZED (LF) bytes so a manifest committed on Windows
(CRLF working tree) still verifies from a fresh Linux clone, and vice
versa. Records the implementation/evidence CONTENT commit explicitly
(passed as argv[1] or read from the env) rather than a self-referential
final SHA. Excludes this generator and the manifest itself.

    .venv/Scripts/python.exe results/task83_r1_production_collector_closure/_make_manifest.py <content_commit_sha>
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "evidence_manifest.json"
EXCLUDED = {"evidence_manifest.json", "_make_manifest.py"}


def _lf_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _sha256_lf(path: Path) -> str:
    return hashlib.sha256(_lf_bytes(path)).hexdigest()


def _byte_len_lf(path: Path) -> int:
    return len(_lf_bytes(path))


def build(content_commit: str | None) -> dict:
    artifacts = []
    for p in sorted(HERE.rglob("*")):
        if not p.is_file() or p.name in EXCLUDED:
            continue
        # transient / non-committed files are never part of the manifest
        if "__pycache__" in p.parts or p.suffix in {".pyc", ".pyo"} or p.name.endswith(".tmp"):
            continue
        artifacts.append({
            "file": p.relative_to(HERE).as_posix(),
            "bytes": _byte_len_lf(p),
            "sha256": _sha256_lf(p),
        })
    return {
        "task": "Task 83-R1 Production Collector Correctness and Evidence-Integrity Closure",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "algorithm": "sha256 over git-normalized (LF) bytes",
        "content_commit": content_commit or os.getenv("TASK83R1_CONTENT_COMMIT") or "UNSET",
        "excluded": sorted(EXCLUDED),
        "note": (
            "Hashes are over LF-normalized bytes so this manifest verifies from a "
            "fresh clone regardless of the checkout's line-ending policy. "
            "content_commit is the code/evidence commit these hashes describe -- "
            "this manifest and its generator are excluded to avoid a self-referential SHA."
        ),
        "file_count": len(artifacts),
        "artifacts": artifacts,
    }


def main() -> int:
    content_commit = sys.argv[1] if len(sys.argv) > 1 else None
    payload = build(content_commit)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({payload['file_count']} files, content_commit={payload['content_commit']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
