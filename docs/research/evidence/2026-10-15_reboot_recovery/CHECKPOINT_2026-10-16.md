# Read-only checkpoint: 2026-10-16 08:06Z (09:06 BST)

**`CURRENTLY_HEALTHY`.** Every authorised component is up, with one logical owner each and fresh completed work.
Recovery from the 2026-10-15 reboot is complete. Its gaps are permanent and recorded in `RECOVERY_REPORT.md`:
- the 10-15 forward slot was MISSED;
- 10-15 processing was ~19h late for Opportunity and ~31h late for ops/V2.

Nothing was restarted, rerun, fetched or sent by this checkpoint.

| Item | Value |
|---|---|
| Observation | 2026-10-16 08:05:49Z |
| Boot | 2026-10-15 00:32:07Z (Windows Update, 2 planned restarts from 00:29:09Z); sign-in 19:26:22Z |
| Git | `feature/continuous-opportunity-engine`; HEAD = origin = `3117d08` before this commit. `forward_alpha_validation.md` sha256 `b1c886ba…` unchanged, uncommitted |

## Components

| Component | Restart path | Now |
|---|---|---|
| Redis | **Automatic** (Docker after sign-in) | PONG |
| Opportunity supervisor + ingestion, discovery, evaluators ×4, notifier, outcomes, reporting, promotion, Sentinel | **Manual**, 2026-10-15 19:42–19:43Z | All UP. Heartbeats ≤ 12 s. Last ingestion cycle 08:05:29Z (PREMARKET). Last discovery scan 08:02:37Z. 0 errors since restore |
| Ops supervisor, Original, Intelligence, :8787, V2 companion, checkpoint daemon | **Manual**, 2026-10-16 07:50Z (owner-authorised one-time `--force`, §3 of report) | V2 tick 7, CURRENT, hb 08:06:03Z. Intelligence cycle 5, FRESH (08:04:11Z). :8787 HTTP 200 |
| VR tracker | **Manual**, 2026-10-15 19:45Z | One chain. hb 08:05:34Z |
| V2 forward loop | **Manual**, 2026-10-15 19:46Z | One chain, `sleep-to-next-slot` |
| DTU collector, ERM | Not restored (by design) | No process; ERM/UniverseVerify tasks have no next run |

- **Ownership:** exactly one process per logical component (venv launcher/child counted once). Stop flags: 0. Start
  lock owner = live V2 companion.
- **Positions:** V2 0 positions / 0 pending intents. VR 0 OPEN.
- **Notifications:**
  - Intelligence AMBIGUOUS 3 (preserved, not resent); PENDING 2 (new DIGEST rows, normal).
  - Release/ops: FAILED 1 / EXPIRED 2 (historical).
  - Duplicate dedup keys: 0 in every outbox.

## V2 forward

| Day | State |
|---|---|
| 2026-10-15 | **MISSED.** Machine at sign-in screen at 06:00Z; loop absent. No record; not rerun |
| 2026-10-16 | **SUCCESS.** Run `20261016T060000Z-2f704a`, `forward_runner v1.2`. Scheduled 06:00Z, start 06:00:00.35Z, end 06:04:57.43Z, deadline 07:30Z. Filings ≤ 10-15, prices ≤ 10-15. 5/5 stages exit 0, 0 retries, empty stderr. EDGAR `EDGAR_CLOSURES_V1` `a03cdf54…`, SEC-closed [10-12]. Artifact validated, problems [] |

- **Next slot:** 2026-10-17 06:00Z (07:00 BST). One logical loop; end 2026-10-31 inclusive.
- **Dashboard completeness:** expect 10-15 to show missing, not failed. Its absence is a missed slot with no record,
  not a failed run.

## Universe and review delivery

- **Membership:** 10-16 published: DTU_V3_TOP600 `2849da5594f272db`, **Core 600**, event-eligible 0, reconciled.
- **Fetch scope:** 603 = 564 Core + 39 operator-added (V2 scope; 3 are V2-only), protected 0.
  - The first premarket DTU cycle (08:02:28Z) briefly had 606 (protected additions). Discovery's 08:02:37Z scan used
    that cycle.
  - **Admissible = 600** throughout.
- **Sentinel:** reads the same snapshot (summary `2026-10-16@2026-10-15#2849da5594f272db`), DRY_RUN, 0 failures.
- **Acquisition:** recent acquisition failures 0.
- **Review delivery:**
  - Enabled: RESEARCH_REVIEW, not paused, boundary unchanged. Loaded promotion version `de24a9891031`
    (RESEARCH_REVIEW_COMPACT_V2).
  - Tracing: last 15 sends API_ACCEPTED with message ids.
  - No sends yet today. Premarket only; the regular session opens 13:30Z.

## VR endpoint readiness

- **Tracker:** running, one owner, `--until 2026-10-16`.
- **Entries:** both arms BLOCKED. 0 trades created after the 2026-10-07 11:25:41Z boundary.
- **Positions:** 0 OPEN. 1 legacy `PAPER_ENTRY_PENDING` (NVCT, unchanged).
- **Expected timeline:**
  - Last collection today about 20:21Z.
  - Exit 2026-10-17 about 00:00–00:01Z.
  - Closeout not before 00:05Z, and only with owner authorisation.

## PDM

- **Integrity:** `verify_integrity` OK (6 implementation hashes + calendar).
- **Schedule:** 1 task with triggers 00:15 / 06:30 London. Next run 2026-10-19 23:15Z. Never run.
- **No early collection:** no study store.
- **Conditions:** Interactive principal and AC both satisfied now.

## Remaining actions, by urgency

1. **2026-10-17 00:05Z onward.** Confirm the VR process exited (endpoint runbook §3). The §4 closeout needs owner
   authorisation.
2. **Before 2026-10-19 23:15Z (PDM) and each 06:00Z forward slot.** Owner decision on Windows Update restart
   behaviour (active hours 07:00–01:00). An overnight restart leaves the machine at sign-in, which blocks the
   Interactive PDM task and every loop.
3. **Before any future ops/V2 restart.** Since f78fb34 the release-ancestry preflight is NO_GO. The `--force`
   authorisation covered one start only, so re-freeze or authorise again.
4. **Today 13:30Z+.** Natural confirmation: the first regular-session review alert carries a delivery trace. No test
   send.
5. **No action.** The 10-15 forward observation stays MISSED. The 3 Intelligence AMBIGUOUS rows stay for owner
   disposition.
