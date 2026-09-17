# Package 2 — Durable Account Blocks and Auditable Clearance

**Type**: implementation task. Authorized by Session 13
(`docs/product/DECISION_LOG.md`, `docs/product/REQUIREMENTS_TRACKER.md`
`S13-10`). Starting HEAD `bc6273a` (Package 1's own commit), branch
`feature/task131-option-a-integration`.

## 1. Scope

Closes the enforcement half of `OPS-012`/`OPS-015`: Package 1 fixed
`EXIT_UNRESOLVED`'s *correctness* (capacity, symbol-ownership,
valuation, reconciliation) but explicitly left the account-wide
admission block and clearance workflow out of scope. This task
implements that block: a new, generic, storage-layer-agnostic
`account_blocks`/`block_clearances` table pair
(`talonx_ops/account_blocks.py`), embedded additively into each
account's own existing ledger file — `v2_lane.db` for V2,
`paper_trading.db` for Original's Intraday and Long-term lanes (one
file, two separate account identities: `ORIGINAL_INTRADAY`,
`ORIGINAL_LONGTERM`).

Four reason types are modelled (`EXIT_UNRESOLVED`, `LEDGER_MISMATCH`,
`CASH_DEFICIT`, `IDENTITY_MISMATCH`); three are wired to their real,
already-existing detection sources:

- **`EXIT_UNRESOLVED`** — `talonx_v2/store.py::mark_exit_unresolved()`
  records the block in the SAME commit as the status transition.
- **`LEDGER_MISMATCH` / `CASH_DEFICIT` (V2)** —
  `talonx_ops/prospective/close.py::_record_v2_reconciliation_blocks()`
  connects `_v2_reconcile()`'s own already-verified
  `cash_plus_open_cost_reconciles`/`no_negative_cash` FAIL results.
- **`LEDGER_MISMATCH` (Original/Intraday)** —
  `talonx_ops/eod_reconciliation.py::_record_original_intraday_
  reconciliation_blocks()` connects `build_reconciliation()`'s own
  conservative `original_paper: N open position(s) but 0 trades
  recorded ever` check. This is `OPS-015`'s own literal finding
  location. `original_paper` here reads exclusively the
  `positions`/`trade_history` tables — never `long_term_positions`/
  `long_term_trade_history` — so attribution to `ORIGINAL_INTRADAY`
  specifically (never `ORIGINAL_LONGTERM`) is exact, not invented.
- **`IDENTITY_MISMATCH`** — **no detector exists anywhere in this
  codebase**; per this task's own instruction not to invent identity
  checks, this reason type has no automated producer and clearance for
  it always refuses (see §5).

`experimental_paper` mismatches are **not** wired — Package 2's own
scope is "local Intraday and V2" only; Experimental is a separate,
untouched architecture.

## 2. Enforcement mechanism

The authoritative check runs as the **first statement** inside the
**same protected transaction** as the entry's own economic mutation —
never an earlier read, never a dashboard flag:

- `talonx_v2/paper.py::enter_position()` — checks
  `account_blocks.blocked_reason(c, V2_ACCOUNT_ID)` as the first line
  inside `with store.transaction() as c:`.
- `talonx_paper/store.py::execute_buy()` /
  `::execute_long_term_buy()` — checks
  `account_blocks.blocked_reason(self._conn, <account_id>)` as the
  first statement inside `with self._lock:`, returning `None` (the
  same established "rejected, nothing mutated" contract already used
  by `execute_sell`/`execute_dca_contribution`) if blocked.
  `talonx_paper/consumer.py`'s two `_execute_buy` call sites handle a
  `None` return gracefully (increment `trades_ignored`, log, return).

Blocks are ordinary rows in the account's own persistent ledger file —
restart-durable by construction, not in-memory state. `record_block()`
is an idempotent upsert: repeated detection of the same
`(account_id, reason_type, reference)` never creates a duplicate active
row and never perturbs an already-`ACTIVE` block's own
`detected_at_utc`. Clearing one block reason never clears another, and
this mechanism is entirely separate from the pre-existing user-pause
control (neither reads nor writes it).

## 3. Test-first verification

`tests/test_package2_account_blocks.py` was written to prove the
required acceptance criteria — 25 tests, all passing (see
`package2_tests_passing_raw.txt`), covering each of the task's own 12
acceptance items verbatim:

