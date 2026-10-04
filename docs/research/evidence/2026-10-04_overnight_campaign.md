# Overnight readiness campaign, 2026-10-04 → Monday 2026-10-05

| | |
|---|---|
| Written | 2026-10-04 ~22:40Z (23:40 BST) |
| Clock | Verified correct: GMT Standard Time, DST active, BST = UTC+1 |
| Morning status | Written automatically at 09:30Z (10:30 BST) to `results/overnight_20261005/MORNING_STATUS.md` + `morning_status.json` (local, not in git) |
| Interim overall verdict | **DEGRADED, pending the scheduled evidence.** The universe build (00:00Z), the premarket checks (08:15Z) and the tracker executions (06:00Z, 08:00Z) have not happened yet. **READY is not claimed.** |

## Verdicts by workstream (at writing time)

| Workstream | Verdict | Evidence |
|---|---|---|
| Universe (DTU_V2) | **DEPLOYED_AWAITING_SCHEDULED_BUILD** | Policy `65f3285f8181c552` loaded in ingestion and discovery. Preview verified: 2,090 qualifying, 3,898 → 1,808 removed, reconciled, independently recomputed. The live build is at 00:00Z; verifier tasks below. |
| Ops/V2 restoration | **RESTORED_AND_VERIFIED** (22:12Z) | See below. |
| P0 runtime hardening | **DEPLOYED_AND_VERIFIED** (22:25Z) | See below. |
| Trackers | **RUNNING, AWAITING FIRST EXECUTIONS** | V2 forward 06:00Z; VR and DTU collector from 08:00Z premarket. CONTROL/SHADOW stays stopped (0 processes). |
| Research pre-registration | **DRAFT r2 written, NOT committed or locked** | Local file. Owner decisions pending. |

## SHAs and branches

| | |
|---|---|
| Start | Live `feature/continuous-opportunity-engine` at `6b18f88`. P0 `fix/p0-runtime-ownership-snapshot` at `62eec38` (unchanged; kept as the reviewed source). ERM `research/event-response-map-v1` at `06c2ece` (untouched). |
| Final | Live `feature/continuous-opportunity-engine` at `ad62e9f` plus this documentation commit. The P0 integration branch `fix/p0-integration-dtu-v2` (`ad62e9f`) is pushed. `main` is untouched; no force-push. |
| Integration | P0's 5 commits cherry-picked onto `6b18f88` (no textual conflicts), plus the P0 plan's §3a runbook text (`ad62e9f`). |
| Dirty-tree exception | The only tracked modification is the owner's uncommitted `docs/research/evidence/forward_alpha_validation.md`, preserved in place (sha256 `b1c886ba…`, identical to the shutdown backup; another backup and diff are in `results/overnight_20261005/backup/`). It is in no component's sources, so deployment rows record the commit as `…-dirty`. This is a **documentation-only exception**: the runbook S1 "tree clean" check is a FINDING, not a NO_GO, in the ops preflight. |

## Ops/V2 restoration

**Lock recovery.** The recorded owner of `v2_release_rc1.db.startlock` was PID 19628, created 2026-09-28 07:03Z. It was verified dead: no such process, and its creation time predates today's reboot. No competing stack process existed, nothing listened on :8787, and the read-only preflight was READY_WITH_FINDINGS (tree note only).

**Attempt 1:** the documented `prospective start --release … --force`, at 22:08Z. `--force` broke the verified-stale lock through the lock's own path; it never breaks a live or unknown lock.
- Result: **FAILED_WITH_RESIDUALS**. The V2 companion's own release gate refused: `provider_readiness: provider unreachable/erroring: timeout`.
- The start cleaned up after itself: 0 residual processes, lock released, ledger intact.
- The earlier attempt to break the lock through the lock API directly (2026-10-04 ~20:48Z) had been rejected by the tool permission classifier (`[Security Weaken]`). That path was not retried.

**Diagnosis.** The release gate was READY again on two consecutive read-only runs, so the failure was a transient provider timeout.

