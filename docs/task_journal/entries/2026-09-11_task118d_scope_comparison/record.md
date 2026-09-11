# Task 118D — matched-scope profitability comparison and session evidence

## Objective and acceptance criteria
Run a runtime-matched A (39-name) vs B (remaining panel) vs C (A∪B)
comparison with proper uncertainty quantification, plus remaining live
readiness/Experimental/delivery evidence, without repeating a broad audit.

## Timing
- UTC start: 2026-09-11T~14:49 (baseline re-verification)
- UTC end: 2026-09-11T~15:05 (comparison + live evidence complete, pushed;
  session still live, pre-EOD)

## Branch / SHA
- Release: unchanged, `0209ada` (no code/runtime touched this task).
- Research: `7551c98` → this entry.

## Requested vs. completed scope
- Part 1 (populations): **DONE** — A=39 (existing), B=587, C=626, run
  fresh under matched runtime; explicit correction that Task 116's
  620-panel could not be reused verbatim (6 of A's names absent from it).
- Part 2 (comparability): **DONE** — B/C run as independent replays, not
  filtered from a shared ledger; capital constraints confirmed non-binding
  for all three at $10M sizing.
- Part 3 (economics + uncertainty): **DONE** — point estimates + issuer-
  block bootstrap (seed 118118, 5000 reps) for A/B/C and A-B/A-C
  differences; A's low block-count (6) caveat stated explicitly.
- Part 4 (product answer + next analysis): **DONE** — recommends a
  composition-characteristic comparison (why A/B differ), using only
  already-collected data.
- Part 5 (live evidence): **DONE** — readiness (24/43), Experimental exact
  reconciliation (4 closes = -$324.4662 exact match, SPCX open with
  timestamped unrealized P&L), delivery by domain, incident carryover
  kept unresolved.
- Part 6 (EOD): not yet due at completion; required operator action
  unchanged.

## Source / runtime / data manifest
`results/task118_profitability/run_populations_bc.py` (B/C replay,
matched runtime verified via `v2_fingerprint()` check before running),
`bootstrap_comparison.py` (uncertainty). Both checked in with outputs
(`reconciliation/population_manifest.json`, `trades_{B,C}.csv`,
`bootstrap_comparison.json`, `baseline_{B,C}_summary.json`).

## Tests / experiments / results / limitations
Two real replays executed (B: 40.8s, C: 34.5s — well within bounded
compute). Limitations: B/C daily equity curves not built (only A's is
published); A's bootstrap CI is low-powered (6 issuer blocks, stated
explicitly); the A-vs-B/A-vs-C difference intervals are marginal, not
decisive.

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Operational verdict: runtime unchanged throughout; session healthy.
- Profitability verdict: A remains inconclusive at its own sample size;
  B (matched runtime, N=147) shows a credibly positive interval; the
  direct A-vs-B difference is negative in point estimate but only
  marginally distinguishable from zero at 95%. Not presented as a
  resolved profitability claim for A.

## Production effects, external sends, protected-state checks
Zero production writes — all replays ran in the isolated research
worktree against frozen historical data; all live-session reads were
read-only. No Redis mutation, no external send.

## Findings
- Fixed: none (research/analysis task).
- Open: whether A's issuer composition differs systematically from B's
  (Part 4's recommended next analysis, not yet run); heartbeat-lapse
  locus and "45 candidates" source (Task 118C, still unresolved, no new
  evidence found).
- Deferred: B/C daily equity-curve construction.

## Evidence links
`docs/research/TASK118D_SCOPE_COMPARISON.md`,
`docs/research/TASK118D_LIVE_EVIDENCE.md`;
`results/task118_profitability/{run_populations_bc.py,bootstrap_comparison.py}`
+ outputs.

## Later corrections
None yet.
