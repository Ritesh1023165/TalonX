# Lock ownership lifecycle — real tests (Task 117 final-activation A4)

`talonx_ops/prospective/lock.py` rewritten; `talonx_ops/prospective/proc.py`
(`start_stack`/`_start_stack_locked`/`stop_stack`) updated to match. All 18
tests in `tests/test_task117_single_writer_lock.py` are **real**: real files,
real `os.open(O_CREAT|O_EXCL)`, real `os.rename` claim races, real OS
subprocesses (`subprocess.Popen`, `creationflags` matching production
`_spawn`). None are mocked process scans.

## Defects found and fixed

### 1. Lock recorded the short-lived `start` CLI's own pid, not the surviving writer
Previously the lock's `pid` was whatever process called `acquire()` — the
`prospective start` CLI itself. Once that CLI process finished spawning and
exited (its job done), the lock's recorded owner was dead, so `_owner_state()`
classified it `stale` and a second `start` (even without `--force`, since
`break_stale` defaulted `True`) could take over **while the actual supervisor
+ V2 companion it spawned were still alive and writing `v2_lane.db`.**

**Fix:** `rebind_owner(pid=v2_companion_pid)` — called from
`_start_stack_locked` right after the V2 companion (the actual ledger writer)
is spawned, *before* the `start` CLI returns. The lock's liveness now tracks
the writer, not the CLI invocation. An `owner_token` (a uuid, independent of
pid) travels across the rebind so release remains an entitlement check, never
a pid-equality coincidence.

Test: `test_start_command_exits_while_writer_survives_second_start_and_force_both_refuse` —
a real starter subprocess rebinds to a real long-lived writer subprocess,
exits, and a second `acquire()` (with or without `force=True`) is refused for
as long as the writer is alive; only once the writer is killed does `acquire`
succeed.

### 2. A stale-lock break race could delete a racer's freshly-created replacement lock
The original break-stale path was `unlink()` the file, then `O_CREAT|O_EXCL`
a new one. Two racers who both observed `stale` could interleave so that
racer B's `unlink()` fires *after* racer A has already created its own fresh,
live lock — silently deleting A's live lock and letting B become a second
owner. **Reproduced directly**: a real 2-subprocess test against a genuinely
stale forged lock consistently produced two "OWNER" outcomes before the fix.

