# Task 118 — Baseline reconciliation, profitability diagnostics and task journal

## Objective and acceptance criteria
Reconcile the Task 118 Deliverable A V2 baseline (10 trades, −2.93% net,
PF 0.315) down to trade-level evidence; determine why Original intraday
rarely produces alerts; reconcile the 5 open Experimental positions;
produce one ranked next-experiment recommendation; implement a permanent
task journal; preserve the live V2 paper session throughout; perform the
canonical EOD close only if/when the session was still active at verified
XNYS close.

## Timing
- UTC start: 2026-09-11T10:08 (first live status check this task)
- UTC end: 2026-09-11T~11:00 (research deliverables complete and pushed;
  live session still pre-EOD — see Production effects below)

## Branch / SHA
- Release (not modified this task): `research/talonx-strategy-validation` @ `fb4b071eafb74f13bf2ab290d1e2c80e400d6163` (unchanged, read-only inspection only)
- Research: `research/talonx-profitability-2026-09`, starting SHA `c85a72ffb3dd6153c88a4e74bc9eeee5586aca54`, result SHA — see `outcome.md` (filled at push time)

## Requested vs. completed scope
- Part 1 (task journal): **DONE** — this journal.
- Part 2 (V2 baseline reconciliation A/B/C): **DONE** —
  `docs/research/TASK118_BASELINE_RECONCILIATION.md`,
  `results/task118_profitability/reconcile.py`,
  `results/task118_profitability/reconciliation/{episodes,trades}.csv`,
  plus a new separately labelled $300k diagnostic re-run
  (`run_baseline_a_300k_diagnostic.py`). The "earlier three trades"
  comparison point could not be located in repo history — reported as a
  named gap (§B.3 of that report), not fabricated.
- Part 3 (Original selectivity): **DONE, read-only** —
  `docs/research/TASK118_ORIGINAL_SELECTIVITY.md`. Live warm-up
  measurement done; outcome measurement for the full candidate population
  explicitly **not** run (already covered by the closed Task 95A space; no
  new bounded hypothesis was supplied to justify reopening it).
- Part 4 (Experimental outcomes): **DONE** —
  `docs/research/TASK118_EXPERIMENTAL_OUTCOMES.md`. Found a real,
  previously-undocumented lifecycle gap (`check_exits`/`flatten_all` never
  invoked live) — reported, not fixed.
- Part 5 (decision table): **DONE** —
  `docs/research/TASK118_NEXT_EXPERIMENT.md`.
- Part 6 (live session/EOD): **live session preserved throughout; EOD not
  yet due** at the time this task's research work completed (checked
  2026-09-11T10:24 UTC, `NOT_DUE_YET`, close is 20:00 UTC) — the canonical
  close was **not** performed this task; the required operator action and
  deadline are stated in `outcome.md` and here.

