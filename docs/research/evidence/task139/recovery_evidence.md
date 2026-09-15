# Task 139 — Host-Restart Recovery Evidence

## 1. Restart cause: CONFIRMED — planned OS update

Windows Event Log (`System`, event ID `1074`) shows a chain of three
TrustedInstaller-initiated restarts, each explicitly reason-coded
`Operating System: Upgrade (Planned)`:

```
02:44:47 local  TrustedInstaller.exe -- restart -- Operating System: Upgrade (Planned)
02:45:46 local  TrustedInstaller.exe -- restart -- Operating System: Upgrade (Planned)
02:46:28 local  TrustedInstaller.exe -- restart -- Operating System: Upgrade (Planned)
```

`Get-CimInstance Win32_OperatingSystem`: `LastBootUpTime = 09/15/2026
02:47:33` (local). Host-local timezone this period is Europe/London,
UTC+1 (confirmed throughout this project by direct comparison against
independent embedded `_utc` fields — never inferred from the raw prefix
alone). **UTC boot completion: `2026-09-15T01:47:33Z`.**

Corroborating internal evidence: the last `intel_event_processing`
enrichment-progress timestamp before the gap is
`2026-09-15T01:44:10.218498+00:00` — 37 seconds before the first
reboot-initiation event — and the supervisor log records BOTH `original`
and `intelligence` exiting simultaneously at that same moment with exit
code `1073807364` (`STATUS_CONTROL_C_EXIT`, Windows' console shutdown/
logoff signal), a code that appears nowhere else in this log's history.
This is a clean, distinct signature from the `4294967295` ("forceful
external kill") code seen in every other exit — see
`exit_classification.md` for the full breakdown, including why this is
NOT the same pattern as the day's earlier application-level restarts.

**This was a confirmed OS-update restart, not an application crash and
not an unknown-cause event.**

## 2. Actual HEAD and recovered Task 139 work

- Actual HEAD at recovery start: `0fe57f4be5642403c84ce0d76f22a6bf76372b64`
  — exactly matches the directive's "last confirmed HEAD before Task139"
  and `origin/feature/task131-option-a-integration`. `git status` was
  clean.
- **No prior Task 139 work existed anywhere** — no
  `docs/research/evidence/task139/` directory, no matching commits, no
  uncommitted edits, no interrupted-test artifacts in any local scratch
  directory. The directive's "CONTINUATION" framing assumed prior
  progress that, on inspection, was never actually started (or never
  reached disk) before the host restart. This is reported plainly rather
  than fabricating recovered work that does not exist. All Task 139 work
  in this bundle was performed fresh, in this recovery session, following
  the directive's own recovery-safety procedure throughout.

## 3. Infrastructure / components restored

| component | pre-recovery state | action | post-recovery state |
|---|---|---|---|
| Redis (`talonx-redis` Docker container) | up (Docker auto-restarted it) | none needed | healthy, `PING`→`PONG`, AOF+RDB persistence confirmed enabled, `DBSIZE` non-zero (durable keys like `metrics:*` survived) |
| supervisor / original / experimental / intelligence / dashboard | ALL DOWN — zero `python.exe` processes running | `python -m talonx_ops.prospective start --expected-sha 0fe57f4 --force --pricing-mode csv --execution-scope resolved-active-watchlist --deliver --transport telegram --enable-broad-discovery` (secrets omitted from the command line; resolved via the existing `.env`/environment-inheritance path, unchanged) | all 5 processes up, single owner each, `startup verdict: READY` |
| V2 companion | down; `v2_lane.db.startlock` left behind referencing dead PID `19984` (independently confirmed dead via `Get-Process` before acting — not assumed from process absence alone) | same `start` command; `--force` invoked `SingleWriterLock`'s own `break_stale=True` path, which re-verifies staleness via recorded `create_time` before removing the lock (never blindly deletes the file; the `state=="live"` branch is hard-blocked regardless of `--force`) | lock re-acquired cleanly, rebound to the new companion PID; `v2_ledger_continuity`/`v2_ledger_not_recreated` both `OK` in preflight |
| checkpoint daemon | down since `2026-09-14T21:21:04Z` (its own prior "_final" checkpoint — an INTENTIONAL, correct stop at the *previous* session's `until_close` boundary, not a crash; see below) | spawned fresh by `start` for the new `2026-09-15` session | `checkpoint_0001_20260915T023046Z.json` written; `campaign.campaign_day` correctly continued at `6` (not reset to `1`) |

Preflight (`python -m talonx_ops.prospective preflight --expected-sha
0fe57f4`) reported **READY** with every check `OK` before the start
command was issued, including `repo_head_matches_release`,
`v1_fingerprint`, `v2_fingerprint`, `redis_reachable`,
`no_stale_talonx_processes`, `required_ports_free`,
`v2_ledger_continuity`, `v2_ledger_not_recreated`.

**Checkpoint-daemon stop was NOT a defect.** `session_loop.run_loop`'s
`until_close=True` default causes it to write a final checkpoint and
exit cleanly once `now >= <session's own close deadline>` — the prior
session's (2026-09-14) checkpoint stream ran 27 checkpoints from
`09:50` to `21:21` UTC and stopped exactly at that session's own close
boundary, hours before tonight's OS restart even happened. This was
independently investigated and confirmed intentional design before
concluding a fresh daemon for the new session was the correct recovery
action (not a bug needing a fix).

## 4. Runtime attribution (verified, not merely claimed)

Post-restart, `talonx_ops.supervisor status` →
`producers.original.metadata.commit_sha` =
`5eb9f360a183ce6a310b1725aaf119cc7bc52744` was observed BRIEFLY right
after restart — this was the STALE `runtime_metadata.json` left by the
PRE-restart process, not yet overwritten. Re-checked ~2 minutes later
(the time `run_talonx.py`'s own startup genuinely takes to reach its
`write_runtime_metadata()` call) and confirmed fresh:
`commit_sha: 0fe57f4be5642403c84ce0d76f22a6bf76372b64`, `pid: 15952`
(the actual current real-worker PID), `started_at:
2026-09-15T02:32:35Z`. This is a genuine in-process `git rev-parse HEAD`
readout by the running process itself, not an inference from a log
marker. Intelligence has no equivalent in-process readout; its
attribution remains the same indirect method used in the Task 138
report (exact PIDs killed + fresh process launch + `git status` verified
clean at the correct HEAD immediately before/after) — stated as a
limitation, not claimed as direct.

## 5. Post-launch progress and reconciliation

**Accounting — byte-identical before and after, both databases:**

| | Original `current_cash` | Original `open_positions` | V2 `cash` | V2 `open_positions` | V2 intents/cooldowns/trades |
|---|---|---|---|---|---|
| pre-restart (last Task 138 check) | 10000.0 | 0 | 300000.0 | 0 | 0 / 0 / 0 |
| post-recovery | 10000.0 | 0 | 300000.0 | 0 | 0 / 0 / 0 |

**Informational outbox** — 0 `IN_FLIGHT` rows found after the restart;
`AMBIGUOUS` count unchanged at 2 (same two pre-existing rows, AXP and
ADI); no forced resend of any uncertain delivery.

**Real, completed-work progress observed** (not merely a heartbeat):

- Intelligence: fresh `intel_event_processing` rows with
  `updated_at_utc` timestamps of `2026-09-15T02:33:0Xz` onward — genuine
  post-restart enrichment work, confirmed via direct query, not
  inferred from process liveness alone.
- V2: `tick: 1` succeeded at `02:30:49Z` with `data_state: CURRENT`,
  `source.ok: true`, `execution_scope_enforced: true`,
  `stale_entry_skipped_this_tick: 3` (the Task 113 staleness guard
  correctly rejected 3 historical episodes on the very first tick —
  positive evidence AGAINST any retrospective/late entry, exactly the
  no-backdating requirement in Section 4 of the directive). By the
  second checkpoint capture, `tick: 3`, `service_health.health:
  HEALTHY`.
- Market data: `market.state` was `STALE` (last tick ~47 minutes old,
  pre-dating the reboot) for the first ~4 minutes after restart, then
  transitioned to `HEALTHY` on its own once the provider's first
  post-restart poll cycle completed — a normal cold-start delay, not an
  intervention-requiring fault.
- Dashboard (`:8787`): `200 OK` confirmed after restart.
- `telegram_send_ok: true`, `telegram_receive_owner_count: 1` — the
  single Telegram listener owns updates correctly and the bot token
  reached the child process via the existing (unmodified) `.env`
  inheritance path; no secret value was printed or logged to confirm
  this.
- Scope evidence (Task 137/138's own fix, re-verified live post-
  recovery): `qualification: FRESH_VALID`, `reported_scope_count: 626`
  == `reconstructed_scope_count: 626`, `watchlist_only_count: 39` kept
  distinct — the Workstream-1B fix continues working correctly across a
  full stack recovery.
- EOD: `state: NOT_DUE_YET`, `reason: "XNYS close
  2026-09-15T20:00:00+00:00 not reached"` — confirmed BEFORE any EOD
  command was considered, and none was run.

Full raw capture: `post_recovery_checkpoint_capture.json`.

## Natural inbound "details" reply check

`.run/logs/talonx.log` (the one rotating log all `run_talonx.py`
invocations across this entire session append to) was searched for
every `TelegramReplyListener`/listener-drain log line across its full
retained history. The listener's own startup line ("Telegram reply
listener polling...") appears at every restart, including the fresh one
tonight; its "Drained N pending Telegram update(s) on startup" line
(which would fire if any inbound message had queued while the listener
was down) **never appears once, across the entire retained log**. This
is consistent with — not new evidence against — the Task 138 report's
own honest statement that no natural operator reply has occurred yet.
**Status unchanged: PENDING.** No inbound update was fabricated or
manufactured to test this.
