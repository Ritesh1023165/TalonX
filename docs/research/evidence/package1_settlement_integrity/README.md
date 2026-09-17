# Package 1 — Settlement Integrity & Unresolved Obligations

**Type**: implementation task (the first code change in this
documentation series). Authorized by Session 13 (`docs/product/
DECISION_LOG.md`, `docs/product/REQUIREMENTS_TRACKER.md` `S13-09`).
Starting HEAD `58249ef35bc68523ebdcb95f1787feb4e4005ff1`, branch
`feature/task131-option-a-integration`.

## 1. Scope

Two defects, both confirmed by direct code reading before any change
was made (not assumed from an earlier audit):

**A. Duplicate settlement.** `talonx_v2/paper.py::close_position()`
called `store.close_position()` — a conditional SQL `UPDATE ... WHERE
status='OPEN'` — but never checked whether that UPDATE actually
matched a row before unconditionally crediting cash, appending a
trade, and resetting cooldown. A second call against a stale snapshot
of an already-closed position (e.g. two overlapping callers that both
read the position while it was still `OPEN`) duplicated all three
economic effects even though the underlying SQL guard itself was
correct.

**B. Unresolved-obligation visibility.** `EXIT_UNRESOLVED` positions
were invisible to `V2Store.n_open()` (capacity) and
`V2Store.position_for_symbol()` (symbol ownership), and their cost
basis was silently omitted from V2's reconciliation
(`talonx_ops/prospective/close.py::_v2_reconcile()`) and equity
reporting (`talonx_ops/paper_performance.py::_v2_snapshot()`) — able to
under-count capacity, admit a second position in the same security,
report a fabricated "COMPLETE" cash-only equity, and produce a
fabricated cash-loss reconciliation mismatch, purely because the
unresolved position's cost was omitted from those calculations.

## 2. Baseline reproduction (before any fix)

`tests/test_package1_settlement_integrity.py` was written first and
run against the unmodified baseline. **9 of 14 tests failed**,
reproducing both defects precisely — see `baseline_failures_raw.txt`
for the full, unedited pytest output. Summary of the 9 failing
assertions:

| Test | Failing assertion |
|---|---|
| `test_sequential_duplicate_close_same_stale_snapshot` | cash credited twice for one close |
| `test_concurrent_duplicate_close_two_independent_connections` | same, via two real `threading.Thread`s + independent `V2Store` connections |
| `test_duplicate_close_does_not_reset_cooldown_twice` | cooldown moved forward by a duplicate call |
| `test_close_position_returns_a_no_op_outcome_for_an_already_closed_position` | `ExitOutcome` had no way to express "already settled" |
| `test_unresolved_position_retains_one_occupied_slot` | `n_open() == 0` after `EXIT_UNRESOLVED` (should retain the slot) |
| `test_unresolved_position_blocks_a_second_open_in_the_same_symbol` | a second entry was silently admitted into the same symbol |
| `test_unresolved_position_never_produces_complete_cash_only_equity` | `equity.status == "COMPLETE"` with an entirely-unknown-value obligation |
| `test_reconciliation_does_not_fabricate_a_cash_loss_for_unresolved` | `cash_plus_open_cost_reconciles: FAIL` purely from the omitted cost |
| `test_restart_preserves_unresolved_capacity_and_symbol_block` | same capacity/symbol gaps survive a simulated restart |

The remaining 5 tests (atomic-rollback-on-failure, cost/valuation
preservation on the row, no-phantom-credit-on-mark, normal re-entry
after a genuine close, normal OPEN/CLOSED sanity) **passed against the
baseline** — confirming the test file was not fabricating failures or
merely mirroring the intended fix.

## 3. Fix (minimum diff)

- `talonx_v2/store.py::close_position()` — returns `cursor.rowcount >
  0` instead of `None`; this IS the authoritative, atomic eligibility
  check (SQL-level, inside the same transaction).
- `talonx_v2/paper.py::close_position()` — checks that return value
  before any cash/trade/cooldown mutation; `ExitOutcome` gained a
  `settled: bool` field.
- `talonx_v2/pipeline.py::settle_due_exits()` — skips the exit-record/
  alert path when `out.settled` is `False`, so a no-op outcome never
  produces a duplicate notification.
