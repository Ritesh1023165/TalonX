# V2@1 forward run 2026-10-13: verification (read-only)

**Observed:** 2026-10-13 13:04–13:06Z (14:04–14:06 BST).

**Verdict: `RUN_FAILED_EDGAR_HTTP_403`.**
- The study-day observation failed at its first stage.
- Status persistence on runner v1.1 worked correctly in live operation: there was no stuck RUNNING record, no
  persistence retry and no diagnostic.
- **The reliability task is not closed**, because the run did not succeed. It needs an owner decision on the blocker
  below.

## Today's run (status record `forward_runs/2026-10-13.json`, status fields only)

| Field | Value |
|---|---|
| Run id / runner | `20261013T060000Z-e83f58` / `forward_runner v1.1 (2026-10-12: bounded status-persistence retries, fail-closed boundaries)` |
| Scheduled / started / ended | 06:00:00Z / 06:00:00.305Z / 06:00:36.629Z |
| Deadline | 07:30:00.305Z |
| Cutoffs | as_of 2026-10-13; filings ≤ 2026-10-12; prices ≤ 2026-10-12 |
| Recorded state | **FAILED**; `failed_stage=edgar_crawl`, `error_class=EDGAR_FAILED:EXHAUSTED:HTTP_403` |
| Stages | `edgar_crawl` FAILED, exit 1 (06:00:00.307–06:00:36.628Z); `episodes`, `prices`, `evaluate`, `forward` **NOT_RUN** |
| Recorded artifact validation | `validated: false` (`NOT_PRODUCED_BY_THIS_RUN`) |
| Persistence | `persistence_retries` absent (0); no `2026-10-13.*.persistence_failure.*.json` |
| Cause (recorded) | `/Archives/edgar/daily-index/2026/QTR4/form.20261012.idx: HTTP_403 after 4 attempts`. `_crawl_status.json`: this run's id, state FAILED, cause `EXHAUSTED:HTTP_403`, `day_interrupted 2026-10-12`. |

No outcome stage ran. No output was opened, and no research-statistics log line was read.

## Blocker and assessment

**The 403.** The crawler (`form4_edgar.Client`) treats HTTP 403 as a throttle: 4 attempts with ×5 backoff, then
`EdgarUnavailable`. **Only a 404** is accepted as a missing daily index (holiday or not yet published).

**Context that fits but does not prove a holiday-index explanation:**
- **2026-10-12 was the second Monday of October** (Columbus Day / Indigenous Peoples' Day), a US federal holiday on
  which EDGAR publishes no daily index.
- SEC access in general works: Intelligence polled 39/39 issuers via data.sec.gov at 13:02Z today with 0 failures.
- The previous runs' crawls (through 2026-10-11) recorded no missing-index days. There is no earlier live evidence of
  how SEC answers for a missing *weekday* index.

**Unverified alternatives:** a path-specific access block, or a User-Agent or rate refusal. No request was made to SEC
in this read-only task.

**Forward impact (high, time-critical):**
- The crawl walks every weekday from 2026-09-30 and skips only days with a `.done` marker. `20261012.done` does not
  exist.
- The **2026-10-14 06:00Z run will request `form.20261012.idx` again**. If SEC keeps returning 403 for it, **every
  remaining run (10-14 … 10-31, 18 slots) will FAIL at `edgar_crawl`**, with no observation and later stages not run.

**Bounded proposed next action** (each step needs owner authorisation; none was taken):
1. **Before 2026-10-14 06:00Z,** authorise one diagnostic HEAD/GET, with the crawler's declared User-Agent, for
   `form.20261012.idx` and a known-good index such as `form.20261009.idx`. This separates "holiday index absent but
   served as 403" from "access refused".
2. **If the index is absent on a holiday:** decide, as a pre-registered research-infrastructure rule, whether a 403 on
   a federal-holiday daily index is treated like the existing 404 "index not found" policy (for example, via an
   explicit EDGAR holiday calendar).
   - This changes the acquisition rule, so it must be reviewed, versioned and tested before activation.
   - Without it, the remaining runs fail as described.
3. **If access is refused:** investigate User-Agent and rate compliance; do not change the study.

Do not rerun or backfill 2026-10-13 in any case.

## Dashboard agreement (live `:8787` Validation panel, generated 13:05:40Z)

| Item | Value |
|---|---|
| Current health (latest run only) | **ATTENTION (FAILED)** |
| Completeness | 2026-09-30 .. 2026-10-31 (inclusive), 32 slots |
| Success | **6** (10-06 … 10-10, 10-12) |
| Incomplete or missing | **3**: 10-05 PARTIAL (RECONSTRUCTED), 10-11 ABANDONED, **10-13 FAILED** |
| Unverified (legacy) | **5** (09-30 … 10-04) |
| Not yet due | **18** (10-14 … 10-31) |
| Running/due, unreadable | 0, 0 |
| Total | 32 |

This matches the run record. Historical completeness and current health are shown separately.

## Reliability evidence level

**Normal scheduled operation verified on v1.1.**
- Every status write (start, the pre-stage write, the failure record and the end record) persisted on the first
  attempt.
- The failure was recorded truthfully and terminally: FAILED, failed stage, error class, later stages NOT_RUN, and
  `ended_utc` set. It did not leave a dead RUNNING record.

**Contention recovery** (replace retries) **remains fixture-tested only**: no retry occurred live.

## Continuity

- **V2 forward:** exactly one logical loop: 3344 → 7184 → 24096 → 11972 → sleeper 7620/19912 (`sleep-to-next-slot`).
  - Next run **2026-10-14 06:00Z (07:00 BST)**; end 2026-10-31 inclusive (loop script `f295f6b0…`, unchanged).
  - No Task Scheduler trigger exists for the forward study: no duplicate trigger.
- **PDM:** `verify_integrity` = []. Task `\TalonX\PDM_V1_Collector` is Ready with two triggers, 2026-10-20 00:15 ..
  2026-11-18 12:00 and 2026-10-20 06:30 .. 2026-11-17 12:00 (London).
- **VR:** entries BLOCKED (wrapper running until 2026-10-16).
- **DTU / ERM:** no DTU or ERM process; the ERM tasks have no next run.
- **Review alerts:** `paused=false`, `RESEARCH_REVIEW`, boundary 2026-10-07 22:42:55Z; promotion UP, v `de24a9891031`;
  Opportunity overall HEALTHY.
- **Historical records:** unchanged (2026-10-05 `900186b3…`, 2026-10-11 `0f2ccf4f…`).

## Confirmation

- Outcomes stayed unread.
- Nothing was restarted, rerun, backfilled, repaired or changed operationally.
- No request was made to SEC, and no message was sent.
- Only this report is committed.
