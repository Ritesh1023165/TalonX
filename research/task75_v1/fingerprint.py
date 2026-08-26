"""Task75A Part 9 -- canonical fingerprint of the frozen V1 contract PLUS
the full freeze document set (risk policy, portfolio construction,
execution costs, validation protocol, holdout lock) so that a later
session can verify NOTHING in the frozen specification changed before
trusting any validation output.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research.task75_v1.contracts import contract_dict

RESULTS_DIR = Path(__file__).resolve().parents[2] / "results" / "task75_cross_sectional_extreme_winner_short_reversion"
COVERED_DOCS = [
    "risk_policy.json", "portfolio_construction.json", "execution_cost_contract.json",
    "validation_protocol.json", "holdout_lock.json", "calendar_session_contract.json",
]


def _read_json(name: str) -> dict:
    path = RESULTS_DIR / name
    return json.loads(path.read_text()) if path.exists() else {"_missing": name}


def compute_fingerprint() -> str:
    payload = {
        "contract": contract_dict(),
        "documents": {name: _read_json(name) for name in COVERED_DOCS},
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_contract_only_fingerprint() -> str:
    """Fingerprint of ONLY the strategy contract (Part 2), independent of
    the freeze documents -- used by tests that don't want to depend on
    results/ file contents existing on disk."""
    payload = json.dumps(contract_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
