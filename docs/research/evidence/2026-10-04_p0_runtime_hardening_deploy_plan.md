# P0 runtime hardening: deploy plan (WRITTEN, NOT RUN)

## Summary

| | |
|---|---|
| **Branch** | `fix/p0-runtime-ownership-snapshot`, from `86f7375` (the live head). The live branch was not touched. |
| **When** | Sunday 2026-10-04, after the Gate D review. The engine is in its **CLOSED** phase: no trading window, and ingestion and discovery idle. |
| **Before the deploy** | **The owner's go after Gate D.** Phase D (`\TalonX\ERM_V1_PhaseD_2026-10-03`) must have **finished**. Check that the task's `LastTaskResult` is set and that `phase_d_runner.log` ends with END or ABORT. |
| **Strategy, scoring, thresholds, notification policy, promotion** | Unchanged. Every strategy fingerprint is byte-identical to `86f7375` (§6). |

**Owner decision (2026-10-01).** Ingestion and discovery are declared **DATA_FIX**, with version-bound declarations. This follows the 2026-09-26 SEC refresh DATA_FIX precedent.

**Expected boundaries:**

| Component(s) | Boundary |
|---|---|
| ingestion | DATA_FIX |
| discovery | DATA_FIX |
| The 8 shared-runtime components (4 evaluators, notifier, outcomes, reporting, promotion) | OPERATIONS_ONLY |
| supervisor, sentinel | Their default class (OPERATIONS_ONLY) |

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

**Boundary fix** (commit `83de736`). `talonx_ops/operator_control/universe_view.py` no longer imports `talonx_premarket`. It reads the V2 scope from the same V2 companion log, read-only, with the identical rule. Sentinel's `/universe` output is byte-identical before and after (tested).

**Lock-file compatibility.** The old code wrote a PID into `<c>.lock`. The new code opens that same file without truncating it and locks byte 0. Old processes take no OS lock, which is why **every** old process must be stopped before any new one starts (§3).

## 2. Boundary classification (expected)

Versions were computed from git (`runtime.version_at_commit` vs the working tree) without opening any live store. The authoritative values are re-computed at deploy time, on the merged commit.

| Component | Changed sources | Expected boundary | How |
|---|---|---|---|
| **ingestion** | `runtime.py`, `ingestion.py`, `universe_tiers.py` (`f7fecb87c555` → `9c66d5708317`) | **DATA_FIX**, `decided_by=DECLARED` | version-bound declaration (§3 step 4) |
| **discovery** | the same (its hash includes `ingestion.py` and `universe_tiers.py`) (`4b853debaf97` → `867eb505f375`) | **DATA_FIX**, `decided_by=DECLARED` | version-bound declaration (§3 step 4) |
| evaluator:INTRADAY / SAME_DAY / SHORT_TERM / LONG_TERM, notifier, outcomes, reporting, promotion | `runtime.py` only | **OPERATIONS_ONLY**, `decided_by=DECLARED` | `declare-shared-runtime --apply` (ELIGIBLE: `runtime.py` is in `SHARED_RUNTIME_OPS_FILES`) |
| **sentinel** | `runtime.py`, `operator_control/universe_view.py` (read transaction + boundary fix) (`29c423cc9f4e` → `4dbd66f0b3e2`) | **OPERATIONS_ONLY** (default class), `decided_by=RULE:UNDECLARED_CODE_CHANGE_DEFAULT` | no declaration; restarted by the coordinated `up` |
| supervisor | `supervise.py`, `__main__.py` (→ `30887e5e3acc`) | **OPERATIONS_ONLY** (default class) | no declaration |

`declare-shared-runtime` (dry run) is expected to report **REFUSED** for ingestion, discovery and sentinel, because their component sources changed. That is correct:
- ingestion and discovery get the DATA_FIX declarations instead;
- sentinel takes its OPERATIONS_ONLY default.

## 3. Procedure (Sunday, CLOSED phase)

Run from `C:\workspace\TalonX`. **Production never runs from the fix branch.** It runs only from `feature/continuous-opportunity-engine` after the fast-forward in step 3.

**Trackers are out of scope. Do NOT restart, stop, reconfigure or modify any of them:**
- the profitability forward tracker (`forward_day.sh`);
- the V2 shadow forward tracker;
- the VR paper live tracker (until 2026-10-16);
- the DTU shadow collector (until 2026-10-08);
- the nightly EOD and holdout jobs.

They keep running against the same stores. The schema change is additive and they read named columns.