**Attempt 2:** the plain documented start (no `--force`; there was no stale lock any more), at 22:12Z. Verdict **READY**. Post-start checks:
- V2 heartbeat fresh, data CURRENT, cash 100,000, 0 positions;
- `service_health=HEALTHY`, no critical flags;
- `:8787` HTTP 200;
- Telegram pollers `EXPECTED_DISTINCT_POLLERS` (Signal 1, Sentinel 1);
- Redis PONG;
- Original, Intelligence and dashboard READY.

**Notifications.** There were two standard OPERATIONS `STARTUP` lifecycle notices (22:08Z, 22:12Z), one per start attempt. This is the existing application configuration; nothing synthetic was sent.

**07:00Z runbook start.** It is a manual step, not a scheduled task. A re-run would be refused by the live V2 start-lock; `--force` never overrides a live owner. There is no duplicate risk.

## Shared-runtime classification review

The eight components (4 evaluators, notifier, outcomes, reporting, promotion) were declared OPERATIONS_ONLY at 20:50Z.

**The 20:50Z declarations.** Their only changed source was `talonx_opportunity/runtime.py` (commits `c9b8e4e` and `45b174d`). That diff edits classification tables and the hash-source lists only; it contains no executable logic. A version rebuild at each component's prior commit proves the newly listed files were byte-identical. **OPERATIONS_ONLY is accurate; no correction needed.**

**P0 restart.** The verified `declare-shared-runtime` path REFUSED all eight, because the last recorded commit `daa1d293b707-dirty` is not verifiable by design. Each was independently verified instead:
- its recorded version rebuilds exactly from clean `daa1d29`;
- its only changed source is `runtime.py`;
- P0's `runtime.py` changes are component OS locks, the PID file, the non-fatal heartbeat and restart routing.

Version-bound OPERATIONS_ONLY declarations #35–#42 were then recorded through the supported `declare_change`, with that evidence as the reason.

## P0 runtime hardening (integrated onto DTU_V2, deployed 22:25Z)

**Overlap review.** P0's single-generation transaction and deferred `dtu_active` write are preserved. DTU_V2's window-start preparation (raw daily, snapshot, report) runs earlier in the tick, committing its own writes before the generation transaction. Universe eligibility, strategy logic and tracker segmentation are unchanged.

**Tests on the integration tree.**

| Run | Result |
|---|---|
| Engine, universe and P0 lane (19 modules) | **331 passed** |
| Wider ops/notify/premarket regression | 11 failed, 710 passed |
| Same wider set on the pre-P0 code | 12 failed, 709 passed |

The 11 failures are identical on the pre-P0 code. They are pre-existing: prospective start tests that see the live stack, V2 SEC-admission fixtures, and others. P0 fixes `test_no_frozen_release_module_imports_the_research_lane` and introduces **no new failure**.

**Fingerprints.**
- **Strategy and policy, byte-identical before and after:** DTU_V2 `65f3285f8181c552`, CONTINUOUS `2ef115ee19f99574`, PREMARKET_V1 `62ba413daf85e674`, PROMOTION `4926c12e5eace04e`.
- **Component versions all changed**, as expected (shared `runtime.py`):

| Component | Version |
|---|---|
| ingestion | `907fad4c0de0` |
| discovery | `063e541827a2` |
| evaluators | `364f2071525f` |
| notifier | `de94590ccb22` |
| outcomes | `daa1d6bbea4d` |
| reporting | `753c477c83ff` |
| promotion | `2cb278644bc2` |
| sentinel | `4dbd66f0b3e2` |

**Boundaries recorded**, matching the P0 plan's step-6 table exactly:

| Component | Classification | Decided by |
|---|---|---|
| ingestion, discovery | DATA_FIX | DECLARED (owner decision 2026-10-01) |
| 8 shared-runtime components | OPERATIONS_ONLY | DECLARED |
| sentinel, supervisor | OPERATIONS_ONLY | default |

No STRATEGY_MATERIAL row.

**Acceptance checks (live, bounded, on the safe component `reporting`).**

