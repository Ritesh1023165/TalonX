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
V2_FINGERPRINT_EXPECTED = "e2acf6454789217e"
# RI-1 (V2 Release Integration Task RI-1): updated from "11107198c5b81237".
# `talonx_v2/config.py` -- one of the 5 files this fingerprint covers -- gained
# two new fields, `campaign_id`/`execution_mode` (default "V2"/"PAPER",
# reproducing the existing production campaign's identity exactly): account/
# operational identity, the SAME category as the already-present, already-
# NOT-frozen `starting_cash_usd`/`per_position_allocation_usd` fields just
# above them (see that field's own docstring: "operational, NOT a research
# lever"). Neither new field is asserted by `V2Config.validate_frozen()`, and
# neither appears in `v2_release_fingerprint()`'s own hashed `cfg` dict (only
# the STRATEGY-semantic fields are individually hashed there) -- confirmed
# unchanged, byte-for-byte, before and after this edit:
#   cluster_window_trading_days=10, min_distinct_owners=2, transaction_code=
#   'P', direction='BULLISH', entry_offset_sessions=1, hold_trading_days=10,
#   stop_loss_enabled=False, max_concurrent_positions=20,
#   reentry_cooldown_trading_days=5, liquidity_lookback_sessions=20,
#   liquidity_min_median_dollar_volume=5000000.0, liquidity_min_close=5.0,
#   exit_fallforward_max_sessions=5, max_entry_staleness_sessions=3.
# Only the FILE'S OWN BYTES changed (two new dataclass fields added), which
# this fingerprint also hashes directly (`_STRATEGY_FILES` includes
# `config.py` in full) -- an intentional, disclosed, non-strategy change,
# exactly the same class of update Task 137 already made to
# `V1_FINGERPRINT_EXPECTED` below (a legitimate, already-authorized change to
# a fingerprinted file, confined to non-gating/non-entry/non-scoring
# concerns). Recomputed directly via
# `research/scripts/task112_v2_release_fingerprint.py`, not guessed.
# Task 137: updated from the stale "2ae6216bca70". Investigated a reported
# mismatch (get_strategy_version() read "2dea67a6f6d2" against this
# constant) with a full per-file comparison across the baseline commit
# (18e93d9, where this constant was first set), the current committed git
# blobs, and the working-tree bytes. Two DISTINCT, separately-confirmed
# causes, not one:
#   1. Line-ending representation -- the working tree materialises these
#      files with CRLF (Windows `core.autocrlf`); the committed git blobs
#      are pure LF. Fixed at the source: get_strategy_version() (talonx_
#      backtest/reproducibility.py) now LF-normalizes before hashing, the
#      same technique tests/test_task65b_protected_fingerprints.py already
#      uses for the other two frozen-candidate fingerprints in this repo.
#   2. A REAL, substantive, already-authorized change: commit 66a49f9
#      ("Task 135 -- surface Redis PUBLISH subscriber count for Quant
#      signals", 2026-09-14) modified talonx_quant/consumer.py -- one of
#      the 5 files this fingerprint covers -- after this constant was
#      frozen. That commit's own message incorrectly claimed no
#      fingerprinted file was touched; it was, but the change is confined
#      to Pub/Sub delivery-observability logging/metrics AROUND an
#      already-decided signal publish (QuantScanner._publish_signal),
#      not any gating/entry/opportunity-scoring logic. Not reverted here
#      (it was a legitimate, tested, already-pushed fix) -- this constant
#      is corrected to the new, current, LF-normalized baseline instead:
#      "ed8272fe568d" (== git show HEAD:talonx_quant/{strategy,
#      indicators,config,session,consumer}.py concatenated, LF-normalized
#      sha256, first 12 hex chars -- reproducible from git alone).
V1_FINGERPRINT_EXPECTED = "ed8272fe568d"
V2_STRATEGY_VERSION = "INSIDER_BUY_CLUSTER_V2@1"

CAMPAIGN_START_DATE = "2026-09-08"          # Day 1 = Task 113
CAMPAIGN_STARTING_CASH = 300_000.0

__all__ = [
    "RELEASE_SHA_EXPECTED", "V2_FINGERPRINT_EXPECTED", "V1_FINGERPRINT_EXPECTED",
    "V2_STRATEGY_VERSION", "CAMPAIGN_START_DATE", "CAMPAIGN_STARTING_CASH",
]
