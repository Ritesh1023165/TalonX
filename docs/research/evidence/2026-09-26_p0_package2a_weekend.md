# Weekend package (2026-09-26): process footprint, missed V2 EOD close, P0 package 2A hardening

Follows [2026-09-26_p0_package1_acceptance.md](2026-09-26_p0_package1_acceptance.md). Evidence: [`2026-09-26_p0_package2a/`](2026-09-26_p0_package2a/). Monday procedure: [`docs/runbooks/2026-09-28_MONDAY_RUNBOOK.md`](../../runbooks/2026-09-28_MONDAY_RUNBOOK.md).

**Context:** Saturday, no XNYS session. SEC live acceptance stays **pending Monday**. Provider mutation stays **OFF** (DRY_RUN).

## 1. Process footprint
- **Initial inventory:** 16 logical TalonX processes, 32 python processes as shim/real pairs.
  - Ops supervisor, which owns run_talonx (Original, the Signal poller), intelligence and the dashboard.
  - V2 companion.
  - 10 Opportunity Engine components and one engine supervisor loop.
  - Plus 2 of my background shells: the engine supervisor loop's host shell, and an idle Monday-acceptance waiter.
  - 0 duplicates. No after-hours, skip or watch trackers were still running (all had finished on Friday night).
- **Stopped:**
  - The Monday waiter (replaced by the runbook).
  - The engine supervisor loop, twice: its own 2 PIDs only, relaunched with the new component list.
- **Weekend minimal set = the full running stack, left in place.**
  - Every component is idle on a non-trading day: CLOSED-phase ticks, no provider fetches, no SEC load.
  - Stopping and restarting the evaluators, ingestion and others would create avoidable deployment boundaries (see F-P2).
  - V2 must stay up for its prospective loop and status.
  - Nothing needed stopping for state safety.
- **Final:** 17 logical processes (34 python processes): the same set plus the `sentinel` component. Validation tasks 0, duplicates 0.

## 2. Missed V2 EOD close (2026-09-25)
**Precheck (PASS):** the snapshot is in `v2_pre_close.json`.
- **Campaign:** V2-PAPER-RC1; strategy `e2acf6454789217e`; provider `ac5e51aa3599d6c9`.
- **Ledger:** cash $100,000; 0 positions, trades, intents and account blocks.
- **Session dir:** had no EOD markers.
- **Why a normal close was unavailable:** `eod_state` returned `NOT_DUE_YET`, because "not an XNYS session today".

**Command semantics.** Repository inspection showed that `close` reconciles `V2_DB_PATH` / `V2_STATUS_PATH` / `TALONX_NOTIFY_DB_PATH`. These default to the **legacy** `v2_lane.db` ($300k, 2026-09-15) and the shared outbox unless the release environment is set. The authorised command therefore ran **exactly as given**, with the documented release environment (`docs/OPERATIONS.md`) set for this process only:
```
TALONX_V2_CAMPAIGN_ID=V2-PAPER-RC1 TALONX_V2_DB_PATH=v2_release_rc1.db TALONX_V2_STATUS_PATH=v2_release_rc1_status.json
TALONX_NOTIFY_DB_PATH=v2_release_rc1_notifications.db (+ cash/allocation/PAPER)
python -m talonx_ops.prospective close --session-dir results/prospective_2026-09-25 --force --no-shutdown
```
**Result: `PASS_WITH_FINDINGS`** (exit 0).
- All 18 V2 reconciliation checks PASS: ledger equation, cash, no negative cash, whole shares, no duplicate BUY/position, no stale episode entered, no illegal flatten, real capital off, shorts off, no external experimental send, no cross-lane contamination, dispatch healthy, ledger copy preserved, lane accounting.
- The one finding is the standing base reconciliation `PARTIAL` (no PIV reader), with `mismatches=[]`.

