# V2@1 forward status persistence fix and dashboard view: deployment (2026-10-12)

**Status: FIX_IMPLEMENTED_AND_ACTIVATED** (code live; the first live exercise is the next scheduled run).

## Activation

| Item | Value |
|---|---|
| Code commit | `d200b52` on `feature/continuous-opportunity-engine`, pushed; the live checkout was fast-forwarded |
| Runner | `talonx_paperperf/forward_runner.py` → `RUNNER_VERSION = forward_runner v1.1 (2026-10-12: …)`. The loop `forward_daily_v2.sh` starts a **fresh** `python -m talonx_paperperf.forward_runner run` at each slot, so the **next run, 2026-10-13 06:00Z (07:00 BST), loads v1.1**. The sleeping process (7132, `sleep-to-next-slot`) only sleeps, so the loop was **not restarted**. No stage was active at deployment (verified: only the loop shells and the sleeper exist). |
| Loop | Exactly one logical chain: wrapper 3344 → 7184 → loop 24096 → 20484 → sleeper 16284/7132. Next slot `2026-10-13T06:00:00Z`; end date `2026-10-31` (loop script sha256 `f295f6b0…`, unchanged). No catch-up: `next_slot` is strictly future. |
| Dashboard | `dashboard_web.py`, the OPTIONAL child of the ops supervisor (5316). It was tree-killed once at 16:16:12Z (`taskkill /PID 16872 /T /F`, the established commit-then-managed-restart cutover). The supervisor respawned it at **16:16:20Z** (10312 → 26188); HTTP 200. Siblings unchanged: Original 2480, Intelligence 6612. Nothing else was restarted. |
| Validation tab | Panel "V2@1 forward tracker runs", data `validation.v2_forward_runs`. |

## Behaviour

**Replace retry.**
- Retried only for Windows errors 5 (`ERROR_ACCESS_DENIED`), 32 (`ERROR_SHARING_VIOLATION`) and 33
  (`ERROR_LOCK_VIOLATION`).
- Waits 0.05, 0.1, 0.2, 0.4, 0.8, 1.6 and 3.2 s: **8 attempts, at most 6.35 s** of waiting. A wait that would cross
  the run deadline is not taken.
- Everything else raises at once with no retry: other OSErrors, Windows permission errors without a classified code,
  and serialization errors.
- Each write uses a unique temp file (`<day>.json.<pid>.<id>.tmp`, exclusive create, fsync, closed before replace).
  Only that file is ever removed, and the destination is never truncated or deleted.
- Scientific request retry budgets are unchanged.

**When persistence stays unavailable:**
- The last valid record is left untouched and no further stage is entered. A completed stage is never repeated.
- A best-effort diagnostic is written: `forward_runs/<day>.<run_id>.persistence_failure.<id>.json`. It holds the
  boundary, the stages actually executed, outcome exposure (`NO_OUTCOME_STAGE_STARTED` or
  `OUTCOME_STAGE_STARTED_OR_WRITTEN:<stages>`), `automatic_recovery: REFUSED`, the attempt history and the sanitized
  exception.
- One stderr JSON line is emitted.
- The runner exits **4**. Diagnostic failure is reported as `DIAGNOSTIC_WRITE_FAILED` and never hides the original
  failure. Nothing is durable if the disk itself has failed.

**Same-day records:** a record that is RUNNING with a dead pid (abandoned), or unreadable, is refused with exit 3 and
never re-run.

**Dashboard view** (`talonx_paperperf/forward_status.py`):
- It reads only `forward_runs/<day>.json` and the names of persistence diagnostics. It never opens `forward/` or any
  other research output (tested).
- Recorded state is shown verbatim. Observed state is derived conservatively:
  - `ABANDONED` needs a verified absent process (the pid is gone, or now belongs to a later or non-runner process)
    **and** a passed deadline;
  - `OVERDUE_ALIVE` means the identity is verified and the deadline has passed;
  - `OVERDUE_UNCONFIRMED` or `UNKNOWN` means liveness was not established;
  - `UNREADABLE` is never shown as healthy;
  - SUCCESS is shown only if the record itself says the artifact validated.
