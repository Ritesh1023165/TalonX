"""Task72 Part 7 -- canonical fingerprint of the frozen strategy contract.
Same pattern as research/task68_f6/fingerprint.py: sha256 over a
canonical (sorted-keys, no whitespace-ambiguity) JSON serialization of the
contract dict. Any semantic change to contracts.py changes this hash --
downstream validation/replication code MUST verify the fingerprint it
recomputes matches the one recorded in strategy_freeze.json before
trusting anything else.
"""
from __future__ import annotations

import hashlib
import json

from research.task72_residual_momentum.contracts import contract_dict


def compute_fingerprint() -> str:
    payload = json.dumps(contract_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
