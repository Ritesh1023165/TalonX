# Reboot recovery report: 2026-10-15/16

**Verdict: `RESTORED_WITH_GAP`.** Every authorised component is running again with one logical owner. The approved
controls are unchanged. The outage left real gaps, and one restoration step briefly ran with the wrong universe mode
(§4). Both are recorded below, not smoothed over.

## 1. What happened

| Time (UTC) | London (BST) | Event (source) |
|---|---|---|
| 2026-10-15 00:27:26Z | 01:27 | Last Opportunity ingestion cycle (OVERNIGHT, 0 fetch as designed). `market.db cycles` id 12436 |
| 00:28:29–00:28:46Z | 01:28 | Last Intelligence poll cycle 3361, complete. Last V2 heartbeat 00:28:34Z |
| 00:29:09Z | 01:29 | `MoUsoCoreWorker.exe` (SYSTEM) initiates a restart: "Operating System: Service pack (Planned)". System log 1074 |
| 00:30:45Z | 01:30 | Boot |
| 00:31:45Z | 01:31 | `TrustedInstaller.exe` (SYSTEM) initiates a second restart: "Operating System: Upgrade (Planned)" |
| **00:32:07Z** | **01:32** | **Final boot** (Kernel-General 12) |
| 00:32Z → 19:26:22Z | | Sign-in screen; nothing ran. Docker Desktop and Redis auto-start only after sign-in |
| 19:26:22Z | 20:26 | Interactive sign-in. Docker/`talonx-redis` up about 19:27Z |
| 19:30:53Z | 20:30 | This recovery began |

**Cause.** Windows Update restarted outside its active hours. Active hours are 07:00–01:00 local, and the restart came
at 01:29 BST. After the restart nothing auto-starts before sign-in, by design. No restart was pending at handoff (WU
`RebootRequired`=false, CBS `RebootPending`=false).

**Recurrence risk.** The 01:00–07:00 BST window overlaps the PDM 06:30 London trigger and sits just before the 07:00
BST forward slot. Another update restart in that window would also leave the PDM task (Interactive principal) unable
to run until sign-in. No setting was changed in this task. Owner decision.

## 2. Baseline before any action (2026-10-15 19:30–19:37Z, read-only)

| Item | Finding |
|---|---|
| Git | Branch `feature/continuous-opportunity-engine`; HEAD = origin = `3117d08`. Only tracked change: owner's `forward_alpha_validation.md`, sha256 `B1C886BA…7936`, unchanged throughout |
| Processes | **No TalonX process.** Redis container up (healthy, PONG) since about 19:27Z |
| Locks | Opportunity liveness = OS byte-range lock, never the PID file. All recorded owners dead. The SAME_DAY `.pid` (16672) had been **reused by an unrelated process**; that was harmless because PID files are display-only. No stop flags. V2 `.startlock` owner 10872 dead. Intelligence `service.lock` owner 14388 dead |
| Scheduled tasks | Only `\TalonX\PDM_V1_Collector` has a next run. ERM/UniverseVerify one-shots have none |
| DB integrity | `PRAGMA quick_check` = ok on all 29 operational DBs: Opportunity, VR, V2, ops outboxes, `~/.talonx` incl. the 0.9 GB `ingestion_ledger.db` and 0.7 GB `market.db`. WAL/SHM preserved; recovered by the normal writers |
| Positions | V2 release ledger: 0 positions, 0 pending intents. VR: 0 OPEN. Row counts unchanged from the 10-14 snapshot (EXITED 300, SKIPPED 1425, PAPER_ENTRY_PENDING 1) |
| Outboxes | Signal review 1544 SENT. Lab 3146 SENT. VR 334 SENT. Release/ops 61 SENT / 2 EXPIRED / 1 FAILED. Intelligence 392 SENT / 3 AMBIGUOUS / 4 PENDING (DIGEST route, enqueued 10-14 10:44–10:47Z) |
| Controls | `promotion_signal_delivery.json` paused=false, RESEARCH_REVIEW, boundary 2026-10-07 22:42:55Z. `dtu_policy_schedule.json` DTU_V3_TOP600 from 10-09. VR `entry_control.json` entries_blocked=true, boundary 2026-10-07 11:25:41Z |

**Backup.** Before any writer started (19:36Z), a consistent SQLite-API backup was taken of the 22 state/outbox DBs
plus 5 control files. Location `results/recovery_20261015/backup_pre_restore/` (local, gitignored, 148 MB;
`MANIFEST.json` lists every sha256). Not used; nothing was restored from it.

