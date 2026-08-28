# Task 81-R1 — Recovery Integrity and Expected-Failure Closure Report

## Verdict

**`BASELINE_VERIFIED_READY_FOR_ISOLATION`** — every baseline/isolation
blocker (recovery integrity, reconciliation completeness, missing-identity
recovery) is closed. Two retained limitations, both explicitly assessed as
**non-blocking for isolation**:

1. The Task 81 §5 IEX finding is qualified (§6): count reconciliation does
   not establish the *cause* of the missing bars nor exclude a
   receipt-vs-source-time freshness issue; unresolved without per-bar
   source-timestamp evidence.
2. 10 xfailed + 1 skipped backtest tests share one root cause — a stale
   synthetic demo dataset (`sample_multi_trade_1m.csv`) — and are
   **RETAINED** with a documented regeneration follow-up
   (`xfail_skip_disposition.md`). Not production defects; zero overlap
   with the recovery/reconciliation/dual-run code paths.

Boundaries honoured: no isolation implementation, no live session, no
broker mutation, no notification, PAPER entries disabled, experimental
auth absent, monitoring paused, strategy `UNVALIDATED`, Gemini
informational only. No changes to
`talonx_quant/{strategy,indicators,consumer,config}.py`. No portfolio or
historical-evidence resets. `stash@{0}`/`stash@{1}` untouched.

## SHAs and changed files

- Starting HEAD: `81d18d5eed00e1aa4b630d31d3f1d1281091f77a` (verified).
- Final HEAD: see `git log` tip of this branch.
- Changed production files: `talonx_piv/lifecycle.py` (§2 late-fill
  recovery, §3 reconciliation completeness), `talonx_piv/session_identity.py`
  (§4 missing/unusable identity).
- New tests: `tests/test_task81_r1_late_fill_recovery.py`,
  `tests/test_task81_r1_reconciliation_completeness.py`,
  `tests/test_task81_r1_missing_identity_recovery.py`,
  `tests/test_task81_r1_guard_negative_controls.py`.
- Evidence: `results/task81_r1_recovery_closure/`.
- No dependency added/upgraded. No test deleted, no assertion weakened, no
  skip broadened, no expected outcome changed.

## §2 — Genuine late-fill recovery (RCA + fix)

**Reproduced** (`test_task81_r1_late_fill_recovery.py`, production
`PaperLifecycle` path): BUY 2 → 1 fills → protective SELL closes that 1
(position `CLOSED`, `remaining_quantity` 0) → the still-outstanding BUY
completes its remaining share. Pre-fix (Task 81's blanket
`LATE_BUY_FILL_ON_CLOSED_POSITION_IGNORED`) left the order at
`filled_qty=2` with the position `CLOSED`/0 — the acquired share silently
discarded.

**Root cause:** the Task 81 §3 guard treated *every* BUY fill landing on a
`CLOSED` position as a duplicate/stale update to refuse, conflating a
genuine positive cumulative-fill delta (a real, newly-acquired share on a
still-outstanding order) with a replay.

**Fix** (`apply_broker_update`, BUY branch):
- `filled_qty` > the intent's requested quantity → visible
  `BROKER_ERROR: BUY_FILL_EXCEEDS_REQUESTED_QUANTITY`, never applied.
- `CLOSED` position + no new quantity (`incremental_qty ≤ 0`) → idempotent
  no-op (`LATE_BUY_FILL_ON_CLOSED_POSITION_NO_NEW_QTY_IGNORED`).
- `CLOSED` position + genuine positive delta → in-place merge that
  **accounts for the new share and re-opens protective monitoring**
  (`status=OPEN`, re-registered in `open_position_by_symbol`,
  `POSITION_OPENED` emitted with `status=REOPENED_BY_LATE_FILL_COMPLETION`)
  while **preserving** `exit_quantity`, realised exit P&L, the
  `triggered_exit_reason` latch, the exit plan (`stop_price`/`target_price`),
  and intent linkage (`position_id = stable_id("position", intent_id,
  symbol)`). Invariant held: `quantity == exit_quantity + remaining_quantity`.
- Already-terminal order (cancellation race) → unchanged terminal-finality
  guard (`STALE_OR_CONTRADICTORY_BROKER_UPDATE_IGNORED`).
- Restart-safe both sides of the late fill; the live decision engine
  re-adopts the re-opened position via its per-bar
  `_flag_orphaned_positions` → `_try_rehydrate_one` hook.