| # | Acceptance criterion | Test(s) |
|---|---|---|
| 1 | V2 EXIT_UNRESOLVED blocks new admissions for OTHER symbols | `test_v2_exit_unresolved_blocks_new_admission_for_a_different_symbol` |
| 2 | Ledger mismatch blocks the affected local account only | `test_ledger_mismatch_block_isolated_to_its_own_v2_account`, `test_eod_reconciliation_mismatch_blocks_original_intraday_only`, `test_original_longterm_block_does_not_affect_intraday_same_file` |
| 3 | Already-pending entry execution rechecks account blocks | `test_pending_entry_execution_rechecks_a_block_activated_after_the_decision_was_formed` |
| 4 | Block check and entry mutation are serialized at the database boundary | `test_competing_writer_cannot_commit_an_entry_after_a_prior_block_activation` |
| 5 | A competing writer cannot commit an entry after a prior block activation | same (real two-connection SQLite write-lock race, `threading.Thread` + two independent `V2Store` connections) |
| 6 | Restart preserves active blocks | `test_restart_preserves_active_blocks`, `test_restart_preserves_original_account_blocks` |
| 7 | Repeated incident detection is idempotent | `test_idempotent_repeated_detection_does_not_duplicate_or_perturb_detected_at` |
| 8 | Multiple block reasons remain independent | `test_multiple_block_reasons_remain_independent`, `test_mark_exit_unresolved_continues_while_entries_already_blocked` |
| 9 | Clearance without required evidence is refused | `test_clearance_without_required_evidence_is_refused` |
| 10 | Authorized clearance preserves its audit trail | `test_authorized_clearance_preserves_its_audit_trail`, `test_restart_preserves_clearance_history` |
| 11 | Existing exits and safe obligation recovery continue while entries are blocked | `test_exits_and_safe_obligation_recovery_continue_while_entries_are_blocked`, `test_mark_exit_unresolved_continues_while_entries_already_blocked` |
| 12 | Collection/notification failures do not erase blocks or accounting state | `test_recorded_reconciliation_block_survives_a_later_pipeline_step_failure` |

Plus dedicated coverage for `clearance.py`'s reason-type-specific
re-verification (refuses while still unresolved/still mismatched,
allows after a fresh re-check genuinely passes, refuses for
combinations with no re-verification workflow), the Original
Intraday/Long-term integration, and `consumer.py`'s graceful `None`
handling (mocked store, matching this project's own established
consumer-test boundary).

Two pre-existing Package 1 tests asserted the specific rejection
string `SYMBOL_ALREADY_OPEN` for a scenario where Package 2's new,
earlier, account-wide `EXIT_UNRESOLVED` check now legitimately fires
first (a stricter superset of the same refusal) — both were corrected
to accept either reason string while preserving each test's original
`entered is False` invariant unchanged (see
`tests/test_package1_settlement_integrity.py`,
`test_unresolved_position_blocks_a_second_open_in_the_same_symbol` and
`test_restart_preserves_unresolved_capacity_and_symbol_block`).

## 4. Two implementation bugs found and fixed during test-first development