## 3. Restoration (dependency order)

| Component | Before | Action | After |
|---|---|---|---|
| Redis | Up (auto after sign-in) | none | PONG |
| Opportunity: evaluator ×4, promotion | Dead, lock free, version unchanged | `up --deliver --supervise` (corrected env, §4) | UP, OPERATIONS_ONLY (`RULE:UNCHANGED_RESTART`) |
| Opportunity: notifier, outcomes, reporting, sentinel | Dead; version moved only via shared `runtime.py` (507f8c0) | Version-bound OPERATIONS_ONLY declarations #58–#61, then same `up` | UP, OPERATIONS_ONLY (declared) |
| Opportunity: ingestion, discovery | Dead; same as above (declarations #56/#57) | Same `up`. Ingestion started first, alone, after §4 | UP, DTU ACTIVE; classified DATA_FIX / STRATEGY_MATERIAL by `RULE:CONFIG_FINGERPRINT_CHANGED` (OFF→ACTIVE, §4) |
| VR tracker | Absent; within lifetime (`--until 2026-10-16`) | `tracker_vr.sh` once, 2026-10-15 19:45:31Z | One chain; first tick 19:45:32Z, `entry_control BLOCKED` |
| V2 forward tracker | Absent | `tracker_v2_forward_v2.sh` once, 19:46:07Z (sleep-first; `next-slot` verified = 2026-10-16 06:00Z beforehand) | One chain (wrapper → loop → sleeper) |
| Ops/V2: ops supervisor, Original, Intelligence, :8787, V2 companion, checkpoint daemon | Absent | 10-15 19:37Z: `prospective start` **refused** (release gate READY, but preflight NO_GO `repo_head_matches_release`: `.gitattributes` changed in f78fb34, an evidence-only `-text` rule for 3 archived EDGAR HTML files). **Blocked pending owner.** 2026-10-16 07:50:42Z: owner authorised one `--force` start with the documented args/env (cash 100000, V2-PAPER-RC1, deliver telegram) | READY 07:51:14Z. Stale start lock rebound by the supported verified-stale path (owner token rotated). V2 tick 1, `data_state=CURRENT`, `V2_RELEASE_PRICE_CONTRACT@1` fallback NONE. :8787 HTTP 200 |

**Version verification.** `declare-shared-runtime` refused, because the recorded commits are `-dirty`. By hand:
- `version_at_commit` reproduces every recorded loaded version from its clean commit.
- `changed_sources_since` = only `talonx_opportunity/runtime.py`.

So the dirty content never touched hashed sources, and only shared runtime changed. This is the same basis as 10-12.

**Not started (by design):** DTU collector and control-shadow (stopped), ERM (parked), PDM (scheduled only), old
checkpoint daemon PIDs from earlier sessions.

## 4. Finding: 2.5 minutes with the DTU universe OFF (corrected)

The runbook's documented Opportunity environment (`2026-10-12_MONDAY_RESTART.md`, "Unexpected full outage") omits
`TALONX_DTU_MODE=ACTIVE`. Its default is **OFF**, which means an uncapped universe. The last full start (10-04 P0
deploy plan) had it.

- **19:38:50Z.** The first launch ran with OFF. It was detected from the deployment record: the `DTU` and
  `DTU_SCHEDULE` config fingerprints were absent. Stopped with the documented `down` (19:40:34–19:41:16Z) plus the
  supervisor process.
- **During OFF:** one ingestion cycle (19:41:16Z, REGULAR) fetched **5,643 symbols / 936,066 bars** instead of the
  capped set. It published one `market.db` generation for window 10-15. The next generation (19:42:43Z) superseded
  it.
- **Discovery** only recorded `PROVIDER_STALE` scans (19:38:51Z, 19:39:53Z: ingestion had no data yet). **No
  candidate, admission, promotion or alert was produced from the uncapped universe.** The one Lab message sent at
  19:38:51Z was the notifier's start-up `OPPORTUNITY_RESEARCH_DIGEST`.
- **Cost:** extra Alpaca quota use (ops/V2 was down; no other consumer was affected) and one superseded generation.
- **Correction:** relaunched with `TALONX_DTU_MODE=ACTIVE`, `TALONX_DTU_POLICY=DTU_V2` and
  `TALONX_SEC_REFRESH_CAPACITY=OBSERVABILITY_ONLY`.
  - Ingestion was started alone first (19:42:24Z). Its first cycle, 19:42:43Z, fetched 604 symbols with policy
    DTU_V3_TOP600 (`2849da5594f272db`).
  - Then the full supervised stack (19:43:09Z).
  - The first real discovery scan (19:43:12Z) applied DTU: active 604, admissible **600**.
- **Runbook corrected** (handoff block and env list). The deployment log records the OFF→ACTIVE config changes
  truthfully.

## 5. Forward tracker

| Day | State | Detail (structured status only; no outcome read) |
|---|---|---|
| 2026-10-15 | **MISSED** | Machine at sign-in screen at 06:00Z. No record, no attempt. **Not rerun, not backfilled.** |
| 2026-10-16 | **SUCCESS** | `forward_runner v1.2`. Scheduled 06:00:00Z, started 06:00:00.35Z, ended 06:04:57.43Z (deadline 07:30Z). Cutoffs: as_of 10-16, filings ≤ 10-15, prices ≤ 10-15. Stages edgar_crawl / episodes / prices / evaluate / forward all SUCCESS, exit 0, retries 0, stderr empty. Acquisition COMPLETE_WITH_EVENTS, `days_sec_closed` [10-12], calendar `EDGAR_CLOSURES_V1` sha256 `a03cdf54…49e3`. Artifact validated, problems []. |

- **Next slot:** 2026-10-17 06:00Z (07:00 BST). The loop runs through 2026-10-31 inclusive.
- **One logical loop:** `tracker_v2_forward_v2.sh` → `forward_daily_v2.sh` → `forward_runner sleep-to-next-slot`.
- The `os.replace` traceback in `forward.log` belongs to the already-recorded 2026-10-11 failure.

## 6. VR_PAPER_V1

- **Entries blocked.** Both arms remain blocked: `entry_control.json` is unchanged and enforced at ingest.
  - 2026-10-15: 3 post-boundary signals were seen and blocked by 19:45:32Z; the cursor advanced; no trade rows.
  - 0 OPEN. Row counts are unchanged.
- **Restart semantics** (verified in code before launch):
  - The loop ticks only the current UTC-date window.
  - `skip_backlog=True`.
  - Blocked signals advance the cursor, so no historical window is replayed and no restored delivery is admitted.
- **No ticks 10-15 08:00–19:45Z.** That window is INPUT_INTERRUPTED regardless (arms closed since 10-07), and there
  were no positions to manage.
- **Endpoint preserved:** `--until 2026-10-16`, child exit at the first check ≥ **2026-10-17 00:00Z (01:00 BST)**.
  No EOD evaluation was run. Closeout follows `docs/runbooks/2026-10-16_VR_PAPER_V1_ENDPOINT.md` (owner
  authorisation).
- **NVCT wording resolved** (docs only; row untouched):
  - The Telegram review alert **was delivered** (Signal outbox SENT 2026-09-30 20:03:43Z, 1 attempt, transport ref
    present).
  - What never happened is the **paper entry**. The promotion was decided at 20:03:41Z, after that window's 19:50Z
    flatten, and `signal_wall_time` was never recorded.
  - Corrected in the endpoint runbook and `2026-10-14_vr_endpoint_prep/STATE.md`.
- **Log side effect:** the restart redirect truncated the wrapper's own `tracker_vr.out/.err` (gitignored console
  files). The tracker's real log `results/vr_paper/live.log` (append) is intact.