**Fix:** `_claim_stale_for_removal()` uses `os.rename(lock_path, claim_path)`
to atomically take exclusive custody of *whatever is currently at the path*
(only one racer's rename of a given source can succeed, verified directly),
then **re-inspects the claimed content** before discarding it — if it turns
out to be a live owner's lock after all (i.e. this call grabbed a racer's
fresh replacement mid-flight), it is restored (itself via `O_CREAT|O_EXCL`,
so a third racer's lock is never clobbered) and `ConcurrentStartError` is
raised instead of silently proceeding as free.

Test: `test_concurrent_stale_recovery_yields_exactly_one_new_owner` — two real
subprocesses race a forced stale-break; exactly one becomes owner, exactly one
is refused, run repeatably (10/10 stable in local repetition during
development).

### 3. Unreadable / partially-written lock content was treated as `stale`
A corrupt or incomplete payload (missing `create_time`/`owner_token` —
exactly what an interrupted write could leave) was previously read as "no
valid owner recorded" and folded into the same `stale` bucket a genuinely dead
owner gets — meaning `--force` (or even the default `break_stale=True`) could
silently take over a lock whose true state was actually unknown.

**Fix:** a new `unknown` state, distinct from `stale`. `acquire()` raises
`LockStateUnknownError` for `unknown` **regardless of `force`** — the only way
past it is the explicit, narrowly-scoped `force_clear_unknown(confirmed_no_live_stack=True)`,
which archives the unreadable file next to itself (never silently discards
it) and requires the caller to have independently verified no live stack is
running.

Test: `test_corrupt_or_incomplete_lock_is_unknown_not_stale_and_force_does_not_bypass`,
`test_force_clear_unknown_requires_explicit_confirmation_and_archives`.

### 4. PID reuse was not distinguished from the original owner
The identity check compared pid alone (plus a loose cmdline match). A pid
recycled by an unrelated process shortly after the original owner died could,
in principle, be mistaken for a live owner.

**Fix:** every liveness check also compares the OS process `create_time`
(1.0 s tolerance) recorded at acquire time against the *current* process at
that pid — a mismatch means the pid was reused, and the entry is correctly
classified `stale`, never `live`.

Test: `test_pid_reuse_is_not_mistaken_for_the_recorded_owner` — a real child
process's pid is recorded with a deliberately wrong `create_time`; the lock
correctly treats it as stale (breakable) despite the pid being genuinely
alive.

### 5. Windows path case was a spurious "different ledger" mismatch
`_owner_state()` compared `ledger_path` strings with a bare `==`. On
case-insensitive NTFS, `C:\workspace\TalonX\v2_lane.db` and
`c:\workspace\talonx\v2_lane.db` are the *same* file but would have compared
unequal, defeating the guard by classifying a live lock as "for a different
ledger" → `stale` → breakable.

**Fix:** identity comparisons use `os.path.normcase()`.

Test: `test_windows_path_case_is_not_a_different_ledger_identity`.

### 6. `stop_stack` released the lock by unconditional path-unlink
`stop_stack` previously did `Path(lock_path).unlink()` directly — no
ownership check at all. Any process (or a stale registry entry pointing at
someone else's session) could remove a lock it had no entitlement to.

**Fix:** `SingleWriterLock.release_by_token(V2_DB_PATH, owner_token)` — the
`owner_token` is carried in `session.pids.json` (`startlock_owner_token`) and
only a matching token removes the file.

Test: `test_release_by_token_refuses_a_mismatched_token`,
`test_rebind_then_release_by_token_from_a_fresh_instance`.

### 7. Partial startup failure could leave the lock in the wrong state either way
Originally, any exception during `_start_stack_locked` triggered an
unconditional `_lock.release()` in the *caller* — even if the supervisor or
V2 companion had already spawned and might still be alive, which would let a
second `start` race a real writer onto the ledger.

**Fix:** `_start_stack_locked` now performs the rollback itself: on any
exception it terminates (ownership-verified, bounded `grace_s=10s` each)
exactly what *this* attempt spawned, and only releases the lock if that
rollback leaves **no residual** — otherwise the lock is deliberately **kept**,
so protection remains until an operator investigates.

Tests: `test_partial_startup_failure_rolls_back_spawned_processes_and_releases`
(real spawned processes, real termination, real release);
`test_partial_startup_failure_keeps_the_lock_if_a_writer_could_not_be_reaped`
(decision-logic check: an unreachable residual keeps the lock held).

### 8. Real Windows process-teardown hazard in `_terminate`/`_still_the_same` (found via real testing)
Directly reproduced while building the real-process rollback test: a
`psutil`-based liveness/identity re-check on a process that is *concurrently*
exiting (specifically the `.venv`-shim → re-exec'd grandchild pattern the
supervisor/V2 companion always use) can **block indefinitely** inside a raw
`psutil.Process(pid)` query. Root cause narrowed to non-detached child
processes (a plain `subprocess.Popen` without `CREATE_NEW_PROCESS_GROUP |
DETACHED_PROCESS`) sharing the parent's console during that transition;
production `_spawn()` always uses those flags, and matching them in the test
made the hang disappear. As defense in depth (not dependent on flags always
being right), `_still_the_same`'s cmdline read is now cached per
`(pid, create_time)` so a hot poll loop re-reads a process's memory at most
once, and **every** psutil call in `_terminate` (`send_signal`, `terminate`,
`kill`, the identity check) runs under a 2 s bounded timeout
(`_run_bounded`, a daemon-thread `join(timeout)`), defaulting to "still
present" on timeout so a caller reports an honest residual instead of
freezing. `stop_stack`'s residual re-check reuses the same cache so a
process's memory is read at most once across the whole teardown, even before
this bounding existed.

## Test matrix (a)–(g) from the review

| id | scenario | test |
|---|---|---|
| a | simultaneous starts → exactly one stack/writer | `test_two_real_concurrent_starts_yield_exactly_one_owner` |
| b | start command exits while stack survives → 2nd start & `--force` both refuse | `test_start_command_exits_while_writer_survives_second_start_and_force_both_refuse` |
| c | starter paused during lock init → competitor cannot delete/bypass | `test_competitor_cannot_bypass_a_lock_paused_mid_initialization` |
| d | concurrent stale recovery → exactly one new owner | `test_concurrent_stale_recovery_yields_exactly_one_new_owner` |
| e | partial startup failure → bounded cleanup; protection remains if residual survives | `test_partial_startup_failure_rolls_back_spawned_processes_and_releases` + `..._keeps_the_lock_if_a_writer_could_not_be_reaped` |
| f | clean close then restart succeeds | `test_clean_close_followed_by_restart_succeeds` |
| g | PID reuse / invalid metadata cannot trigger unsafe takeover | `test_pid_reuse_is_not_mistaken_for_the_recorded_owner`, `test_corrupt_or_incomplete_lock_is_unknown_not_stale_and_force_does_not_bypass` |

18/18 pass, stable over 4 consecutive full-suite runs (9.9 s each) during
development.

## Startup readiness unaffected

`startup_verdict` still requires all mandatory components
(`supervisor_alive`, `v2_companion_alive`, `dashboard_8787`) **and** a fresh
first-tick heartbeat for `READY` — untouched by this lock rework
(`tests/test_task117_startup_verdict.py`, 16/16 pass).

## Production-safety note found and fixed during this work

While re-running the pre-existing `test_task117_execution_scope.py::test_prospective_start_stack_passes_the_deployment_flags`,
a **real, stray `v2_lane.db.startlock`** (pid `4242`, a fake test pid) was
found sitting next to the **live** `v2_lane.db` — that test called
`proc.start_stack()` without isolating `SingleWriterLock`, so it always took
(and, on later runs, could fail against) the real lock path. The stray file
and the WAL/SHM sidecars it left were removed; the live ledger's content and
md5 (`29e57dbcd1a567fbc4bb0e73efdba95f`) were verified unchanged throughout.
The test now monkeypatches `SingleWriterLock` onto an isolated `tmp_path`
ledger, matching the pattern already used elsewhere (`_tmp_lock` in
`test_task117_startup_verdict.py`). A repo-wide sweep confirmed no other test
touches the real `V2_DB_PATH` lock.
