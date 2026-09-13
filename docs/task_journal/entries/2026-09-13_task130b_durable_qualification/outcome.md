# Outcome

**Verdict: `PASS_FOR_INTEGRATION_REVIEW`** (reaffirmed a third time,
now on a durable, accession-level-identity-verified, session-phased
implementation). **Integration remains HOLD. Production remains
paused.** This is not a deployment recommendation.

## What changed from Task 130A

1. **Identity**: the 60-day-grace date-range heuristic is replaced by
   an exact accession-level evidence chain for all 8 traded ambiguous
   symbols — all `VERIFIED_CONSISTENT`. A CIK zero-padding bug in Task
   130A's own reconciliation script is fixed, reducing the
   population-wide unresolved-identity count from 14/35 to 11/35 (0 of
   which are traded).
2. **Durability**: state is now real, committed SQLite (`V2Store`,
   isolated path), verified by genuine close/reopen and 10 failure-
   path tests, not an in-memory convenience.
3. **Event ordering**: four explicit session phases (OPEN/CLOSE/
   POST-CLOSE/MARK) structurally, not just documentally, prevent
   same-day filing information from funding that morning's own
   entries.
4. **Missing-price recovery**: a bounded (5-session), idempotent retry
   now defers rather than immediately expiring a timely intent.
5. **Valuation accounting**: study-cutoff and tail-inclusive equity/
   drawdown are now reported separately; an invested-capital/equity
   exposure ratio (12.07%) is now computed alongside the existing
   day-occupancy measure (89.62%).

## What did not change

The economic result: N=153, net +2.0219%/round trip, both bootstrap
CIs exclude zero and agree, both concentration tests stay positive
through top-5, 2026H1 remains the sole negative half-year, drawdown
−2.7478% (identical peak/trough dates to Task 130A). **Episode-for-
episode identical to Task 130A — explained (capacity was never
binding under either implementation in this specific window/
population), not assumed as general equivalence.** The repairs this
task adds are demonstrated to work by the Part 6 synthetic failure-
path tests, not by this real run (which never exercises capacity
contention or a missing price).

## Disclosed, not fixed

A real characteristic of the frozen, already-deployed `cluster_engine`
was found: its greedy window-consumption can silently drop later,
otherwise-independent filings that fall within the same 10-trading-
day window as an already-activated cluster, without forming a second
episode. This affects population coverage, not the identity or
pricing of any admitted trade. No algorithm change is in scope and
none was made.

## Full evidence

`docs/research/{TASK130B_QUALIFICATION_ADDENDUM,TASK130B_DURABLE_LIFECYCLE_ACCEPTANCE,TASK130B_CORRECTED_ECONOMIC_DECISION}.md`;
`docs/research/evidence/task130b/`; `research/scripts/task130b_*.py`;
`tests/test_task130b_durable_replay.py`.
