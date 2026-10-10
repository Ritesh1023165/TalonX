# TalonX Monday restoration, 12 October 2026

**KEEP THE MACHINE ON.** This is a partial shutdown. The V2 forward study requires Sunday 11 October **06:00 UTC / 07:00 BST**, then Monday 12 October at the same time. Saturday's run was SUCCESS, ending 06:03:48 UTC. Windows must remain running, on AC, connected to the internet and logged in to the existing account/session. Do not sleep, log off, reboot or power off. No power settings were changed and no boot/restart task was registered.

Restore the four paused evaluators by **Sunday 11 October 23:30 UTC / Monday 12 October 00:30 BST**. This allows 30 minutes before Monday's **00:00 UTC / 01:00 BST** overnight window and normal universe preparation. Check again by **05:30 UTC / 06:30 BST**, ahead of the forward run. Premarket is 08:00 UTC / 09:00 BST; regular open is 13:30 UTC / 14:30 BST. Those are later obligations, not the restart deadline.

## Integrity and retained owners

Use PowerShell in `C:\workspace\TalonX`, interpreter `C:\workspace\TalonX\.venv\Scripts\python.exe` (its Windows launcher uses `C:\Users\rites\AppData\Local\Python\pythoncore-3.12-64\python.exe`).

```powershell
Set-Location -LiteralPath C:\workspace\TalonX
git branch --show-current
git log -1 --format='%H %s'
git status --short
Get-FileHash -LiteralPath docs\research\evidence\forward_alpha_validation.md -Algorithm SHA256
```

Branch must be `feature/continuous-opportunity-engine`. Assessed application HEAD and actual remote were `41375bb3477c926be53f3a571408fe5069dec9a3`; subsequent shutdown documentation commits are expected. Review any other code/configuration change before startup. Do not reset, checkout, stash, restore or pull over the owner's dirty document. Its SHA256 must remain `B1C886BAF34D00FDE4EECE73E927C500432581BC6040F38C0549DF3CDCFD7936`.

Check process identity and ancestry; the venv launcher and its interpreter child are one logical owner, not two workers:

```powershell
Get-CimInstance Win32_Process | Where-Object {
  $_.ExecutablePath -notmatch 'pwsh' -and
  $_.CommandLine -match 'talonx|run_talonx|dashboard_web|tracker_|forward_daily'
} | Select-Object ProcessId,ParentProcessId,CreationDate,ExecutablePath,CommandLine
docker ps --format '{{.Names}} {{.Status}}'
docker exec talonx-redis redis-cli PING
Test-NetConnection localhost -Port 8787 -InformationLevel Quiet
```

Keep the ops supervisor, Original (Signal poller), Intelligence, dashboard, V2 companion, Opportunity supervisor, ingestion, discovery, notifier, outcomes, reporting, promotion, Sentinel, VR wrapper and V2 forward wrapper/loop running. Do not launch another supervisor, companion or Signal/Sentinel poller. A fresh supervisor/OS lock, process ancestry and advancing heartbeat must all agree. DTU collector/control-shadow and ERM remain stopped/parked. The missing old checkpoint daemon PID in the local session file is a finding, not permission to create another full stack.

## Restore only what this assessment stopped

These components have no authorised BUY/SELL strategies and create no paper orders. Their durable event cursors and transactions persist. Startup resumes the normal existing event-consumption path; it does not initiate a study backfill or reset a cursor.

```powershell
.venv\Scripts\python.exe -m talonx_opportunity up --only evaluator:INTRADAY,evaluator:SAME_DAY,evaluator:SHORT_TERM,evaluator:LONG_TERM
```

The existing `up` checks each exclusive OS lock, leaves existing owners alone and removes only the requested component stop flags before spawning missing workers. Do not add `--supervise`: the existing Opportunity supervisor already owns relaunch policy. Do not delete locks or PID files. Do not use `down`, `restart promotion`, or a full `up` for this partial restoration.

Check within five minutes:

```powershell
.venv\Scripts\python.exe -m talonx_opportunity status --json
```