## 7. PDM_V1

- **Integrity:** `verify_integrity` on the locked config returns [] (no findings). All 6 implementation sha256 match.
  `calendar_fingerprint(2026-10-19)` = locked `65d1d40d…6c96`. Locked config and bound files are clean in git.
- **Schedule:**
  - Exactly one task, `\TalonX\PDM_V1_Collector`, Ready.
  - Triggers 2026-10-20 00:15 local (end 11-18) and 06:30 local (end 11-17), daily.
  - Next run **2026-10-19 23:15Z**. Last result 267011 (never run). Missed runs 0.
- **No early collection:** no `results/post_delivery_markout` store exists, and the task was not started.
  `--enable` and the collector were not run.
- **Prerequisites now:** user `rites` signed in (Interactive principal), on AC (battery status 2), internet
  available. The task disallows battery start, requires network and does not wake to run. See the §1 recurrence
  risk.

## 8. Notifications: pending and ambiguous

| Store | Disposition |
|---|---|
| Intelligence | The 4 DIGEST PENDING rows from 10-14 were **EXPIRED by the existing sweep** at 2026-10-16 07:51:28Z ("stale_card: 45h old > 24h DIGEST cutoff"); not sent. The 3 AMBIGUOUS rows (2026-09-14 ×2, 2026-10-05) are **preserved**, not retried. The first post-restore cycle (07:50:58Z) found 5 new Form 4 events from the outage: 2 IMMEDIATE cards SENT under existing freshness rules (late by the outage), 2 new DIGEST rows PENDING normally. |
| Signal review alerts | 15 SENT 2026-10-15 19:44:45–20:05:47Z, all with `API_ACCEPTED` traces and message ids (15/15). 126 queued promotions were `REJECTED_WHILE_QUEUED` by existing rules. No duplicate event ids. No old row resent. |
| Lab (research) | 124 SENT 2026-10-15 19:38:51–22:30:14Z (62 NEW, 46 INVALIDATED, 10 UPGRADE, 3 MATERIAL_UPDATE, 3 DIGEST), under the existing Lab budget policy |
| Ops/release | 1 STARTUP lifecycle notice (product of the documented start). FAILED 1 / EXPIRED 2 unchanged, not replayed |
| VR | No new sends (entries blocked) |