**Acceptance** (`v2_post_close.json`):
- The ledger is byte-identical (db sha `891cddac6ce2a1a6` before and after; every table hash unchanged).
- Cash $100,000; 0 positions, trades and intents; fingerprints unchanged.
- `eod.json`, `final_report.md`, `eod_final_checkpoint.json`, `terminal_summary.txt` and `v2_lane.db.eod-copy` were written once.
- The base EOD row is an idempotent upsert, so no duplicate.
- **Shutdown performed: false.** V2 PIDs 12840/20216 are still alive and the heartbeat is fresh.
- **Notification:** exactly one standard `SHUTDOWN` lifecycle notice to Sentinel (OPERATIONS, SENT 09:48:40Z). It is the close procedure's own notice and reads `shutdown_performed=False`.

**V2_EOD_CLOSE_VERDICT: ACCEPTED.**

## 3. Code changes

| Commit | Change |
|---|---|
| `c80ecd2` | **F-P3:** `eod_state` returns `OVERDUE_EOD_CLOSE` (session date, dir, deadline) when the previous XNYS session was started (session dir with `start_verify.json` / `session.pids.json`) but has no `eod.json`. Holidays use the previous real session. `run_close` still requires `--force` for it (surfaced, never closed implicitly). Adds the closed freeze list `FREEZE_P0_2A_OPS_FILES`. |
| `37b04d8` | **F-P1:** `supervisor` and `sentinel` default to OPERATIONS_ONLY.<br>**F-P2:** verified shared-runtime declarations: rebuild the recorded version from git at the recorded commit; ELIGIBLE only if every changed file is in the closed `SHARED_RUNTIME_OPS_FILES` (`runtime.py`). Declarations are bound to `expected_version` (additive column) and never apply to any other version. |
| `c8fe8ef` | **Supervised Sentinel poller** (`talonx_opportunity/sentinel_component.py`): lock, heartbeat, boundary and respawn; idle unless enabled; credentials only via `operator_control.sentinel.operations_poller`; offset persisted before each update (no command replay); owner-only `/status`.<br>**Promotion and sentinel** added to `supervise.COMPONENTS`.<br>**Role-aware Telegram poller health.**<br>**Status:** promotion mode + policy fp; Sentinel enabled / universe mode / bot / last error. |
| `b8b7dec` | `declare-shared-runtime` CLI (dry-run by default, `--apply`). |

## 4. Live boundaries (2026-09-26)

| UTC | Component | Boundary | Class / rule |
|---|---|---|---|
| 10:03:43 | supervisor loop | `20260926T100343Z-supervisor-aa71f6` | **OPERATIONS_ONLY** / UNDECLARED_CODE_CHANGE_DEFAULT (F-P1 proven live; the same shape recorded STRATEGY_MATERIAL at 09:06Z) |
| 10:03:44 | sentinel | `20260926T100344Z-sentinel-a88b26` | OPERATIONS_ONLY / FIRST_START; config `enabled=1, mutation_mode=DRY_RUN, destination=SENTINEL`; bot `@TalonXSentinalBot` |

**F-P2 declarations applied** (`fp2_declarations.json`): version-bound OPERATIONS_ONLY for discovery, the 4 evaluators, notifier, outcomes, promotion and reporting.
- Each passed the git rebuild check, and each changed file is `runtime.py` only.
- **ingestion: REFUSED.** `ingestion.py` itself changed (operator gate, `40386fa`), so it classifies normally.
- Components not restarted keep their running versions.

## 5. Poller health (live)
- **Verdict:** `EXPECTED_DISTINCT_POLLERS`, with roles SIGNAL_COMMANDS 1 (run_talonx 21840) and SENTINEL_COMMANDS 1 (sentinel 17816).
- **Signal invariant:** the ops-supervisor Signal-owner invariant (`count_telegram_get_updates_owners`, run_talonx only) is unchanged.

