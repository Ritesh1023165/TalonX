# Task 81 — Safety Baseline and Verification Closure Report

## Verdict

**`BASELINE_VERIFIED_READY_FOR_ISOLATION`** — with one explicit,
non-blocking data-coverage question carried forward (§5).

This is a software-safety / reporting / verification verdict only. It is
**not** a live-launch, strategy-validation, profitability, or
runtime-isolation verdict. Strategy status remains `UNVALIDATED`;
profitability `UNDETERMINED`. Real capital, shorts, options and leverage
remain out of scope. No live session, broker mutation, notification,
automation resumption, experimental activation, holdout access, or strategy
tuning occurred. Protected `talonx_quant/{strategy,indicators,consumer,
config}.py` were not modified.

## Baseline established

- Repository `C:\workspace\TalonX`, branch `research/talonx-strategy-validation`.
- Starting HEAD `47afb8c9630c0eee5394063a3f574db1b52173dd` — equals the
  task's stated expected starting SHA. (The `docs(task80): preserve
  cleanup evidence and handoff` commit landed immediately after the
  session opened; it added the Task 80 cleanup evidence and is the tree
  the cleanup report itself refers to as runtime SHA `8d2a8dd…`.)
- Tracked worktree clean. `stash@{0}` / `stash@{1}` (task56) preserved
  untouched. Codex paused; Claude sole implementer.
- Task 80 archived evidence, disabled entry settings (35 tickers, all
  `false`), and paused `monitor-talonx-paper-session` automation all
  preserved and unmodified.
- Acceptance matrix recorded up front: `acceptance_matrix.md` (requirement
  → production boundary → regression test → evidence), including the
  numerical-tolerance convention (`1e-6` absolute on quantities) and
  up-front resolution of the two contradictions (BUY-only block vs
  protective-exit preservation; Task 81 §3 supersedes Task 79E-R2-3's
  "silently mint a fresh identity despite unresolved exposure").

## RCA and confirmed fixes

### §2 — Reconciliation completeness & entry admission (`3dbac5d`)

Root cause: `PaperLifecycle.reconcile()` computed `matched` as
`internal_open_symbols == broker_open_symbols` — a **symbol-set-only**
comparison. It ignored position quantities, position sides, outstanding
broker-order identities, and unresolved submissions; and an individual
pending-order refresh failure (`_refresh_non_terminal_orders`) was
swallowed, after which the next `reconcile()` cleared the entry block on
symbol-set agreement alone.

Fixes in `talonx_piv/lifecycle.py`:
- `reconcile()` now compares, per symbol, internal remaining quantity vs
  broker `qty` (abs tol `1e-6`) and side; flags any broker open order not
  attributable to a recorded broker-id / client-order-id
  (`untracked_broker_orders`); counts `SUBMIT_FAILED_UNCERTAIN` intents
  and `UNCONFIRMED_TIMEOUT` orders as unresolved; and validates the
  `open_orders()` / `positions()` response **shape** (list-of-dicts;
  parseable numeric `qty`).
- A pass is `matched` only when **COMPLETE** (every broker read succeeded
  and was well-formed; nothing unresolved) **and CONSISTENT** (symbols,
  quantities, sides agree; no untracked order; no unexpected short). Any
  failed / malformed / incomplete / contradictory read sets
  `entry_admission_blocked = True` in `reconciliation_flags`, which is
  persisted in `lifecycle_state.json` and therefore **survives a restart**.
  `_refresh_non_terminal_orders` now returns per-order failure reasons.
- `order_intent` BUY guard order changed so the specific same-symbol
  guards (`ALREADY_HOLDING_NO_PYRAMIDING`, `PENDING_ENTRY_EXISTS`) fire
  with their precise reason before the generic
  `RECONCILIATION_BLOCKS_NEW_ENTRIES`; `UNEXPECTED_SHORT` stays highest
  priority. Enforcement remains at the single unavoidable
  `order_intent → broker.submit_order` chokepoint.
- Protective exits, alerts, shadow tracking, monitoring and the EOD
  cleanup path are never gated by the block (BUY_TO_OPEN only) —
  regression-tested.
- `eod_lifecycle`: an incomplete reconcile → `INCONCLUSIVE` (distinct from
  `FAILED`, which means the broker was read and definitively did not
  match).

Regression: `tests/test_task81_reconciliation_admission.py` — 14 cases,
proven `11 failed / 3 passed` against the pre-fix code
(`raw_test_output/section2_prefix_failures.txt`). Reproduces all three
confirmed defects (AAPL 10-vs-1; untracked broker BUY order with empty
portfolios; single-order-refresh-failure keeps block across reconcile
*and* restart).

### §3 — Recovery, session binding, cumulative-fill idempotency (`18dc8e3`)

`session_identity.py`: new `assess_session_recovery()` classifies a new
process invocation as `RESUME_SAME_SESSION` (unchanged verified bindings,
still-live same-day session), `FRESH_SESSION_CLEAN` (nothing unresolved),
or `RECOVERY_REQUIRED`. When runtime / config / feed bindings changed, or
the persisted identity is corrupt, or EOD state is incomplete, **and**
exposure or submissions remain unresolved (open position, non-terminal
order, `ORDER_INTENT` / `SUBMIT_FAILED_UNCERTAIN` intent, active
reconciliation block, or an unreadable `lifecycle_state.json`),
`resolve_session_identity()` now **raises `SessionRecoveryRequired`**
instead of silently minting a replacement — preserving `session_identity.
json`, writing `session_recovery_required.json`, and naming the operator
transition (resolve exposure → `cli eod` to `PASSED` → start fresh). This
deliberately supersedes Task 79E-R2-3's accepted "mint fresh despite
unresolved exposure" behaviour (contradiction resolved in the acceptance
matrix, per §1).

`cli.py`: `start` / `supervise` refuse to start on `RECOVERY_REQUIRED`
(exit 2); read-only / recovery commands proceed against the preserved
identity.

`lifecycle.apply_broker_update` (cumulative-fill idempotency): broker
`filled_qty` is cumulative and must never regress. An older / smaller
cumulative report is clamped to the high-water mark; an already-terminal
order is final (no-op, diagnostic only on contradiction); a late BUY fill
on an already-`CLOSED` position is refused rather than resurrecting it
(the broker-vs-internal discrepancy is then surfaced by `reconcile()`).
Exact order→intent pending-plan recovery and its "fail visibly on
ambiguity" behaviour (`decision_engine._rehydrate_pending_entries`,
`pending_buy_intent_ids`) were re-verified — unchanged and correct.

Regression: `tests/test_task81_recovery_binding.py` — 15 cases incl. B6
(partial entry → partial exit → later entry fill → restart → remaining
exit, with a reconciliation failure).

### §4 — Source-health diagnostics & automatic reporting (`fee25a0`)

`observability.build_integrated_projection` gained a `source_health`
section (exposed unchanged via `/piv/status`). Each input source is
classified — `PRESENT_WITH_RECORDS` / `VERIFIED_ZERO` / `ABSENT_OPTIONAL`
/ `ABSENT_REQUIRED` / `EMPTY_REQUIRED` / `UNREADABLE` / `WRONG_SESSION` /
`STALE_SCOPE` / `ZERO_UNCORROBORATED` — so a missing optional ledger, a
genuine verified zero (corroborated by the events log), and an unreadable
required source are three distinct, named states, never collapsed into a
plausible zero. `source_health_ok` + `source_health_diagnostics` summarise.

`reporting.build_session_report`: an absent / empty / unreadable /
stale-scope events source now sets `events_source_health` and forces
`classification = REVIEW_REQUIRED` instead of a zero-activity `PARITY_OK`.

`reporting.finalize_session_report` (new, shared by `cli eod` and
`SessionRunner._run_eod_lifecycle`): builds and durably writes
`latest_session_report.json` for `PASSED` / `FAILED` / `INCONCLUSIVE`
alike, scoped to the **original** live session identity, as a pure read
(never re-triggers broker cancel/close), with `report_generation_status`
recorded separately from `eod_status`. The automatic shutdown path
previously emitted no session report at all (Task 80 finding).

`eod_lifecycle` (C7): internal positions are marked `CLOSED` **only** once
`reconcile()` confirms the broker is genuinely flat (0 orders, 0
positions, no unexpected short, complete read) — never merely because
`close_all_positions` was accepted.

Regression: `tests/test_task81_source_health_and_reporting.py` — 15 cases.

### §5 — Task 80 IEX readiness churn — see `iex_findings.md`

RCA: the churn (532 `DATA_NOT_READY` / 515 `STALE_DATA` / 514
`DATA_RECOVERED`) is **genuine Alpaca-IEX 1-minute bar sparsity** for
mid-liquidity NASDAQ-100 names — **not** a runtime bookkeeping or
freshness defect. Event counts reconcile exactly (`532 = 515` per-episode
`INSUFFICIENT_RECENT_IEX_PRINTS` `+ 17` once-only
`MISSING_REQUIRED_OPENING_MINUTES`; `514 = 515 − 1` unrecovered COST) and
`Σ stale_episode_count` in the independently-written `freshness_report.
json` equals `515`. Coverage is bimodal (mega-caps ~1.0; REGN/VRTX/COST/
HON 0.58–0.65). Infra exclusions are already routed away from the strategy
path (`session_runner.py:386-388`), so they never become one of the 5,721
`LOW_VOLATILITY` strategy rejections. No threshold relaxed, no bar
fabricated.

**Unresolved (evidence-limited):** freshness is measured from receipt
wall-clock, not bar source-time; the preserved evidence has no per-bar
source timestamps / raw bars log, so receipt-vs-source divergence cannot
be confirmed or excluded locally. **Does not block isolation
engineering** (reconciliation/recovery/reporting safety is independent of
feed cadence); should be resolved before a market-session pilot that
depends on the mid-liquidity names being decision-eligible. Required
evidence: a run (or captured raw `bars/latest` log) recording each bar's
source `t` alongside receipt wall-time for REGN/VRTX/COST/HON/GILD/ISRG,
optionally cross-checked via the existing `gap_forensics.py` against
Alpaca's historical IEX archive — external acquisition needs separate
approval.

Regression: `tests/test_task81_iex_readiness_bookkeeping.py` — 4 cases
locking the bookkeeping invariants.

### §6 — Verification weaknesses — see `test_quality_changes.md`

E1 (two weak/placeholder tests strengthened to assert real state), E2
(broker fixtures from documented API shapes; under-specified pre-existing
position fixtures corrected), E3 (two tests no longer overwrite historical
`results/task77i_*` / `results/task78i_*` evidence on a routine run;
clocks frozen, `tmp_path` isolation, no-network guards throughout), E4
(`tests/test_task81_guard_negative_controls.py` — the persisted effect of
each critical guard is deliberately undone and the forbidden outcome is
proven observable).

## Completed acceptance matrix

Every row A1–A11, B1–B6, C1–C7, E1–E5 in `acceptance_matrix.md` has a
landed production change and a passing regression test named in that
matrix. §5 rows D1–D2 are answered by `iex_findings.md` (no defect;
one evidence-limited question, assessed non-blocking for isolation).

## Test evidence (E5)

Commands, exit codes, exact counts — all under `raw_test_output/`:

| Run | Command | Result |
|---|---|---|
| §2 pre-fix proof | `pytest -p no:cacheprovider tests/test_task81_reconciliation_admission.py` (pre-fix tree) | `11 failed, 3 passed`, exit 1 — `section2_prefix_failures.txt` |
| Post-§2 full suite | `pytest -p no:cacheprovider tests/` | `2560 passed, 1 skipped, 10 xfailed`, exit 0 (930s) — `full_suite_after_section2.txt` |
| Task 81 + critical recovery/time | `pytest -p no:cacheprovider tests/test_task81_*.py tests/test_task79e_r2_activation_safety.py tests/test_task79e_r1_activation_safety.py tests/test_task77i_runtime_safety.py tests/test_task72o_eod_lifecycle.py tests/test_task65b_lifecycle_probe.py tests/test_task76s_broker_boundary.py tests/test_task76s_protective_exit_eod.py tests/test_task78i_stage5_rehearsal.py tests/test_yfinance_poller.py` | `236 passed`, exit 0 — `task81_and_critical_recovery.txt` |
| Final full suite (after all edits) | `pytest -p no:cacheprovider tests/` | **`2597 passed, 1 skipped, 10 xfailed`, exit 0 (846s)** — `full_suite_final.txt` |

Baseline was `2546 passed` (Task 80-P1). `2597 = 2546 + 51` new Task 81
cases. `1 skipped / 10 xfailed` unchanged. Zero failures at every recorded
checkpoint.

New Task 81 test files: `test_task81_reconciliation_admission.py` (14),
`test_task81_recovery_binding.py` (15),
`test_task81_source_health_and_reporting.py` (15),
`test_task81_iex_readiness_bookkeeping.py` (4),
`test_task81_guard_negative_controls.py` (3) — **51 new cases**.

Skip/xfail: unchanged from baseline (`1 skipped, 10 xfailed`). No
dependency added or upgraded. No silent waivers.

## Remaining blockers vs non-blocking backlog

**Blockers to isolation engineering:** none.

**Non-blocking backlog / carried forward:**
- §5 receipt-vs-source-bar-time question (evidence-limited; needs a
  captured raw bars log or an approved historical-archive check).
- The HTML/WebSocket dashboard still consumes general-pipeline Redis
  sources while PIV status is the separate JSON projection (Task 80
  finding). §4 corrected the **PIV projection/API** source-health as
  scoped; the separate HTML view is explicitly out of Task 81 scope
  (no dashboard redesign).
- Operator gates unchanged and still required before any session:
  approved SHA bound to the reviewed checkpoint, fresh preserved state
  dir, explicit per-ticker PAPER-entry settings, a currently-passing
  credentialed preflight, and explicit session-start authorisation.

## Handoff to the isolation task

1. Start from this branch at the Task 81 tip commit (see `git log`).
2. `PaperLifecycle.reconcile()` is now the authority on broker/internal
   agreement (quantities, sides, order identities, unresolved
   submissions) — the isolated Original and PIV lifecycles must each carry
   their **own** `lifecycle_state.json` / `reconciliation_flags`; do not
   share the persisted block between them.
3. `assess_session_recovery()` / `SessionRecoveryRequired` key off
   `config.state_dir`; isolation must give Original and PIV **distinct
   state dirs** so a binding change in one cannot raise recovery-required
   against the other. `session_recovery_required.json` is the durable
   marker to surface per side.
4. `finalize_session_report` / `build_integrated_projection` are
   session-`scoped`; the future Original-vs-PIV comparison UI should
   consume two scoped projections, not a merged one. `source_health`
   must be reported per side.
5. Keep infra exclusions (`DATA_NOT_READY` / `STALE_DATA`) separate from
   strategy rejections in both projections — the separation point is
   `session_runner.py:386-388`.
6. Do not begin PIV separation until this checkpoint is reviewed. Stop
   here.
