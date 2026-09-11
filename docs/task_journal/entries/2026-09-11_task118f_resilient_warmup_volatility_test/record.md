# Task 118F — resilient warmup and bounded volatility-return test

## Objective and acceptance criteria
Implement, test, and deploy a real fix for the evidenced multi-hour
warmup-recovery gap; run one predeclared exploratory volatility-return
test on already-collected A/B trade data.

## Timing
- UTC start: 2026-09-11T15:42 (baseline re-verification)
- UTC end: 2026-09-11T~15:56 (implementation, tests, deployment, and
  research test all complete, pushed; session live, pre-EOD)

## Branch / SHA
- Release: starting `0209ada`/code `c88f4d4` → deployed **`5c0b3f3`**
  (merge of hotfix `4531fe2`), docs `0f5b455`.
- Research: `49a054b` → this entry.

## Requested vs. completed scope
- Part 1 (implement resilient warmup): **DONE** — root-caused to
  `QuantScanner._preseed_1m_if_needed`'s unconditional "attempted once
  ever" marker; fixed via `run_bounded_recovery_sweep` (new function,
  `preseed_ordering.py`), reusing the existing fetch path entirely, wired
  into the same pre-market-data safety window `run_initial_preseed`
  already uses.
- Part 2 (validation): **DONE** — 8 new tests (bulk-failure recovery,
  partial recovery, no-duplicate-bars, structural live-tick-race
  exclusion, no signal/Telegram output, no re-fetch of already-recovered
  symbols, clean budget exhaustion, bounded provider-call volume), all
  passing; plus a real, isolated, bounded provider probe (3 symbols, all
  succeeded).
- Part 3 (deployment): **DONE, deployed today** — full stop/backup/merge/
  restart sequence, live-verified: readiness went from 30/43 (natural,
  pre-restart) to **42/43 immediately post-restart**, with the recovery
  sweep's own log line observed live recovering 1/2 remaining symbols in
  2.6 seconds.
- Part 4 (volatility-return test): **DONE** — predeclared protocol,
  issuer-block + time-block bootstrap, A/B separate + pooled secondary,
  drop-MSTR sensitivity. Decision:
  **EXPLORATORY_ASSOCIATION_SUPPORTS_ONE_FURTHER_TEST**.
- Part 5 (session/EOD): **DONE** — SPCX reconfirmed fresh (+$4.09
  unrealized on a 42s-old mark), Experimental/V2 continuity verified
  unchanged across the restart; EOD not yet due.
- Part 6 (journal/publication): this entry + release-side
  IMPLEMENTATION.md/DEPLOYMENT.md.

## Source / runtime / data manifest
`talonx_quant/preseed_ordering.py::run_bounded_recovery_sweep`,
`run_talonx.py` (wiring), `tests/test_task118f_resilient_warmup.py`
(release branch, commit `4531fe2`→merged `5c0b3f3`).
`results/task118_profitability/volatility_return_test.py` (research
branch, this commit).

## Tests / experiments / results / limitations
8 new unit tests (release) + broader `-k "preseed or warmup"` regression
(106 tests, unaffected) + 1 real isolated provider probe (3/3 succeeded).
1 new statistical script (research), issuer-block + time-block bootstrap,
5000 reps each. Limitations: A's within-population volatility-return
significance does not survive MSTR removal (reported explicitly); NUE
remained the one symbol the recovery sweep could not fully close (116/120,
expected to close via live accumulation).

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Operational verdict: real, deployed, live-verified fix — readiness
  42/43 immediately post-restart, full continuity preserved.
- Profitability verdict: EXPLORATORY_ASSOCIATION_SUPPORTS_ONE_FURTHER_TEST
  — a real but MSTR-dependent within-A association; not a profitability
  claim, not a strategy change.

## Production effects, external sends, protected-state checks
Real production changes this task: `talonx_quant/preseed_ordering.py` and
`run_talonx.py` deployed to the live release; one controlled restart
(15:50:06Z–15:51:18Z window). Experimental/V2 ledgers verified byte-
identical in content (positions, trade history, realized P&L) before and
after — only the process pids and log timestamps changed. No Redis flush,
no external send, no strategy/threshold/scope change.

## Findings
- Fixed: the preseed-retry idempotency defect (real, root-caused, now
  live-verified working in production).
- Open: NUE's final readiness (expected to close naturally within
  minutes, not observed to completion in this session); whether the
  volatility-return association holds under genuinely new (future live)
  data.
- Deferred: none new.

## Evidence links
`docs/audits/task118f_resilient_warmup/{IMPLEMENTATION,DEPLOYMENT}.md`
(release, commits `0f5b455`/`5c0b3f3`);
`docs/research/TASK118F_VOLATILITY_RETURN_TEST.md` (this branch).

## Later corrections
None yet.
