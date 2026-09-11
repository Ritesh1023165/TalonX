# Startup concurrency & verdict acceptance (Task 117 §3)

New module `talonx_ops/prospective/lock.py`. Wired into
`talonx_ops/prospective/proc.py` (`start_stack` / `stop_stack`) and
`talonx_ops/prospective/__main__.py` (`cmd_start`).

## Atomic single-writer guard

`SingleWriterLock(ledger_path)`:
- lockfile `<ledger_path>.startlock`, created with
  `os.open(path, O_CREAT | O_EXCL | O_WRONLY)` — the OS guarantees exactly one
  creator across processes; the loser gets `FileExistsError` → `ConcurrentStartError`.
- payload `{pid, host, started_utc, ledger_path}`.
- `_owner_state()` → `free` / `live` / `stale`. `stale` = the recorded PID is
  not alive **or** the recorded `ledger_path` differs from this lock's target.
- `acquire(force=False, break_stale=True)`:
  - `live` owner → **`ConcurrentStartError` even when `force=True`** (a `--force`
    start must never displace an active ledger writer);
  - `stale` → broken and taken when `break_stale` (default) or `force`; refused
    with `StaleLockError` when `break_stale=False`;
  - creation race (two callers pass the checks, one `O_EXCL` wins) → the loser
    gets `ConcurrentStartError`.
- `release()` unlinks the file **only if this instance owns it**.

`proc.start_stack` acquires the lock **before** the secondary
`_live_prior_stack()` process scan and **before** any `_spawn`, and calls
`_lock.release()` on any `BaseException` during startup. `stop_stack` unlinks
the lock only when `not residual` (no leftover processes); otherwise it is kept
with `startlock_released: "kept -- residuals present"`. Lock scope follows the
V2 ledger identity (`V2_DB_PATH`).

## Truthful start verdict

`MANDATORY_STARTUP = ("supervisor_alive", "v2_companion_alive", "dashboard_8787")`.
`startup_verdict(info, verify, *, heartbeat_fresh, within_grace)`:

| process state | heartbeat | grace | residual | verdict |
|---|---|---|---|---|
| all mandatory up | fresh | — | — | **READY** |
| all mandatory up | stale | within | — | STARTING |
| some mandatory up | — | within | — | STARTING |
| some mandatory up | — | elapsed | yes | FAILED_WITH_RESIDUALS |
| both core dead | — | — | none | NOT_STARTED |
| both core dead | — | — | yes | FAILED_WITH_RESIDUALS |

- **READY requires the essential dashboard (`dashboard_8787`) AND a fresh
  first-tick heartbeat**, not merely a live supervisor + companion.
- **STARTING → READY/FAILED resolution mechanism:** `cmd_start` re-polls
  `verify_running` every 3 s until all mandatory components are up or the
  `GRACE_S = 120` s budget elapses. On elapse with a partial stack →
  `startup_verdict` returns `FAILED_WITH_RESIDUALS` and `cmd_start` runs an
  ownership-safe `stop_stack(sd)` + writes `start_cleanup.json`.
- Exit codes: `READY 0 · STARTING 0 · NOT_STARTED 2 · REFUSED_ALREADY_RUNNING 3
  · FAILED_WITH_RESIDUALS 4`.
- A `ConcurrentStartError` from the lock → `cmd_start` prints `START REFUSED`,
  writes `start_verify.json {"verdict":"REFUSED_ALREADY_RUNNING"}`, `return 3`.
  It never implies "did not start" while owned processes are still alive.

## Tests (real, not mocked process scans)

`tests/test_task117_single_writer_lock.py` (5):
- `test_acquire_release_roundtrip`
- `test_second_acquire_while_owner_alive_is_refused_even_with_force`
- `test_stale_lock_from_a_dead_pid_can_be_broken` (opt-out refuses, default breaks)
- `test_lock_for_a_different_ledger_is_treated_as_stale`
- **`test_two_real_concurrent_starts_yield_exactly_one_owner`** — two real
  `subprocess.Popen` children both call `SingleWriterLock(led).acquire()`;
  asserts exactly one prints `ACQUIRED` (rc 0), one `REFUSED` (rc 7), and the
  lockfile is gone after the winner releases.

`tests/test_task117_startup_verdict.py` (16, incl.):
- `test_startup_verdict_matrix` (8 parametrised rows, dashboard included)
- `test_ready_requires_the_dashboard_not_just_sup_and_companion`
- `test_missing_mandatory_is_not_a_cosmetic_warning`
- `test_start_stack_guard_blocks_a_second_spawn` (nothing spawned; lock released
  on failure — `_tmp_lock` points the lock at an isolated tmp ledger, never
  `V2_DB_PATH`)
- `test_start_stack_force_overrides_the_guard` (only the `_live_prior_stack`
  process-scan guard; the live-lock refusal above still stands)

`tests/test_task117_release_rehearsal.py::test_bounded_release_rehearsal` step 7
re-exercises: 2nd `acquire()` → REFUSED, `acquire(force=True)` → REFUSED,
single owner pid, lockfile released.

## Untouched

Unrelated processes and the `talonx-redis` container are never inspected or
signalled by the lock. Redis `run_id 50c35db7f72366789f96c6f1e3718e8942494176`
retained. Restart after a clean `stop_stack` (no residual → lockfile removed)
acquires cleanly.
