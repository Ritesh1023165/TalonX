# Claude Handoff -- after Task74B

## Immediate next priority

**Task75: freeze `CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION`** (see
`primary_candidate_draft.{json,md}`). Do not re-run Task74B's discovery
grid, do not tune any of the 6 already-positive REVERSAL/SHORT cells,
and do not chase the LONG mirror, MOMENTUM hypothesis, or Family A
again -- those are cleanly closed (REJECTED_INSTABILITY,
REJECTED_NO_EDGE, REJECTED_COST/REJECTED_SAMPLE respectively).

## What Task75 specifically needs to decide/do

1. **Pick exact frozen parameters** from the 6 already-computed
   REVERSAL/SHORT cells. `loose/3D` is recommended (the only cell where
   BOTH cluster bootstraps exclude zero: symbol [0.068, 1.271], day
   [0.034, 1.201]) over `loose/5D` (bigger raw edge, 0.706% vs 0.507%,
   but its day-cluster CI crosses zero) -- prefer the more defensible
   cell, not the biggest number, matching the same principle Task72
   itself used when picking 0.75% over 1.50% threshold.
2. **Design and freeze a stop**, using DEVELOPMENT data only --
   `risk_diagnostics.csv` gives median MAE ~2.3-3.4x (in units of 1% of
   entry price) and MFE ~2.7-3.7x for the relevant cells. Multi-day
   holding means overnight-gap risk matters more than for an intraday
   candidate -- consider whether a stop even makes sense for a 3-day
   SHORT position, or whether a different risk control (position size
   cap, max adverse days) is more appropriate. Do not choose a stop by
   maximizing DEVELOPMENT P&L.
3. **Pre-register a validation protocol** BEFORE touching any holdout.
   This candidate's disclosed weaknesses are: (a) SHORT-only asymmetry,
   (b) one of four regimes negative, (c) weak EARLY segment. The
   day-cluster CI DOES exclude zero at the anchor cell (unlike the
   rejected residual-momentum candidate) but the margin is thin (lower
   bound 0.034) -- validation should still explicitly emphasize
   day-level breadth.
4. **Lock a genuinely untouched holdout.** Two reserved 2024 blocks
   already exist and were NOT touched by Task74B:
   - RESERVED VALIDATION: `2024-06-01 .. 2024-09-02`
   - RESERVED REPLICATION: `2024-10-21 .. 2024-12-20`
   Re-verify this inventory yourself (don't just trust this note) before
   locking -- confirm no other task touched them between Task74B's
   commit and whenever Task75 runs.

## If you're asked "why didn't Task74B try harder on Family A or the LONG mirror"

Don't. Family A's REVERSAL hypothesis had attractive point estimates but
only 25-48 trades per cell with BOTH cluster bootstrap CIs crossing zero
at every single cell -- exactly the small-sample pattern Task71's own
forensic audit (`failure_forensics.md`) diagnosed as this program's
biggest historical failure mode. The LONG mirror of the winning
REVERSAL/SHORT finding flips sign at the 2D horizon and never excludes
zero on either cluster axis despite 351-903 trades -- a much weaker
statistical position than the SHORT side, not a matter of needing more
data.

## If you're asked about the day-cluster CI margin

It's thin (0.034 lower bound at the anchor cell) but it DOES exclude
zero -- a genuinely stronger position than the rejected residual-
momentum candidate ever achieved (its day-cluster CI crossed zero at
EVERY cell). Still, with "only" 125 distinct days and multi-day holding
periods that create overlapping exposure windows, day-level dependence
remains the single most important thing for Task75's validation to
stress-test.

## Files worth reading first

- `task74b_summary.md` (this task's full narrative)
- `primary_candidate_draft.md` (the nomination)
- `candidate_ranking.md` (why everything else was rejected, in detail)
- `research_design_lock_v2.md` (the locked mechanism definitions)
