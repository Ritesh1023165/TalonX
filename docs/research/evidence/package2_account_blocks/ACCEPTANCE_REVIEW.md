# Package 2 Acceptance Review

**This is a SEPARATE deliverable from the original Package 2
implementation evidence** (`README.md`, `package2_tests_passing_raw.txt`,
`regression_scope_raw.txt`, `production_state_before/after.json` in
this same directory). Nothing in the original evidence is rewritten
here; this document records the acceptance review's own findings,
corrections, and evidence on top of it.

**Baseline**: branch `feature/task131-option-a-integration`, starting
HEAD `0654491` (verified: current branch, current HEAD, clean working
tree, matching the reported handoff SHA exactly — no drift to
reconcile).

**Files inspected** (beyond the six product docs the task named):
`talonx_v2/service.py` (`_phase_open`/`_phase_close`/`_phase_post_close`),
`talonx_v2/paper.py` (`enter_position`/`close_position`),
`talonx_v2/pipeline.py` (`process_episode`/`settle_due_exits`),
`talonx_v2/store.py`, `talonx_paper/store.py` (all three cash-debit
methods), `talonx_paper/consumer.py`, `talonx_paper/engine.py`,
`talonx_ops/account_blocks.py`, `talonx_ops/prospective/clearance.py`,
`talonx_ops/prospective/close.py`, `talonx_ops/eod_reconciliation.py`,
`talonx_ops/dashboard_read.py`, `talonx_ops/prospective/lane_accounting.py`,
`research/scripts/task112_tuesday_preflight.py`.

---

## A1 — Blocked account vs. already-admitted PENDING intents