## Source / runtime / data manifest
See `docs/research/TASK118_BASELINE_RECONCILIATION.md` §A for the full
module/hash table. Summary: `talonx_v2/{service,form4_source,store}.py`
verified byte-identical to the release worktree this session (not merely
asserted from an earlier task); `pricing.py` confirmed absent (out of scope
for the `pricing_mode="csv"` replay). Data: SEC Form-4 code-P parquet +
local daily-bar CSVs under `C:\workspace\TalonX\results\` (frozen,
read-only). Reproducible command:
`C:/workspace/TalonX/.venv/Scripts/python.exe results/task118_profitability/reconcile.py`
(from the research worktree; requires the already-generated
`replay_v2_lane.db`/`baseline_a_replay_result.json`, which are gitignored —
hashes recorded below).

Gitignored raw artifacts (databases + large JSON, per this task's own
"keep large/private artifacts out of Git, with hashes and locations"
instruction):

| file | md5 | bytes |
|---|---|---:|
| `results/task118_profitability/replay_v2_lane.db` | `fc36fec8befc3d2550b5bf479eabecd6` | 135,168 |
| `results/task118_profitability/replay_v2_lane_300k.db` | `eca65ff44e86bfb086c959fad254ee48` | 135,168 |
| `results/task118_profitability/baseline_a_replay_result.json` | `900730a91db785e5af5579ebba6377ee` | 20,316 |
| `results/task118_profitability/baseline_a_300k_replay_result.json` | `cf5c97e6fff97ea0f7ab102684749a38` | 20,372 |
| `results/task118_profitability/baseline_a_summary.json` | `7c22a0d139e9cd64a20bc3c0e4fa9988` | 5,483 |

## Tests / experiments / results / limitations
- Re-derived all Part 2 metrics independently from raw replay artifacts —
  matched the original Deliverable A report to the cent/basis point.
- Ran one new experiment: $300,000-starting-cash diagnostic replay
  (byte-identical script otherwise) — result: identical trades/metrics to
  the $10,000,000 run (max concurrent notional was only $20,000; the $300k
  constraint was never binding for this scope/window).
- Queried live `quant.db` (`suppression_counts`, `bar_buffer`) and
  `exp_alerts.db` (`experimental_trades`) read-only; queried live `:8787`
  API sections (`validation`, `overview`, `premarket`). No writes to any
  of these from this task except one self-inflicted, harmless, 0-byte
  stray file (see Findings).
- Limitations: Original's full-candidate-population outcome measurement
  not run (out of scope, already-closed space); the causal link between
  today's pre-open 1-minute-buffer warm-up gap and any actual lost
  qualified evaluation during a regular session could not be established
  from currently available data (no persisted preseed-status artifact
  exists); the "earlier three trades" comparison point is unreproducible.

## User-visible outcome
See `outcome.md` for the verbatim final response delivered.

## Verdicts (kept separate)
- Operational verdict: live V2 paper session (`fb4b071`,
  `results/prospective_2026-09-11`) **preserved, unmodified, still
  running** throughout this task; EOD not yet due.
- Profitability / research verdict: the reconciled N=10 39-name-scope
  baseline stays **net-negative and inconclusive at this sample size**
  (−2.926%, PF 0.315) — reconciliation corrected the portfolio-drawdown
  framing (real book drawdown −0.23%, not −42.7%) and confirmed the cost
  convention, but did **not** change the headline sign or make the result
  positive. This verdict is explicitly not inferred from, or conflated
  with, the operational verdict above.

## Production effects, external sends, protected-state checks
**Zero production/live database writes.** All queries against
`v2_lane.db`, `ingestion_ledger.db`, `quant.db`, `exp_alerts.db` were
read-only (`file:...?mode=ro` SQLite URIs) or via the read-only `:8787`
dashboard API. No Redis mutation. No external message sent (no Telegram
send attempted by this task — Task 117's connectivity test and natural
delivery predate this task). No Experimental Telegram enablement. No
strategy/threshold/config change in the release worktree.

## Findings
- **Fixed**: none (read-only/measurement task by design; the two real
  code-level gaps found were reported, not fixed, per this task's own
  boundaries).
- **Open**: (1) Experimental `check_exits`/`flatten_all` never invoked
  from `talonx_signals/run.py`'s live loop — 5 open positions can never
  auto-exit; 2 of 5 (VRT, BLSH) already past their recorded stop in
  reference-price terms. (2) Original's pre-open 1-minute-buffer warm-up
  gap (4/43 ready at inspection time) — root cause (preseed failure vs.
  partial buffer retention) not distinguishable from available evidence;
  its actual regular-session impact today is unverified.
- **Deferred**: full-candidate-population Original outcome measurement
  (already-closed Task 95A space, no new hypothesis supplied to reopen
  it); a formal discovery/holdout statistical split for the 39-name-scoped
  cut specifically (noted as a Deliverable A limitation, unchanged here).

## Evidence links
`docs/research/TASK118_BASELINE_RECONCILIATION.md`,
`TASK118_ORIGINAL_SELECTIVITY.md`, `TASK118_EXPERIMENTAL_OUTCOMES.md`,
`TASK118_NEXT_EXPERIMENT.md`; `results/task118_profitability/reconcile.py`,
`reconciliation/{episodes,trades}.csv`,
`run_baseline_a_300k_diagnostic.py`; this journal's `TASK_INDEX.md` row.

## Later corrections
None yet.
