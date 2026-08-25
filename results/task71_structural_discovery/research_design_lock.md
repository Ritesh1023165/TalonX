# Task71 Research Design Lock

Locked **before** any new Task71 family outcome is computed. See
`research_design_lock.json` for the machine-readable version — this is
the human-readable companion.

## Four families, no fifth

- **A — AVWAP_FLOW_STATE**: continuation vs. reversion around a causal
  session-anchored VWAP. 4 directions (never pooled): continuation-long,
  continuation-short, reversion-long, reversion-short.
- **B — OVERNIGHT_GAP_CONTINUATION** (not "PEAD" — see `event_data_audit.json`):
  overnight gap persistence into the regular session. 2 directions.
- **C — IDIOSYNCRATIC_RESIDUAL_MOMENTUM**: causally-estimated market-model
  residual persistence. 2 directions.
- **D — FAILED_STRUCTURAL_BREAK**: reversal after a failed penetration of
  prior-day high/low. 2 directions.

No fifth family is declared. The forensic audit (Part 1) did not surface a
materially new structural opportunity outside these four.

## Predeclared grid (72 cells total — see json for the exact breakdown)

Coarse, not fine: 2 threshold/parameter bands per family, 3-5 horizons per
family depending on what's structurally sensible (not every family through
every horizon). This bounds multiple-testing exposure by construction and
is reported in full in `multiple_testing_summary.json` regardless of which
cells look interesting.

## Cost levels

0 / 5 / 10 / 15 / 20 bps round-trip, every family, every direction.

## Development data policy

Broaden DEVELOPMENT using already-contaminated 2025-01-24..2026-08-14
history only (see `development_universe_audit.json`/
`development_data_manifest.json`). All remaining clean 2024 territory is
never touched — enforced by a `DevelopmentOnlyGuard` (tested).

## Stability tests

Time-stability (early/middle/late + regime slices), parameter-response
surfaces (prefer broad plateau over sharp optimum), dependence diagnostics
(cluster-by-symbol AND cluster-by-day, report the weaker), concentration
(top1/top3 symbol and day).

## Nomination

At most one `PRIMARY_CANDIDATE_READY_TO_FREEZE`, at most one additional
`RESEARCH_LEAD_ONLY`. The 15-condition bar from the task's own Part 21 is
reproduced verbatim in `candidate_ranking.md` and not loosened.

## Complexity penalty

Recorded (conditions/parameters/data-sources count) for every surviving
combination — downranks, does not automatically reject.

## Holdout protection

Task70's two consumed 2024 blocks and all remaining clean 2024 territory
are off-limits for the entire duration of this task. Only an inventory of
future candidate holdout periods is produced at the end — zero outcomes
computed against any of it.