## 6. Sentinel DRY_RUN acceptance
- **Offline reply render** (`sentinel_reply_render.txt`): every requested command was rendered against the live stores, with an isolated operator DB.
  - Help, per-command help, status, scanned (summary / candidates / setups / signals / CSV file, 5,653 rows, 619 KB) and exclude/universe status.
  - `/exclude add TSLA weekend-test` → "accepted as PENDING … live provider fetching unchanged until activation"; then remove → "restore accepted as PENDING — no replay".
  - Unauthorised chat → "⛔ Not authorised".
  - UX: icons, short sections, a DRY_RUN banner on the help and mutation paths, examples, no secrets, no stack traces.
- **Real Telegram round-trip:** see §6.1.
- **Authorisation (tests):**
  - An unauthorised chat can neither mutate nor read `/status`; both attempts are audited `REJECTED_UNAUTHORIZED`.
  - The poller only ever holds the Sentinel bot, so Signal and Lab bots cannot deliver commands to it.
  - Detail, config and logs contain no token (the sentinel log was scanned: 0 token patterns; httpx request logging is suppressed).

### 6.1 Real Telegram round-trip: **ACCEPTED** (2026-09-26 13:28–13:35Z)
The owner sent the commands to **@TalonXSentinalBot** in its private owner chat. There was no webhook, and before sending 0 updates were pending.

**Sources:** the Sentinel reply ledger (`sentinel_replies.jsonl`, added in `cd6797a`), the saved offset (`sentinel_state.json`), operator audit rows, runtime detail and poller health. Chat IDs and user IDs are deliberately omitted.

| # | UTC | Command | Result | Reply (first line) | Telegram msg id | Audit |
|---|---|---|---|---|---|---|
| 1 | 13:28:22 | `/help` | SENT, 523 chars | ⚙️ TALONX SENTINEL — COMMAND HELP | 26 | — |
| 2 | 13:29:11 | `/help exclude` | SENT, 796 chars | ⚙️ … — /exclude | 28 | — |
| 3 | 13:29:28 | `/help scanned` | SENT, 297 chars | ⚙️ … — /scanned | 30 | — |
| 4 | 13:29:58 | `/status` | SENT, 288 chars | 🛰 TalonX Sentinel — /status | 32 | — |
| 5 | 13:30:10 | `/scanned` | SENT, 248 chars | ⚙️ … — SCANNED (2026-09-26) | 34 | — |
| 6 | 13:30:22 | `/scanned candidates` | SENT | ACTIVE CANDIDATES (0) | 36 | — |
| 7 | 13:30:36 | `/scanned setups` | SENT | ACTIVE SETUPS (0) | 38 | — |
| 8 | 13:30:48 | `/scanned signals` | SENT | PAPER PROMOTIONS (0) | 40 | — |
| 9 | 13:30:56 | `/scanned file` | **DOCUMENT SENT** `talonx_scanned_2026-09-26.csv`, 134 B (header only, 0 rows) | scanned export: 0 symbols (2026-09-26) | 42 | — |
| 10 | 13:31:18 | `/exclude status TSLA` | SENT | ⚙️ … — TSLA | 44 | — |
| 11 | 13:31:32 | `/universe status TSLA` | SENT | ⚙️ … — TSLA | 46 | — |
| 12 | 13:31:47 | `/exclude add TSLA weekend-test` | SENT: accepted as **PENDING** | OPERATOR CONTROL | 48 | `8073f2ccc0b04a2f`: authorized, DRY_RUN, `PENDING_ACTIVATION`, reason `weekend-test`; state `EXCLUDED / PENDING_ACTIVATION` |
| 13 | 13:32:04 | `/exclude remove TSLA` | SENT: restore accepted as **PENDING** | OPERATOR CONTROL | 50 | `e8b4cd23868c4c13`: authorized, DRY_RUN, `PENDING_ACTIVATION`; state `RESTORED / PENDING_ACTIVATION` |
| 14 | 13:34:43 | `/help universe` (sent last) | SENT, 666 chars | ⚙️ … — /universe | 52 | — |

