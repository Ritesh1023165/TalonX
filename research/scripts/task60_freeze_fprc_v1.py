"""Reproduce the Task 60 FPRC_V1 implementation freeze evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


BASE_COMMIT = "af3bc97d47b3216f053a09fce533f51509b0c695"
FROZEN_FILES = (
    "results/task59_candidate_architecture_triage/next_candidate_spec.md",
    "talonx_quant/fprc_v1.py",
    "talonx_quant/fprc_v1_shadow.py",
)
CURRENT_CANDIDATE_FILES = (
    "talonx_quant/strategy.py",
    "talonx_quant/indicators.py",
    "talonx_quant/consumer.py",
    "talonx_quant/config.py",
    "talonx_backtest/engine.py",
    "talonx_backtest/execution.py",
)
EXPECTED_FINGERPRINT = "be91c38047cf9aa9dbb6c8a948eaf52dd64ed4b16c7d8a70359388b58e5c2a64"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in FROZEN_FILES:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    frozen = fingerprint(root)
    diff = subprocess.run(
        ["git", "diff", "--name-only", BASE_COMMIT, "--", *CURRENT_CANDIDATE_FILES],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    payload = {
        "base_commit": BASE_COMMIT,
        "frozen_files": {path: sha256(root / path) for path in FROZEN_FILES},
        "implementation_fingerprint_sha256": frozen,
        "fingerprint_matches_freeze": frozen == EXPECTED_FINGERPRINT,
        "current_candidate_diff": diff,
        "current_candidate_zero_drift": not diff,
        "validation_started": False,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["fingerprint_matches_freeze"] and not diff else 1


if __name__ == "__main__":
    raise SystemExit(main())
