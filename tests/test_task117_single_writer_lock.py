"""
Task 117 Section 3 -- atomic single-writer lock.

These are REAL tests: real files, real ``os.open(O_CREAT|O_EXCL)``, and real
concurrent subprocesses. Not mocked process scans.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from talonx_ops.prospective.lock import (
    ConcurrentStartError, SingleWriterLock, StaleLockError, _pid_alive,
)


def test_acquire_release_roundtrip(tmp_path):
    led = tmp_path / "v2.db"
    lk = SingleWriterLock(led)
    lk.acquire()
    assert lk.lock_path.exists()
    owner = lk.read_owner()
    assert owner["pid"] == os.getpid() and owner["ledger_path"] == str(led.resolve())
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
    # forge a lock owned by a PID that does not exist
    dead = 2_000_000_000
    assert not _pid_alive(dead)
    lk.lock_path.write_text(json.dumps(
        {"pid": dead, "host": "x", "started_utc": "2026-01-01T00:00:00+00:00",
         "ledger_path": str(led.resolve())}), encoding="utf-8")
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
        {"pid": os.getpid(), "host": "x", "started_utc": "2026-01-01T00:00:00+00:00",
         "ledger_path": "/some/other/ledger.db"}), encoding="utf-8")
    assert lk._owner_state() == "stale"                       # identity mismatch


_CHILD = textwrap.dedent("""
    import sys, time, json
    from talonx_ops.prospective.lock import SingleWriterLock, ConcurrentStartError
    led = sys.argv[1]
    # small stagger so both are genuinely contending
    time.sleep(0.05)
    try:
        lk = SingleWriterLock(led).acquire()
        print("ACQUIRED")
        time.sleep(1.5)          # hold it so the sibling definitely collides
        lk.release()
        sys.exit(0)
    except ConcurrentStartError:
        print("REFUSED")
        sys.exit(7)
""")


def test_two_real_concurrent_starts_yield_exactly_one_owner(tmp_path):
    led = str(tmp_path / "v2.db")
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    p1 = subprocess.Popen([sys.executable, str(script), led], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    p2 = subprocess.Popen([sys.executable, str(script), led], env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    o1, _ = p1.communicate(timeout=25)
    o2, _ = p2.communicate(timeout=25)
    outs = [o1.strip(), o2.strip()]
    rcs = sorted([p1.returncode, p2.returncode])
    assert "ACQUIRED" in outs[0] + outs[1]
    assert "REFUSED" in outs[0] + outs[1]
    assert rcs == [0, 7]                                      # one owner, one refused
    assert not (tmp_path / "v2.db.startlock").exists()        # released by the winner