**Checks:**
- **Exactly once:**
  - 14 expected, 14 received, 14 SENT.
  - 0 NO_REPLY, 0 FAILED.
  - Update IDs are 14 consecutive values with no gap and no repeat.
  - Runtime `handled = 14`.
  - 2 audit rows, exactly the two mutations.
- **No replay:** the saved offset is `next_offset = last update + 1`, written before each update was handled. A restart resumes after command 14.
- **DRY_RUN and no provider mutation:**
  - Every mutation is `PENDING_ACTIVATION` in DRY_RUN, and the gate is an exact identity.
  - Ingestion fetch universe is 5,653 symbols, unchanged (last cycle 2026-09-25 23:59Z; no weekend cycle).
  - No discovery or promotion effect: 0 candidate events and 0 promotions since 10:00Z.
- **Routing / isolation:** every reply came from @TalonXSentinalBot. Since 10:00Z:
  - Lab outbox: 0 rows.
  - Promotion (Signal) outbox: 0.
  - V2 outbox: 0.
  - Signal-side logs: no command traffic.
- **V2:** unchanged. Ledger sha `891cddac6ce2a1a6`, cash $100,000, 0 positions, trades and intents; status CURRENT.
- **Broker calls:** 0; there is no order path.
- **Poller health after the burst:** `EXPECTED_DISTINCT_POLLERS`, SIGNAL_COMMANDS 1 and SENTINEL_COMMANDS 1, with 0 unknown and 0 duplicates. Sentinel heartbeat fresh.
- **Transient:** one getUpdates long-poll `TimedOut` at 13:36:10Z, after all commands had been handled (1 in 578 polls). The runtime backed off 20 s; the component showed DEGRADED for about 20 s, then RUNNING with 0 consecutive failures. Overall HEALTHY again at 13:37Z.

**Findings / follow-ups (not fixed; UX only):**
- **S-UX1:** on a non-trading day `/scanned` reads the current (empty) window and renders placeholders: `Phase: None · last scan Z (Nones)`, `data-ready None`. It should say `CLOSED · No scans today` and point to the last session.
- **S-UX2:** consider an optional historical form, e.g. `/scanned file YYYY-MM-DD`, for the last session's CSV on weekends. Today's file was correctly the empty 2026-09-26 export.
- **S-OPS1 (LOW):** a single Telegram long-poll timeout flips the component to DEGRADED until the next poll. Consider treating `TimedOut` on `get_updates` as an empty poll.

**Verdicts:**
- `SENTINEL_DRY_RUN_ROUNDTRIP = ACCEPTED`
- `CONTROL_PLANE_ACTIVE_MUTATION = STILL_OFF`
- `READY_FOR_MONDAY_ACTIVE_PROOF = YES`, subject to the runbook gates: SEC live acceptance passes, the F-W2 declarations are made, and the owner authorises ACTIVE.

## 7. Tests

| Suite | Result |
|---|---|
| focused `tests/test_p0_package2a.py` (F-P3 ×7, F-P1 ×2, F-P2 ×5, poller health ×8, Sentinel component ×6, supervision/status ×3) | **32 passed** |
| regression sweep: Opportunity Engine, P0-1 SEC/AH, SEC refresh, promotion, operator control, V2 routing, notification isolation (5 suites), pre-full-day cleanup, premarket engine, session03, task114 prospective, task117 owner dedup, task100b runtime, task102 finalization, legacy cleanup, canary hardening | **571 passed, 4 failed** → after the guard fix: 3 failed, all baseline |
| baseline failures (identical on START_SHA `c8ca1c7`) | `test_task102::test_36_original_strategy_unchanged` (diff lists `talonx_paper` / `talonx_quant` files this branch did not touch); `test_task114::test_start_stack_*enable_broad_discovery*` ×2 (`ConcurrentStartError`: live stack running) |

The one real failure during development was the research-lane guard `test_15`: the component named the OPERATIONS destination. It was fixed by moving credential resolution into the control plane (`operations_poller`); the lane never names it.

