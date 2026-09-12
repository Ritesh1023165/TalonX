# Task 121 — Experimental exact-contract economic evaluation

## Objective and acceptance criteria
Evaluate `EXPERIMENTAL_RELAXED_V1` once, without tuning, using existing
replay infrastructure; correct Task 120's remaining accounting labels;
reach a completed replay and one product decision, not a framework
proposal.

## Timing
2026-09-12, continuing the same session as Task 120A-C.

## Branch / SHA
Release: verified `f28986999eec5e313cfc89db24e4dbacfb378891` unchanged —
**no release-branch work this task** (research-only). Research `47530ce`
→ this entry's commit.

## Requested vs. completed scope

- **PART 1 (Task 120 corrections): DONE.** "Properly powered" wording
  withdrawn (two edits in `TASK120ABC_CORRECTED_BASELINE_AND_DECISION.md`
  + a correction blockquote on the prior journal outcome). Gross-vs-cost-
  adjusted equity bug found and reconciled exactly: B3's $296,307.36 is
  GROSS (V2's paper ledger models zero cost); cost-adjusted equity =
  **$295,167.37** (starting $300,000.00 + gross P&L −$3,692.63 − cost
  −$1,140.00, the last verified exactly = 57 × $10,000 avg notional ×
  20bps). 4 new tests
  (`tests/test_task121_task120_equity_reconciliation.py`) all pass.
  Documented in `docs/research/TASK121_TASK120_ACCOUNTING_CORRECTIONS.md`.
- **PART 2/3 (contract + harness): DONE.** Recorded `EXPERIMENTAL_RELAXED_V1`'s
  full contract from source (`talonx_signals/{config,relaxed_profile}.py`,
  `talonx_quant/{consumer,strategy,session}.py`) — same production
  `QuantScanner`/`evaluate_signals()` as Original, three thresholds
  relaxed, `volatility_gate_mode`/`confluence_contract` locked identical
  (verified). Found an EXISTING, mature, already-tested backtest engine
  (`talonx_backtest.engine.BacktestEngine`) that reuses the same
  `talonx_quant.consumer` gate free-functions — reused verbatim as the
  narrow adapter (`research/scripts/task121_experimental_replay.py`), no
  new research platform built. 102 pre-existing tests
  (lookahead/lifecycle/live-parity/state/reproducibility/execution) cited
  as harness-equivalence evidence, all pass. **Material finding**: a
  full-codebase search found `ExperimentalPaperEngine.check_exits()` /
  `.flatten_all()` have **no caller anywhere in the live
  `talonx_signals.run` runtime** — the current repaired Experimental
  lane opens positions but has no automatic exit mechanism in normal
  operation; the four 2026-09-11 "recovery-affected" exits were an
  out-of-band intervention, consistent with this finding. Exit lifecycle
  in this replay is labelled `DESIGNED_LIFECYCLE` (stop/target + EOD
  flatten, as coded), not `EXACT_CONTRACT` (not proven scheduler-invoked
  live) — per this task's own instruction not to claim EXACT_CONTRACT
  where material behavior differs.
- **PART 4/5 (data/replay): DONE, with a disclosed two-step scope
  reduction.** A timed, progress-logged smoke test measured ~42-48
  bars/sec single-threaded. A full one-month run (393,624 bars) was
  actually launched and observed reaching 5.0% after ~8 minutes
  (confirming ~2.5hr total) — no economic outcome inspected at that
  point — then stopped and narrowed to **one calendar week**
  (2025-01-24→2025-01-31, all 35 symbols, 116,295 bars) to fit this
  task's session-interactive time budget. Both narrowing decisions were
  made from elapsed-time/progress-percentage observations only, before
  any trade/candidate/rejection count was inspected at any window size —
  recorded in full chronological detail in `TASK121_PROTOCOL.md` §2.
  Full coverage (35/35 symbols), 0 data-quality blocking issues.
- **PART 6 (economics): DONE — a zero-trade result.** 2,300 raw
  candidates, 75 fully gate-cleared published signals, **0 closed long
  trades**. The 75-published/75-`NO_ACTIVE_POSITION`-rejected exact match
  is consistent with every published candidate this week being BEARISH
  (a LONG_ONLY contract never opens on a bearish signal) — reported as
  an inference from the arithmetic, not independently re-verified via
  direction-level telemetry (would have cost a second ~38-minute run).
  All win-rate/PF/expectancy/CI fields are `None` by construction (0
  trades, 0 issuers) — not fabricated as zero-with-confidence.
- **PART 7 (decision): DONE.** `INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER`
  — not a negative-economics or engine-defect finding (the pipeline ran
  cleanly and produced far more raw activity than Original ever does);
  the exact blocker is that one calendar week is too small a sample for
  this LONG_ONLY contract's realized direction mix to guarantee even one
  qualifying entry. Smallest next action: re-run the SAME unmodified
  adapter over a longer slice of the SAME already-available dataset (no
  new strategy/threshold/adapter) — full acceptance criteria in
  `TASK121_EXPERIMENTAL_CONTRACT_RESULTS.md` §5.
- **PART 8 (journal/publication): DONE** — this entry; sanitized adapter
  + 10 new focused tests (4 equity-reconciliation + 6 adapter-unit) all
  passing; protocol/results/corrections docs; small (3.1KB) sanitized
  replay-summary evidence committed (small because 0 trades); raw
  replay JSON/isolated ledger kept local-only
  (`results/task121_experimental_replay/`, gitignored).

## Source / runtime / data manifest
New: `research/scripts/task121_experimental_replay.py` (reuses
`talonx_backtest.engine.BacktestEngine`/`talonx_quant.consumer` gate
functions unmodified), `tests/test_task121_task120_equity_reconciliation.py`
(4 tests), `tests/test_task121_experimental_replay_adapter.py` (6 tests),
`docs/research/{TASK121_PROTOCOL,TASK121_EXPERIMENTAL_CONTRACT_RESULTS,
TASK121_TASK120_ACCOUNTING_CORRECTIONS}.md`,
`docs/research/evidence/task121/{experimental_replay_summary,runtime_manifest}.json`
+ `{rate_smoke_test,run}.log`. Reused unmodified: `talonx_backtest/*`,
`talonx_quant/*`, `talonx_signals/{config,relaxed_profile,experimental_paper}.py`,
`talonx_paper/engine.py`. Source data: `task93_canonical_v1`
(`results/task93_alpha_foundation/_canonical_data`, sha256
`796893860a2733...`, already-published, no new download).

## Tests / experiments / results / limitations
`pytest tests/test_task121_task120_equity_reconciliation.py
tests/test_task121_experimental_replay_adapter.py -q` → 10 passed.
Existing `talonx_backtest` equivalence suite (102 tests, 6 files) → all
pass. One real replay executed to completion (fingerprint-gated,
`2ae6216bca70` matched) — a genuine zero-trade result over a
one-calendar-week window, disclosed as such, not padded or reframed.
Limitations: one week only (not the full Segment A); exit lifecycle is
DESIGNED not proven live-wired; pre-market session excluded; no
continuous daily mark-to-market.

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Part 1 (Task 120 corrections): `TASK120_ACCOUNTING_CORRECTIONS_COMPLETE`.
- Part 2/3 (contract + harness): `HARNESS_REUSE_CONFIRMED_WITH_OPERATIONAL_GAP_FINDING`.
- Part 5/6 (replay + economics): `REPLAY_COMPLETE_ZERO_TRADE_RESULT`.
- Part 7 (decision): `INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER`.

## Production effects, external sends, protected-state checks
None — research-only task. Release branch untouched (`f289869` unchanged,
verified at task start and end). No application process started/left
running (a stray duplicate replay process from an earlier, intentionally-
abandoned one-month run was found still alive under a different
interpreter path — Windows venv-shim child-process pattern, see
[[talonx_windows_venv_shim_pids]] — and explicitly killed by PID; only
the intended single one-week run's process pair remained thereafter).
Redis/production DBs re-verified clean at task end.

## Findings
- Fixed: Task 120's gross/cost-adjusted equity conflation and unsupported
  "properly powered" wording.
- New, material: Experimental's live exit lifecycle (`check_exits`/
  `flatten_all`) has no caller anywhere in the current runtime — an
  operational gap, not previously documented in this session's memory,
  worth a dedicated fix task.
- New: a real, existing production-grade backtest engine
  (`talonx_backtest`) was already available and load-bearing for this
  entire task — not something this task needed to build.
- Open: the one-week window's zero-trade result leaves Experimental's
  true entry frequency/economics unmeasured — named as the next action's
  exact target, not resolved this task.
- Deferred: extending the replay to the rest of Segment A; investigating/
  fixing the exit-lifecycle wiring gap (a product/ops decision, out of
  this research-only task's authorization).

## Evidence links
`docs/research/{TASK121_PROTOCOL,TASK121_EXPERIMENTAL_CONTRACT_RESULTS,
TASK121_TASK120_ACCOUNTING_CORRECTIONS}.md`,
`docs/research/evidence/task121/*` (this commit);
`results/task121_experimental_replay/` (local, full artifacts incl. raw
replay JSON and isolated `.db` ledger — never committed).

## Later corrections
None yet.
