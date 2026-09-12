# Task 121A — repair runtime parity and complete the Experimental replay

## Objective and acceptance criteria
Correct Task 121's source/protocol errors, prove the replay represents
the repaired Experimental runtime (not the earlier unwired version, not
Original's lifecycle), then run one fixed longer historical window and
reach a usable economic result or a precisely evidenced blocker.

## Timing
2026-09-12, continuing the same session as Task 121.

## Branch / SHA
Release: verified `f28986999eec5e313cfc89db24e4dbacfb378891` unchanged —
no release-branch work this task (research-only). Research `2f28922` →
this commit.

## Requested vs. completed scope

- **PART 1 (source provenance): DONE.** Root cause confirmed by git
  ancestry (`git merge-base`) and byte-hash comparison, not asserted:
  the research branch forked from the release lineage at `9bec279`
  (Task 114); the release branch gained 38 subsequent commits including
  `72baca2` (Task 118A P1's `check_exits()` wiring into
  `talonx_signals/run.py`), never synced into research. `run.py`
  specifically differs (528 vs. 605 lines); every OTHER module the
  adapter actually imports (`talonx_quant/*`, `talonx_paper/engine.py`,
  `talonx_backtest/*`, `talonx_signals/{config,relaxed_profile,
  experimental_paper,directional}.py`) is byte- or content-identical
  (CRLF-only where it differs at all) — Task 121's computed economics
  were unaffected; only its SEPARATE narrative claim about `run.py` was
  wrong. `research/scripts/task121a_experimental_replay.py::verify_provenance()`
  now inserts the release worktree at `sys.path[0]`, imports every
  dependency, asserts each resolves under the release root, hashes it,
  and raises before any replay if not — narrow, reproducible,
  programmatic, no branch merge, no manual copy. Corrections appended to
  `TASK121_EXPERIMENTAL_CONTRACT_RESULTS.md`/`TASK121_PROTOCOL.md`
  (blockquotes, originals preserved).
- **PART 2 (corrected contract): DONE.** Read directly from the RELEASE
  source (not memory, not the stale copy): entry price = the signal's
  own bar close (NOT next-bar-open, `talonx_backtest.engine`'s own
  convention — corrected); exit = `check_exits()` (stop/target,
  single-price sampled, wired via Task 118A P1) only; bearish signals do
  NOT close a position (`run.py::handle_message` never calls close on
  bearish — corrected from Task 121's use of `talonx_backtest`'s
  bearish-signal-exit lifecycle); EOD flatten is NOT scheduled
  (`flatten_all()` confirmed to have no caller — corrected from Task
  121's `eod_flatten_enabled=True`). Cost convention verified with a
  worked test (`apply_spread(100.0, 5.0, "BUY")==100.025`,
  `..."SELL")==99.975`, round-trip 5.0bps exactly) — confirms, does not
  change, Task 121's own prior label.
- **PART 3 (parity proof): DONE.** `ExperimentalLifecycleShim` — a
  duck-typed composition object replacing `talonx_backtest.execution.
  TradeSimulator` as `engine.simulator`, routing every entry/exit through
  the REAL `talonx_signals.experimental_paper.ExperimentalPaperEngine.
  open_long`/`.check_exits` (not a reimplementation). 12 new parity tests
  (`tests/test_task121a_parity_trace.py`) cover all 9 required scenarios
  (valid entry at signal-bar-close price, stop exit, target exit, exit
  evaluated despite a same-bar entry-gate rejection, bearish with/without
  an open position, missing-observation no-fill, session-close crossing
  with the position held, simultaneous multi-symbol candidates,
  restart/state-persistence) plus the spread worked-example and a
  zero-external-sends structural check — all 12 pass. Reused the
  established `_signal`/`_step` hand-built-QuantSignal-injection pattern
  from the EXISTING `tests/test_backtest_long_only_lifecycle.py` (cited,
  not duplicated as "proof"; genuinely reused as the driving mechanism).
- **PART 4 (telemetry/universe): PARTIALLY DONE, with a disclosed gap
  (see PART 5).** `ExperimentalLifecycleShim.published_log`/`.exit_log`
  designed to capture every published signal's direction/action and the
  true (fine-grained) exit reason — implemented and proven correct by
  the Part 3 parity tests, but this run's OWN funnel/published-log output
  was lost to a process hang before reaching disk (see PART 5) —
  reported as UNAVAILABLE for this run, not fabricated. Universe mapping
  (`docs/research/evidence/task121a/universe_mapping.json`, generated
  fresh, not hand-typed): only 12 of the 35 historical symbols intersect
  the CURRENT configured live watchlist (47 tickers); 23 historical
  symbols are not configured today; 35 configured tickers have no
  historical coverage at all. The 35-symbol historical universe is
  EXPLICITLY not claimed as "the complete configured product scope."
- **PART 5 (fixed longer replay): DONE, with a disclosed reliability
  gap.** One frozen calendar month (2025-01-24→2025-02-23 inclusive,
  375,628 bars, all 35 symbols) — window fixed from a fresh rate
  measurement (not Task 121's one-week number, not a blind re-assertion
  of its ~2.5hr estimate either) before any outcome was inspected. The
  backtest itself (`engine.run()`) completed in 5,312.8s (~88.5 min),
  timed in-process. The POST-backtest summary-construction step then
  hung at 100% CPU for over an hour (confirmed via repeated `psutil`
  inspection — not a crash, a genuine runaway computation, most likely
  caused by an unbounded `published_log` growth path, fixed in the
  adapter for future runs but not in effect for this one). Rather than
  wait indefinitely or discard 88.5 minutes of completed compute, the
  stuck process was killed and the ALREADY-DURABLE SQLite ledger
  (`trade_history`/`positions`/`portfolio_state`) was read directly with
  a small, separate, read-only salvage script — every economic figure in
  the results doc comes from that real, completed ledger, none
  estimated. No abandoned duplicate processes remain (verified: only the
  operator's own inspection commands matched the process filter
  afterward).
- **PART 6 (economics): DONE.** N=33 closed trades, 18 distinct issuers,
  win rate 21.2%, PF 1.13, net $61.92 total (+$1.88/trade mean), ending
  equity $100,061.92 (0 open positions, genuinely resolved not
  force-closed), holding duration 3 min to ~7.0 days (mean ~20.7h) —
  itself independent evidence the no-EOD-flatten correction is real, not
  merely asserted. Issuer-block bootstrap 95% CI on net $/trade:
  [−$12.36, +$16.88] — includes zero. Drop-top-1-issuer (AMAT, 3/33)
  sensitivity: mean moves to +$3.23 (more positive, sign unchanged). No
  threshold search, no loser removal, no cherry-picked cost assumption.
- **PART 7 (decision): DONE.** `INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER`
  — not REJECT (net expectancy positive, PF>1, sensitivity doesn't flip
  sign) and not ADVANCE (CI includes zero — this task's own predeclared
  rule requires both frequency AND a CI excluding zero). Frequency is no
  longer the binding constraint (33/month vs. Original's ~0.15/month,
  ~220×) — a materially more informative result than Task 121's
  zero-trade week. Smallest next action: extend the SAME frozen
  adapter/contract to the rest of Segment A (no new methodology).
- **PART 8 (journal/publication): DONE** — this entry; corrected adapter
  + 12 new parity tests + a reliability fix (logging cap), all committed;
  `docs/research/{TASK121A_PROVENANCE_AND_CONTRACT,
  TASK121A_CORRECTED_REPLAY_RESULTS}.md`; small (<20KB each) sanitized
  evidence under `docs/research/evidence/task121a/`; raw replay DB
  (already deleted, was local/temp-only, never committed).

## Source / runtime / data manifest
New: `research/scripts/task121a_experimental_replay.py` (reuses
`talonx_backtest.engine.BacktestEngine`'s gate/candidate pipeline
unmodified via composition; drives the REAL `ExperimentalPaperEngine` for
lifecycle), `tests/test_task121a_parity_trace.py` (12 tests),
`docs/research/{TASK121A_PROVENANCE_AND_CONTRACT,
TASK121A_CORRECTED_REPLAY_RESULTS}.md`,
`docs/research/evidence/task121a/{module_manifest,universe_mapping,
month1_corrected_SALVAGED}.json` + `run.log`. Reused unmodified (verified
release-sourced, hashed): `talonx_quant/*`, `talonx_paper/engine.py`,
`talonx_backtest/{engine,execution,data,portfolio}.py`,
`talonx_signals/{config,relaxed_profile,experimental_paper}.py`. Source
data: `task93_canonical_v1` (already-published, no new download).

## Tests / experiments / results / limitations
`pytest tests/test_task121a_parity_trace.py
tests/test_task121_task120_equity_reconciliation.py
tests/test_task121_experimental_replay_adapter.py
tests/test_task120a_cost_reconciliation.py -q` → 29 passed. One real
replay executed (fingerprint-gated, `2ae6216bca70` matched); backtest
itself completed and is fully trustworthy; post-processing partially
failed (disclosed reliability gap, salvaged, not hidden). Limitations,
stated plainly: funnel-level telemetry (raw candidate/rejection counts,
fine-grained exit reason) unavailable for this run; N=33/18-issuer result
is genuinely inconclusive (CI includes zero) — not reframed as a finding.

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Part 1 (provenance): `STALE_WORKTREE_ROOT_CAUSE_CONFIRMED`.
- Part 2/3 (contract + parity): `CORRECTED_CONTRACT_PARITY_PROVEN`.
- Part 5/6 (replay + economics): `REPLAY_COMPLETE_WITH_DISCLOSED_TELEMETRY_GAP`.
- Part 7 (decision): `INSUFFICIENT_EVIDENCE_WITH_SPECIFIC_BLOCKER`.

## Production effects, external sends, protected-state checks
None — research-only task. Release branch untouched (`f289869`
unchanged, verified at task start and end). No application process left
running (verified: only the operator's own inspection commands matched
the process filter after cleanup). Redis reachable, 0 `talonx:*` keys.
Temp SQLite ledger deleted after salvage (was local-only, never
committed).

## Findings
- Fixed: the false "no exit caller" / "manual Friday exits" claims
  (withdrawn, root-caused, not merely corrected in wording).
- Fixed: the mismatched exit lifecycle (EOD-flatten, bearish-close) that
  made Task 121's zero-trade result methodologically unrepresentative of
  Experimental's real behavior.
- New, material: a genuine adapter reliability bug (unbounded
  `published_log` growth) that cost over an hour of wall-clock time and
  required a salvage workaround — fixed for future runs, disclosed here
  rather than hidden behind a clean-looking result.
- New: N=33/month is a real, decisive FREQUENCY finding (contract fires
  regularly) but an inconclusive ECONOMICS finding (CI includes zero).
- Open: sign/magnitude of Experimental's net expectancy (named next
  action, not resolved this task).
- Deferred: extending the replay to the rest of Segment A; any fix to
  Experimental's own EOD/overnight-holding product behavior (a product/ops
  decision, out of this research-only task's authorization).

## Evidence links
`docs/research/{TASK121A_PROVENANCE_AND_CONTRACT,
TASK121A_CORRECTED_REPLAY_RESULTS}.md`,
`docs/research/evidence/task121a/*` (this commit);
`results/task121a_experimental_replay/` (local, gitignored).

## Later corrections
None yet.