Operational status only: do not read forward outcome artifacts, run study evaluators manually, or inspect protected ERM inputs. Confirm one OS-lock owner per evaluator and advancing heartbeat timestamps. LONG_TERM remains `IDLE_NOT_IMPLEMENTED`, as designed. Verify the other component owners did not change. Dashboard: `http://localhost:8787` must return HTTP 200, show fresh operational timestamps, and identify the restored evaluators correctly. A process present with an old heartbeat is not working.

## Tracker and universe checks

The retained forward chain at assessment was wrapper 3344 → 7184 → loop 24096 → shell 21732 → sleeper launcher 23280 → interpreter 17276. Verify current identities, not these PIDs alone. It runs every calendar day through 31 October. Operational record `results\v2_validation\forward_runs\2026-10-11.json` must become SUCCESS after Sunday's natural slot; Monday uses `2026-10-12.json`. Inspect only state, scheduled/start/end/heartbeat timestamps, failed stage and exit status. Never open `results\v2_validation\forward\*.json` for this task.

If the retained tracker unexpectedly died, first verify no wrapper/loop/stage owner remains and no run is RUNNING with a live PID. The supported wrapper command is:

```powershell
& 'C:\Program Files\Git\bin\bash.exe' results/ops_restore_20261004/tracker_v2_forward_v2.sh
```

Run it only for actual recovery, once, in a persistent session; it waits until the next strictly future 06:00 UTC slot. **Do not directly start `forward_daily_v2.sh`: it executes immediately.** A restart after 06:00 UTC skips that day's scheduled observation; there is no automatic catch-up. Report the missed observation. Do not manually run, rerun or backfill the study.

