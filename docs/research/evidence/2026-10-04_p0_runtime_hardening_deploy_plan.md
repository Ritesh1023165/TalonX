# P0 runtime hardening: deploy plan (WRITTEN, NOT RUN)

## Summary

| | |
|---|---|
| **Branch** | `fix/p0-runtime-ownership-snapshot`, from `86f7375` (the live head). The live branch was not touched. |
| **When** | Sunday 2026-10-04, after the Gate D review. The engine is in its **CLOSED** phase: no trading window, and ingestion and discovery idle. |
| **Before the deploy** | Phase D (`\TalonX\ERM_V1_PhaseD_2026-10-03`) must have **finished**. Check that the task's `LastTaskResult` is set and that `phase_d_runner.log` ends with END or ABORT. |
| **Strategy, scoring, thresholds, notification policy, promotion** | Unchanged. Every strategy fingerprint is byte-identical to `86f7375` (§6). |
| **Goal** | One coordinated restart of every component at an **OPERATIONS_ONLY** boundary, followed by status/deployment checks and cursor/outbox no-replay checks in the 2026-09-26 evidence format. |

## 1. What changes at runtime

**Ownership (FIX 1).**
- Each component holds an **exclusive OS lock** (`results/opportunity/locks/<c>.lock`, msvcrt byte-range lock) for its whole lifetime. `<c>.pid` is display only.
- A component is live if and only if its lock is held.
- The supervisor holds its own lock (`supervisor.lock`), so only one supervisor can run, and it writes a heartbeat.
- `restart <c>` hands the restart to the supervisor (`control/<c>.restart`) while the supervisor's heartbeat is under 60 s old. Without a live supervisor, the CLI restarts the component directly.
- No spawn happens unless the stop is confirmed; otherwise the event is `RESTART_ABORTED_STOP_FAILED`.
- Heartbeat writes are retried and never fatal; a failure is recorded as `HEARTBEAT_WRITE_FAILED`.
- **Force-kill** applies only to a PID whose command line is this component. A reused PID is never killed.

**Snapshots (FIX 2).** These are additive schema changes to `market.db`, migrated in place at ingestion start:
- the new `snapshot_generations` table;
- a `generation` column on `ingestion_state` and `aggregates`.

The DTU active set, the aggregates and `as_of` are written in **one transaction per cycle** under one generation. All of these read one committed generation inside one read transaction:
- `read_state` (discovery);
- the `:8787` read model (`opportunity_read`);
- the Sentinel `UniverseView` / `LiveUniverse`.

A DTU set that isn't the generation's own is never served. Discovery falls back to its existing full-universe path in that case.

**Lock-file compatibility.** The old code wrote a PID into `<c>.lock`. The new code opens that same file without truncating it and locks byte 0. Old processes take no OS lock, which is why **every** old process must be stopped before any new one starts (§3).

## 2. Boundary classification

Component versions move as follows. They were computed from git (`runtime.version_at_commit` vs the working tree) without opening any live store.

| Component | Changed sources | Class at restart | How |
|---|---|---|---|
| evaluator:INTRADAY / SAME_DAY / SHORT_TERM / LONG_TERM, notifier, outcomes, reporting, promotion | `runtime.py` only | OPERATIONS_ONLY | `declare-shared-runtime --apply` (ELIGIBLE: `runtime.py` is in `SHARED_RUNTIME_OPS_FILES`) |
| supervisor | `supervise.py`, `__main__.py` | OPERATIONS_ONLY | default class (F-P1) |
| sentinel | `runtime.py`, `operator_control/universe_view.py` (read transaction only) | OPERATIONS_ONLY | default class |
| **ingestion** | `runtime.py`, `ingestion.py`, `universe_tiers.py` | **needs a declaration** (default DATA_FIX) | version-bound declaration (§3 step 4) |
| **discovery** | the same (its hash includes `ingestion.py` and `universe_tiers.py`) | **needs a declaration** (default STRATEGY_MATERIAL) | version-bound declaration (§3 step 4) |

**Owner decision for ingestion and discovery.**
- **The case for OPERATIONS_ONLY:**
  - Same rules and same fingerprints.
  - The same data, now published atomically.
  - The V1 bit-identical feature and PREMARKET classification tests pass.
