# Record

## Baseline verification (start of task)

- Research branch HEAD: `738d101796dc1353c5dfa65b192ddb79a20ee905`
  (matches expected exactly).
- Release worktree HEAD: `f28986999eec5e313cfc89db24e4dbacfb378891`
  (matches expected exactly), clean throughout this task. Neither
  branch reset.

## Actions taken, in order

1. Wrote and committed `docs/research/TASK130B_QUALIFICATION_ADDENDUM.md`
   (commit `ed5ec91`, pushed) BEFORE any corrected return was
   computed — exact defects repaired from Task 130A (60-day-grace
   identity heuristic, a CIK zero-padding bug, in-memory-only state,
   implicit rather than structural event ordering, unbounded
   missing-price expiry, no restart tests), identity evidence
   requirements, durable transaction boundaries, the explicit
   session-phase simulated-clock model, missing-price policy,
   study-window/tail boundary, and unchanged acceptance rules. Also
   recorded a new, disclosed (not fixed — out of scope) characteristic
   of the frozen `cluster_engine`: its greedy window-consumption can
   silently drop same-window later filings after a cluster has already
   activated, verified directly with a minimal reproducible script,
   not inferred.
2. Wrote `research/scripts/task130b_accession_identity.py` (Part 2) —
   removes the 60-day-grace heuristic entirely: for each of the 8
   traded ambiguous symbols, re-runs the real, unmodified
   `detect_episodes_for_issuer` on that symbol's own records and
   recovers the EXACT constituent Form 4 rows that formed the winning
   episode. All 8 (CZR, DOC, LB, MRVL, MTCH, PCG, TPL, WTW) classify
   `VERIFIED_CONSISTENT`.
3. Wrote `research/scripts/task130b_durable_replay.py` — a new,
   isolated, `V2Store`-backed (unmodified import, existing schema,
   isolated SQLite path, hard-refused against the live ledger path)
   driver with four explicit session phases (OPEN/CLOSE/POST-CLOSE/
   MARK) per simulated session, a bounded idempotent missing-price
   retry, and a study-cutoff/settlement-tail boundary.
4. Wrote `tests/test_task130b_durable_replay.py` (10 tests) using
   REAL temporary SQLite files. Bugs found and fixed before any result
   was trusted: (a) `V2Store.append_trade()`'s SELL-side call was
   missing the required `position_cost` kwarg; (b) the store-level
   durability test's own `ClusterEpisode`/`V2Decision` construction was
   missing several required fields (fixed to match the real dataclass/
   schema exactly); (c) the cold-start test's original dates
   accidentally fell inside one 10-trading-day cluster window, merging
   into a single episode instead of two — root-caused by directly
   inspecting `detect_episodes_for_issuer`'s own output for the test's
   4 synthetic records (this is what surfaced the disclosed
   `cluster_engine` characteristic recorded in the addendum), then
   fixed by spacing the two clusters beyond the window and asserting
   the REAL resulting disposition (`SKIPPED_ENTRY_STALE`, not the
   originally assumed `SKIPPED_NO_PRIOR_INTENT`); (d) the
   same-session-funding test's original natural-cluster-formation
   approach could not construct a genuinely open FFF position within
   the staleness grace window — repaired per the task's own
   instruction by seeding an already-open position directly into the
   store (`insert_open_position` + a synthetic `append_trade`) and
   reasoning through the driver's actual reservation-gate design (a
   competing intent's reservation is rejected AT CREATION time, before
   FFF's cash was ever freed — a stronger demonstration of the same
   safety property than the original design assumed). **10/10 pass.**
5. Ran the real evaluation (~4 minutes; `V2Store`'s real SQLite
   commits are slower than Task 130A's in-memory driver) over the full
   frozen window (2024-09-01 → 2026-03-31, plus a 20-session
   settlement tail) on the unchanged 626-name Discovery Universe v1.
6. Wrote `research/scripts/task130b_stats.py` (reuses `compute_stats`,
   unmodified import from `task130a_identity_and_stats.py`) and
   `task130b_episode_comparison.py` (Part 9 per-episode diff against
   Task 130A's 153 trades).
7. Wrote `research/scripts/task130b_full_identity_classification.py`
   (Part 3) — classifies ALL 35 ambiguous symbols in the population
   (reusing `reconcile_identities`, unmodified import, for the base
   date-range evidence), overlaid with the true accession-level
   evidence for the 8 traded symbols. Result: 8 `VERIFIED_CONSISTENT`,
   0 `VERIFIED_ERROR_REQUIRING_CORRECTION`, 11 `UNRESOLVED` (down from
   Task 130A's 14, closing the CIK-padding bug), 16
   `NOT_TRADED_DATE_RANGE_CONSISTENT` (explicitly not claimed
   accession-verified, since no trade ever exercised them).
8. Computed the per-episode comparison: the durable driver's own 153
   closed trades are EPISODE-FOR-EPISODE IDENTICAL to Task 130A's 153
   (same episode_ids, timing, quantity/cost, P&L, identical daily-
   marked drawdown −2.7478% with identical peak/trough dates). Explained
   (not assumed): capacity was never binding under either
   implementation in this window/population (no
   `SKIPPED_INSUFFICIENT_CAPACITY` ever fires); this task's own
   durability/session-phasing repairs specifically matter under
   capacity contention or missing-price gaps, neither of which the
   real dataset happens to trigger — demonstrated instead by the
   synthetic Part 6 failure-path tests.
9. Computed study-cutoff vs. tail-inclusive accounting (Part 8) for
   the first time: 2 positions open at the 2026-03-31 cutoff (equity
   $330,840.98), both settled naturally within the 20-session tail (0
   open/0 unresolved after, equity $330,935.40). Computed the
   invested-capital/equity exposure ratio for the first time (12.07%,
   distinct from the existing 89.62% day-occupancy measure).
10. Wrote `docs/research/TASK130B_DURABLE_LIFECYCLE_ACCEPTANCE.md`
    (Parts 4-8) and `TASK130B_CORRECTED_ECONOMIC_DECISION.md` (Parts
    2-3, 8-10's comparison and separate-gate verdict table).
11. Copied compact evidence (`summary.json` 1.2KB, `corrected_stats.json`
    2.2KB, `funnel_counts.json` 0.2KB, `episode_comparison.json` 66KB,
    `closed_trades.json` 62KB, `classification_summary.json` 0.3KB,
    `full_identity_classification.json` 119KB — `daily_marks.json`
    156KB, `audit_log.json` 72KB, and `accession_evidence_chains.json`
    80KB stay local only, over this program's evidence-size
    convention) to `docs/research/evidence/task130b/`.
12. Updated `docs/research/PRODUCT_STATUS.md` (header, the V2
    Discovery Universe v1 row, and the full-evidence links section)
    and `docs/research/TALONX_RESEARCH_LEDGER.md` (new Task 130B
    entry) minimally — no other product/ledger content touched.
13. Re-verified production/Redis/process preservation (same result as
    baseline).

## Production preservation (end of task)

Unchanged from baseline — no process started, no port opened, Redis
`talonx:*` key count still 0, release worktree still clean at
`f28986999eec5e313cfc89db24e4dbacfb378891`. The durable SQLite ledger
this task's driver wrote to (`results/task130b_durable_replay/task130b_full_replay.db`)
is a git-ignored, local-only research artifact at an explicitly
isolated path — never `v2_lane.db`, verified both by the driver's own
`assert_research_ledger_path` hard refusal and by direct inspection.