0. **Preconditions.**
   - **Branch pre-check (amended 2026-10-01):** run `git fetch origin`, then `git rev-parse origin/feature/continuous-opportunity-engine`. It **must be `86f7375`**.
     If it moved, **STOP** and do not deploy:
     - rebase `fix/p0-runtime-ownership-snapshot` onto the new head;
     - re-run the 450-test engine lane (the 21 files plus `test_p0_runtime_ownership_snapshot.py` and `test_universe_view_boundary.py`) and the strategy-fingerprint comparison;
     - recompute the §2 versions;
     - report to the owner, and wait for a new go.
   - `python -m talonx_opportunity status` shows the phase CLOSED and all components RUNNING.
   - Phase D has finished.
   - No Lab or promotion outbox item is PENDING.
   - Take a backup copy of `results\opportunity\market.db`, `runtime.db` and `opportunity.db`, taken after step 2 (with WAL checkpointed by the clean stop) for the rollback.
1. **Pre-snapshot.** Run the 2026-09-26 tool against the live stores, read-only:
   `python docs\research\evidence\2026-09-26_p0_package1\tools\snap.py > results\p0_runtime_hardening\pre_snap.json`
   It records the 6 consumer cursors, candidates and events (total and distinct), decisions, the Lab outbox by state, promotion SENT/queued, scans, deployments and components.
2. **Stop the engine with the OLD code**, while the old code is still checked out:
   - Stop the supervisor loop (its console, or kill its process; it is not a component).
   - Then run `python -m talonx_opportunity down`, which stops all 11 components, including **sentinel**.
   - Confirm every `results\opportunity\locks\*.lock` owner PID is gone (`Get-Process -Id <pid>` fails for each).
   - **Do not continue while any old component is alive.** Trackers are not touched.
3. **Update the code** (amended 2026-10-01). Production never runs from the fix branch.
   1. **Fast-forward merge `f32f7ac` into the live branch, then push**, without touching any worktree:
      `git push origin f32f7ac6653bed9403f32bf80b7e5a1e29041d97:refs/heads/feature/continuous-opportunity-engine`
      This is fast-forward only: git refuses a non-fast-forward push, and no force is ever used. Then confirm `git ls-remote origin feature/continuous-opportunity-engine` = `f32f7ac`.
   2. **Check out that head in the live worktree:**
      `git -C C:\workspace\TalonX pull --ff-only origin feature/continuous-opportunity-engine`
      Confirm `git rev-parse HEAD` = `f32f7ac` and that the tracked files are clean.
   3. **Deploy commit (doc-only), on the live branch.**
      - Apply the runbook update in §3a to `docs/runbooks/CONTINUOUS_ENGINE.md`.
      - Bring over this amended plan with `git checkout origin/fix/p0-runtime-ownership-snapshot -- docs/research/evidence/2026-10-04_p0_runtime_hardening_deploy_plan.md`.
      - Commit with the message `docs(runbook): P0 restart semantics + retire interim "stop supervise before restart" directive`, then push (fast-forward).
      - Before committing, confirm that no component version changed: `python -c "from talonx_opportunity import runtime as R, supervise as SV; print({c: R.component_version(c) for c in SV.COMPONENTS})"` is identical before and after. Neither doc is in any `COMPONENT_SOURCES` entry.
      - The live worktree is now at the deploy commit.
4. **Declare boundaries.**
   - `python -m talonx_opportunity declare-shared-runtime` (dry run). Expect ELIGIBLE for the 8 components and REFUSED for ingestion, discovery and sentinel.
   - `python -m talonx_opportunity declare-shared-runtime --apply`
   - Ingestion and discovery, **DATA_FIX**, version-bound so that any further code change is classified normally:

```
python -c "from talonx_opportunity.runtime import RuntimeStore, component_version as v; r=RuntimeStore(); [print(c, r.declare_change(c, 'DATA_FIX', 'P0 snapshot atomicity: single-generation write/read; strategy fingerprints unchanged; outputs identical except in race windows', expected_version=v(c))) for c in ('ingestion','discovery')]"
```

   - No declaration for sentinel or the supervisor: their default class is OPERATIONS_ONLY.
5. **Single coordinated start**, with the same environment as the 2026-09-30 activation:
   `python -m talonx_opportunity up --deliver --supervise` with `TALONX_DTU_MODE=ACTIVE`, `TALONX_SEC_BACKGROUND_REFRESH_ENABLED=1`, `TALONX_SEC_REFRESH_CAPACITY=OBSERVABILITY_ONLY`, `TALONX_NOTIFY_RESEARCH_ENABLED=1`, `TALONX_OPP_NOTIFY_POLICY=LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925`, `TALONX_OPPORTUNITY_PROMOTION_MODE=PAPER_SIGNAL`, `TALONX_SENTINEL_COMMANDS_ENABLED=1` and `OPERATOR_UNIVERSE_MUTATION_MODE=DRY_RUN`.
   - This starts all 11 components, **including the sentinel restart**, and the new supervisor loop.
   - Then restart the `:8787` cockpit (`dashboard_web.py`), which serves `opportunity_read`.
