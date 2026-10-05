# V2 forward tracker reliability fix and verifier v3 (2026-10-05)

## Incident

On 2026-10-05 the V2@1 shadow forward cycle started at 06:00:00Z.

| Stage | Result |
|---|---|
| `edgar_crawl` | completed |
| `episodes` | completed |
| `prices` | **failed** on `URLError: <urlopen error _ssl.c:993: The handshake operation timed out>` |
| `evaluate`, `forward` | never ran |

The loop still logged `{"cycle_done": "2026-10-05T06:01:02Z"}`, and no `forward/2026-10-05.json` exists.

**Root cause.** `AlpacaData._default_get` (`talonx_premarket/alpaca_data.py`) retries only HTTP 429; every transport error escapes. `forward_daily.sh` chained the stages with `&&` and wrote `cycle_done` unconditionally.

**The 2026-10-05 observation stays missing.** It is not re-run and not backfilled. An operational status record, `results/v2_validation/forward_runs/2026-10-05.json`, carries `state=PARTIAL` and is **labelled `reconstructed_from_log`**; it holds no research output. The runner refuses to run a day that already has a record.

## Ownership (before the fix)

| Concern | Owner | Retry behaviour |
|---|---|---|
| Daily schedule, stop date | `forward_daily.sh` loop (started by the machine-local wrapper `results/ops_restore_20261004/tracker_v2_forward.sh`) | none |
| Stage order, exit status | the `&&` chain in `forward_daily.sh`; `cycle_done` was written regardless | none |
| EDGAR crawl | `talonx_paperperf.form4_edgar.Client.get` | its own: 4 attempts, exponential backoff, returns None after exhaustion (unchanged; residual risk) |
| Prices | `v2_validation.fetch_prices` → `AlpacaData._call` → `_default_get` | 429 only, fixed 2/4/6 s, no Retry-After |
| Episodes, evaluate, forward | local computation | n/a; outputs written non-atomically |

`talonx_premarket/alpaca_data.py` is hashed by the ingestion, promotion and outcomes engine components, so it was **not** changed. The fix stays in the research lane, and every engine component version is unchanged (verified).

## Changes (commit `51aa8b3`, branch `fix/v2-forward-tracker-reliability`, fast-forwarded into `feature/continuous-opportunity-engine`)

### `talonx_paperperf/transient_http.py`

Classified, bounded retries, used as `AlpacaData._get` by the prices stage only. It **replaces** the 429 loop rather than nesting inside it, and the rate limiter is re-acquired before every retry.

| Class | Failures |
|---|---|
| **Retryable** | TLS handshake timeout; socket/read timeouts; connection reset, aborted or refused; remote disconnect / incomplete read; temporary DNS; HTTP 429 (Retry-After honoured, never shortened); HTTP 500/502/503/504 |
| **Never retried** | certificate verification failures and other TLS errors (verification stays ON); HTTP 400/401/403/404/422 and other 4xx; anything unclassified |

**Budget.** At most 5 attempts per request, with backoff of 2, 4, 8 and 16 s (cap 30 s). The limits are 240 s per request and the runner's absolute stage deadline. A Retry-After longer than 120 s exhausts the request instead of being shortened.

**Exhaustion** raises `TransientExhausted` and logs a JSON line on stderr (`EXHAUSTED_ATTEMPTS`, `EXHAUSTED_BUDGET` or `EXHAUSTED_RETRY_AFTER_TOO_LONG`).

Non-retryable HTTP errors keep the old `RuntimeError("HTTP <code>: <body>")` contract, which `fetch_prices`' invalid-symbol handling relies on.

### `talonx_paperperf/v2_validation.py`

- The prices stage uses the transport above.
- All stage artifacts (`txn_2026q2.json`, `episodes.json`, `daily_bars.json`, `rows.json`, `evaluation.json`, `forward/<day>.json`) are written atomically (tmp + `os.replace`).
- The price cache stays resumable: a failed stage leaves the previous cache intact, and a re-run fetches only missing symbols, so there are no duplicate bars.

### `talonx_paperperf/forward_runner.py`

It runs the **unchanged** five stages with the **unchanged** arguments, and records the run in `results/v2_validation/forward_runs/<day>.json`. The record is written atomically at the start and after every stage. It holds:
- the run id and the scheduled, started, ended and deadline times;
- for each stage: state, exit code, retry count, the stderr log path and a sanitised error (queries stripped, keys and tokens masked).

| State | Meaning |
|---|---|
| RUNNING | in progress (`pid` and `heartbeat_utc` show whether the process is still alive) |
| **SUCCESS** | every stage exited 0 **and** `forward/<day>.json` was written by this run and validates (`as_of == day`, required keys present) |
| PARTIAL | at least one stage completed, then a later stage failed, timed out or was not reached; no observation |
| FAILED | the first stage failed, the runner failed, or every stage exited 0 but the artifact did not validate |

**Rules:**
- A stage is never retried as a whole; retries are request-level only.
- One cycle per day: a SUCCESS, live RUNNING or already-attempted day is refused (exit 3).
- Run deadline = min(start + 90 min, 23:30 of the study day), so no retry can push the snapshot across the study's `date.today()` boundary. A stage still running at the deadline is stopped (`TIMEOUT`).
- Exit codes: 0 SUCCESS, 2 PARTIAL, 1 FAILED.

