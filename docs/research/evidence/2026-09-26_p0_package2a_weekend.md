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

### 6.1 Real Telegram round-trip
*(recorded after the owner's live test; see the addendum below)*

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
