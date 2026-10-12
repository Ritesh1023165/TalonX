# V2@1 forward-study completeness reconciliation (2026-10-12)

## Cause of the omitted date

- The dashboard's "incomplete days in view" (`talonx_paperperf.forward_status.view`, `d200b52`) took only the **last
  7 run-record files** (`[-days:]`). There are 8 files, 2026-10-05 to 2026-10-12, so the reconstructed 2026-10-05
  PARTIAL record (the oldest) fell outside the window.
- The view had no notion of the registered schedule, so the record-less legacy days before 2026-10-05 were never
  considered at all.
- The 2026-10-05 record itself was classified correctly: terminal PARTIAL, `reconstructed_from_log`. **The omission
  was a code defect, not a wording issue.**

## Authoritative expected schedule

From `docs/research/evidence/2026-09-30_v2_validation/forward_daily.sh` (registration) and `forward_daily_v2.sh`
(2026-10-05 reliability loop, same schedule and stop date):

- **Start.** The loop waits for the Jul–Sep EDGAR backfill marker (`edgar/20260929.done`), then runs a **start-up cycle
  immediately**. It ran on **2026-09-30**, `cycle_done` 15:02:15Z, so this is not a 06:00Z slot.
- **Daily.** **06:00Z** (07:00 BST / 07:00 GMT after 2026-10-25) on **every calendar day**. There is no weekday filter,
  so weekends are required.
- **End.** The loop continues while `date.today() <= 2026-10-31`, so the stop date is **inclusive**: the last slot is
  2026-10-31 06:00Z.
- **Registered slots: 32** (2026-09-30 start-up + 2026-10-01 … 2026-10-31).
- **Documented interruptions:** none skipped a slot. The 2026-10-05 loop replacement happened at 06:40Z, after that
  day's cycle, and the 2026-10-10 weekend assessment kept the loop running.
- The live V2 companion campaign (V2-PAPER-RC1) is a separate study and its dates were not used.

## Reconciliation (as of 2026-10-12 19:52Z, `RECONCILIATION.json`)

**Evidence used** (status only):
- the run record `forward_runs/<day>.json`, read;
- structured loop markers in `forward.log`: only whole-line JSON objects made entirely of operational keys; every other
  line is dropped unparsed;
- the output file's **existence and mtime** (`stat`). Outputs are never opened, and an output's existence is never
  proof.

| Day | Expected | Evidence and provenance | Recorded | Derived | Validation recorded | Notes |
|---|---|---|---|---|---|---|
| 2026-09-30 Wed | start-up cycle | legacy `cycle_done` 15:02:15Z; output written during the cycle | — | **UNVERIFIED** | none | legacy loop recorded no exit status or validation |
| 2026-10-01 Thu | 06:00Z | legacy `cycle_done` 06:04:01Z; output written during the cycle | — | **UNVERIFIED** | none | as above |
| 2026-10-02 Fri | 06:00Z | legacy `cycle_done` 06:05:29Z; output written during the cycle | — | **UNVERIFIED** | none | as above |
| 2026-10-03 Sat | 06:00Z | legacy `cycle_done` 06:08:38Z; output written during the cycle | — | **UNVERIFIED** | none | as above |
| 2026-10-04 Sun | 06:00Z | legacy `cycle_done` 06:02:06Z; output written during the cycle | — | **UNVERIFIED** | none | as above |
| 2026-10-05 Mon | 06:00Z | run record **RECONSTRUCTED from log** (written by the 2026-10-05 fix); legacy `cycle_done` 06:01:02Z; no output | PARTIAL | **PARTIAL** | `validated: false` (`NOT_PRODUCED`) | prices failed, `TLS_HANDSHAKE_TIMEOUT`; reconstructed provenance preserved |
| 2026-10-06 – 10-10 | 06:00Z | runner records; loop `cycle_end` SUCCESS/exit 0; output present | SUCCESS | **SUCCESS** | `validated: true` | 10-10 is a Saturday |
| 2026-10-11 Sun | 06:00Z | runner record; loop `cycle_end` RUNNING/exit 1; orphaned temp record (not read); no output | RUNNING | **ABANDONED** | none | process 772 verified absent, deadline 07:30Z passed |
| 2026-10-12 Mon | 06:00Z | runner record; loop `cycle_end` SUCCESS/exit 0; output present | SUCCESS | **SUCCESS** | `validated: true` | |
| 2026-10-13 – 10-31 | 06:00Z | — | — | **NOT_YET_DUE** | — | 19 slots, weekends included |

**Counts** (32 slots, one state per slot):

| State | Slots | Days |
|---|---|---|
| Success | **6** | |
| Incomplete or missing | **2** | 10-05 PARTIAL, 10-11 ABANDONED |
| Unverified (legacy) | **5** | 09-30 to 10-04 |
| Running / due | 0 | |
| Not yet due | **19** | |
| Unreadable / unknown | 0 | |

**Conflicts:** none found.

## Legacy evidence limitations

- `forward_daily.sh` chained the stages with `&&` and wrote `cycle_done` **unconditionally**. It recorded no exit status
  and no artifact validation.
- For 2026-09-30 to 10-04, an output file whose mtime falls inside each cycle shows that the final stage wrote
  *something*. Without opening it (not permitted) and without a recorded validation, completion cannot be established,
  so these days are **UNVERIFIED**, not SUCCESS and not failed.
- Their status would only change if some separately recorded operational validation existed. None was found.

## Correction (dashboard only)

**What changed** (`talonx_paperperf/forward_status.py`):
- `completeness()` builds slots from the registered schedule over the whole period.
- Each slot gets one state, with provenance, its listed evidence and any conflicts. A conflict is listed, and the less
  favourable record is never overridden.
- `DUE_AWAITING_RECORD` is used inside the 90-minute run budget. `MISSING` is used only for an elapsed slot with no
  evidence, and future slots are always `NOT_YET_DUE`.

**Dashboard** (Validation tab panel):
- New study-completeness line: period, as-of time, and the six counts.
- An affected-dates table: day, state, provenance, reason, conflicts.
- The bounded "recent run records" table is kept.
- Current health (latest run only) stays separate.
- The misleading `incomplete_days_in_view` was removed.

**Reads:** still rate-limited by the existing 60 s `view_cached`. Short reads only: about 30 small records plus a
25 KB log, at most once per minute. No new polling was added.

## Not changed

Historical records, the runner, the schedule, research rules, the end date, PDM, VR, DTU, ERM and review delivery. No
study day was run, retried or backfilled, and no output was opened.