## 8. Findings
- **F-W1 (LOW):** `talonx_ops.prospective close` and `status` silently target the legacy `v2_lane.db` / shared outbox when the release environment is not exported. Consider refusing when `TALONX_V2_CAMPAIGN_ID` is unset but a release ledger exists.
- **F-W2 (MEDIUM, before Monday ACTIVE):** `OPERATOR_UNIVERSE_MUTATION_MODE` is not in any component's config fingerprint.
  - An ACTIVE restart is only classified by declaration. Worse, a pending version-bound OPERATIONS_ONLY declaration (discovery) would apply unless a fresh declaration is made first.
  - The runbook §3 requires DATA_FIX declarations before each ACTIVE restart.
  - Next version: add `operator_universe_mode` to the ingestion, discovery and promotion config fingerprints.
- **F-W3 (INFO):** the `declare-shared-runtime` dry run opened `runtime.db` read-write and applied the additive `expected_version` column migration. This is compatible with running components (named-column inserts).
- **F-W4 (decision):** promotion remains in PAPER_SIGNAL (status quo from 2026-09-25) and will send paper Signals in Monday's REGULAR session unless the owner switches it to SHADOW (runbook §6).

## 9. Unchanged
- Scoring, lifecycle, notifier ranking/rates and caps, and the promotion eligibility contract.
- V2 strategy, provider and campaign.
- The SEC refresher (still deployed and pending).
- The AH reserve fix (accepted on replay).
- No ACTIVE provider mutation, no fetch-universe change, no broker path, no real orders.

## 10. Controlled weekend shutdown (2026-09-26 17:46–17:49Z)
- **Pre-shutdown (17:46:52Z), PASS:**
  - HEAD `1098633`, clean tracked tree, `main` `696370e`.
  - 34 python processes, i.e. 17 logical, 0 duplicates; pollers `EXPECTED_DISTINCT_POLLERS` (Signal 1, Sentinel 1).
  - Every engine cursor at 4,550 (lag 0); 2,065 candidates, 4,550 events.
  - Promotion PAPER_SIGNAL, 0 queued; Sentinel handled 14, offset 920191867.
  - 0 pending or failed in the Lab, Signal-promotion, V2 and shared outboxes.
  - V2 $100,000, 0 positions/trades/intents/actionable rows, 09-25 closed.
  - 19 of 19 databases pass `quick_check`.
- **Method** (supported paths, in order):
  1. Stop the engine supervisor loop (its own two PIDs; the loop has no stop command, only Ctrl-C) so nothing can respawn.
  2. `python -m talonx_opportunity down`: all 11 components graceful, 10 s.
  3. `talonx_ops.prospective.proc.stop_stack(results/prospective_2026-09-25)`, the ownership-verified teardown `prospective close` uses. `close` itself was not re-run, so the accepted 09-25 EOD evidence was not overwritten.
     - Checkpoint daemon: not running.
     - V2 companion tree (3): stopped.
     - Ops supervisor tree (9: Original/run_talonx with the Signal poller, intelligence, dashboard): stopped.
     - 0 residual; ports 8787/8760/8770/8501 closed; PID registry cleared; V2 start-lock released with its owner token.
- **Post-shutdown (17:49:19Z, 70 s later), CLEAN:**
  - 0 TalonX processes, 0 Telegram pollers, 0 supervisors, 0 validation tasks; no respawn.
  - Outboxes byte-identical, with 0 pending/failed created.
  - Engine counts, cursors, promotion states and Sentinel offset unchanged.
  - V2 ledger sha unchanged; only the companion's final status tick (620 → 621).
  - 19 of 19 databases `ok`; no broker calls.
- **Monday:** start at **08:00 UK = 07:00Z**, following `docs/runbooks/2026-09-28_MONDAY_RUNBOOK.md` §S. Every mode comes from an explicit versioned start command or a persisted store (no reliance on this session's shell). Provider mutation stays DRY_RUN.
- **Evidence:** `2026-09-26_p0_package2a/weekend_shutdown/`.
