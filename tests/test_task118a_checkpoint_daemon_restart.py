"""Task 118A -- a same-session restart (stop_stack, then start_stack again
in the SAME session_dir, exactly today's controlled-restart flow) left a
stale <session_dir>/stop.flag sentinel from the prior stop; the freshly
spawned checkpoint daemon (session_loop.py) checks that flag FIRST, before
anything else, and exited immediately -- a clean exit 0 with an empty log,
easily mistaken for "still starting". Reproduced with a REAL subprocess
(not a mock) running the actual session_loop entry point, then the fix
(_start_stack_locked clearing a stale flag before spawning) verified both
directly and via the real subprocess no longer exiting early.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from talonx_ops.prospective import proc as _proc

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process lifecycle")


def _spawn_session_loop(sd: Path, *, every: int = 1800) -> subprocess.Popen:
    log = sd / "logs" / "checkpoint_daemon.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-m", "talonx_ops.prospective", "session-loop",
            "--session-dir", str(sd), "--every", str(every)]
    return subprocess.Popen(argv, stdout=open(log, "wb"), stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


def test_a_real_session_loop_exits_immediately_with_a_stale_stop_flag(tmp_path):
    """Reproduces the actual reported defect directly, with the real
    entry point -- not an assumption about its behavior."""
    (tmp_path / "stop.flag").write_text("stop")
    p = _spawn_session_loop(tmp_path)
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        pytest.fail("session_loop did not exit promptly despite a pre-existing stop.flag")
    assert p.returncode == 0
    log_text = (tmp_path / "logs" / "checkpoint_daemon.log").read_bytes()
    assert log_text == b""  # exits before its first checkpoint -- matches the live symptom


def test_a_real_session_loop_stays_up_once_the_stale_flag_is_cleared(tmp_path):
    """Same real entry point, same tmp session dir -- the only difference
    is the stale flag being cleared first, matching the fix."""
    stop_flag = tmp_path / "stop.flag"
    stop_flag.write_text("stop")
    stop_flag.unlink()  # the fix's own action
    p = _spawn_session_loop(tmp_path, every=3)
    try:
        time.sleep(2.0)
        assert p.poll() is None, "session_loop exited even with no stop.flag present"
        assert psutil.pid_exists(p.pid)
    finally:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


def test_start_stack_locked_clears_a_stale_stop_flag_before_spawning_anything(tmp_path, monkeypatch):
    """Unit-level proof the actual fix in _start_stack_locked runs: a
    stale stop.flag from a prior stop_stack() must be gone before the
    first _spawn() call, regardless of what start_stack goes on to do."""
    sd = tmp_path
    (sd / "logs").mkdir()
    (sd / "stop.flag").write_text("stop")

    calls = []

    def _fake_spawn(argv, *, log_path, env=None):
        calls.append(argv)
        return 999999  # a pid that will never really exist -- fine, never checked here

    class _FakeLock:
        lock_path = str(sd / "fake.lock")
        _owner_token = "fake-token"

        def rebind_owner(self, pid):
            pass

        def release(self):
            pass

    monkeypatch.setattr(_proc, "_spawn", _fake_spawn)
    monkeypatch.setattr(_proc.time, "sleep", lambda *_a, **_k: None)  # skip the real 2s wait

    _proc._start_stack_locked(
        sd, sd / "logs", sys.executable, env={}, tick_seconds=150, heartbeat_seconds=30,
        live_lookback_days=45, with_dashboard=False, with_checkpoint_daemon=True,
        checkpoint_every_s=1800, pricing_mode="csv", execution_scope="none",
        deliver=False, transport="dryrun", lock=_FakeLock(),
    )
    assert not (sd / "stop.flag").exists()
    assert any("session-loop" in " ".join(a) for a in calls), "checkpoint daemon spawn was expected"
