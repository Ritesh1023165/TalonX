# ERM nominee validation (window B): closeout of the blocked attempt

**Outcome: `ACQUISITION_BLOCKED` at the first S&P coverage check (S0). No strategy result exists.**

This is neither a strategy FAIL nor INCONCLUSIVE. No outcome was computed, and no statistical verdict was reached.

**Candidate status: `PARKED_DATA_COVERAGE_BLOCK`.** The hypothesis is `GAP_UP_10|SHORT|H10|L1_V1` (config cell
`GAP_UP_10|SHORT|H10|L1`), window B 2024-01-02..2026-09-30, reference date R = 2026-10-06, release `b98689a9…`.

## Timeline

| Event | UTC | Europe/London (BST) |
|---|---|---|
| Scheduled trigger | 2026-10-06 20:35:00 | 21:35:00 |
| Launcher precheck (lock verify PASS) | 20:35:02.457 | 21:35:02 |
| Locked command started | 20:35:02.622 | 21:35:02 |
| Execution admitted (attempt ledger `EXECUTION_STARTED`) | 20:35:04.151 | 21:35:04 |
| S&P listing retrieved | 20:35:04.435 | 21:35:04 |
| S&P membership file retrieved | 20:35:06.168 | 21:35:06 |
| Blocked (attempt ledger `EXECUTION_FAILED`, run record `INCOMPLETE_ACQUIRE`) | 20:35:06.231 | 21:35:06 |
| Launcher ended (exit 1) | 20:35:06.395 | 21:35:06 |
| Observer: started / terminal observation / exited 0 | 20:25:01 / 20:40:01 / 20:40 | 21:25 / 21:40 / 21:40 |

## Coverage block

**Exact reason recorded by the locked acquirer:**

> "last membership row 2026-08-18 < required coverage 2026-09-30: membership after 2026-08-18 unknown"

The run stopped at stage `S0_SP500_COVERAGE`, state `INSUFFICIENT_HISTORICAL_COVERAGE`.

**Source:**

| Field | Value |
|---|---|
| Repository | fja05680/sp500 |
| File | `S&P 500 Historical Components & Changes (Updated).csv` |
| Listing entry | git blob `656b033be9418db272f1903f4f8e79a2a8664e6a`, size 5,530,907 B |
| Retrieved file | 5,530,907 B, sha256 `36326709d46d6cd25834de5df457b16f5f96fad3a06b9beac28f7b88aa0b0d54` |

The downloaded bytes matched the listing's git blob sha. The file passed the locked format checks (header, strictly
increasing ISO dates, full snapshots) and the response-scope check (no row after R + 1 day). Only the coverage rule
failed.

**What the block does and does not mean:**

- A last snapshot dated 2026-08-18 does **not** show that membership changed afterwards.
- It does **not** establish membership through 2026-09-30 under the locked rule. That rule requires a full snapshot
  dated on or after the window end, and membership is never assumed unchanged.
- No source-update date is known or claimed. The source publishes no as-of date or schedule; its README gives only an
  informal cadence.

## Requests and exposure

| # | Request | Category | Result | Attempts | Body | sha256 (body) |
|---|---|---|---|---|---|---|
| 1 | `api.github.com/repos/fja05680/sp500/contents` | `sp500_pit` | HTTP 200, RETRIEVED_USABLE | 1 | 9,854 B | `3e33b93c99c8f3b7d99e35a4b4ed445f0c876db3274a47d69cc79e5731e0280d` (identical to the 2026-10-05 metadata check) |
| 2 | `raw.githubusercontent.com/.../S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv` | `sp500_pit` | HTTP 200, RETRIEVED_USABLE | 1 | 5,530,907 B | `36326709d46d6cd25834de5df457b16f5f96fad3a06b9beac28f7b88aa0b0d54` |

- Both requests succeeded first time. There were no transport failures and no retries.
- **Actual exposure:** S&P 500 point-in-time membership metadata only (the listing and the membership file, last row
  2026-08-18). This means the release was **partly used**.