### `docs/research/evidence/2026-09-30_v2_validation/forward_daily_v2.sh`

- Same 06:00Z schedule and 2026-10-31 stop date as `forward_daily.sh`, which is kept unchanged for provenance.
- Runs the cycle through the runner.
- Logs a truthful `{"cycle_end": …, "day": …, "state": …, "exit": …}` line.
- Sleeps to the next 06:00Z (`forward_runner.next_slot`, always strictly in the future: no catch-up).

## Tests

`tests/test_v2_forward_reliability.py` has 24 tests, using mocks and fixtures only; the study was not run. They cover:
- classification of 10 error types;
- a transient failure then success, with the limiter re-acquired per retry;
- exhaustion by attempts, by time budget and by the absolute deadline;
- certificate and authentication errors failing on the first attempt;
- Retry-After honoured, and too long a Retry-After causing exhaustion;
- the transport's TLS behaviour and the `RuntimeError` contract;
- a mid-stage failure leaving the previous price cache intact, then resuming without duplicates;
- PARTIAL propagation with later stages NOT_RUN;
- FAILED for a first-stage failure, and for all-zero exits with a missing artifact;
- a pre-existing or old artifact never counting;
- duplicate and already-attempted days refused (today's 10-05 record included);
- the stage deadline stopping a hung stage;
- the next slot after a failure being tomorrow;
- error sanitisation;
- the loop script's truthful line and its stage commands being identical to the original's.

Results:
- **24 passed**;
- affected regression (every test importing `talonx_paperperf` or `alpaca_data`, 15 modules): **313 passed**;
- engine component versions: unchanged.

## Activation (2026-10-05 06:40Z)

The old loop had its cycle body already parsed in memory, so it had to be replaced to load the fix.
- **Old chain:** wrapper 3716 → 316 → loop 11504 → 23220 → sleeper 19196/5944. It was verified by command line, held no active stage (only `time.sleep` until 2026-10-06 06:00Z), and was stopped by PID. This tracker has no stop command.
- **No cycle started during the stop:** `forward.log`, `episodes.json` and `daily_bars.json` are unchanged.
- **Replacement:** exactly one wrapper, `results/ops_restore_20261004/tracker_v2_forward_v2.sh` (PID 3344; machine-local). It logged `{"wrapper_v2_start": "2026-10-05T06:40:18Z", "first_cycle_at": "2026-10-06T06:00:00+00:00"}`, sleeps via `forward_runner sleep-to-next-slot`, then execs `forward_daily_v2.sh`.
- **First run with the fix:** 2026-10-06 06:00Z (07:00 BST). The stop date stays 2026-10-31.
- **Pick-up:** every stage is a fresh Python process, so later code is loaded at each invocation.
- Evidence: `results/ops_restore_20261004/v2_forward_wrapper_replacement_20261005.txt`.

## Verifier v3 (machine-local `results/ops_restore_20261004/verify_universe_20261005.py`)

**Install.** It was installed atomically (`os.replace`) at 06:30:56Z while no verifier ran. Versions and hashes are in `VERIFIER_VERSIONS.txt`; the v1 and v2 copies are in `results/overnight_20261005/backup/`. Completed results were not modified: the scheduled build result remains `PENDING_TIMEOUT` from run `20261005T001500Z-8b1039`.

**Classification changes:**
- A build-stage timeout is now `BUILD_NOT_OBSERVED_BY_DEADLINE` (it was previously defaulted to `RUNTIME_DEFECT`).
- The consolidated report shows the scheduled-check deadline (01:45Z) **and** the measured publication time (02:20:19Z), the late observations with their own timestamps (`20261005T062221Z-8fedbe` PASS at 06:22Z), and the current fresh re-check (`VERIFIED_LATE`).
- `INVALID_MEMBERSHIP` is kept separate.

**Build timeline.** The measured timestamps (universe 00:25Z, split daily 02:19Z, raw daily and snapshot 02:20Z, overnight cycle intervals) are labelled separately from the **inferred** cause (slow provider). The verifier's timeout was not simply extended.

**Report sections:**
1. live engine/ops readiness;
2. universe verification;
3. research-tracker completeness;
4. overall.

V2 forward, VR and DTU each show their own state: `NOT_YET_DUE`, `OBSERVED`, `MISSING`, or the runner's `SUCCESS`/`PARTIAL`/`FAILED` (reconstructed flagged). **A missing research observation keeps the overall verdict DEGRADED even when the live application is READY.**

**Tests.** `test_verifier_v3.py`, beside the verifier: 4 passed.

## Rollback

- **Tracker.** Stop the `tracker_v2_forward_v2.sh` chain: verify by command line and terminate by PID; only do this outside a running cycle (check `forward_runs/<day>.json` is not RUNNING). Then start `results/ops_restore_20261004/tracker_v2_forward.sh` (sleep to the slot, then `forward_daily.sh`).
- **Code.** `git revert 51aa8b3` on the live branch (no force-push). The engine is unaffected either way.
- **Verifier.** `results/overnight_20261005/backup/verify_universe_20261005.v2.py` → `os.replace` into place while no verifier task runs.