- `talonx_v2/store.py::n_open()` / `::position_for_symbol()` —
  broadened to `status IN ('OPEN','EXIT_UNRESOLVED')`.
  `open_positions()` itself (and therefore `due_exits()`, the
  retryable/actionable set) is **unchanged** — `EXIT_UNRESOLVED`
  positions remain correctly excluded from automatic re-settlement,
  per this task's explicit instruction not to broaden every `OPEN`
  query.
- `talonx_ops/prospective/close.py::_v2_reconcile()` — sums
  `EXIT_UNRESOLVED` position cost separately and includes it in the
  `cash_plus_open_cost_reconciles` formula.
- `talonx_ops/paper_performance.py::_v2_snapshot()` — queries
  unresolved-position rows (not just a count), includes their cost in
  `expected_cash`, and forces `equity_status = "PARTIAL"` whenever any
  unresolved position exists. Adds a new, additive
  `exit_unresolved_cost_basis_total` field; the existing
  `exit_unresolved` integer-count field's type is unchanged (a known
  consumer, `talonx_ops/dashboard_read.py:285`, treats it as a count).

**Explicitly not done** (Package 2's own scope): no account-wide
admission block was added for `EXIT_UNRESOLVED` or for a reconciliation
mismatch. Slot/capacity/symbol-ownership/valuation/reconciliation
*correctness* is fixed; the separate "block ALL new admissions in the
account" workflow and its explicit-clearance mechanism are not — see
`docs/product/OPERATIONAL_FINDINGS.md` `OPS-012`/`OPS-015` for what
remains open.

## 4. Post-fix verification

All 14 tests pass — see `post_fix_passing_raw.txt`.

A scoped regression run of 32 existing test files that exercise the
same store/paper/pipeline/close/paper_performance surface (406 tests
total) found **zero new failures**. 9 pre-existing failures were
independently reproduced against the unmodified baseline (`git stash`)
and confirmed unrelated to this change — see
`regression_scope_post_fix_raw.txt` and `regression_baseline_raw.txt`.
Two of those pre-existing failures are a stale hardcoded fingerprint
constant in two unrelated test files, newly tracked as
`docs/product/OPERATIONAL_FINDINGS.md` `OPS-017` (not fixed here, out
of Package 1's scope).

Two pre-existing tests asserted the *old* (incorrect) `n_open() == 0`
behavior for an `EXIT_UNRESOLVED` position and were corrected to
assert the fixed behavior, preserving each test's original intent:

- `tests/test_task117_phase0_entry_timing.py::
  test_e8c_exit_unresolved_when_target_and_all_fallforward_missing`
- `tests/test_task112_tuesday_release.py::
  test_15_missing_through_plus5_is_explicit_unresolved`

## 5. Strategy-contract preservation

The V2 release fingerprint was directly re-computed (not inferred)
after the fix:

```
got:      11107198c5b81237
expected: 11107198c5b81237
match:    True
```

`v2_release_fingerprint()` hashes `V2Config`'s frozen parameter values
and `V2_VERSION` only — not source files — and none of those values
were touched by this change. Original's own fingerprint mismatch
(`ed8272fe568d` vs. two test files' hardcoded `2ae6216bca70`) is the
pre-existing, unrelated `OPS-017` finding above.

## 6. Runtime and scope

- No application start/stop, no Telegram sends, no provider activation,
  no strategy-parameter change, no database reset.
- No live database was touched: `v2_lane.db` (repo root, gitignored)
  was confirmed unmodified (mtime predates this session by two days)
  throughout — every test uses an isolated `tmp_path` SQLite file.
- No TalonX application process was running at any point during this
  task (confirmed by a read-only process check).
- Diff scope: 5 production files (`talonx_v2/{store,paper,pipeline}.py`,
  `talonx_ops/{paper_performance.py,prospective/close.py}`), 2
  pre-existing test files corrected for the intentional behavior
  change, 1 new test file. No unintended files, no config/runtime
  changes.

## 7. Evidence files

- `baseline_failures_raw.txt` — full pytest output, unmodified
  baseline, 9/14 failed.
- `post_fix_passing_raw.txt` — full pytest output, after the fix,
  14/14 passed.
- `regression_baseline_raw.txt` / `regression_scope_post_fix_raw.txt`
  — the 32-file scoped regression run before/after, confirming no new
  failures.
