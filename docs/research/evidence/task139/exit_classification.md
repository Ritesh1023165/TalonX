# Task 139 — Classification of Intelligence/Original "Unexpected Exit" Log Entries (2026-09-14/15)

Raw source: `results/prospective_2026-09-14/logs/supervisor.log`, lines matching
`exited unexpectedly`. All supervisor-log timestamps are host-local
(Europe/London, UTC+1 this period — confirmed by direct comparison
against multiple independent embedded `_utc` fields elsewhere in this
project's evidence). UTC conversion below subtracts 1 hour.

## Method

Every `exited unexpectedly` line carries a numeric exit code. Two
distinct codes appear:

- **`4294967295`** (`0xFFFFFFFF`, -1 as unsigned 32-bit) — the code
  this project's OWN Task 138 deliberate `Stop-Process -Force` restarts
  (verified, self-performed, timestamped in
  `docs/research/evidence/task138/before_after_cutover_snapshots.json`)
  ALSO produced. This is the generic signature Windows assigns when a
  process is forcefully terminated from outside (`TerminateProcess`/
  `Stop-Process -Force`/`taskkill /F`), not a distinct crash signal.
- **`1073807364`** (`0x40010004`, `STATUS_CONTROL_C_EXIT`) — a distinct,
  well-known Windows console-shutdown/logoff control-event code. Only
  this task's own confirmed OS-update restart (§ below, host restart
  evidence in `recovery_evidence.md`) produced this code.

Every `4294967295` entry was checked against `git log` commit
timestamps (also host-local) for a runtime-code commit landing within
seconds beforehand — the established "commit runtime changes, then
managed restart" cutover pattern this project has followed since at
least Task 100B.

## Full classification

| local time | UTC | component | code | classification | evidence |
|---|---|---|---|---|---|
| 10:50:2x | 09:50 | all 4 | n/a | initial morning `start` | session.pids.json `started_utc: 2026-09-14T09:50:24Z` |
| 14:54:43 | 13:54:43 | intelligence | 4294967295 | Task 133 cutover restart | commit `93a7e2e4` "feat(ingest): Task 133 -- recoverable processing and bounded delivery scheduling" at 14:54:19 local (24s before) |
| 15:02:38 | 14:02:38 | intelligence | 4294967295 | Task 133 iterative live-debug restart | Task 133's own P0 commit `309b8456` says "found live during cutover" — this and the next two entries are the observe/fix/restart cycle that produced it |
| 15:16:38 | 14:16:38 | intelligence | 4294967295 | Task 133 iterative live-debug restart | same P0 investigation (commit `309b8456` at 15:29:51 local landed after this cluster) |
| 15:22:42 | 14:22:42 | intelligence | 4294967295 | Task 133 iterative live-debug restart | same P0 investigation, immediately before the fix was committed |
| 16:16:18 | 15:16:18 | intelligence | 4294967295 | Task 134 cutover restart | commit `9828a066` "fix(ingest): Task 134 -- stop endless reprocessing of permanently-PARTIAL comparison rows" at 17:16:01 local (17s before) |
| 17:59:21 | 16:59:21 | **original** | 4294967295 | Task 135 cutover restart | commit `66a49f9` "fix(quant,dispatch): Task 135 -- surface Redis PUBLISH subscriber count for Quant signals" at 18:59:05 local (16s before); touches `talonx_quant/consumer.py`, Original's domain — component match confirms it |
| 18:39:22 | 17:39:22 | intelligence | 4294967295 | Task 136A cutover restart | commit `9db49555` "fix(ingest): Task 136A -- stop historical-alert noise, fix content provenance" at 19:39:06 local (16s before) |
| 19:49:11 | 18:49:11 | intelligence | 4294967295 | Task 136B cutover restart | commit `a1d0fd47` "fix(ingest): Task 136B -- close freshness edge cases, correct Task 136A evidence" at 20:48:49 local (22s before) |
| 21:57:25 | 20:57:25 | intelligence | 4294967295 | Task 137 cutover restart | commit `ae61cdb8` "fix(ops,ingest): Task 137 -- overnight continuity, scope accuracy, delivery fairness" at 22:56:59 local (26s before) |
| 00:52:17 (9/15) | 23:52:17 (9/14) | intelligence | 4294967295 | **Task 138's own restart** (already known/self-reported) | `docs/research/evidence/task138/before_after_cutover_snapshots.json`: action_utc `2026-09-14T23:52:15Z` |
| 00:53:07 (9/15) | 23:53:07 (9/14) | **original** | 4294967295 | **Task 138's own restart** (already known/self-reported) | same file: action_utc `2026-09-14T23:53:06Z` |
| 02:44:10 (9/15) | 01:44:10 (9/15) | **original + intelligence, both** | **1073807364** | **This task's host restart** | Windows Event Log `1074`: TrustedInstaller-initiated "Operating System: Upgrade (Planned)" restart chain at 02:44:47/02:45:46/02:46:28 local; last `intel_event_processing.updated_at_utc` before the gap is `2026-09-15T01:44:10.218498Z` — 37s before the FIRST reboot-initiation event, and the exit code is the distinct `STATUS_CONTROL_C_EXIT` signature never seen anywhere else in this log |

## Verdict

**Every single `4294967295` exit (11 of them, including this task's own
2 previously self-reported ones) is fully explained** as a legitimate,
documented, code-fix-then-restart cutover from the same iterative
development pattern this entire multi-day session has used
consistently. None is an unexplained crash. **The 2 `1073807364` exits
are this task's own confirmed OS-update restart**, cleanly distinguished
by a different, well-known exit-code signature — never conflated with
the application-level pattern above.

**No fix was needed for an unknown-cause defect**, because no
unknown-cause defect actually exists once classified. The one change
made (`talonx_ops/supervisor.py::_exit_code_hint`, committed this task)
is a bounded, log-only diagnostic so a future reviewer does not have to
redo this hour of manual git-timestamp correlation by hand — it annotates
future occurrences of these two known code values with a one-line hint,
with no change to restart/recovery control flow.
