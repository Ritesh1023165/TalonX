# 2026-10-14 natural run: EDGAR closure correction verified end to end

**Observed:** 2026-10-14 09:42–09:43Z (10:42–10:43 BST), read-only, using `NEXT_RUN_VERIFICATION.md`.

**Verdict: `VERIFIED_END_TO_END`.** The scheduled run loaded runner v1.2 and calendar `EDGAR_CLOSURES_V1`, recorded
2026-10-12 as `SEC_CLOSED` without requesting its index, acquired 2026-10-13 under the unchanged rules, and finished
SUCCESS with a runner-validated artifact.

## Run record `forward_runs/2026-10-14.json` (status fields only)

| Field | Value |
|---|---|
| Run id / runner | `20261014T060000Z-737d13` / `forward_runner v1.2 (2026-10-13: …; v1.1 2026-10-12: …)` |
| Scheduled / started / ended | 06:00:00Z / 06:00:00.361Z / 06:04:58.706Z |
| Deadline | 07:30:00.361Z |
| Cutoffs | as_of 2026-10-14; filings ≤ 2026-10-13; prices ≤ 2026-10-13 |
| State | **SUCCESS**; no failed stage or error class |
| Stages (all exit 0) | `edgar_crawl` 06:00:00.36–06:02:13.62; `episodes` –06:02:50.65; `prices` –06:03:54.07; `evaluate` –06:04:58.46; `forward` –06:04:58.70 |
| Artifact | `validated: true`, no problems (as recorded by the runner; no output opened) |
| Calendar | `EDGAR_CLOSURES_V1`, sha256 `a03cdf54c3b448d77eebbc237d5eb3a7cdc6d0f41203f5109538f8bf992949e3`, years [2026] |
| Persistence | 0 retries; no `2026-10-14.*.persistence_failure.*.json` |

## Closure handling (crawl manifest `edgar/_crawl_status.json`, operational fields)

**Manifest summary:**
- `run_id` matches the run.
- `state COMPLETE`, `COMPLETE_WITH_EVENTS`, window 2026-09-30 … 2026-10-13.
- `days_sec_closed ["2026-10-12"]`; `days_completed_this_run ["2026-10-13"]`; `days_index_not_found []`; 8 days already
  done.

**No index request for 2026-10-12:**
- `requests 523` = 1 daily index (2026-10-13) + 522 filings fetched (`filings_not_found 0`).
- A 10-12 index request would have added at least one request. A 403 would also have added up to 3 retries and failed
  the crawl.
- Request-level URLs are not logged; this conclusion rests on the count and the classification.

**No fake data:** `edgar/20261012.done` and `edgar/20261012.jsonl` are absent. `20261013.done` and `20261013.jsonl` were
written at 06:02:13Z by the normal acquisition path.

## Dashboard (`:8787` Validation panel, generated 09:43:35Z)

| Item | Value |
|---|---|
| Current health | **HEALTHY** (latest 2026-10-14 SUCCESS, validated, 0 retries) |
| Completeness | 2026-09-30 … 2026-10-31 (inclusive), **32** slots |
| Success | **7** |
| Incomplete | **3**: 10-05 PARTIAL (reconstructed), 10-11 ABANDONED, 10-13 FAILED |
| Unverified (legacy) | **5** (09-30 … 10-04) |
| Not yet due | **17** |
| Unreadable / running | 0 / 0 |
| Next run | **2026-10-15 06:00Z**; one loop chain: 24096 → 26264 → sleeper 27268/5632 |

## Unchanged

- Historical records 2026-10-13 `2e3e4bfc…`, 2026-10-11 `0f2ccf4f…` and 2026-10-05 `900186b3…` are byte-identical;
  10-13 stays FAILED.
- No outcome was opened, no data was fetched, and nothing was restarted, rerun or backfilled.
