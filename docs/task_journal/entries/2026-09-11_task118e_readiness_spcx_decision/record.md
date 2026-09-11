# Task 118E — readiness recovery, SPCX freshness, one research decision

## Objective and acceptance criteria
Resolve/investigate three specific limitations (readiness gap, SPCX price
staleness, Task118D accounting clarity) and end with one concrete research
decision (ONE_TESTABLE_HYPOTHESIS or NO_SUPPORTED_STRATEGY_CHANGE).

## Timing
- UTC start: 2026-09-11T15:21 (baseline re-verification)
- UTC end: 2026-09-11T~15:35 (all parts complete, pushed; session live,
  pre-EOD)

## Branch / SHA
- Release: unchanged, `0209ada` / code `c88f4d4` (no defect proven → no
  restart).
- Research: `355eb16` → this entry.

## Requested vs. completed scope
- Part 1 (readiness gap): **DONE** — 25/43 ready live (up from 24), 18
  not-ready with rate-estimated ETAs (60–80 min for the worst laggers).
- Part 2 (bounded recovery): **DONE, no action taken** — reasoned
  decision not to build/deploy a new backfill mechanism given the time
  available to safely test it against this task's own strict safety
  requirements (no retrospective signals, no replayed historical exits);
  natural recovery already bounded and in progress.
- Part 3 (SPCX): **DONE** — traced full path, found the 25-min-old mark
  was a report-snapshot limitation, not a defect; fresh mark (~2 min old)
  and updated unrealized P&L reported; realized P&L reconfirmed unchanged.
- Part 4 (accounting): **DONE** — full episode/entered/closed-round-trip/
  BUY-SELL-row reconciliation at every level, C=A+B verified exactly at
  both the total-disposition and ENTERED levels; one predeclared
  time-dependence (month-of-entry) sensitivity run, found the A-vs-B
  significance conclusion is **not robust** across resampling-unit choice
  — reported honestly, not resolved in either direction.
- Part 5 (composition): **DONE** — one predeclared feature (20-td
  pre-entry realized volatility), sector/size explicitly omitted (no
  PIT source available); A's issuers found at the 96.8th percentile of
  random B-subset volatility — descriptive, not causal.
- Decision: **A. ONE_TESTABLE_HYPOTHESIS** (volatility-conditioned
  expectancy), explicitly labelled exploratory with a genuinely unused
  (future live) confirmation requirement.
- Part 6 (deployment): **not triggered** — no defect proven anywhere in
  this task.
- Part 7 (EOD): not yet due at completion; required operator action
  unchanged.

## Source / runtime / data manifest
`results/task118_profitability/time_block_sensitivity.py`,
`composition_check.py` (both checked in, predeclared methodology stated
in their own docstrings before any result was computed).

## Tests / experiments / results / limitations
No code changed in the live system — no new tests needed. Two new
bounded analyses run (both <10s). Limitations: readiness ETAs are a
linear extrapolation from two spaced snapshots, explicitly uncertain; the
composition check is a 6-issuer descriptive association, not causal.

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Operational verdict: runtime unchanged; SPCX/readiness both confirmed
  healthy/recovering, not defective.
- Profitability verdict: unchanged/inconclusive — the composition finding
  is descriptive, not a profitability claim; the time-block sensitivity
  shows the A-vs-B difference conclusion is method-sensitive, reinforcing
  caution rather than resolving it.

## Production effects, external sends, protected-state checks
Zero production writes — all reads read-only; the two new analysis
scripts ran against already-collected historical data (research worktree)
and read-only live queries (release worktree). No Redis mutation, no
external send, no strategy/config change.

## Findings
- Fixed: none (no defect found).
- Open: whether the volatility-conditioned hypothesis holds under future
  live data (Part 5's decision); the 18 not-yet-ready symbols' actual
  readiness time (estimated, not observed to completion).
- Deferred: none new.

## Evidence links
`docs/research/TASK118E_READINESS_SPCX_DECISION.md`;
`results/task118_profitability/{time_block_sensitivity.py,composition_check.py}`
+ outputs.

## Later corrections
None yet.
