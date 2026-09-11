"""
Task 117 Section 3 (+ final-activation correction) -- atomic single-writer
lock, ownership lifecycle (rebind/release-by-token), and race safety.

These are REAL tests: real files, real ``os.open(O_CREAT|O_EXCL)``, real
``os.rename`` claim races, and real concurrent OS subprocesses. Not mocked
process scans. A couple of sub-cases that would require literally forcing an
OS to reuse a PID or literally deadlock a termination call are clearly marked
as behaviour-level (decision-logic) checks; every liveness/race claim itself
is exercised against a real process.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import psutil
import pytest

from talonx_ops.prospective.lock import (
    ConcurrentStartError, LockStateUnknownError, SingleWriterLock, StaleLockError,
    _pid_alive, _proc_create_time,
)

_REPO = Path(__file__).resolve().parents[1]
_ENV = dict(os.environ, PYTHONPATH=str(_REPO))


def _sleeper(seconds: float) -> subprocess.Popen:
    """A real, lightweight, long-lived child process -- used as a stand-in
    for 'the surviving writer' without pulling in the full V2 companion.
    stdout/stderr are never inherited -- an inherited pipe handle held open
    by a still-running child is a classic Windows hang for whatever captures
    THIS test process's own output."""
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        env=_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL)


def _wait_dead(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


# --------------------------------------------------------------------------- basics
def test_acquire_release_roundtrip(tmp_path):
    led = tmp_path / "v2.db"
    lk = SingleWriterLock(led)
    lk.acquire()
    assert lk.lock_path.exists()
    owner = lk.read_owner()
    assert owner["pid"] == os.getpid() and owner["ledger_path"] == str(led.resolve())
    assert owner["owner_token"] and owner["create_time"] is not None
    lk.release()
    assert not lk.lock_path.exists()


def test_second_acquire_while_owner_alive_is_refused_even_with_force(tmp_path):
    led = tmp_path / "v2.db"
    a = SingleWriterLock(led).acquire()      # this process = a live owner
    try:
        with pytest.raises(ConcurrentStartError):
            SingleWriterLock(led).acquire(force=True)   # --force must NOT break a live lock
    finally:
        a.release()


def test_stale_lock_from_a_dead_pid_can_be_broken(tmp_path):
    led = tmp_path / "v2.db"
    lk = SingleWriterLock(led)
    # forge a COMPLETE lock (all required fields) owned by a PID that does not exist
    dead = 2_000_000_000
    assert not _pid_alive(dead)
    lk.lock_path.write_text(json.dumps(
        {"pid": dead, "create_time": 1_700_000_000.0, "host": "x",
         "started_utc": "2026-01-01T00:00:00+00:00",
         "ledger_path": str(led.resolve()), "owner_token": "dead-token"}), encoding="utf-8")
    assert lk._owner_state() == "stale"
    with pytest.raises(StaleLockError):
        SingleWriterLock(led).acquire(break_stale=False)      # opt-out -> refuse
    got = SingleWriterLock(led).acquire(break_stale=True)     # default -> break + take
    assert got.read_owner()["pid"] == os.getpid()
    got.release()


def test_lock_for_a_different_ledger_is_treated_as_stale(tmp_path):
    led = tmp_path / "v2.db"
    lk = SingleWriterLock(led)
    lk.lock_path.write_text(json.dumps(
        {"pid": os.getpid(), "create_time": _proc_create_time(os.getpid()), "host": "x",
         "started_utc": "2026-01-01T00:00:00+00:00",
         "ledger_path": "/some/other/ledger.db", "owner_token": "t"}), encoding="utf-8")
    assert lk._owner_state() == "stale"                       # identity mismatch


def test_windows_path_case_is_not_a_different_ledger_identity(tmp_path):
    led = tmp_path / "v2.db"
    lk_lower = SingleWriterLock(str(led).lower())
    lk_mixed = SingleWriterLock(str(led))
    got = lk_lower.acquire()
    try:
        # same underlying file, different case -> must see it as the SAME
        # ledger identity (a case-flip must not defeat the guard).
        with pytest.raises(ConcurrentStartError):
            lk_mixed.acquire()
    finally:
        got.release()


# ------------------------------------------------------------- rebind / release-by-token
def test_rebind_then_release_by_token_from_a_fresh_instance(tmp_path):
    led = tmp_path / "v2.db"
    lk = SingleWriterLock(led).acquire()
    token = lk._owner_token
    child = _sleeper(15)
    try:
        lk.rebind_owner(pid=child.pid)
        owner = lk.read_owner()
        assert owner["pid"] == child.pid and owner["owner_token"] == token
        # a same-token release from a DIFFERENT instance succeeds
        assert SingleWriterLock.release_by_token(led, token) is True
        assert not lk.lock_path.exists()
    finally:
        child.terminate()
        child.wait(timeout=10)


def test_release_by_token_refuses_a_mismatched_token(tmp_path):
    led = tmp_path / "v2.db"
    lk = SingleWriterLock(led).acquire()
    try:
        assert SingleWriterLock.release_by_token(led, "not-the-real-token") is False
        assert lk.lock_path.exists()          # untouched
    finally:
        lk.release()


def test_rebind_requires_holding_the_lock():
    lk = SingleWriterLock(Path("nonexistent") / "v2.db")
    with pytest.raises(RuntimeError):
        lk.rebind_owner(pid=os.getpid())


# --------------------------------------------------------------------------- 4g unknown / corrupt
def test_corrupt_or_incomplete_lock_is_unknown_not_stale_and_force_does_not_bypass(tmp_path):
    led = tmp_path / "v2.db"
    lk = SingleWriterLock(led)
    # missing create_time / owner_token -- exactly the shape an interrupted
    # partial write could leave behind
    lk.lock_path.write_text(json.dumps(
        {"pid": os.getpid(), "host": "x", "ledger_path": str(led.resolve())}),
        encoding="utf-8")
    assert lk._owner_state() == "unknown"
    with pytest.raises(LockStateUnknownError):
        SingleWriterLock(led).acquire()
    with pytest.raises(LockStateUnknownError):
        SingleWriterLock(led).acquire(force=True)             # force does NOT bypass 'unknown'
    # truly unreadable (not JSON at all) is the same class of failure
    lk.lock_path.write_text("{not json", encoding="utf-8")
    assert lk._owner_state() == "unknown"


def test_force_clear_unknown_requires_explicit_confirmation_and_archives(tmp_path):
    led = tmp_path / "v2.db"
    lk = SingleWriterLock(led)
    lk.lock_path.write_text("not even json", encoding="utf-8")
    with pytest.raises(LockStateUnknownError):
        lk.force_clear_unknown(confirmed_no_live_stack=False)
    assert lk.lock_path.exists()                              # untouched by the refusal
    lk.force_clear_unknown(confirmed_no_live_stack=True)
    assert not lk.lock_path.exists()
    archives = list(tmp_path.glob("v2.db.startlock.unknown.*.bak"))
    assert len(archives) == 1 and "not even json" in archives[0].read_text()


def test_pid_reuse_is_not_mistaken_for_the_recorded_owner(tmp_path):
    """A genuinely alive pid, recorded with a create_time that does not match
    that process's ACTUAL create_time, must be treated as a reused pid (i.e.
    the recorded owner is gone) -- never as a live owner."""
    led = tmp_path / "v2.db"
    child = _sleeper(15)
    try:
        real_ct = _proc_create_time(child.pid)
        assert real_ct is not None
        lk = SingleWriterLock(led)
        lk.lock_path.write_text(json.dumps(
            {"pid": child.pid, "create_time": real_ct - 999.0,  # deliberately wrong
             "host": "x", "started_utc": "2026-01-01T00:00:00+00:00",
             "ledger_path": str(led.resolve()), "owner_token": "stale-owner"}),
            encoding="utf-8")
        assert lk._owner_state() == "stale"          # not 'live' despite a real, alive pid
        got = SingleWriterLock(led).acquire(force=True)
        got.release()
    finally:
        child.terminate()
        child.wait(timeout=10)


# --------------------------------------------------------------------------- real subprocess races
_CHILD_SIMPLE = textwrap.dedent("""
    import sys, time
    from talonx_ops.prospective.lock import SingleWriterLock, ConcurrentStartError
    led = sys.argv[1]
    time.sleep(0.05)
    try:
        lk = SingleWriterLock(led).acquire()
        print("ACQUIRED")
        time.sleep(1.5)
        lk.release()
        sys.exit(0)
    except ConcurrentStartError:
        print("REFUSED")
        sys.exit(7)
""")


def test_two_real_concurrent_starts_yield_exactly_one_owner(tmp_path):
    """(a) Simultaneous starts: exactly one stack/writer."""
    led = str(tmp_path / "v2.db")
    script = tmp_path / "child.py"
    script.write_text(_CHILD_SIMPLE, encoding="utf-8")
    p1 = subprocess.Popen([sys.executable, str(script), led], env=_ENV,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    p2 = subprocess.Popen([sys.executable, str(script), led], env=_ENV,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    o1, _ = p1.communicate(timeout=25)
    o2, _ = p2.communicate(timeout=25)
    outs = [o1.strip(), o2.strip()]
    rcs = sorted([p1.returncode, p2.returncode])
    assert "ACQUIRED" in outs[0] + outs[1]
    assert "REFUSED" in outs[0] + outs[1]
    assert rcs == [0, 7]                                      # one owner, one refused
    assert not (tmp_path / "v2.db.startlock").exists()        # released by the winner


_STARTER = textwrap.dedent("""
    import json, sys, time
    from talonx_ops.prospective.lock import SingleWriterLock
    led, writer_pid, mode = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    lk = SingleWriterLock(led).acquire()
    if mode == "pause_before_rebind":
        # (c) simulate being paused mid-initialization, BEFORE the rebind --
        # the lock is already visibly live (this starter's own pid) the whole
        # time, so a competitor must be refused throughout.
        time.sleep(2.5)
    lk.rebind_owner(pid=writer_pid)
    print("STARTED", flush=True)
    # (b) the starter now exits WITHOUT releasing -- the lock must keep
    # protecting the ledger via the rebound writer pid, not this exiting CLI.
    sys.exit(0)
""")


def test_start_command_exits_while_writer_survives_second_start_and_force_both_refuse(tmp_path):
    """(b) Start command exits while the writer survives: second start AND
    --force both refuse."""
    led = str(tmp_path / "v2.db")
    writer = _sleeper(20)
    try:
        script = tmp_path / "starter.py"
        script.write_text(_STARTER, encoding="utf-8")
        starter = subprocess.run(
            [sys.executable, str(script), led, str(writer.pid), "no_pause"],
            env=_ENV, capture_output=True, text=True, timeout=20)
        assert "STARTED" in starter.stdout
        assert starter.returncode == 0                         # the CLI process is gone

        with pytest.raises(ConcurrentStartError):
            SingleWriterLock(led).acquire()
        with pytest.raises(ConcurrentStartError):
            SingleWriterLock(led).acquire(force=True)           # force still refused

        owner = SingleWriterLock(led).read_owner()
        assert owner["pid"] == writer.pid                       # rebound, not the dead CLI pid
    finally:
        writer.terminate()
        writer.wait(timeout=10)

    assert _wait_dead(writer.pid)
    got = SingleWriterLock(led).acquire(force=True)              # writer gone -> now stale, breakable
    got.release()


def test_competitor_cannot_bypass_a_lock_paused_mid_initialization(tmp_path):
    """(c) Starter paused during lock initialization (before rebind):
    a competitor cannot delete or bypass it."""
    led = str(tmp_path / "v2.db")
    writer = _sleeper(20)
    try:
        script = tmp_path / "starter.py"
        script.write_text(_STARTER, encoding="utf-8")
        starter = subprocess.Popen(
            [sys.executable, str(script), led, str(writer.pid), "pause_before_rebind"],
            env=_ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        time.sleep(0.5)   # let the starter create the lock (still its own pid, pre-rebind)
        with pytest.raises(ConcurrentStartError):
            SingleWriterLock(led).acquire(force=True)            # must NOT bypass
        with pytest.raises(ConcurrentStartError):
            SingleWriterLock(led).acquire()
        out, _ = starter.communicate(timeout=20)
        assert "STARTED" in out
    finally:
        writer.terminate()
        writer.wait(timeout=10)


_STALE_RECOVER = textwrap.dedent("""
    import sys, time
    from talonx_ops.prospective.lock import SingleWriterLock, ConcurrentStartError
    led = sys.argv[1]
    try:
        lk = SingleWriterLock(led).acquire(force=True)  # forced stale-break
        print("OWNER", lk.read_owner()["pid"], flush=True)
        # HOLD the lock open -- a winner that exits immediately would make
        # itself 'stale' again before the loser even checks, which is a
        # different (already-covered) scenario, not concurrent contention.
        time.sleep(1.5)
        lk.release()
        sys.exit(0)
    except ConcurrentStartError:
        print("REFUSED", flush=True)
        sys.exit(7)
""")


def test_concurrent_stale_recovery_yields_exactly_one_new_owner(tmp_path):
    """(d) Concurrent stale recovery: exactly one new owner."""
    led = tmp_path / "v2.db"
    dead = 2_000_000_001
    assert not _pid_alive(dead)
    led.parent.mkdir(parents=True, exist_ok=True)
    lock_path = led.with_suffix(led.suffix + ".startlock")
    lock_path.write_text(json.dumps(
        {"pid": dead, "create_time": 1_700_000_000.0, "host": "x",
         "started_utc": "2026-01-01T00:00:00+00:00",
         "ledger_path": str(led.resolve()), "owner_token": "dead"}), encoding="utf-8")

    script = tmp_path / "recover.py"
    script.write_text(_STALE_RECOVER, encoding="utf-8")
    p1 = subprocess.Popen([sys.executable, str(script), str(led)], env=_ENV,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    p2 = subprocess.Popen([sys.executable, str(script), str(led)], env=_ENV,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    o1, _ = p1.communicate(timeout=20)
    o2, _ = p2.communicate(timeout=20)
    outs = [o1.strip(), o2.strip()]
    owners = [o for o in outs if o.startswith("OWNER")]
    refused = [o for o in outs if o == "REFUSED"]
    assert len(owners) == 1 and len(refused) == 1
    # by now the winner has already released (it slept, then released, then
    # exited) -- assert the lock is clean, not that it is still held
    assert not SingleWriterLock(led).lock_path.exists()


# --------------------------------------------------------------------------- (f) clean restart
def test_clean_close_followed_by_restart_succeeds(tmp_path):
    """(f) Clean close followed by restart succeeds."""
    led = tmp_path / "v2.db"
    lk = SingleWriterLock(led).acquire()
    token = lk._owner_token
    child = _sleeper(10)
    try:
        lk.rebind_owner(pid=child.pid)
    finally:
        child.terminate()
        child.wait(timeout=10)
    assert _wait_dead(child.pid)
    # "close" releases by token (mirrors stop_stack), not via the original instance
    assert SingleWriterLock.release_by_token(led, token) is True
    got = SingleWriterLock(led).acquire()          # restart: must succeed cleanly
    got.release()


# --------------------------------------------------------------------------- (e) bounded rollback
def test_partial_startup_failure_rolls_back_spawned_processes_and_releases(monkeypatch, tmp_path):
    """(e) Partial startup failure: bounded cleanup within budget, using REAL
    spawned processes for the rollback/termination path. The cmdline carries
    a real TalonX marker so the ownership-verified terminate logic (the same
    one ``stop_stack`` uses) genuinely recognises and reaps them."""
    import talonx_ops.prospective.proc as proc

    real_children: list[subprocess.Popen] = []

    def _fake_spawn(argv, *, log_path, env=None):
        marker = "talonx_v2.run" if "supervisor" not in " ".join(argv) else "talonx_ops.supervisor"
        p = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", f"--{marker}"], env=_ENV,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            # match production _spawn's creation flags exactly -- a plain
            # (non-detached) child inherits this test's console, and a real
            # reproduction showed that combination can make Windows stall a
            # cmdline/liveness re-query indefinitely while its .venv-shim
            # parent is exiting. Detached, own-process-group is the REAL
            # shape supervisor/companion children are always spawned in.
            creationflags=proc._DETACH)
        real_children.append(p)
        return p.pid

    monkeypatch.setattr(proc, "_spawn", _fake_spawn)
    # NOTE: deliberately NOT patching proc.time.sleep here -- _terminate()'s
    # own grace-period wait loop uses time.sleep(0.5) to THROTTLE its poll;
    # no-op'ing that turns a bounded wait into a tight busy-spin against
    # real, unmocked wall-clock deadlines, which is both wasteful and (per a
    # concrete repro during development) can starve the very termination it
    # is polling for. A couple of real seconds of setup delay here is fine.

    led = tmp_path / "v2.db"
    lock = SingleWriterLock(led).acquire()
    sd = tmp_path / "session"
    sd.mkdir()
    (sd / "logs").mkdir()

    def _boom(*a, **k):
        raise RuntimeError("simulated checkpoint-daemon spawn failure")

    # let supervisor + v2 companion spawn for real, then fail the 3rd spawn
    calls = {"n": 0}
    orig_fake = _fake_spawn

    def _fake_spawn_then_fail(argv, *, log_path, env=None):
        calls["n"] += 1
        if calls["n"] >= 3:
            _boom()
        return orig_fake(argv, log_path=log_path, env=env)

    monkeypatch.setattr(proc, "_spawn", _fake_spawn_then_fail)

    try:
        with pytest.raises(RuntimeError):
            proc._start_stack_locked(
                sd, sd / "logs", sys.executable, env={}, tick_seconds=300,
                heartbeat_seconds=30, live_lookback_days=45, with_dashboard=True,
                with_checkpoint_daemon=True, checkpoint_every_s=1800,
                pricing_mode="csv", execution_scope="none", deliver=False,
                transport="dryrun", lock=lock)
        # bounded rollback: both real children that DID spawn are reaped
        for p in real_children:
            assert _wait_dead(p.pid, timeout=15.0), f"pid {p.pid} survived rollback"
        # no residual -> the lock was safely released
        assert not lock.lock_path.exists()
    finally:
        for p in real_children:
            if p.poll() is None:
                p.kill()


def test_partial_startup_failure_keeps_the_lock_if_a_writer_could_not_be_reaped(monkeypatch, tmp_path):
    """(e) complement -- decision-logic check: if rollback cannot fully clear
    the spawned tree (residual survives), the lock must be KEPT, not
    released, so protection remains. ``_terminate`` itself is stubbed here to
    report an unreachable residual (an unkillable process is not something a
    unit test can safely construct on a shared CI box); the OS-level
    terminate/kill path is exercised for real in the sibling test above."""
    import talonx_ops.prospective.proc as proc

    monkeypatch.setattr(proc, "_spawn", lambda argv, *, log_path, env=None: 999999)
    monkeypatch.setattr(proc, "_terminate",
                        lambda pid, **k: {"status": "residual", "residual": [{"pid": pid, "cmd": "x"}]})
    monkeypatch.setattr(proc.time, "sleep", lambda *_: None)

    led = tmp_path / "v2.db"
    lock = SingleWriterLock(led).acquire()
    sd = tmp_path / "session"
    sd.mkdir()
    (sd / "logs").mkdir()

    calls = {"n": 0}
    orig_spawn = proc._spawn

    def _fail_third(argv, *, log_path, env=None):
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RuntimeError("simulated failure")
        return orig_spawn(argv, log_path=log_path, env=env)

    monkeypatch.setattr(proc, "_spawn", _fail_third)

    with pytest.raises(RuntimeError):
        proc._start_stack_locked(
            sd, sd / "logs", sys.executable, env={}, tick_seconds=300,
            heartbeat_seconds=30, live_lookback_days=45, with_dashboard=True,
            with_checkpoint_daemon=True, checkpoint_every_s=1800,
            pricing_mode="csv", execution_scope="none", deliver=False,
            transport="dryrun", lock=lock)
    assert lock.lock_path.exists()            # KEPT -- residual writer reported
    lock.release()
