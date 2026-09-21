# Task 75S — Evidence Closure and Non-Tuning Gate Audit

## Stage 0 — Baseline: PASS
Branch/HEAD (`45814d2`)/clean-tree/origin-sync confirmed, no concurrent session. Re-read all Task 74S
evidence. Verified both excluded large telemetry files still present locally, hashes/row counts exact
matches to the committed manifest -- noted explicitly that this proves internal consistency only, not
independent confirmation of the original execution (Task 73S's own saved full-suite log is separately
found to be truncated/incomplete -- see Stage 1).

## Stage 1 — Test collection and dependency closure: PASS (repaired)
Reproduced the reported collection failure exactly before changing anything (2179 collected, 2 errors,
full run aborts with zero tests executed). Root cause: `exchange-calendars==4.13.2` is declared only in
a task-specific requirements file (`research/requirements-task61.txt`), and the two affected test files
lack a skip guard. Could not establish the package was ever previously present in this `.venv`; **Task
74S's "present two days ago, absent now" claim is withdrawn as unsupported** -- the two runs are ~7.5
hours apart on the same calendar day, and site-packages evidence suggests the dependency likely was not
present in the earlier run either. Applied the permitted repair (`pip install -r
research/requirements-task61.txt`, an already-declared/pinned dependency into the project's own venv).
After repair: 2185 collected/0 errors; the two modules' 6 tests pass; **full suite: 2174 passed, 1
skipped, 10 xfailed, 0 collection errors** -- exactly 2168 (Task 74S's `--ignore`'d count) + 6.

## Stage 2 — Scope and provenance audit: PASS with a disclosed qualification
- **Universe (10 vs. 35 symbols): MATCHES REQUESTED SCOPE.** Verified on strong, documented ledger
  provenance. One secondary sentence additionally cited a prior task's (Task 37) outcome as
  corroboration -- flagged as an unnecessary boundary blur, not the actual basis; selection unchanged.
- **Window (full ~1yr vs. the established 2025-08-15..2025-12-31 development-period convention):
  PREREGISTERED BUT WIDER THAN THAT CONVENTION.** Preregistered before execution, but the written
  justification was interpretive, not provenance-grounded like the universe choice.
  **Outcome-invariance confirmed**: the narrower sub-range (1,342 of 5,021 candidates) also shows zero
  trades -- the conclusion is unchanged either way.
- **Holdout exclusion: MATCHES REQUESTED SCOPE**, verified directly against the actual reserved-data
  file manifests (not merely assumed symbol-disjointness) -- zero overlap.

## Stage 3 — Trace of the four surviving candidates: PASS
Reprocessed Task 74S's preserved telemetry only; no rerun of the 1.9M-bar evaluation. All 4 candidates'
exact, authoritative rejection reasons established: STX → `TREND_GATE`; AMD and both PYPL signal_types
→ `CLOSING_BLACKOUT`. Established the actual gate-evaluation order
(`talonx_quant/consumer.py::_GATE_NAMES`), resolving Task 74S's own previously-unresolved question about
AMD's classification (blackout gates are checked before confluence/RR/trend; diagnostic telemetry
computes those values unconditionally regardless) -- not a defect. Full funnel reconciled with
explicit, non-mixed bar-level vs. candidate-level denominators throughout.

## Stage 4 — Non-tuning gate correctness audit: COMPLETE, no defect found
`LOW_VOLATILITY` and `LOW_CONFLUENCE` audited line-by-line (formula, units, threshold source, boundary
semantics, NaN handling, production/replay agreement) and boundary-tested below/at/above each threshold
using both real production telemetry and direct, labeled (`TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE`)
calls to the real, unmodified functions. **Both gates are implemented exactly as documented; no
implementation/specification mismatch found.** No threshold was changed; no recommendation to lower
either gate is made. High rejection rates are not treated as evidence of a defect.

## Stage 5 — Close the evidence
Separate verdicts: environment/test completeness PASS (after repair); scope compliance PASS with the
disclosed window qualification; funnel accounting PASS; gate implementation correctness PASS; research
interpretation confirmed. **Overall**: `NO_ELIGIBLE_LONG_SETUPS_IN_TESTED_DEVELOPMENT_SCOPE` /
`NOT SUITABLE FOR CURRENT SIGNAL-FREQUENCY OBJECTIVE` / `PROFITABILITY_UNDETERMINED`. This is **not**
proof the strategy can never trade or never be profitable. Published
`task74s_evidence_addendum.md` correcting the two overstated claims and disclosing the window
qualification, preserving all original evidence unchanged.

## Verification and git
Protected files/EOD code: zero diff since `848de0d`. Zero holdout/market-download/broker/notification
activity. New audit evidence and the full suite (post-repair) both verified. Dependency repair is an
environment-only change (no repo files modified by it). All evidence committed together (research
evidence + the addendum); no failing code or hidden collection failures.

## Recommendation
See `next_task_recommendation.md`: a bounded, non-tuning hypothesis-discovery task into why
`LOW_VOLATILITY`/`LOW_CONFLUENCE` bind this hard for this universe/period. Not started, per instruction.
