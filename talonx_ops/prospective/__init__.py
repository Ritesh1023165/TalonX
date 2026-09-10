"""
talonx_ops.prospective -- autonomous prospective V2 campaign operator (Task 114B)
==============================================================================
One command in the morning, one command in the evening; unattended during
the session with automatic machine-readable checkpoints + event
classification.

  python -m talonx_ops.prospective start      # preflight + start + verify + spawn checkpoint daemon
  python -m talonx_ops.prospective close      # final checkpoint + EOD reconcile + report + graceful shutdown
  python -m talonx_ops.prospective checkpoint # one-shot checkpoint to stdout
  python -m talonx_ops.prospective status     # quick health/data/activity read
  python -m talonx_ops.prospective session-loop --session-dir ...   # (internal) the checkpoint daemon

Deterministic only -- NO AI in runtime supervision.  Reuses the
authoritative supervisor / EOD reconciliation / V2 store / dashboard
read model; does not reimplement strategy math.  Never resets, recreates
or reseeds ``v2_lane.db`` -- fails closed on ledger-integrity problems.
"""
from __future__ import annotations

RELEASE_SHA_EXPECTED = "0d52e7c"  # Task 117 final activation release
V2_FINGERPRINT_EXPECTED = "11107198c5b81237"
V1_FINGERPRINT_EXPECTED = "2ae6216bca70"
V2_STRATEGY_VERSION = "INSIDER_BUY_CLUSTER_V2@1"

CAMPAIGN_START_DATE = "2026-09-08"          # Day 1 = Task 113
CAMPAIGN_STARTING_CASH = 300_000.0

__all__ = [
    "RELEASE_SHA_EXPECTED", "V2_FINGERPRINT_EXPECTED", "V1_FINGERPRINT_EXPECTED",
    "V2_STRATEGY_VERSION", "CAMPAIGN_START_DATE", "CAMPAIGN_STARTING_CASH",
]
