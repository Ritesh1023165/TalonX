# Monday restoration report: 2026-10-12

**Verdict: `RESTORED_WITH_GAP`.**
- **Restored:** the four Opportunity evaluators, at 2026-10-12 15:26:59Z (16:26:59 BST).
- **Gap 1:** evaluator processing for Monday's window was **delayed, not lost**. All 667 queued events were evaluated
  on resumption.
- **Gap 2 (separate):** the **Sunday 2026-10-11 V2 forward observation FAILED** and is preserved as failed. It was not
  rerun.
- Everything else was running and healthy throughout, and nothing healthy was restarted.

## Baseline (read-only, before any change)

| Item | Finding |
|---|---|
| Time | 2026-10-12 15:24:50Z = 16:24:50 BST, during US regular trading |
| Machine | No reboot since 2026-10-04 18:13:22Z, so the machine stayed on all weekend |
| Git | Branch `feature/continuous-opportunity-engine`; HEAD = origin = `3bab002`. The only tracked change is the owner's `forward_alpha_validation.md` (sha256 `b1c886ba…`, unchanged). |
| Running | Ops supervisor, Original, V2 companion, Intelligence, dashboard, Opportunity supervisor, and Opportunity ingestion, discovery, notifier, outcomes, reporting, promotion and Sentinel (heartbeats ≤ 20 s); VR wrapper; V2 forward wrapper and loop; Redis (`PONG`); dashboard HTTP 200 |
| Stopped | `evaluator:INTRADAY/SAME_DAY/SHORT_TERM/LONG_TERM`: STOPPED, stop flags present in `results/opportunity/control/`, last heartbeat 2026-10-10 19:03:40–42Z |
| Impaired | No other impairment. The Opportunity status "PAPER" block showed a V2 heartbeat of 2026-10-10 19:03Z, but that is the **SHORT_TERM evaluator's last stored observation** of the V2 status file. The V2 companion itself was fresh (status tick 4436 at 15:25:34Z, `data_state=CURRENT`). |
| Restoration by others | None. There were no evaluator START or RESTART events between the 2026-10-10 19:03Z stops and this session. |

## Action (runbook `docs/runbooks/2026-10-12_MONDAY_RESTART.md`, "Restore only what this assessment stopped")

**Startup checks** (from code):
- Each evaluator reads `candidate_events` after its durable cursor, 2,000 per 30 s tick.
- It writes `INSERT OR IGNORE` research records with `action_state=NONE`.
- It sends nothing and creates no orders. Its only reader is reporting.
- Resuming therefore processes the queued events of the current window; it does not replay alerts.

**Version.** The hashed sources changed only through shared `runtime.py`, which gained one entry in promotion's source
list (`delivery_trace.py`, commit 507f8c0). `evaluators.py`, `db.py`, `phases.py` and `config.py` are unchanged, so
there was no behaviour change.

**Steps:**
1. Declared each evaluator `OPERATIONS_ONLY`, declarations #52–#55. Recorded as `DECLARED`, version `364f2071525f` →
   `67093049c7b1`.
2. Ran once at 15:26:57Z:
   `.venv\Scripts\python.exe -m talonx_opportunity up --only evaluator:INTRADAY,evaluator:SAME_DAY,evaluator:SHORT_TERM,evaluator:LONG_TERM`.
   - It removed only those four stop flags and spawned the four missing workers.
   - It did not use `--supervise` (the existing supervisor keeps relaunch authority).
   - No lock or PID file was deleted, and no other component was touched.

| Component | Before | Action | After |
|---|---|---|---|
| evaluator:INTRADAY / SAME_DAY / SHORT_TERM | STOPPED (stop flag) | declared OPERATIONS_ONLY, `up --only` | UP, one launcher→interpreter pair each, hb ≤ 2 s, cursor at the current max seq |
| evaluator:LONG_TERM | STOPPED | same | UP, `IDLE_NOT_IMPLEMENTED` (by design) |
| All other components and trackers | UP | none | UP, owners unchanged (same PIDs as at baseline) |

**After restoration:**
- **Cursors:** all four advanced from 47565 to 48232 (the maximum at the time), then followed live events (48234 at
  15:30:29Z).
