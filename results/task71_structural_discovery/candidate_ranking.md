# Task71 Candidate Ranking

Full data: `candidate_ranking.csv`. Reproducing the task's own Part 21
nomination bar verbatim (not loosened):

> Candidate must collectively demonstrate on DEVELOPMENT: 1. coherent
> structural/economic mechanism; 2. causal implementation; 3. positive
> economic expectancy at realistic friction; 4. meaningful margin above
> friction rather than barely surviving; 5. adequate event count; 6. broad
> symbol/day participation; 7. acceptable concentration; 8. stable sign
> across development slices; 9. long/short side independently justified;
> 10. neighboring parameter stability; 11. no critical provider-portability
> blind spot; 12. no obvious dependence on one market event; 13. explicit
> horizon; 14. plausible stop/risk semantics OR STOP_UNRESOLVED clearly
> stated; 15. no critical data-integrity issue.

## Result: exactly one candidate clears the bar

**FAMILY_C_RESIDUAL_MOMENTUM, LONG side only** —
`PRIMARY_CANDIDATE_READY_TO_FREEZE`. See `primary_candidate_draft.{json,md}`
for the full nomination writeup against all 15 conditions.

## Everything else: rejected, none rise even to RESEARCH_LEAD_ONLY

- **Family A (AVWAP)**: near-zero gross expectancy in all 24 predeclared
  cells (both continuation and reversion bets, both extension sides, both
  threshold bands, all 3 horizons) — net negative everywhere at 10bps, PF
  well under 1 throughout. No structural edge found in either direction.
  Clean, uninteresting rejection.
- **Family C, SHORT side**: negative gross and net in most time segments
  and regimes — the mirror-image bet to the LONG candidate above does NOT
  work. Per the task's own instruction, this does not disqualify the LONG
  side; LONG_ONLY is an explicitly valid candidate shape.
- **Family B (overnight gap continuation)**: 18 of 20 cells net-negative.
  The two nominally-positive cells (LONG @1.0/3-DAY-CLOSE, SHORT
  @1.0/EOD) are each immediately adjacent (same threshold/direction) to a
  STRONGLY negative cell at a neighboring horizon (NEXT_DAY_CLOSE at
  -0.43%/-0.46% net, 120m/180m at -0.13% to -0.25% net respectively) — this
  is exactly the "isolated winner surrounded by failures" pattern Part 12
  instructs to down-rank, not an isolated statistical fluke to chase.
  Rejected without further chasing.
- **Family D (failed structural break)**: the structurally-correct-signed
  side (SHORT after a failed break above prior-day high) has small
  positive gross expectancy in 3 of 4 regime slices, but net expectancy is
  negative at 10bps in **every single time segment and every single
  regime slice** — it never once clears realistic friction. The mirror
  side (LONG after failed break below prior-day low) is wrong-signed in 3
  of 4 regimes. Neither side qualifies even as a research lead — there is
  no margin-above-friction anywhere to build on.

## Why no second family is recorded as RESEARCH_LEAD_ONLY

Part 21 allows recording one additional research lead; it does not
require one. None of A/B/D showed a corroborated, cost-surviving signal in
more than an isolated cell, and Part 13's own multiple-testing discipline
requires exactly this kind of isolated-cell result to be downgraded, not
promoted to "worth watching." Recording a lead here would repeat the
pattern this task's forensic audit (Part 1) diagnosed as F6's own failure
mode — nominating a single passing cell out of many without asking whether
its neighbors agree. None do, so none is recorded.