6. **Status and deployment checks.**
   - `python -m talonx_opportunity status`: 11 components RUNNING, plus a supervisor row with a fresh heartbeat.
   - Each lock is held: a second `python -m talonx_opportunity component reporting` must exit with `AlreadyRunning` and spawn nothing.
   - `python -m talonx_opportunity deployments` must show exactly these new rows:

| Component | classification | decided_by | restart_only |
|---|---|---|---|
| ingestion | DATA_FIX | DECLARED | 0 |
| discovery | DATA_FIX | DECLARED | 0 |
| 4 evaluators, notifier, outcomes, reporting, promotion | OPERATIONS_ONLY | DECLARED | 0 |
| **sentinel** | OPERATIONS_ONLY | RULE:UNDECLARED_CODE_CHANGE_DEFAULT | 0 |
| supervisor | OPERATIONS_ONLY | RULE:UNDECLARED_CODE_CHANGE_DEFAULT | 0 |

   - **No STRATEGY_MATERIAL row.** Any deviation is a rollback trigger.
   - Sentinel answers `/universe` (DRY_RUN), and the output format is unchanged.
   - The one-restart-authority check: run `python -m talonx_opportunity restart reporting`. It should print "requested" and log `RESTART_REQUESTED` → `SUPERVISOR_PERFORMED_RESTART`, with exactly one new reporting PID. It records an OPERATIONS_ONLY / `RULE:UNCHANGED_RESTART` row.
7. **Cursor and outbox no-replay checks** (post-snapshot, same tool):
   `snap.py > results\p0_runtime_hardening\post_snap.json`, then diff against the pre-snapshot.
   - All 6 consumer cursors unchanged; candidates = distinct; events = distinct; decisions unchanged.
   - Lab outbox SENT unchanged, with no new PENDING from replay.
   - Promotion SENT unchanged, 0 queued.
   - Scans only + CLOSED ticks.
   - `market.db`: the schema has `snapshot_generations`, and the old rows read as generation NULL.

   **Supervisor respawn and single-instance checks (amended 2026-10-01):**
   - **Kill reporting.** Take the PID from `results\opportunity\locks\reporting.pid`; this is the real worker that holds the lock, not the venv shim. Run `Stop-Process -Id <pid> -Force`, then confirm the lock is released (`python -c "from talonx_opportunity.runtime import lock_held; print(lock_held(None,'reporting'))"` → False).
   - **Respawn.** The supervisor respawns reporting within **poll (15 s) + startup grace (90 s) = 105 s** at most:
     - a `SUPERVISOR_RESTART` event appears for reporting;
     - `lock_held(None,'reporting')` is True again with a new PID;
     - the new deployment row is **OPERATIONS_ONLY, `restart_only=1`, `decided_by=RULE:UNCHANGED_RESTART`**.
   - **No duplicate instance.** `Get-CimInstance Win32_Process | ? { $_.CommandLine -like '*talonx_opportunity component reporting*' }` shows exactly one worker (plus its venv shim, if any). The component events show no second START for reporting.
   - **A second `up` is refused** for every component: `python -m talonx_opportunity up --only <c>` returns `ALREADY_RUNNING` for each of the 11 components and spawns nothing, so no new START event appears. `python -m talonx_opportunity component reporting` exits with `AlreadyRunning`.
   - Rollback trigger: a missed respawn after 105 s, two reporting workers, any new deployment row other than OPERATIONS_ONLY/restart_only, or a second instance that starts.
8. **Evidence.** Write `docs/research/evidence/2026-10-04_p0_runtime_hardening_deploy.md` in the 2026-09-26 format:
   - the restart set with PIDs old → new (11 components, including sentinel, plus the supervisor and the `:8787` cockpit; trackers listed as **not restarted**);
   - the declarations, with IDs and bound versions;
   - the deployment rows;
   - the no-replay table and findings.

   **It must state this segmentation:**
   - **Discovery and candidate statistics, and every forward-tracker statistic, SEGMENT at this boundary** (ingestion and discovery are DATA_FIX).
   - Funnel counts, candidate creation/updates, alert counts, MFE/MAE, missed-opportunity and the forward trackers' CONTROL/SHADOW and VR/V2 forward statistics are reported **separately before and after** the boundary's `at_utc`, and are never pooled across it.
   - The trackers themselves are not restarted or modified. Only the analysis segments at the boundary timestamp.

## 3a. Runbook update (part of the deploy commit, step 3.3)

In `docs/runbooks/CONTINUOUS_ENGINE.md`, add the following section after the restart example (the `restart notifier` line):