- **Not requested:** no SEC request (submissions, filing headers, Form 3/4/5, master.idx, reference files), no Alpaca
  request (asset list, corporate actions, renames, ETF dividends) and no bars. No outcome data was acquired.
- **Attempts:** acquisition attempts **1**, scoring attempts **0**. The outcome stage was never entered
  (`outcome_exposure: false`).
- **Not produced:** `obs.csv`, `gates.json`, `diagnostics.json`, `manifest.csv`, `report.md` and `RUN_COMPLETE.json`
  do not exist. No completion marker was created.

**Raw archive (local only, outside Git).** These stay in the gitignored `results/` tree of worktree
`C:\workspace\TalonX-erm-val`:

| File | Compressed | sha256 (gz file) | Body sha256 |
|---|---|---|---|
| `results/erm_nominee_validation/validation_B/archive/sp500/raw.csv.gz` | 44,258 B | `784536bda17d2285cb7e9435081d0a4bf3492c53ef0b0f4855617ffeb46bcdcd` | `36326709…` |
| `results/erm_nominee_validation/validation_B/archive/sp500/listing.json.gz` | 1,251 B | `0fb850c31dbd9bd125e8ac610b98ea700bedd62fb98b98e3c8c79115054d2fef` | `3e33b93c…` |

## Integrity

| Check | Result |
|---|---|
| Run record bindings | config `d8ad21af…`, implementation `ce924d90…`, protocol `7e71fabc…`, protocol lock `55a31d24…`, implementation lock `1584e460…`, all equal to the locked values |
| `python -m research.erm_nominee_validation.lock verify` | PASS before the run (`go_B/lock_verify_prerun.json`) and at closeout |
| Tracked working-tree changes | none; no executable drift |
| Frozen ERM guard state | `b512322d…`, unchanged |
| Original records | not altered; counters not reset; no completion marker created |

## Execution left inactive

- **Validation task** `ERM_NOMINEE_VALIDATION_B_GO_2026-10-06`: a one-off trigger that ran once (last result 1), with
  no next run and a trigger end boundary of 2026-10-06 23:30Z. Its launcher is one-shot (`go_B/LAUNCHED.lock`
  exists), so a re-trigger would be refused.
- **Observer task** `ERM_NOMINEE_VALIDATION_B_OBSERVER_2026-10-06`: ran once (exit 0), no next run, one-shot
  (`OBSERVER.lock`).
- No validation or observer process is running. Both definitions and all their evidence are kept.

**Remaining retry: intentionally NOT used.** The locked D6a policy would admit one acquisition retry with a recorded
reason (`retry_allowed: true`). No evidence establishes that the coverage gap is recoverable inside this release, so
none was attempted. Repeated source requests and polling for a newer file were not made.

**Authorisation expiry (from the locked implementation).** The release journal keeps its state `ACTIVE`, because the
reviewed mechanism has no expiry transition and the journal is not edited by hand. The locked code bounds its use:

| Mechanism | Rule | Effect |
|---|---|---|
| `attempts.AttemptLedger.admit` | refuses every new execution when the UTC date is later than R + `RETRIEVAL_WINDOW_DAYS` (1) | `REFERENCE_WINDOW_EXPIRED` |
| `acquirer.get` | refuses every broad-endpoint request on the same condition | `RESUME_AFTER_REFERENCE_WINDOW` |

The S&P request (S0) is a broad endpoint and is the first request of any execution. No execution can therefore be
admitted or acquire anything from **2026-10-08T00:00:00Z (2026-10-08 01:00 BST)**. Until then, Alpaca and SEC requests
remain barred 13:00–20:30Z by R5, and no trigger exists.

**Attempt ledger.** `results/erm_nominee_validation/ATTEMPT_LEDGER.jsonl` (key `GAP_UP_10|SHORT|H10|L1|B`) is
preserved and must carry over to any future release. It cannot be reset by a new run ID or directory.

**Not done:** no retry, source switch, window change, guard expansion, scoring, new GO, change to the live system, or
change to locked code, protocol or configuration. A future data-source amendment needs a separate bounded instruction.