**Full lifecycle traced**: candidate → `_phase_post_close`'s "PRE-OPEN
ENTRY INTENT PASS" (reservation: `upsert_entry_intent` inside
`with self.store.transaction():`, gated only by
`_capacity_rejection_reason()`) → durable PENDING intent → a LATER
tick's `_phase_open` → `pipeline.process_episode` → `paper.
enter_position()` (the actual economic mutation, inside
`with store.transaction() as c:`).

**Finding (fill path — already safe)**: `enter_position()`'s block
check (`account_blocks.blocked_reason(c, V2_ACCOUNT_ID)`) is the FIRST
statement inside its own protected transaction, and this is the ONLY
code path anywhere that ever marks an intent `FILLED`
(`service.py::_on_entry_recorded`, reached only after `res.entries`
actually grew from a real `enter_position` success). A PENDING intent
therefore cannot silently fill while blocked — confirmed by tracing
every `mark_entry_intent(..., "FILLED", ...)` call site (exactly one)
and re-verifying with an isolated test.

**Finding (reservation path — a real gap, corrected)**:
`_capacity_rejection_reason()`, the ONLY gate on creating a NEW
PENDING intent, checked cash/slot capacity only — never the account
block. A brand-new episode discovered while the account was seriously
blocked could still receive a fresh reservation and an ACTIONABLE
"ENTRY_INTENT" alert promising a future BUY that could never actually
fill — misleading to an operator, and a form of new commitment the
product rule ("a serious account block must stop NEW account
exposure") should cover.

**Correction** (`talonx_v2/service.py`): an unconditional (never
gated behind `TALONX_V2_DURABLE_STORE_ENABLED`, unlike the capacity
check — a serious block is a safety mechanism, not an opt-in
admission-policy refinement) `account_blocks.blocked_reason(c,
V2_ACCOUNT_ID)` check, read on the SAME connection/transaction as the
reservation write, added immediately before the existing capacity
check inside the PRE-OPEN loop. A blocked account now records
`SKIPPED_ACCOUNT_BLOCKED` and creates no intent, no alert. New
`_account_blocked_intent_rejected` counter, reported in tick status
(`account_blocked_intent_rejected_this_tick`).

**What was explicitly NOT touched** (per the task's own "do not
indiscriminately block every state transition"): legitimate
expiry/cancellation of an EXISTING PENDING intent
(`_phase_post_close`'s unconditional staleness sweep); existing
open-position exits (`_phase_close`/`settle_due_exits`); the
already-correct fill-time recheck itself.

**Tests** (`tests/test_package2_acceptance_review.py`, all passing):
- `test_a1_pending_intent_created_before_block_does_not_silently_fill_while_blocked`
- `test_a1_new_reservation_refused_while_account_is_blocked`
- `test_a1_blocked_pending_intent_can_still_legitimately_expire`
- `test_a1_existing_open_position_exit_continues_while_blocked`
- `test_a1_independent_connections_block_visible_to_second_writer` (two
  genuinely independent `V2Store`/`V2Service` instances)

---

## A2 — Original CASH_DEFICIT

**Authoritative cash model**: exactly two persisted fields --
`portfolio_state.current_cash` (`ORIGINAL_INTRADAY`) and
`long_term_portfolio_state.current_cash` (`ORIGINAL_LONGTERM`). No
reservation concept exists for Original (unlike V2's PENDING intents)
-- every BUY/DCA debits immediately.

**Finding (a real, structural reliability gap)**: three debit paths
existed -- `execute_buy`, `execute_long_term_buy`,
`execute_dca_contribution` -- and ALL THREE trusted a caller-supplied
`cost`/`contribution_usd` value with NO internal cap against
`current_cash`. Callers (`consumer.py`) do pre-size via
`calculate_buy()` (capped) or pre-check (`if contribution_usd >
summary["current_cash"]:`), but the STORE ITSELF never verified this
-- a caller-side sizing bug, a stale/raced pre-check, or a future call
site skipping sizing entirely could all silently debit past available
cash with no defense at the point of mutation. Additionally,
`execute_dca_contribution` had **no account-block check at all** -- a
DCA contribution commits new economic exposure into an existing
position, the same category the block already covered for a fresh
BUY, and Package 2's original implementation missed it.

**Correction** (`talonx_paper/store.py`): all three methods now cap
their own debit (`if cost > current_cash + 1e-6: refuse, no mutation,
ignored_decisions recorded`) inside the same locked block as the
write, the SAME "rejected, nothing mutated" contract the account-block
check already established. `execute_dca_contribution` now also checks
the `ORIGINAL_LONGTERM` account block first, mirroring
`execute_long_term_buy` exactly.

**Detector implemented** (`talonx_ops/eod_reconciliation.py`, new
`_record_original_cash_deficit_blocks()`, wired into
`run_and_persist()`): once every debit path is capped, `current_cash <
0` has NO benign explanation -- it is reachable only through genuine
corruption (external tampering, a bug that bypassed the store's own
guards, a legacy pre-fix row). This is a MORE reliable invariant than
`eod_reconciliation.py`'s own existing "open positions but no trades"
heuristic. A negative balance records a `CASH_DEFICIT` block on the
correct account (`ORIGINAL_INTRADAY` from `portfolio_state`,
`ORIGINAL_LONGTERM` from `long_term_portfolio_state` -- read
separately, attributed exactly, never conflated).

**Tests**: `test_a2_execute_buy_refuses_a_cost_exceeding_available_cash`,
`test_a2_execute_long_term_buy_refuses_a_cost_exceeding_available_cash`,
`test_a2_execute_dca_contribution_now_checks_the_account_block`,
`test_a2_execute_dca_contribution_refuses_a_contribution_exceeding_cash`,
`test_a2_cash_deficit_detector_blocks_original_intraday_only`,
`test_a2_cash_deficit_detector_blocks_original_longterm_only`,
`test_a2_cash_deficit_detector_is_a_no_op_when_cash_is_healthy`.

---

## A3 — Live database-owning processes (read-only)

Investigated via: `tasklist`, `Get-CimInstance Win32_Process` (full
command-line search for `python|talonx|wsl|docker`), `wsl -l -v`,
`docker ps -a`, and `~/.talonx/runtime_metadata.json` (the last
self-recorded process start). **No process was killed, signalled,
stopped, or attached to in a mutating manner.**

| PID | start time | command | worktree/path | running SHA | confidence |
|---|---|---|---|---|---|
| 13616 (from `runtime_metadata.json`; **NOT found in a live `tasklist`/WMI lookup by this PID -- confirmed not currently running**) | 2026-09-15T10:40:07 UTC | unrecorded (metadata file has no full command line) | unrecorded | `12be1bd7` (an ancestor of current HEAD `0654491` -- several commits behind both Package 1 and Package 2) | INFERRED (from the last self-written status file only; not independently confirmed to have ever matched a live process observed by this review) |
| none | — | — | — | — | KNOWN: no `python.exe` (or any process with "talonx" in its command line) is running right now, per native Windows process enumeration |

**Supporting observations**: the WSL `Ubuntu` distro (the only
plausible host for a TalonX process invisible to native Windows
tooling) is `Stopped`. Docker Desktop's own backend distro is
`Running`, hosting exactly one relevant container, `talonx-redis`
(image `redis:7.0.15`, up 2 days, healthy) -- this is message-bus
infrastructure only, not itself a reader/writer of the SQLite ledger
files. `v2_lane.db`/`paper_trading.db`/`dispatch_audit.db`'s own
CONTENT mtimes are unchanged since 2026-09-15 21:45/05:45 UTC
(multiple checks across this review, hours apart, all identical); only
their `-shm` companion files show recent touches, fully explained by
this review's OWN repeated read-only `sqlite3.connect(mode=ro)`
snapshots (which update WAL reader bookkeeping even for a pure read)
rather than any external writer.

**Limitation, disclosed per the task's own instruction**: this is a
snapshot judgement, not a guarantee for any other moment in time -- a
process could start between one check and the next, and a process
inside a WSL distro OTHER than the two enumerated here, or one that
evades `Get-CimInstance`'s command-line capture, would not be visible
to this investigation. The task's own premise (a live process was
"reportedly found" during Package 2's own session) is not contradicted
by this finding -- that observation was made several hours/turns
earlier; the process the earlier `-shm` activity was attributed to may
simply have exited since. Nothing was assumed stopped for the purpose
of choosing what actions this review took (no database was mutated
regardless of this finding).

---

## A4 — Clearance/verification serialization

**Race found and confirmed real**: `clearance.py::clear_block()`
(before this correction) called `verify_clearance_eligible()` on
short-lived, separate connections that opened and closed BEFORE
`store.attempt_block_clearance()` even began its own transaction --
textbook T1-verify / T2-mutate / T1-clear-on-stale-evidence.

**Correction**:
- **V2**: `clear_block()` now opens `V2Store(db_path).transaction()`
  FIRST (`BEGIN IMMEDIATE`, V2's existing real cross-process write
  lock), performs the fresh verification read and the clearance write
  BOTH inside that SAME held transaction, then commits. A competing
  writer's own `BEGIN IMMEDIATE` against the same file must wait until
  this transaction completes.
- **Original**: `PaperTradingStore` gained a public `lock()` context
  manager. Two layers, both needed: `self._lock` (in-process,
  `threading.Lock`) for same-instance callers, PLUS a real SQL `BEGIN
  IMMEDIATE` issued the instant `lock()` opens -- this is what
  actually closes the race for Original, since `clear_block()`
  constructs its OWN fresh `PaperTradingStore` instance rather than
  reusing any existing one, so the Python-level lock alone provides NO
  protection against a genuinely separate instance (the live trading
  engine's own long-lived instance, or a second CLI invocation). Also
  added `PRAGMA busy_timeout=30000` to `PaperTradingStore.__init__`
  (previously absent -- default 0, meaning a contending writer would
  have raised `OperationalError: database is locked` immediately
  rather than correctly waiting), matching `V2Store`'s own existing
  default.

**Independent-writer test evidence** (not a single-connection unit
test -- see the file for full methodology):
`test_a4_concurrent_writer_cannot_land_between_verification_and_clearance_write`
races a genuinely independent `V2Store` connection attempting to
re-record the SAME block while `verify_clearance_eligible` (stubbed to
report "healthy" and then pause) holds clearance's write lock; a
bounded `Thread.join(timeout=0.5)` liveness check confirms the
competing writer is still blocked before the lock is released, then
confirms it correctly lands AFTER (re-activating the block, since the
issue genuinely recurred -- not a race that let stale evidence win).
`test_a4_original_clearance_also_serializes_verification_and_write`
proves the equivalent for Original.

**Disclosed limitation**: Original's serialization is real
(SQL-level `BEGIN IMMEDIATE`, cross-process), matching V2's guarantee
for the specific clearance path this review changed. It does NOT
retrofit `BEGIN IMMEDIATE` onto Original's OTHER writers
(`execute_buy` etc., which still rely on implicit DEFERRED
transactions) -- doing so is a broader change than this acceptance
review's bounded scope ("do not redesign Original accounting");
`busy_timeout=30000` (added here) at least ensures any such writer
that DOES contend with clearance's held lock waits rather than
instant-fails.

---

## A5 — Settlement authoritative inputs

**Finding**: `talonx_v2/paper.py::close_position()` computed
`pnl_usd`/`pnl_pct`/`held` from the CALLER-supplied `position` dict's
`entry_price`/`shares`/`entry_session` BEFORE ever touching the
database, and used the caller's `shares`/`position_cost` for the cash
credit and trade record too. The earlier reasoning ("these DB columns
are write-once, so this is safe") was correct about the SCHEMA today
but was not itself proof settlement uses the authoritative persisted
values -- it was proof the caller's copy currently happens to agree
with them, which is a weaker, more fragile guarantee (holds only as
long as no future code ever legitimately needs to touch those
columns, and provides no defense against a caller bug or a stale
snapshot from an overlapping reader).

**Correction**: `close_position()` now treats ONLY `position_id` as a
trusted lookup key. Immediately inside `with store.transaction() as
c:`, it re-reads `episode_id`, `symbol`, `entry_price`, `shares`,
`position_cost`, `entry_session` fresh via `c.execute(...)` against
the live row, computes PnL/holding-period from THOSE values, and uses
them for every subsequent mutation (the `close_position()` status
UPDATE's own PnL fields, the cash credit, the trade record, the
`ExitOutcome` returned to the caller). A `position_id` that no longer
exists returns a non-fabricating `settled=False` outcome rather than
crash or invent numbers.

**Tests**:
`test_a5_close_position_ignores_a_stale_caller_supplied_shares_and_entry_price`
(a caller passing 100x the real share count and a wildly wrong entry
price still produces the CORRECT cash credit/P&L, proving the DB
values won, not the caller's);
`test_a5_close_position_ignores_a_stale_caller_supplied_position_id_free_fields`
(wrong symbol/episode_id in the caller dict still produce the correct
trade record);
`test_a5_close_position_refuses_a_nonexistent_position_id_without_fabricating_an_exit`.

Package 1's own 14-test suite (`test_package1_settlement_integrity.py`)
re-run unmodified against this rewrite: 14/14 still pass -- the
rewrite preserves every existing guarantee (duplicate-settlement
prevention, atomic rollback, no-op detection) while additionally
closing this one.

---

## A6 — Unresolved-position presentation omissions

| file/function | omission | safety impact | action | follow-up |
|---|---|---|---|---|
| `talonx_ops/dashboard_read.py` (`v2_broad_discovery`/ledger section, `~line 1032-1051`) | `capacity`/`allocated_capital`/`n_open` count only `status='OPEN'`, excluding `EXIT_UNRESOLVED` | **(B) presentation only** -- this is a read-only human display; the actual admission gate (`enter_position`'s `n_open()` check, and the account block) is separately and correctly computed elsewhere and does not consult this dashboard field at all | not fixed (out of this review's bounded scope) | P3: a human operator glancing at "capacity: 3/20" could underestimate true occupied capacity by one when a slot is EXIT_UNRESOLVED (the SAME payload does separately show `exit_unresolved: N` explicitly, so the information is present, just not summed into the headline number) |
| `talonx_ops/prospective/lane_accounting.py:150` | `open_positions` count excludes `EXIT_UNRESOLVED` | **(B) presentation/reporting only** -- confirmed by tracing its one caller (`close.py`'s `run_close`): the value is written ONLY to an evidence JSON file (`lane_accounting_eod.json`); `asserts["lane_accounting_snapshot"]` reflects whether the snapshot itself succeeded, never this count's value -- no gating decision reads it | not fixed | P3; secondarily **(C)**: a future researcher reading historical `lane_accounting_eod.json` files without knowing this exclusion could slightly undercount capacity utilization in a retrospective analysis |
| `research/scripts/task112_tuesday_preflight.py` | historical/frozen research script | re-examined this review: it already reports `unresolved` as a SEPARATE, explicit field alongside `opens` (line 110) -- not actually a silent omission at all, just doesn't sum the two in whatever it computes downstream | not fixed (historical evidence-generation script; re-running it is explicitly out of scope) | none -- lower severity than previously catalogued; informational only |

None of the three influence any operational admission/safety decision.
None required a fix under this review's own acceptance standard.

---

## A7 — Production preservation claim

**What was actually observed**: three read-only logical-state
snapshots this review (start-of-review, matching Package 2's own
`production_state_after.json` exactly; and end-of-review, after every
code change and test run in this session) — see
`acceptance_review_production_state_start.json` /
`acceptance_review_production_state_end.json`. Both snapshots'
observed fields — `cash`, `n_open`/`n_closed`/`n_unresolved`,
`n_trades`, `intraday_current_cash`, `longterm_current_cash`, the
sorted table-name list, and `has_account_blocks_table` — are
byte-identical between start and end. Separately, direct filesystem
`stat` checks of `v2_lane.db`/`paper_trading.db`/`dispatch_audit.db`
(not their `-shm`/`-wal` companions) show unchanged content
modification timestamps throughout this entire review.

**What this precisely proves**: the SPECIFIC fields this review chose
to read were observed unchanged before and after, and — separately —
no write operation performed by this review's own code (every test
uses an isolated `tmp_path` fixture; every production-state check used
only a read-only `sqlite3.connect(..., mode=ro)` connection) ever
touched these files. Combined with the file-content-mtime evidence,
this supports "no mutation was performed by this task."

**What this does NOT prove, and is not claimed**: this is not a
byte-for-byte hash comparison of the full files (deliberately —
`-shm`/`-wal` activity from legitimate concurrent readers, including
this review's own repeated read-only queries, makes raw file bytes an
unreliable signal, as already disclosed in the original Package 2
evidence). It does not prove every ROW in every TABLE is unchanged —
only the specific counts/fields queried. It does not prove no OTHER
process wrote and then reverted a change within the review window, nor
that no row outside the queried columns/tables was touched. These are
the same, disclosed limits the original Package 2 evidence already
stated; this review's own new evidence is held to the identical
standard, not a stronger one.

---

## Summary of code/document changes this review made

| file | change |
|---|---|
| `talonx_v2/service.py` | A1: account-block check before creating a NEW PENDING intent (reservation); new counter + status field |
| `talonx_v2/paper.py` | A5: `close_position()` re-reads authoritative position data from inside the protected transaction; caller dict now used only as a `position_id` lookup key |
| `talonx_paper/store.py` | A2: cash-debit caps in `execute_buy`/`execute_long_term_buy`/`execute_dca_contribution`; account-block check added to `execute_dca_contribution`; A4: `PRAGMA busy_timeout=30000`; `lock()` context manager now issues a real `BEGIN IMMEDIATE` |
| `talonx_paper/consumer.py` | A2: comment update reflecting the DCA loop's `None`-return causes (position closed / blocked / cash-capped) |
| `talonx_ops/eod_reconciliation.py` | A2: new `_record_original_cash_deficit_blocks()`, wired into `run_and_persist()` |
| `talonx_ops/prospective/clearance.py` | A4: `clear_block()` rewritten to hold the account's own write lock across verification + write, for both V2 and Original |
| `tests/test_package2_acceptance_review.py` | new file, 17 targeted tests (A1 ×5, A2 ×7, A4 ×2, A5 ×3) |
| `docs/product/{REQUIREMENTS_TRACKER,OPERATIONAL_FINDINGS,DECISION_LOG}.md` | acceptance-review findings recorded (see below) |

---

## Test commands and results (this review)

```
.venv/Scripts/python.exe -m pytest tests/test_package2_acceptance_review.py -p no:cacheprovider -q
17 passed

.venv/Scripts/python.exe -m pytest tests/test_package1_settlement_integrity.py tests/test_package2_account_blocks.py tests/test_package2_acceptance_review.py -p no:cacheprovider -q
56 passed

.venv/Scripts/python.exe -m pytest <42-file combined scoped regression -- see acceptance_review_regression_raw.txt> -p no:cacheprovider -q
663 passed, 9 failed
```

The 9 failures are byte-identical BY NAME to the 9 pre-existing
failures already documented in the original Package 2 evidence
(`README.md` §6) and Package 1's own evidence before it -- confirmed
again this review by direct inspection of two of them
(`test_item3_original_strategy_fingerprint_unchanged`,
`test_03_v1_fingerprint_intact`: both report the SAME unexpected
fingerprint value `ed8272fe568d`, the already-tracked `OPS-017`
finding in `talonx_quant/*`, a subsystem this review never touches).
Zero new failures introduced by this review's own corrections.

V2's own strategy fingerprint (`11107198c5b81237`) was independently
re-verified unchanged after every code change in this review via
`tests/test_task114_prospective.py::test_b1_preflight_fingerprints_are_expected`
and `::test_task114_does_not_change_fingerprints` (both pass).