Coverage: 10 cases including partial-exit, cancellation race, out-of-order
updates, duplicate/stale repeats, and restart. 5 proven to fail pre-fix
(`raw_test_output/section2_prefix.txt`).

## §3 — Reconciliation completeness (RCA + fix)

**Reproduced** (`test_task81_r1_reconciliation_completeness.py`) — two
remaining false passes:
- **A.** An internally cancelled (terminal) order still listed in the
  broker's open-orders response was accepted because its id was
  historically known.
- **B.** An orphan `ORDER_INTENT` (persisted intent, no recorded broker
  order — a crash between persisting the intent and calling `submit_order`)
  was excluded from unresolved submissions, so a later pass cleared the
  admission block.

**Fix** (`reconcile()`):
- New `_classify_broker_open_order(row)` matches each broker-reported OPEN
  order against its **exact durable intent**: a broker id / client-order-id
  that maps to an order this system holds in a DONE-NOT-FILLED state
  (`canceled`/`rejected`/`expired`) which the broker still reports open is
  a **contradiction** (`contradictory_broker_orders` → `consistent = False`
  → block), not an accepted match; a matched id whose symbol/side/qty
  disagree with the intent payload (`_fields_agree`) is also a
  contradiction. (A locally-`filled` order lingering in the broker's open
  list is left to the position-quantity comparison — weaker signal,
  commonly just broker eventual-consistency.)
- Orphan `ORDER_INTENT`-status intents with no recorded broker order are
  counted as unresolved (`orphan_intents` → `complete = False` → block);
  they clear only after a verified matching order or an explicit operator
  disposition. Absence is not proof of non-submission.
- `status = INCOMPLETE_RECONCILIATION`, reason string, and the result dict
  (`contradictory_broker_orders`, `orphan_intents`) reflect both buckets.
- Malformed/incomplete/contradictory responses still never clear the block
  (Task 81 §2 shape checks unchanged); block persists across restart and
  clears only on a complete + consistent pass; protective exits still
  sized against verified holdings − outstanding sells.

Coverage: 8 cases. 5 proven to fail pre-fix
(`raw_test_output/section3_prefix.txt`).

## §4 — Missing-identity recovery (RCA + fix)

**Reproduced** (`test_task81_r1_missing_identity_recovery.py`):
`lifecycle_state.json` has an `OPEN` position but `session_identity.json`
is **absent** → `assess_session_recovery` returned `FRESH_SESSION_CLEAN`
and `resolve_session_identity` minted a new authorization-bound identity
around the unresolved exposure.

**Root cause:** the `RECOVERY_REQUIRED` trigger only checked
`identity_corrupt`, which requires the file to *exist*; an absent file
fell through.

**Fix** (`assess_session_recovery`): `identity_missing` /
`identity_unusable` (`not identity_wellformed`, covering absent + corrupt +
incomplete) added to the trigger; `SESSION_IDENTITY_MISSING` reason string
(distinct from `SESSION_IDENTITY_CORRUPT`). `resolve_session_identity`
raises `SessionRecoveryRequired`; `cli start`/`supervise` refuse (exit 2,
`PIV_BLOCKED_RECOVERY_REQUIRED`) and the identity file is never written.
`FRESH_SESSION_CLEAN` is still reached only when nothing is unresolved, so
`mode` / `reasons` / `unresolved_exposure` never contradict. Genuinely-clean
startup, unchanged-binding restart, and the existing runtime/config/feed/
date binding requirements are all preserved (parametrized recovery matrix
+ `test_binding_requirements_unchanged`).

Coverage: 9 items incl. the CLI refusal. 5 proven to fail pre-fix
(`raw_test_output/section4_prefix.txt`).

## §5 — Expected-failure inventory

See `xfail_skip_disposition.md`. Baseline re-run confirmed exactly
`2597 passed, 1 skipped, 10 xfailed`. All 11 investigated with
`--runxfail` (`raw_test_output/xfail_runxfail_*.txt`). **Single root
cause** — stale `sample_multi_trade_1m.csv` → 0 trades. **RETAINED** (not
production defects, not isolation blockers, markers accurate). Fix is a
documented synthetic-data regeneration follow-up.

## §6 — IEX evidence correction

