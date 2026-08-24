"""Task 65B Part F/E#18 -- ORPB_V1 and FPRC_V1 implementation fingerprints
remain exactly as frozen at their respective rejection tasks (63P, 60).
Reuses the identical fingerprint computation research/scripts/
task62_freeze_candidate.py and task60_freeze_fprc_v1.py already established
-- not a new definition."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ORPB_FROZEN_FILES = (
    "results/task62_new_alpha_candidate/candidate_spec.md",
    "results/task62_new_alpha_candidate/validation_protocol.md",
    "talonx_quant/orpb_v1.py",
    "talonx_quant/orpb_v1_shadow.py",
)
ORPB_EXPECTED_FINGERPRINT = "b1e283bd36eb0cb2ecc5303b104ec2bd8defc60f6eacef4879e7711d560d113f"

FPRC_FROZEN_FILES = (
    "results/task59_candidate_architecture_triage/next_candidate_spec.md",
    "talonx_quant/fprc_v1.py",
    "talonx_quant/fprc_v1_shadow.py",
)
FPRC_EXPECTED_FINGERPRINT = "be91c38047cf9aa9dbb6c8a948eaf52dd64ed4b16c7d8a70359388b58e5c2a64"


def _fingerprint(files: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update((ROOT / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def test_orpb_v1_fingerprint_unchanged():
    assert _fingerprint(ORPB_FROZEN_FILES) == ORPB_EXPECTED_FINGERPRINT


def test_fprc_v1_fingerprint_unchanged():
    assert _fingerprint(FPRC_FROZEN_FILES) == FPRC_EXPECTED_FINGERPRINT