1. **`sqlite3.OperationalError: cannot commit - no transaction is
   active`** in both `close.py::_record_v2_reconciliation_blocks()`
   and the new `eod_reconciliation.py::_record_original_intraday_
   reconciliation_blocks()`: Python's stdlib `sqlite3.Connection.
   executescript()` implicitly commits/ends any open transaction on
   that connection — calling it *after* `BEGIN IMMEDIATE` silently
   closed the transaction the code thought it still held. Fixed by
   running the additive `CREATE TABLE IF NOT EXISTS` DDL *before*
   `BEGIN IMMEDIATE`, never inside it.
2. **`TypeError: tuple indices must be integers or slices, not str`**
   in `account_blocks.py`'s `Block.from_row()`/`clearance_history()`:
   both assumed `sqlite3.Row`-style name-keyed access, but
   `talonx_paper.store.PaperTradingStore`'s own connection never sets
   `row_factory = sqlite3.Row` (unlike `V2Store`'s). Fixed by making
   both functions positional (`dict(zip(FIXED_COLUMN_ORDER, row))`),
   which works identically for a `sqlite3.Row` or a plain tuple —
   correctly honoring this module's own "storage-layer-agnostic"
   design contract instead of silently assuming every caller's
   connection is configured the same way `V2Store`'s is.

Both were caught by the test suite itself (not a later regression
pass) and are reflected in `package2_tests_passing_raw.txt`'s final,
all-green state.

## 5. Clearance interface

`python -m talonx_ops.prospective list-blocks --account {V2,
ORIGINAL_INTRADAY,ORIGINAL_LONGTERM} [--db-path PATH]` lists active
blocks. `python -m talonx_ops.prospective clear-block --account ...
--block-id ID --operator NAME --reason TEXT --evidence-ref TEXT
[--db-path PATH]` re-verifies fresh evidence
(`talonx_ops/prospective/clearance.py`) and persists exactly one
clearance attempt — approved or refused — with a full audit trail:

- `EXIT_UNRESOLVED` — allowed only if the referenced position is no
  longer `EXIT_UNRESOLVED` in the ledger. No supported
  accounting-correction workflow exists to resolve one today, so in
  practice this always refuses — an explicit, disclosed limitation,
  not an invented bypass (Package 2 never fabricates an exit price or
  forces settlement).
- `LEDGER_MISMATCH`/`CASH_DEFICIT` (V2) — re-runs `_v2_reconcile()`
  fresh and checks the *specific* assert the block was raised for.
- `LEDGER_MISMATCH` (`ORIGINAL_INTRADAY`,
  `original_paper_open_with_no_trades`) — re-runs
  `build_reconciliation()` fresh and checks whether an
  `original_paper:` mismatch is still present.
- Everything else (`CASH_DEFICIT`/Original, `IDENTITY_MISMATCH`
  anywhere) — no automated re-verification workflow exists; clearance
  always refuses rather than fabricate one.

**Trust boundary (disclosed, not fixed)**: `--operator` is a
self-reported identity recorded into the permanent audit trail, not an
authentication credential. The actual access control is OS/filesystem
access to run this script on the machine holding the production
ledger — identical to every other local administrative action already
in this project (`prospective start/close`, the loopback-only
`/admin/config` endpoint). This is a real limitation for a future
genuinely-remote or multi-operator deployment; introducing a new
authentication platform was explicitly out of this task's scope.

## 6. Regression

A combined 42-file scoped run (`regression_scope_raw.txt`) — Package
1's own test file, this task's new test file, and every existing test
file that imports any of the six modules this task touched
(`talonx_v2.{store,paper}`, `talonx_paper.{store,consumer}`,
`talonx_ops.prospective.{close,ledger_guard}`, plus
`talonx_ops.eod_reconciliation`'s own consumers) — produced **646
passed, 9 failed, 0 new failures**. All 9 failures are byte-identical
by name to the 9 pre-existing failures already documented in
`docs/research/evidence/package1_settlement_integrity/README.md`
(`test_task131_spa_discovery_backend.py::
test_admission_policy_reflects_permissive_default`; five
`test_task117_migration.py` tests; `test_task117_deployment_rehearsal.
py::test_bounded_controlled_deployment_rehearsal`;
`test_task112_tuesday_release.py::test_03_v1_fingerprint_intact`;
`test_task111_v2_e2e.py::test_item3_original_strategy_fingerprint_
unchanged`) — the last two are `OPS-017`'s already-tracked stale
fingerprint constant, independently reproduced again this session and
confirmed still unrelated (Package 2 never touches `talonx_quant/*`).

## 7. Strategy-contract preservation

V2's release fingerprint was directly re-verified (not inferred) via
`tests/test_task114_prospective.py::
test_b1_preflight_fingerprints_are_expected` and
`::test_task114_does_not_change_fingerprints` — both pass, confirming
`11107198c5b81237` unchanged. `V2Config`'s frozen parameter values were
not touched by this task.

## 8. Runtime and scope

- No application start/stop, no Telegram sends, no provider
  activation, no strategy-parameter change, no database reset.
- No production store was ever opened via a migrating/writing
  constructor for any read performed during this task — every test
  uses an isolated `tmp_path` SQLite file; production-state checks
  used only read-only `sqlite3.connect(..., mode=ro)` connections.
- A live TalonX process appears to hold `v2_lane.db`/
  `dispatch_audit.db` open (recent `-shm`/`-wal` activity observed at
  session start) — raw file-byte hashing was therefore judged
  unreliable evidence (legitimate concurrent production writes would
  make bytes differ regardless of this task's own effect), so a
  read-only **logical-state** snapshot (cash, open/closed/unresolved
  counts, trade count, and confirmation that no `account_blocks` table
  exists yet — i.e. no runtime activation has occurred) was captured
  instead — see `production_state_before.json`. `has_account_blocks_
  table: false` in that snapshot for both `v2_lane.db` and
  `paper_trading.db` confirms this task's new schema has not been
  applied to production data; it is applied automatically only the
  next time each store's normal constructor runs (no deployment was
  performed as part of this task).
- Diff scope: 6 production files modified
  (`talonx_v2/{store,paper}.py`, `talonx_paper/{store,consumer}.py`,
  `talonx_ops/prospective/{close,ledger_guard}.py`,
  `talonx_ops/eod_reconciliation.py`), 3 new production files
  (`talonx_ops/account_blocks.py`,
  `talonx_ops/prospective/clearance.py`, plus the `__main__.py`
  CLI-subcommand addition), 1 new test file, 2 pre-existing test
  assertions corrected for an intentional, disclosed behavior change.
  No config/runtime changes.
- `ledger_guard.py`'s own bounded Package 1 correction (found during
  this task's own Part 1 prerequisite verification, not a Package 2
  feature): `check_ledger_continuity()` had the identical fabricated-
  cash-mismatch defect Package 1 already fixed in
  `close.py::_v2_reconcile()` — an `EXIT_UNRESOLVED` position's cost
  basis was omitted from `expected_cash_if_flat`'s comparison. Fixed
  identically (add `unresolved_cost`, include it in the comparison).

## 9. Evidence files

- `package2_tests_passing_raw.txt` — full pytest output, this task's
  new test file, 25/25 passed.
- `regression_scope_raw.txt` — the 42-file combined scoped regression
  run, 646 passed / 9 failed (all pre-existing, byte-identical names
  to Package 1's own documented baseline).
- `production_state_before.json` / `production_state_after.json` —
  read-only logical-state snapshots of `v2_lane.db`/`paper_trading.db`,
  captured before and after this task's work. Identical: cash
  ($300,000.00 / $10,000.00), open-position counts, and table lists
  unchanged; `has_account_blocks_table: false` in both, confirming this
  task's new schema was never applied to production data.