See `iex_evidence_correction.md`. Task 81 `iex_findings.md` preserved
unchanged. Correction: count reconciliation proves the bookkeeping is
sound but does not establish *why* bars were missing and does not exclude
a source-time freshness problem; the receipt-vs-source question is
unresolved without per-bar source timestamps. Minimum future evidence
documented. No data acquisition / live session / threshold change /
fabricated bars.

## §7 — Verification

- Each confirmed defect reproduced before its fix (pre-fix logs committed).
- Production call paths exercised with isolated in-memory broker fakes
  built to the documented Alpaca REST contract; deterministic clocks
  (explicit `now` / `filled_at`); per-test `tmp_path`; autouse
  no-real-network guards. No test writes into `results/task*`.
- Neighbouring states covered together (duplicate vs genuine delta;
  missing vs corrupt identity; known-id vs consistent-order;
  contradiction vs untracked).
- Negative controls (`test_task81_r1_guard_negative_controls.py`, 4 cases)
  deliberately undo each guard's persisted effect and prove the forbidden
  outcome occurs.

### Test evidence (E5)

| Run | Command | Result |
|---|---|---|
| Baseline | `pytest -p no:cacheprovider tests/ -q -rxXs` | `2597 passed, 1 skipped, 10 xfailed`, exit 0 — `baseline_full_suite.txt` |
| §2 pre-fix | `pytest tests/test_task81_r1_late_fill_recovery.py` (pre-fix) | `5 failed, 5 passed` — `section2_prefix.txt` |
| §3 pre-fix | `pytest tests/test_task81_r1_reconciliation_completeness.py` (pre-fix) | `5 failed, 1 passed` — `section3_prefix.txt` |
| §4 pre-fix | `pytest tests/test_task81_r1_missing_identity_recovery.py` (pre-fix) | `5 failed, 3 passed` — `section4_prefix.txt` |
| Focused recovery/reconciliation ×2 | `pytest -p no:cacheprovider <19 recovery/reconciliation/eod/cli suites>` | run 1: `252 passed`; run 2: `252 passed` — `focused_recovery_run{1,2}.txt` |
| xfail exposure | `pytest --runxfail <10 xfails + 1 skip>` | all 10 fail with `trades_executed=0`-family errors; the skip conditionally skips — `xfail_runxfail_*.txt` |
| Final full suite | `pytest -p no:cacheprovider tests/ -q -rxXs` | **`2625 passed, 1 skipped, 10 xfailed`, exit 0 (848s)** — `final_full_suite.txt` |

**Count reconciliation:** baseline `2597 passed / 1 skipped / 10 xfailed`
→ final `2625 / 1 / 10`. Delta `+28 passed` = exactly the 28 new items
collected across the 4 new `test_task81_r1_*` files (verified via
`pytest --collect-only`). `skipped` and `xfailed` unchanged; `0` failed,
`0` xpassed, `0` errors. No dependency added/upgraded; no skip/xfail
marker changed.

## Remaining blockers vs deferred work

**Blockers to Original/PIV isolation: none.**

**Deferred (non-blocking):**
- IEX receipt-vs-source-time question — needs a captured raw `bars/latest`
  log with per-bar source `t`, or an approved `gap_forensics.py` check
  against Alpaca's historical archive. Relevant only to a future
  mid-liquidity pilot / a market-age freshness gate.
- `sample_multi_trade_1m.csv` regeneration — a Task 73S-style synthetic
  OHLCV authoring follow-up; closes the 10 xfails + enables case #9's
  assertion in place of skip S1.
- (Carried from Task 81) the HTML/WebSocket dashboard still consumes
  general-pipeline Redis sources; the PIV projection/API source-health is
  corrected and scoped.

## Handoff to the isolation task

Unchanged from the Task 81 handoff, plus:
- `apply_broker_update`'s late-fill re-open path emits `POSITION_OPENED`
  with `status=REOPENED_BY_LATE_FILL_COMPLETION`; an isolated Original and
  PIV must each track this per-side (their own `open_position_by_symbol`).
- `reconcile()`'s `contradictory_broker_orders` / `orphan_intents` buckets
  and `_classify_broker_open_order` are per-`lifecycle_state.json`; the
  isolated sides must not share order/intent state.
- `assess_session_recovery` now treats a missing identity as unusable —
  each isolated side needs its own `session_identity.json` in its own
  `state_dir`, or one side's absence blocks the other.

Stop here. Do not begin isolation implementation.