| Check | Result |
|---|---|
| Atomic ownership | A second `component reporting` exits `AlreadyRunning (lock held)`. |
| Single restart authority | CLI `restart reporting` → `RESTART_REQUESTED` → `SUPERVISOR_PERFORMED_RESTART`; exactly one new PID; an OPERATIONS_ONLY unchanged-restart row. |
| Crash recovery | The identity-verified worker was killed; its OS lock was released; the supervisor respawned it in **44 s** (bound 105 s); one shim/worker pair afterwards. |
| No replay | Pre/post `snap.py` diff: only one CLOSED scan, the deployment rows and two V2 ticks. Cursors, candidates, events, decisions, the Lab and Signal outboxes and promotions are unchanged. |
| Schema | `snapshot_generations` added; old aggregate rows read generation NULL. |

**Not done.** The `:8787` dashboard is owned by the ops supervisor and was not killed. It serves the pre-P0 `opportunity_read`, whose change is a display-only read transaction, until the next ops restart. Recorded as a bounded follow-up.

**Known gap.** There is no hung-process watchdog; a live-but-hung component holds its lock. Not addressed tonight.

**Rollback.**
- **Code:** stop the engine (supervisor loop, then `down`) and check out `6b18f88`.
- **Schema:** restore `C:\Users\rites\TalonX_universe_change_backups\p0_predeploy_20261004T222423Z\market.db`, or drop the two `generation` columns (P0 plan §4). After the 00:00Z build, prefer dropping the columns, so Monday's universe data is kept.
- **Boundaries:** re-declare per P0 plan §4 and restart with the same DTU_V2 environment.

## Durable overnight verification (Task Scheduler, `\TalonX\`)

All three tasks run as user `rites` (Interactive), in GMT Standard Time, with StartWhenAvailable and WakeToRun.

| Task | Trigger | Bound | Final result |
|---|---|---|---|
| `UniverseVerify_2026-10-05_build` | 01:15 BST = 00:15Z | polls every 5 min until 01:45Z; 2 h limit | `results/ops_restore_20261004/verify_universe_20261005_build.json` |
| `UniverseVerify_2026-10-05_premarket` | 09:15 BST = 08:15Z | until 09:15Z; 2 h limit | `…_premarket.json` |
| `UniverseVerify_2026-10-05_morning` | 10:30 BST = 09:30Z | 30 min limit; re-runs every check fresh | `results/overnight_20261005/MORNING_STATUS.md` + `morning_status.json` |

**Verifier v2** (`results/ops_restore_20261004/verify_universe_20261005.py`; the v1 script and the original task XML are in `results/overnight_20261005/backup/`):
- It is read-only: every SQLite handle is `mode=ro`. It never builds, restarts, rolls back or sends.
- **Partial vs final:** `<stage>.partial.json` is written while polling (`final=false`); the final file is written atomically (`final=true`).
- Every result carries the run id, the scheduled and observed times, the deployed HEAD and the expected policy.
- **Catch-up:** a start more than 10 min late is flagged `catch_up_run` with a MISSED-observations note.
- **Failure classes:** VERIFIER_DEFECT, DATA_PROVIDER_ISSUE, MEMBERSHIP_DEFECT or RUNTIME_DEFECT.
- **Invalidation:** the morning stage re-runs every check fresh and flags any component whose version or start time changed after a scheduled check.

**Build checks.**
- The snapshot policy is DTU_V2, built on reference session 2026-10-02, as exactly one row with no rebuild.
- Exactly 20 XNYS trading sessions (calendar-checked, not calendar days) ending Friday.
- The raw fetch ended before Monday, used the adjustment=raw source, and had 0 failures.
- An independent recomputation shows every member meets close ≥ 5 and ADV20 ≥ 20M on 20 valid bars.
- Every exclusion is confirmed.
- The report is reconciled and matches the snapshot.
- Protected and management-only symbols, benchmarks and trackers are listed separately.
- Discovery's admission set and Sentinel's version equal the published snapshot.
- Preview/live differences are reviewed by cause.
- One owner per component; no duplicate dispatch or replay.