- **The honest case for DATA_FIX:**
  - In a race, a reader now sees a consistent snapshot rather than a mixed one, so a mid-race scan can differ from what the old code would have produced. That is the bug being fixed.
  - With DTU active and a missing generation link, discovery now uses the full universe rather than a possibly stale set.
- **The plan below assumes OPERATIONS_ONLY.** If you choose DATA_FIX, change the class in step 4. Discovery's detection comparability then breaks at this boundary.

## 3. Procedure (Sunday, CLOSED phase)

Run from `C:\workspace\TalonX`. The p0 branch is first merged or fast-forwarded into the live branch through the normal PR flow, which is outside this plan's scope; this plan starts from "the live worktree is at the merged commit".

0. **Preconditions.**
   - `python -m talonx_opportunity status` shows the phase CLOSED and all components RUNNING.
   - Phase D has finished.
   - No Lab or promotion outbox item is PENDING.
1. **Pre-snapshot.** Run the 2026-09-26 tool against the live stores, read-only:
   `python docs\research\evidence\2026-09-26_p0_package1\tools\snap.py > results\p0_runtime_hardening\pre_snap.json`
   It records the 6 consumer cursors, candidates and events (total and distinct), decisions, the Lab outbox by state, promotion SENT/queued, scans, deployments and components.
2. **Stop everything with the OLD code**, while the old code is still checked out:
   - Stop the supervisor loop (its console, or kill its process; it is not a component).
   - Then run `python -m talonx_opportunity down`.
   - Confirm every `results\opportunity\locks\*.lock` owner PID is gone (`Get-Process -Id <pid>` fails for each).
   - **Do not continue while any old component is alive.**
3. **Update the code**: check out the merged commit in the live worktree.
4. **Declare boundaries.**
   - `python -m talonx_opportunity declare-shared-runtime` (dry run). Expect ELIGIBLE for the 8 components in §2 and REFUSED for ingestion and discovery.
   - `python -m talonx_opportunity declare-shared-runtime --apply`
   - Ingestion and discovery, version-bound so that any further code change is classified normally:
     `python -c "from talonx_opportunity.runtime import RuntimeStore, component_version as v; r=RuntimeStore(); [r.declare_change(c, 'OPERATIONS_ONLY', 'P0 runtime hardening: atomic ownership + one-generation snapshots; strategy fingerprints unchanged (2026-10-04)', expected_version=v(c)) for c in ('ingestion','discovery')]"`
5. **Single coordinated start**, with the same environment as the 2026-09-30 activation (the DTU ACTIVE environment):
   `python -m talonx_opportunity up --deliver --supervise` with `TALONX_DTU_MODE=ACTIVE`, `TALONX_SEC_BACKGROUND_REFRESH_ENABLED=1`, `TALONX_SEC_REFRESH_CAPACITY=OBSERVABILITY_ONLY`, `TALONX_NOTIFY_RESEARCH_ENABLED=1`, `TALONX_OPP_NOTIFY_POLICY=LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925`, `TALONX_OPPORTUNITY_PROMOTION_MODE=PAPER_SIGNAL`, `TALONX_SENTINEL_COMMANDS_ENABLED=1` and `OPERATOR_UNIVERSE_MUTATION_MODE=DRY_RUN`.
   Then restart the `:8787` cockpit (`dashboard_web.py`), which serves `opportunity_read`.
6. **Status and deployment checks.**
   - `python -m talonx_opportunity status`: 11 components RUNNING, plus a supervisor row with a fresh heartbeat.
   - Each lock is held: a second `python -m talonx_opportunity component reporting` must exit with `AlreadyRunning` and spawn nothing.
   - `python -m talonx_opportunity deployments` must show **every** new row as `OPERATIONS_ONLY`:
     - `restart_only=0` for code changes;
     - `decided_by` is `DECLARED` (the 8 shared-runtime components, ingestion, discovery) or `RULE:UNDECLARED_CODE_CHANGE_DEFAULT` (supervisor, sentinel);
     - no `STRATEGY_MATERIAL` or `DATA_FIX` row.
   - The one-restart-authority check: run `python -m talonx_opportunity restart reporting`. It should print "requested" and log `RESTART_REQUESTED` → `SUPERVISOR_PERFORMED_RESTART`, with exactly one new reporting PID.
