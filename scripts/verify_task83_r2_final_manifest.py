"""Verify the committed Task 83 manifest against content and final blobs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_REL = Path("results/task83_r1_production_collector_closure")
MANIFEST_REL = (EVIDENCE_REL / "evidence_manifest.json").as_posix()


def _blob(commit: str, rel: str) -> bytes | None:
    result = subprocess.run(
        ["git", "cat-file", "-p", f"{commit}:{rel}"], cwd=ROOT,
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def _verify(commit: str, artifacts: list[dict]) -> tuple[int, list[str]]:
    checked = 0
    mismatches: list[str] = []
    for artifact in artifacts:
        rel = (EVIDENCE_REL / artifact["file"]).as_posix()
        raw = _blob(commit, rel)
        if raw is None:
            mismatches.append(f"{artifact['file']}: missing from {commit}")
            continue
        normalized = raw.replace(b"\r\n", b"\n")
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
    return checked, mismatches


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_task83_r2_final_manifest.py <final_commit>", file=sys.stderr)
        return 2
    final_commit = sys.argv[1]
    manifest_raw = _blob(final_commit, MANIFEST_REL)
    if manifest_raw is None:
        print(f"manifest missing from final commit {final_commit}", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(manifest_raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        print(f"committed manifest is corrupt: {exc}", file=sys.stderr)
        return 2

    content_commit = manifest.get("content_commit")
    artifacts = manifest.get("artifacts")
    declared = manifest.get("file_count")
    if not content_commit or content_commit == "UNSET" or not isinstance(artifacts, list):
        print("committed manifest lacks content identity or artifacts", file=sys.stderr)
        return 2
    if declared != len(artifacts):
        print(f"manifest declares {declared} but lists {len(artifacts)}", file=sys.stderr)
        return 1

    content_checked, content_mismatches = _verify(content_commit, artifacts)
    final_checked, final_mismatches = _verify(final_commit, artifacts)
    result = {
        "final_commit": final_commit,
        "content_commit": content_commit,
        "declared": declared,
        "content_checked": content_checked,
        "final_checked": final_checked,
        "content_mismatches": content_mismatches,
        "final_mismatches": final_mismatches,
    }
    print(json.dumps(result, indent=2))
    return 0 if (
        content_checked == declared
        and final_checked == declared
        and not content_mismatches
        and not final_mismatches
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
