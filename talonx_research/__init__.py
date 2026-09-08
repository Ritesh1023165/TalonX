"""
talonx_research -- Strategy Validation & Promotion Framework (Task 115).
====================================================================
Permanent infrastructure so every future strategy change is validated
the same way and CANNOT bypass the promotion gate.

Locked governance (authoritative TalonX strategy governance):

  R1  any semantic change -> a NEW immutable strategy version + new fingerprint;
      an already-promoted version is never mutated in place.
  R2  no version becomes ACTIVE live-paper without >= 2-year chronological
      historical validation of its exact frozen implementation.
  R3  validation covers discovery/holdout, realistic costs, net & holdout
      expectancy > 0, PF > 1, sample size, concentration robustness,
      top-winner removal, drawdown/loss-tail, causal timing, runtime parity,
      practical frequency.  (CI lower bound > 0 is desirable, NOT required for
      initial paper candidacy.)
  R4  research / shadow / active lanes are isolated and NON-BLOCKING -- a
      failure in research/replay/shadow/dashboard never stops or corrupts
      ACTIVE live-paper, the Active V2 ledger, or the official alert path.
  R5  historical replay may exercise signal/Brain/paper/alert-payload, but
      external transport is DRY-RUN ONLY -- it never sends Telegram.
  R6  promotion is explicit: HYPOTHESIS -> DISCOVERY -> FREEZE -> HOLDOUT ->
      2-YEAR EXACT RUNTIME REPLAY -> VALIDATION VERDICT -> SHADOW_ELIGIBLE ->
      LIVE SHADOW -> PROMOTION DECISION -> ACTIVE.  A better number never
      auto-promotes.
  R7  an ACTIVE version keeps rollback / reproducibility.
"""
from __future__ import annotations

PRIMARY_COST_BPS = 20
COST_GRID_BPS = (0, 5, 10, 20, 30, 50)

# frozen references (the currently ACTIVE version -- immutable)
V2_ACTIVE = "INSIDER_BUY_CLUSTER_V2@1"
V2_ACTIVE_FINGERPRINT = "11107198c5b81237"
V1_BASELINE_FINGERPRINT = "2ae6216bca70"

__all__ = ["PRIMARY_COST_BPS", "COST_GRID_BPS", "V2_ACTIVE",
           "V2_ACTIVE_FINGERPRINT", "V1_BASELINE_FINGERPRINT"]
