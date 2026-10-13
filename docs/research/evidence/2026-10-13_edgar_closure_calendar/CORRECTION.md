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

**Run once at 2026-10-13 20:31:20–20:31:30Z, after R5**, by `sec_diagnostic.py`.
- Crawler identification and transport (the User-Agent value is not recorded).
- **One attempt per URL, no retries, 5 requests.** Full record: `SEC_DIAGNOSTIC.json`.

| URL | Status | Server / type | Body | Class |
|---|---|---|---|---|
| EDGAR calendar page | 200 | nginx, text/html | 67,436 B, sha256 `a50a1290…`, archived `calendar_2026-10-13T203120Z.html` | OK |
| EDGAR News & Announcements | 200 | nginx, text/html | 159,419 B, `07da672d…`, archived `announcements_2026-10-13T203123Z.html` | OK |
| Accessing EDGAR Data | 200 | nginx, text/html | 80,349 B, `9a4d3cd9…`, archived `accessing_edgar_data_2026-10-13T203125Z.html` | OK |
| `daily-index/2026/QTR4/form.20261012.idx` (closure) | **403** | Apache, `application/xml`, `Content-Encoding: gzip`, `x-amz-request-id` present, `no-cache` | 240 B (gzip), `2941e8fe…`; not stored | UNCLASSIFIED* |
| `daily-index/2026/QTR4/form.20261009.idx` (known good) | **200** | Apache, `application/octet-stream`, Last-Modified 2026-10-10 02:01:37 GMT | 626,694 B, `385793e7…`; not stored or parsed | OK |

\* The error body was gzip-encoded and the classifier inspected the raw bytes, so it could not read the text. No
further request was made to re-read it.

**The archived pages confirm:**
- The calendar page contains "October 12", "Columbus Day" and "will not receive, process, or accept filings".
- The announcements page's only closure notice is "EDGAR Will Be Closed December 24, 2025 Through December 26, 2025".

**What this supports:**
- The same identification and transport retrieve a normal-day Archives daily index (200) and SEC web pages (200).
- Only the closure-date index is refused.
- The refusal is a small XML error from the Archives' object-store-style backend (`x-amz-request-id`). That fits how
  such backends commonly answer a request for a non-existent object when listing is not permitted.

**What remains unknown:**
- The exact reason for the 403. It was not decoded, and SEC documents no meaning for it.
- This evidence does **not** prove the 403 means "file absent".
- The correction does not depend on it. It relies only on the official closure calendar, and a 403 on any **expected**
  filing day remains a failure.

## Rollback

1. `git revert` the correction commit and fast-forward live **before** a 06:00Z slot. The next run then loads the
   previous crawler and will again request the 2026-10-12 index, so expect the previous failure.
2. Keep `docs/research/protocols/edgar_calendar/`, this evidence, every `forward_runs/*` record and every
   `results/v2_validation/edgar/*` file. Nothing is deleted.

## Archive reproducibility (2026-10-13 22:2xZ)

The recorded `body_sha256` values in `SEC_DIAGNOSTIC.json` are the **original fetched bytes**. They are unchanged.

| Archive | Recorded sha256 / bytes | Original file (worktree) | Committed blob (`827fcda`) | Live checkout before fix |
|---|---|---|---|---|
| `calendar_2026-10-13T203120Z.html` | `a50a1290…` / 67,436 | match (LF only) | match | **mismatch**: 68,877 B, CR added to 1,441 lines |
| `announcements_2026-10-13T203123Z.html` | `07da672d…` / 159,419 | match | match | **mismatch**: 161,052 B, CR added to 1,633 lines |
| `accessing_edgar_data_2026-10-13T203125Z.html` | `9a4d3cd9…` / 80,349 | match | match | **mismatch**: 82,025 B, CR added to 1,676 lines |

**Cause.** `core.autocrlf=true` converted LF to CRLF on checkout. The committed blobs were always byte-exact.

**Correction.**
- A narrowly scoped `.gitattributes` rule,
  `docs/research/evidence/2026-10-13_edgar_closure_calendar/*.html -text`, so these three archives are never
  converted.
- The live working copies of those three files were restored from their (unchanged) blobs.

**Not changed:** no archive content, no recorded hash, no SEC request, and nothing in the calendar, runner, protocol or
run records.

**Verified:** see `ARCHIVE_VERIFICATION.json`. A fresh temporary clone with `core.autocrlf=true` reproduces all three
recorded hashes.