- **Duplicate event ids:** 0.
- **Records written** (exactly each horizon's phase scope):

  | Evaluator | Records | Scope |
  |---|---|---|
  | SAME_DAY | 667 | all phases |
  | INTRADAY | 576 | premarket 222 + regular 354 |
  | SHORT_TERM | 91 | overnight |
  | LONG_TERM | 0 | not implemented |

- `status`: `overall=HEALTHY`.

## Evaluator gap (operational metadata only)

| Point | UTC |
|---|---|
| Last evaluated event before the stop | seq 47565, event 2026-10-09 23:20:00Z (window 2026-10-09); cursor written 23:20:10–34Z |
| Graceful stop | 2026-10-10 19:03:40–42Z |
| Candidate events Fri 23:20Z → Mon 00:00Z | **0** (no weekend window activity) |
| Events not evaluated at the time they occurred | **667**, seq 47566–48232, window 2026-10-12, 00:00:01Z → 15:25:00Z (overnight 91, premarket 222, regular 354) |
| Restored | 2026-10-12 15:26:59Z |

**Confirmed processing gap.** Evaluator records for Monday 00:00:01Z–15:25:00Z were written late, at
`recorded_utc` ≈ 15:26:59Z, up to about 15.4 hours after the event. `at_utc` keeps the true event time. No event was
skipped.

**Confirmed delivery failures caused by the gap: none.** Evaluators feed no delivery path:
- Promotion and the Lab notifier read `candidate_events` directly.
- 17 review alerts were promoted and delivered on 2026-10-12, all `SENT` and `TRACE_OK`.
- The Lab research outbox has only `SENT` rows.

**Unknown effects:**
- Reporting snapshots and the dashboard's horizon panel produced before 15:26:59Z showed the evaluators as STOPPED, and
  the horizon counts excluded Monday's records.
- No evaluator output was used for trading; there are no authorised BUY/SELL strategies.
- No claim is made about missed opportunities or returns.

## Monday data and admission

- **Universe:** `2026-10-12@2026-10-09#2849da5594f272db`, policy DTU_V3_TOP600 (schedule hash `9f0c07a5…`).
  - Snapshot: 600 `ACTIVE_CORE`, 5,041 auto-excluded and 8,752 structurally excluded.
  - Report `results/opportunity/universe_reports/2026-10-12/`: reference session 2026-10-09, `reconciled=true`, no
    schedule error or fallback.
- **Consumers agree:**
  - The DTU active set (08:02:26Z full set) has 603 names: 600 Core plus 3 V2-scope protected names (ABCL, ACHR,
    ADC), with Core ⊆ active.
  - Ingestion fetches 603 (`as_of` 15:09Z, incomplete 0).
  - Discovery: last scan 15:25:00Z, eligible 603.
  - Sentinel reads the same `market.db` `dtu_snapshot`/`dtu_active` (Sentinel DRY_RUN).
  - The protected names are management subscriptions, not admissions.
- **Review delivery:** `RESEARCH_REVIEW`, boundary unchanged (control sha256 `f0589fb1…`).
  - 17 alerts delivered today, all SENT.
  - Outbox: 1,466 rows, all SENT; none pending.
  - Trace: 17 `TRACE_OK` today.
- **Template V2 natural verification: PASS.**
  - 17 of 17 post-deployment rows (BIIB, NOW, FRO, SHOP, META, FSLR, ACN, TMUS, WDAY, RIG, FANG, INTU, ASTS, EBAY,
    PENG, SN, TYL) are byte-identical to the deployed renderer's output re-derived from generation records.
  - All carry `template_version RESEARCH_REVIEW_COMPACT_V2`, `TRACE_OK`, a single attempt and a unique dedup key.
  - Evidence: `NATURAL_V2_VERIFICATION.json`.
- **Dashboard:** :8787 `/api/sections` is fresh (generated 15:32Z) and shows Opportunity `HEALTHY` with no STOPPED
  evaluator.

## Trackers and controls (operational status only; no outcome artifact opened)

**V2 forward:**

| Day | State | Detail |
|---|---|---|
| 2026-10-10 | SUCCESS | |
| 2026-10-11 | **FAILED** (record still says `RUNNING`) | See below |
| 2026-10-12 | **SUCCESS** | Run `20261012T060000Z-444a23`, 06:00:00.87–06:02:44.66Z, five stages exit 0; cutoffs info ≤ 2026-10-11, prices ≤ 2026-10-11 |

**Sunday's run, `20261011T060000Z-394d68`:**
- Started 06:00:00.31Z; `edgar_crawl`, `episodes` and `prices` exited 0.
- At 06:01:33Z, writing the state record before `evaluate` failed. The loop log shows
  `PermissionError [WinError 5] Access is denied` on `os.replace(2026-10-11.json.tmp → 2026-10-11.json)`: the record
  was held open by another reader at that instant, and the reader is unknown.
- The runner exited 1. The loop logged `state RUNNING exit 1` and slept to the next slot.
- `evaluate` and `forward` never ran. The orphaned `.tmp` and `RUNNING` record are preserved; PID 772 is gone and the
  07:30Z deadline has passed.
- **Not rerun or backfilled.** The as-of-2026-10-11 observation is missing.
- **Finding (not fixed here):** `forward_runner.write_atomic` has no retry for a Windows sharing violation. The
  dashboard does not show forward-run state, so the failure was invisible there.
- **Next run:** 2026-10-13 06:00Z (07:00 BST), from the single loop (wrapper 3344 → loop 24096 → sleeper 7132).

**VR:**
- `entry_control` BLOCKED (sha256 `bd10edf6…`); ARM interruption record unchanged (`477e20d6…`).
- Trades: EXITED 300, SKIPPED 1,425, `PAPER_ENTRY_PENDING` 1. There are no OPEN trades to manage.
- The pending row, identified by metadata: `trade_id 13babda614db1b23`, promotion
  `OPPORTUNITY_ENGINE:2026-09-30:NVCT:GAP_UP`, created and last updated 2026-09-30 20:03:48Z, so it is the old NVCT
  row and unchanged.
- One wrapper (`--until 2026-10-16`).

**Other controls:**
- **DTU:** collector and control-shadow not running.
- **ERM:** parked; the ERM tasks have no next run.
- **PDM:** `verify_integrity` = []; config sha256 `f7f012fd…`, config hash `6c451267…`, protocol `c812a3e65e4018a5`;
  task `\TalonX\PDM_V1_Collector` Ready, never run, next run 20/10/2026 00:15 BST (= 2026-10-19 23:15Z). Not
  activated.

## Notifications

**Intelligence** (`~/.talonx/ingestion_ledger.db`):
- The Saturday PENDING row (CSCO, DIGEST) became `EXPIRED` at 2026-10-10 20:10:59Z through the existing rule
  `stale_card: 24.0h old > 24h DIGEST cutoff`. It was never sent.
- The three AMBIGUOUS rows are unchanged and were not retried:
  - AXP and ADI from 2026-09-14 ("send cancelled while possibly in flight");
  - AMAT from 2026-10-05 ("Telegram send outcome unconfirmed (TimedOut)").

  None has a message id.
- Totals: SENT 368, EXPIRED 50,847, AMBIGUOUS 3, PENDING 0.
- The service works: last cycle 15:28:39Z, 39 of 39 symbols polled, 0 failed, 0 new events, no backlog. No new watched
  filings since 2026-10-09 21:07Z means no event was observed; it is not a delivery fault.

**Release outbox:** 60 SENT (up 3 through normal V2 delivery), 2 EXPIRED, 1 FAILED (both unchanged).

**Others:** only SENT/EXPIRED. Nothing was marked, deleted or resent.

## Next obligations

- **V2 forward:** 2026-10-13 06:00Z (07:00 BST), automatically from the loop. The machine must stay on, on AC,
  connected and logged in.
- **VR wrapper:** runs until 2026-10-16. Entries stay blocked.
- **PDM collector:** first trigger 2026-10-19 23:15Z (00:15 BST on 10-20). The study's first session is 2026-10-19.