- Current health (latest day) is shown separately from incomplete days in view (study completeness).
- **The dashboard is itself a reader.** On this machine any open read handle blocks `os.replace` (verified on
  synthetic files, including with `FILE_SHARE_DELETE`), so the view re-reads at most once per 60 s per process. The
  runner's bounded retries absorb a residual collision.

**Live view at deployment:**

| Day | Recorded | Observed |
|---|---|---|
| 2026-10-12 | SUCCESS | SUCCESS |
| 2026-10-11 | RUNNING | **ABANDONED** (verified process absent and deadline passed; last persisted stage `prices` SUCCESS) |
| 2026-10-10 | SUCCESS | SUCCESS |
| 2026-10-09 | SUCCESS | SUCCESS |

Current health `HEALTHY`; incomplete days in view `[2026-10-11]`; next run `2026-10-13T06:00:00Z`.

## Unchanged and preserved

- **Sunday's files:** `2026-10-11.json` sha256 `0f2ccf4f…` and `.tmp` `9f112685…`, byte-identical. That observation
  remains missing. See [`INCIDENT_2026-10-11.md`](INCIDENT_2026-10-11.md).
- **Study rules:** stages, order, cutoffs, deadline, artifact validation, attempt policy and end date.
- **Controls:**
  - PDM `verify_integrity` = [] (config file sha256 `f7f012fd…`);
  - review control `f0589fb1…`;
  - VR entry control `bd10edf6…` and ARM interruption `477e20d6…`;
  - DTU schedule `9f0c07a5…`;
  - wrapper `tracker_v2_forward_v2.sh` `e5331df7…`;
  - `forward_alpha_validation.md` `b1c886ba…`.
- No study command was run during testing or deployment. The fixtures use temp directories, mocked errors and test
  processes only.

## Tests

- **New:** `tests/test_v2_forward_status_persistence.py`, 26 tests, all passing. They cover:
  - transient-then-success, budget exhausted, deadline stop, permanent and unclassified errors, serialization error;
  - previous record preserved, handles closed before replace, only own temp removed;
  - pre-stage failure blocks the stage with no rerun, the day refused afterwards;
  - outcome exposure and refusal;
  - diagnostic failure keeping the original error;
  - unreadable record refused;
  - dashboard: ABANDONED, PID reuse, non-runner pid, overdue alive, unknown liveness, malformed record, SUCCESS without
    the validated flag, health vs completeness, no outcome reads, rate-limited cache, real test-process liveness, panel
    wiring.
- **Existing forward suites:** 42 tests, all passing.
- **Broad dashboard and release suites** (every test file referencing these components): **531 passed, 23 failed,
  1 skipped**. All 23 failures were re-run on the unmodified baseline `3b38da9` and fail there identically. They are
  environment-related (Original strategy fingerprints, :8770/:8501 parity, residual inventories, release-preflight
  fixtures), not regressions.
- **Freeze gate** (`a56ec8c`): pass.

## Pending

Live proof is the 2026-10-13 06:00Z run. Check that `forward_runs/2026-10-13.json` shows
`runner_version forward_runner v1.1 …` and a terminal state. A `persistence_retries` entry, if one appears, shows that
the retry path was exercised. No run is manufactured.

## Rollback

Code only; it never reruns a day or erases evidence.
1. `git revert d200b52`, then push and fast-forward live.
2. Before the next 06:00Z slot, nothing else is needed: the loop loads the runner fresh per run.
3. For the dashboard, repeat the single tree-kill of the `dashboard_web.py` child so the ops supervisor respawns it with
   the reverted code.

Keep `forward_runs/*`, any `*.persistence_failure.*.json` diagnostics and this evidence.