**Catch-up burst.** The first post-outage discovery scan saw a full trading day at once: 665 events, 146 candidates.
The review and Lab alerts that followed are new detections on current data (data as of 19:27Z), not replays. But they
were **late relative to when the moves happened**, and they arrived in a burst. No delivery setting was changed. The
existing queue expiry and budgets bounded it.

## 9. Gaps: confirmed versus unknown

**Confirmed gaps:**

| Component | Down (UTC) | Duration | Effect |
|---|---|---|---|
| Opportunity (all) | 10-15 00:29Z → 19:38/19:43Z | ~19h10m | No overnight, premarket or regular processing of window 10-15 until 19:43Z. The 10-15 universe had been published before the reboot. Detection, promotion and Lab alerts for 10-15 were late (catch-up burst) or absent |
| Review-alert delivery | → 19:44:45Z | ~19h15m | None sent during the session. 15 late |
| VR | 10-15 08:00 → 19:45Z | ~11h45m in-window | No ticks. No position impact (0 OPEN, entries blocked) |
| Forward | 10-15 06:00Z slot | 1 observation | MISSED; preserved |
| Original, Intelligence, V2 companion, :8787 | 10-15 00:29Z → 10-16 07:50Z | ~31h20m | No Original alerts, no timely Intelligence cards (2 sent late), no V2 ticks (0 positions; resumed with 45-day live lookback), no dashboard |

**Unknown:**
- Which setups or alerts would have fired intraday on 10-15, and when. Absence of records during downtime is not
  evidence that nothing was missed.
- Whether any V2 insider cluster had a time-sensitive entry during 10-15/16 (resumed: 0 open, 0 closed, 5 records
  seen).
- Whether Intelligence's bounded re-acquisition recovered every filing in the 31h window. Durable checkpoints support
  resumption; it is not a guarantee.

## 10. Post-restore observation

**2026-10-15, 19:43–22:30Z** (REGULAR → AFTER_HOURS):
- Opportunity HEALTHY. No component errors and no supervisor relaunches.
- 15 review alerts traced. 124 Lab messages sent.

**Overnight into 2026-10-16:**
- The supervisors kept the same owners all night.
- The 10-16 universe published naturally: DTU_V3_TOP600, Core 600, event-eligible 0, reconciled, no schedule error.
- The forward slot ran SUCCESS.

**2026-10-16 08:02–08:06Z** (PREMARKET, after the ops/V2 start):
- Ingestion cycles every ~60 s (data as_of 07:50Z, SIP delay).
- Discovery SCANNED at 08:02:37Z with DTU applied (admissible 600).
- V2 tick 7, CURRENT. Intelligence cycle 5, FRESH. VR heartbeat 08:05:34Z, BLOCKED. :8787 HTTP 200.
- Every component has exactly one logical owner. 0 stop flags. 0 duplicate dedup keys in any outbox.

**Awaiting the regular session (13:30Z):** a natural review alert with a trace, and paper management under live data.
These are not failures before then. The checkpoint is in `CHECKPOINT_2026-10-16.md`.

## 11. Evidence

- **Local, gitignored:**
  - `results/recovery_20261015/backup_pre_restore/MANIFEST.json`
  - `start_opportunity_supervisor.ps1` (corrected env)
  - `opportunity_supervisor.console.log`
  - `results/prospective_2026-10-15/` (refused start)
  - `results/prospective_2026-10-16/` (release gate, preflight, start_verify READY)
- **Runtime records:** `runtime.db` declarations #56–#61 and deployment events 2026-10-15 19:38–19:43Z.
- **Nothing committed** contains DB content, credentials or Telegram identifiers.