7. **Cursor and outbox no-replay checks** (post-snapshot, same tool):
   `snap.py > results\p0_runtime_hardening\post_snap.json`, then diff against the pre-snapshot.
   - All 6 consumer cursors unchanged; candidates = distinct; events = distinct; decisions unchanged.
   - Lab outbox SENT unchanged, with no new PENDING from replay.
   - Promotion SENT unchanged, 0 queued.
   - Scans only + CLOSED ticks.
   - `market.db`: the schema has `snapshot_generations`, and the old rows read as generation NULL.
8. **Evidence.** Write `docs/research/evidence/2026-10-04_p0_runtime_hardening_deploy.md` in the 2026-09-26 format: restart set with PIDs old → new, declarations, deployment rows, no-replay table and findings.

## 4. Rollback

The trigger is any of: a deployment row other than OPERATIONS_ONLY; a component failing to start; a no-replay mismatch; any regression in the `restart` check.

1. **Stop all components (NEW code).** `python -m talonx_opportunity down` stops them through stop flags and waits for the OS locks to be released. Then stop the supervisor console.
2. **Restore the code.** Check out `86f7375` in the live worktree.
3. **Schema.** No action is needed.
   - The old code ignores `snapshot_generations` and the added `generation` columns.
   - The old code's positional `INSERT … VALUES (8 values)` into `ingestion_state` and `(4 values)` into `aggregates` **would fail** against the added columns. Before restarting the old code, the dropped columns must therefore be handled. The simplest path is to rebuild those two tables from the new ones (SQLite ≥ 3.35 supports `ALTER TABLE … DROP COLUMN`):
     `python -c "import sqlite3; c=sqlite3.connect(r'results\opportunity\market.db'); c.execute('ALTER TABLE ingestion_state DROP COLUMN generation'); c.execute('ALTER TABLE aggregates DROP COLUMN generation'); c.commit()"`
   - Take a backup of `market.db` (+ `-wal`/`-shm` after `down`) **before** step 3 of §3, so the pre-deploy file can simply be restored instead. This is the preferred rollback.
4. **Old boundaries.** Run `declare-shared-runtime --apply` against `86f7375` (same rule, other direction). Ingestion and discovery need the same version-bound OPERATIONS_ONLY declaration, now bound to the old versions (`f7fecb87c555`, `4b853debaf97`).
5. **Start and verify.** Run `up --deliver --supervise` with the same environment, then repeat checks 6–7.

## 5. Tests (offline, branch)

- **Reproductions** (`tests/test_p0_runtime_ownership_snapshot.py`): 9 tests, **all FAIL on `86f7375`** (commit `7d01219`) and **all PASS after the fix**.
- **Acceptance tests:** 7 more, covering generation monotonicity and consistency, no cross-generation DTU set, failed-commit safety, the pinned Sentinel view snapshot, one supervisor, CLI restart routing, and no force-kill of a reused PID.
- **Engine lane** (the 21 files): baseline on `86f7375` was 425 passed / 1 failed. After the fix, 441 passed / 1 failed, i.e. 425 + the 16 new tests. The single failure is **pre-existing and unchanged**: `test_no_frozen_release_module_imports_the_research_lane`, which flags `talonx_ops/operator_control/universe_view.py` (2026-09-30 Sentinel DTU work); this branch adds no import to that file.

## 6. Strategy fingerprints (base `86f7375` == fix, byte-identical)

V1 PremarketConfig `62ba413daf85e674` · CONTINUOUS_RESEARCH_V1 `2ef115ee19f99574` · LAB_NOTIFY_POLICY_V1 `50dfea564413f30a` · selected REGULAR_EXT policy `dec8d1a865f25424` · PROMOTION_V1 `4926c12e5eace04e` · LAB_DELIVERY_POLICY_V1 `46a2c622a7856f88` · DTU_V1 `da27de22a3bb839a` · V2 release contract `ac5e51aa3599d6c9` · V2 strategy `e2acf6454789217e`.