```markdown
### Restart semantics (since the 2026-10-04 P0 runtime hardening)

- **Ownership and liveness = the OS lock.** Each component holds an exclusive OS lock on
  `results/opportunity/locks/<component>.lock` (msvcrt byte-range lock on Windows) for its whole lifetime. A component
  is running if and only if that lock is held. The OS releases it when the process exits for any reason.
- **The PID file is display only.** `locks/<component>.pid` shows the current owner's PID. It is never used to decide
  liveness, so a reused PID after a reboot can neither block a start nor be force-killed (force-kill also requires the
  process command line to be that component).
- **`restart <component>` routes via the supervisor.** While a supervisor (`up --supervise`) has a fresh heartbeat
  (< 60 s), the CLI only writes `control/<component>.restart`, and the supervisor performs the restart with its own
  environment (`RESTART_REQUESTED` -> `SUPERVISOR_PERFORMED_RESTART`). The CLI spawns directly only when no supervisor is
  alive.
- **A failed stop never spawns.** A restart spawns only after the old owner's lock is confirmed released; otherwise it is
  recorded as `RESTART_ABORTED_STOP_FAILED` and the CLI exits non-zero.
- **One supervisor.** The supervisor holds its own lock (`locks/supervisor.lock`); a second `up --supervise` is refused.
- **A second instance is refused.** `up` reports `ALREADY_RUNNING` for a running component, and `component <c>` exits with
  `AlreadyRunning`.

**Retired:** the interim directive "stop `up --supervise` before running `restart`" is **retired** as of this deploy.
It existed only because a CLI restart and the supervisor could both spawn the same component. Run `restart` with the
supervisor running; that is now the intended path.
```

## 4. Rollback

The trigger is any of: a deployment row other than those in step 6; a component failing to start; a no-replay mismatch; any regression in the `restart` or `/universe` checks.

1. **Stop all components (NEW code).** `python -m talonx_opportunity down` stops them through stop flags and waits for the OS locks to be released. Then stop the supervisor console. Trackers are not touched.
2. **Restore the code.** Check out `86f7375` in the live worktree.
3. **Schema.**
   - **Preferred:** restore the pre-deploy backup of `market.db` (§3 step 0).
   - **Alternative:** drop the added columns, because the old code's positional `INSERT … VALUES` (8 values into `ingestion_state`, 4 into `aggregates`) fails against them. This was verified offline on SQLite 3.49.1:
     `python -c "import sqlite3; c=sqlite3.connect(r'results\opportunity\market.db'); c.execute('ALTER TABLE ingestion_state DROP COLUMN generation'); c.execute('ALTER TABLE aggregates DROP COLUMN generation'); c.commit()"`
     `snapshot_generations` can stay; the old code ignores it.
4. **Old boundaries.** Run `declare-shared-runtime --apply` (the 8 components back to the `86f7375` versions). Ingestion and discovery get **DATA_FIX** declarations bound to `f7fecb87c555` / `4b853debaf97`, reason "rollback of P0 snapshot atomicity". Sentinel and the supervisor take their OPERATIONS_ONLY defaults.
5. **Start and verify.** Run `up --deliver --supervise` with the same environment, then repeat checks 6–7 with the mirrored expected rows. The rollback is also a segmentation boundary for discovery, candidate and tracker statistics.

## 5. Tests (offline, branch)

- **Reproductions** (`tests/test_p0_runtime_ownership_snapshot.py`): 9 tests, **all FAIL on `86f7375`** (commit `7d01219`) and **all PASS after the fix** (`1e43dcf`).
- **Acceptance tests:** 7 more, covering generation monotonicity and consistency, no cross-generation DTU set, failed-commit safety, the pinned Sentinel view snapshot, one supervisor, CLI restart routing, and no force-kill of a reused PID.
- **Boundary fix** (`tests/test_universe_view_boundary.py`, commit `83de736`):
  - V2-scope parity with the research-lane rule (4 log layouts);
  - Sentinel `/universe` output byte-identical between the `86f7375` module and the fix on a fixture store (3 log layouts);
  - an AST import check.
  - The pre-existing guard `test_no_frozen_release_module_imports_the_research_lane` now **passes**.
- **Engine lane** (the 21 files plus the 2 new files): **450 passed, 0 failed**. That is the 426 baseline tests (including the previously failing guard), 16 P0 tests and 8 boundary tests. The baseline on `86f7375` was 425 passed, 1 failed.

## 6. Strategy fingerprints (base `86f7375` == fix, byte-identical)

V1 PremarketConfig `62ba413daf85e674` · CONTINUOUS_RESEARCH_V1 `2ef115ee19f99574` · LAB_NOTIFY_POLICY_V1 `50dfea564413f30a` · selected REGULAR_EXT policy `dec8d1a865f25424` · PROMOTION_V1 `4926c12e5eace04e` · LAB_DELIVERY_POLICY_V1 `46a2c622a7856f88` · DTU_V1 `da27de22a3bb839a` · V2 release contract `ac5e51aa3599d6c9` · V2 strategy `e2acf6454789217e`.