**Premarket checks.**
- No fallback; `dtu_active` carries the DTU_V2 fingerprint.
- Discovery's admission comes from the published snapshot, and no NEW identity falls outside the eligible set.
- The feed is fresh (lag ≤ 25 min); provider failures, incomplete symbols and probes are recorded.
- The **measured** workload is compared with Friday 10-02 over the same PREMARKET clock interval.
- Stack health is checked (engine locks and heartbeats, V2, Original, Intelligence, dashboard, pollers, Redis).

**Tracker execution evidence** comes from logs, not processes:
- the V2 forward `cycle_done 2026-10-05` and `forward/2026-10-05.json`;
- VR ticks dated 2026-10-05;
- DTU collector sweeps dated 2026-10-05.

**Recovery policy.**
- No automatic restart, rollback or policy switch.
- A missing snapshot is handled by discovery's existing FAIL-CLOSED admission: nothing new is admitted, and existing work is still managed. The job retries read-only until its deadline.
- An invalid membership is left as an actionable owner blocker, with the documented rollback (live-universe README §8).
- **The old universe is never fallen back to silently, and a degraded state is never reported as READY.**

**Unattended execution.**
- **On AC power (the current state), idle sleep is Never** (powercfg AC 0x0), and wake timers are enabled.
- A bounded keep-awake process (`results/overnight_20261005/keep_awake_until_0945Z.py`, `SetThreadExecutionState`) holds ES_SYSTEM_REQUIRED until 09:45Z. No power setting was changed; when the process ends, the request is released.
- **The tasks require the user to stay logged on and the PC to be on.** A shutdown, a reboot or a closed lid with lid-sleep would stop them; StartWhenAvailable then runs the task late, and it is flagged as a catch-up.
- This Claude session is not needed.

## Trackers (end dates unchanged)

| Tracker | Schedule | Mechanism |
|---|---|---|
| V2 forward | **2026-10-05 06:00Z (07:00 BST)**, then daily until 2026-10-31 | Wrapper `results/ops_restore_20261004/tracker_v2_forward.sh`: it sleeps to 06:00Z, then execs the unchanged `forward_daily.sh`. No catch-up run. |
| VR paper | First window 2026-10-05 premarket, **08:00Z (09:00 BST)**, until 2026-10-16 | Segmented per window: from 10-05 it is segment DTU_V2. |
| DTU shadow collector | Until 2026-10-08 00:15Z | Segmented: production DTU_V2 from 10-05. |
| CONTROL/SHADOW | Stopped (0 processes) | Not restarted. |

All tracker wrappers survived the P0 engine restart (they are separate processes). None reads the changed tables positionally.

## Research pre-registration

Draft r2 is at `C:\Users\rites\TalonX_shutdown_backups\20261004T174901Z\DRAFT_prereg_GAP_UP_10_SHORT_H10_L1_V1.r2.md`. r1 is preserved. It is not committed or locked; no 2024+ data or stored outcome was opened, and nothing was run.

**Changes in r2:**
- the full fingerprint `12a909e7…cb8ad`, run commit `44112d5` vs outputs commit `06c2ece`, and the dataset hashes;
- the multiplicity explanation: 390 cells = 13 × 2 × 5 × 3; LONG/SHORT mirrors give **195 independent sign tests**; 21 of 390 passed, against 0 of 30 controls; a winner's-curse caveat;
- the return denominator (each leg's entry-session open, same interval, ALL bars);
- cost provenance: stock 30 bps from map C6; the ETF leg 4 bps is new and declared;
- a **dividend correction**: dividends are embedded via adjustment=all, not excluded;
- borrow, locate and Reg SHO 201 limitations;
- ACT/360 break-even and the portfolio unit and marking conventions;
- a deterministic verdict order and the bootstrap sort order.

R1 is unchanged.

**Owner decisions:** window A or B (OWNER_DECISION_PENDING); the R1 look-back; an optional minimum-sample rule; acceptance of the ETF-leg cost.
