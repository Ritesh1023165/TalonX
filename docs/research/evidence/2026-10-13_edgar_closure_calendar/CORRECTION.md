# EDGAR closure-calendar acquisition correction for the V2@1 forward crawler (2026-10-13)

**Classification: `DATA_FIX`** (repository `CLASSIFICATIONS`, `talonx_opportunity/runtime.py`). It is an
acquisition-input correction: it affects provider coverage and detection inputs, and changes no strategy, cutoff,
cost, stage order, schedule or endpoint. The forward tracker is not a runtime-managed Opportunity component, so
`declare-change` does not apply. This record is the declaration.

## Incident

- The 2026-10-13 run failed in `edgar_crawl`: `form.20261012.idx` returned HTTP 403 on all 4 attempts. No later stage
  ran.
- That day **remains FAILED**; its status, logs and attempt evidence are untouched.
- The crawler requested the 2026-10-12 index because it treated every weekday as an expected filing day.

## Official evidence (SEC; not derived from the XNYS calendar or a generic holiday library)

**EDGAR calendar** (`/submit-filings/filer-support-resources/edgar-calendar`).
- It states: *"The EDGAR system will not receive, process, or accept filings in observance of the following federal
  holidays."*
- It covers **2026 only** and lists **Monday 2026-10-12 (Columbus Day)**. The full 2026 list: 01-01, 01-19, 02-16,
  05-25, 06-19, 07-03, 09-07, 10-12, 11-11, 11-26, 12-25.

**EDGAR News & Announcements** (checked 2026-10-13; announcements shown 2025-07-28 … 2026-10-07).
- There is no 2026 exceptional closure.
- The only exceptional closure listed is 2025-12-24 … 12-26, which is outside the supported years.

**Accessing EDGAR Data:**
- *"Indexes incorporating the current business day's filings are updated nightly starting about 10:00 p.m., ET; the
  process is usually completed within a few hours."*
- Fair access: declare a User-Agent; at most 10 requests/s.

**Archive.** The pages were first read on 2026-10-13 ~14:50Z via a web-fetch tool, not from this machine. Raw captures
from this machine, with sha256, are taken after R5 by `sec_diagnostic.py` (see *Diagnostics*).

## Mechanism

**Calendar.** `docs/research/protocols/edgar_calendar/EDGAR_CLOSURES_V1.json`, `calendar_id EDGAR_CLOSURES_V1`, sha256
(LF-normalised) **`a03cdf54c3b448d77eebbc237d5eb3a7cdc6d0f41203f5109538f8bf992949e3`**. Supported years: **2026**.
Loaded once per crawl; there is no online lookup.

**Classes** (`talonx_paperperf/edgar_calendar.py`):

| Class | Meaning | Crawler behaviour |
|---|---|---|
| `WEEKEND` | Saturday or Sunday | Unchanged |
| `SEC_CLOSED` | Documented closure (scheduled or exceptional) | Recorded in `days_sec_closed`. **No index request; no `.jsonl`; no `.done`.** Not counted as fetched, empty or `INDEX_NOT_FOUND`. |
| `EXPECTED_FILING_DAY` | Any other weekday in a supported year | **Unchanged.** The index is required, HTTP 403 remains a failure (4 attempts, ×5 backoff), the 404 policy is unchanged, and the checkpoint/resume and deadline rules are unchanged. |
| `UNKNOWN_COVERAGE` | A weekday in an unsupported year | The crawl FAILS **before any request** (`CALENDAR_COVERAGE_UNKNOWN`) |

**Checks before any request:**
- An invalid calendar fails with `CALENDAR_INVALID`.
- Existing `.done` or `.jsonl` data on a documented closure fails with `CALENDAR_CONFLICT`. The data is preserved
  untouched and must be reconciled.

**Provenance:** `_crawl_status.json` and the run record (`stages[edgar_crawl].acquisition`) carry `calendar`
(`calendar_id`, `sha256`, `supported_years`, `path`) and `days_sec_closed`. Runner version: `forward_runner v1.2`.

**Unchanged:**
- The tracker still runs on **every registered calendar day**, 2026-09-30 … 2026-10-31 inclusive. Only the set of
  expected index dates changed.
- Info and price cutoffs, stage order, strategy, costs, the schedule and the endpoint.
- No day is marked done manually, no index is faked, and no archived data is deleted or overwritten.

**Coverage.** The crawl window `2026-09-30 … <UTC yesterday>` is entirely within 2026 through the 2026-10-31 run (end
2026-10-30). Inside that window the only documented closure is 2026-10-12.

**Separate gap, not changed here.** An expected filing day whose index is 404 is still treated as "not found; retried
later", and an unpublished same-day index is not treated as empty.

## Deployment boundary

- The code is fast-forwarded into the live checkout while no forward stage is active.
- The sleeping loop (`forward_daily_v2.sh` → `forward_runner sleep-to-next-slot`) starts a **fresh**
  `forward_runner run`, and that starts a fresh `form4_edgar` process. So the **2026-10-14 06:00Z** run is the first
  run on the corrected code and calendar. The loop is not restarted, and no catch-up runs.
- Earlier records (2026-10-13 FAILED, 2026-10-11 ABANDONED, 2026-10-05 PARTIAL) are unchanged.

## Diagnostics

PENDING: see `SEC_DIAGNOSTIC.json` once captured, at or after 20:30Z (R5 ends at 16:30 ET).

## Rollback

1. `git revert` the correction commit and fast-forward live **before** a 06:00Z slot. The next run then loads the
   previous crawler and will again request the 2026-10-12 index, so expect the previous failure.
2. Keep `docs/research/protocols/edgar_calendar/`, this evidence, every `forward_runs/*` record and every
   `results/v2_validation/edgar/*` file. Nothing is deleted.
