"""Verify Task 83-R1 evidence working bytes against one committed content SHA.

This is the pre-manifest gate: it builds the would-be LF-normalized artifact
inventory in memory and compares every item with the blob at ``content_commit``.
It never writes the final evidence manifest.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_REL = Path("results/task83_r1_production_collector_closure")
GENERATOR = ROOT / EVIDENCE_REL / "_make_manifest.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("task83_r1_manifest_generator", GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_task83_r2_content_commit.py <content_commit>", file=sys.stderr)
        return 2
    content_commit = sys.argv[1]
    commit = subprocess.run(
        ["git", "cat-file", "-e", f"{content_commit}^{{commit}}"], cwd=ROOT,
        capture_output=True,
    )
    if commit.returncode != 0:
        print(f"content commit unavailable: {content_commit}", file=sys.stderr)
        return 2

    payload = _load_generator().build(content_commit)
    mismatches: list[str] = []
    checked = 0
    for artifact in payload["artifacts"]:
        rel = (EVIDENCE_REL / artifact["file"]).as_posix()
        blob = subprocess.run(
            ["git", "cat-file", "-p", f"{content_commit}:{rel}"], cwd=ROOT,
            capture_output=True,
        )
        if blob.returncode != 0:
            mismatches.append(f"{artifact['file']}: not in content commit")
            continue
        normalized = blob.stdout.replace(b"\r\n", b"\n")
        checked += 1
        if len(normalized) != artifact["bytes"]:
            mismatches.append(
                f"{artifact['file']}: bytes {len(normalized)} != {artifact['bytes']}"
            )
        digest = hashlib.sha256(normalized).hexdigest()
        if digest != artifact["sha256"]:
            mismatches.append(
                f"{artifact['file']}: sha256 {digest} != {artifact['sha256']}"
            )

    result = {
        "content_commit": content_commit,
        "declared": payload["file_count"],
        "checked": checked,
        "mismatches": mismatches,
    }
    print(json.dumps(result, indent=2))
    return 0 if checked == payload["file_count"] and not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