The normal Monday universe window starts 00:00 UTC, verified using `talonx_opportunity.phases.trading_window(2026-10-12)`. Retained ingestion builds through `_ensure_daily` and `_prepare_live_dtu`; expected publication is shortly after window start, not a guaranteed fixed completion time. Check the fresh Monday report in `results\opportunity\universe_reports\2026-10-12\`, its inputs ending Friday 9 October, `DTU_V3_TOP600`, Core ≤600, Event-eligible 0, reconciled=true and no schedule error/fallback. Do not force a build or change the schedule.

Before new admissions at 08:00 UTC, ingestion and discovery must use the same published snapshot/window/policy fingerprint, and Sentinel must read that same membership. Protected management subscriptions can make the fetched set exceed 600; they do not permit new admissions outside Core. At assessment Friday membership had 600 Core and ingestion fetched 603 (Core union V2 scope). If Monday publication/consumer agreement fails, report the failure and do not authorise new admissions or relax rules.

## Controls, notifications and PDM

Compare controls against the hashes in `docs\research\evidence\2026-10-10_weekend_shutdown\RESTORE_MANIFEST.json`:

- Review alerts: `results\opportunity\control\promotion_signal_delivery.json`, `paused=false`, `delivery_mode=RESEARCH_REVIEW`, original delivery boundary intact. Loaded promotion version was `de24a9891031`, source commit `643c22aece4c-dirty`; template V2 was deployed at 2026-10-09 20:30:42 UTC. Natural V2-template delivery remains awaiting a qualifying event; do not send a test.
- VR: `results\vr_paper\entry_control.json`, `entries_blocked=true`; interruption boundary and record unchanged. No OPEN trades, but one historical ACTIONABLE `PAPER_ENTRY_PENDING` remains. VR stays running; do not discard the row or start a second wrapper. Its durable cursor/open-management semantics and `skip_backlog=True` are unchanged, end date 16 October unchanged.
- Notifications: Intelligence had 1 PENDING and 3 AMBIGUOUS; preserve them. Existing Intelligence expiry applies at sweep and immediately before send; stale IN_FLIGHT claims become AMBIGUOUS, not automatically retried. Durable event-processing states, filing identity dedup and historical backfill checkpoints support normal resumption, but bounded acquisition is not a guarantee of arbitrary missed-period recovery. Delivery remains unchanged because the pending row's disposition/replay safety is unresolved. The release outbox has 1 FAILED, 2 EXPIRED, 57 SENT. Other inspected operational outboxes had only SENT/EXPIRED. Never mark pending rows SENT or purge a backlog. Never replay ambiguous or failed sends by operator action.
- PDM approved `first_session=2026-10-19`; leave config and implementation locks intact and collector inactive. Task `\TalonX\PDM_V1_Collector` is Ready, first trigger **20 October 00:15 BST (19 October 23:15 UTC)**, then 06:30 BST. This is the overnight processing trigger after the approved first session, not early activation. Verify with `Get-ScheduledTask` and `Get-ScheduledTaskInfo`; do not use `Start-ScheduledTask`.
- Existing ERM and UniverseVerify one-shot tasks have no next run. No other inspected TalonX scheduler action requires a weekend execution; the forward obligation comes from its retained loop, not Task Scheduler.

## Unexpected full outage

Power-off is not authorised by this runbook. Scheduled tasks cannot boot a powered-off laptop. If an outage occurs, preserve locks, outboxes, WAL/SHM and cursors; record any missed forward observation. Do not restore Saturday database backups over newer state.

After verifying all prior owners are absent, startup dependency order is Redis → ops/V2 stack (Original Signal poller, Intelligence, dashboard) → Opportunity stack (Sentinel) → tracker wrappers. Existing documented commands are:

```powershell
docker start talonx-redis
$env:TALONX_V2_CAMPAIGN_ID='V2-PAPER-RC1'
$env:TALONX_V2_DB_PATH='v2_release_rc1.db'
$env:TALONX_V2_STATUS_PATH='v2_release_rc1_status.json'
$env:TALONX_V2_STARTING_CASH_USD='100000'
$env:TALONX_V2_ALLOCATION_USD='10000'
$env:TALONX_V2_EXECUTION_MODE='PAPER'
$env:TALONX_NOTIFY_DB_PATH='v2_release_rc1_notifications.db'
.venv\Scripts\python.exe -m talonx_v2.release_gate
.venv\Scripts\python.exe -m talonx_ops.prospective start --release --expected-sha 41375bb --tick-seconds 150 --heartbeat-seconds 30 --live-lookback-days 45 --execution-scope resolved-active-watchlist --deliver --transport telegram
```

The start uses existing durable campaign state, not a new campaign. Its release gate and single-writer lock must accept it. Do not bypass a failed gate or remove a stale/unknown lock manually. This baseline SHA is an ancestry gate; documentation descendants are expected. No `--force` or new study activation is authorised here. If the start refuses a stale lock, retain evidence and resolve through the supported recovery procedure before proceeding.

In a separate persistent PowerShell session, only after verifying the Opportunity supervisor and all its components are absent:

```powershell
Set-Location -LiteralPath C:\workspace\TalonX
$env:TALONX_SEC_BACKGROUND_REFRESH_ENABLED='1'
$env:TALONX_NOTIFY_RESEARCH_ENABLED='1'
$env:TALONX_OPP_NOTIFY_POLICY='LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925'
$env:TALONX_OPPORTUNITY_PROMOTION_MODE='PAPER_SIGNAL'
$env:TALONX_SENTINEL_COMMANDS_ENABLED='1'
$env:OPERATOR_UNIVERSE_MUTATION_MODE='DRY_RUN'
Remove-Item Env:TALONX_OPP_ROOT -ErrorAction SilentlyContinue
.venv\Scripts\python.exe -u -m talonx_opportunity up --deliver --supervise
```

Restore forward through its sleep-first wrapper above; if the VR chain is absent, use its preserved command once in a persistent session:

```powershell
& 'C:\Program Files\Git\bin\bash.exe' results/ops_restore_20261004/tracker_vr.sh
```

Leave DTU/ERM off and PDM scheduled. Verify Redis PONG, dashboard HTTP 200, distinct single Signal and Sentinel pollers, fresh V2 heartbeat/data timestamp and provider contract, advancing Intelligence poll timestamp, fresh Opportunity heartbeats and natural universe publication before declaring restoration working. Saturday backup paths/hashes are in the restore manifest; backups are local and access restricted to the Windows account, SYSTEM and administrators.
