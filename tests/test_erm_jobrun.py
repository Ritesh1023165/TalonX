"""Orphan fix (runner, not fingerprinted): a stage process tree runs inside a Job Object with KILL_ON_JOB_CLOSE.
(A) the runner's own timeout (60 s) kills the WHOLE tree and leaves no survivor;
(B) if the runner process itself is killed, KILL_ON_JOB_CLOSE kills the whole tree.
The fake worker goes through the venv shim, starts the real interpreter and a grandchild, and sleeps 600 s."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "research" / "event_response_map_v1" / "tools"
VENV_PY = Path("C:/workspace/TalonX/.venv/Scripts/python.exe")
PS = "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects")


def _pids(pidfile: Path, timeout=60) -> list[int]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pidfile.exists() and pidfile.read_text().strip():
            return [int(x) for x in pidfile.read_text().split()]
        time.sleep(0.5)
    raise AssertionError("fake worker never wrote its pids")


def _alive(pids) -> list[int]:
    return [p for p in pids if psutil.pid_exists(p) and psutil.Process(p).status() != psutil.STATUS_ZOMBIE]


def _cmd(pidfile: Path) -> str:
    return f'"{VENV_PY}" "{TOOLS / "fake_worker.py"}" "{pidfile}"'


def test_a_runner_timeout_kills_the_whole_tree(tmp_path):
    pidfile = tmp_path / "pids.txt"
    script = (f". '{TOOLS / 'jobrun.ps1'}'; $r = Invoke-InJob -CommandLine '{_cmd(pidfile)}' "
              f"-WorkingDirectory '{tmp_path}' -TimeoutSeconds 60; "
              "\"TIMEDOUT=$($r.TimedOut) ACTIVE_AFTER=$($r.ActiveProcessesAfter) PID=$($r.Pid)\"")
    t0 = time.time()
    out = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                         capture_output=True, text=True, timeout=180).stdout
    elapsed = time.time() - t0
    pids = _pids(pidfile, timeout=1)
    assert "TIMEDOUT=True" in out and "ACTIVE_AFTER=0" in out, out
    assert 55 <= elapsed <= 120, elapsed
    time.sleep(1)
    assert _alive(pids) == [], f"survivors after the runner timeout: {_alive(pids)}"


def test_b_killing_the_runner_kills_the_whole_tree(tmp_path):
    pidfile = tmp_path / "pids.txt"
    script = (f". '{TOOLS / 'jobrun.ps1'}'; $r = Invoke-InJob -CommandLine '{_cmd(pidfile)}' "
              f"-WorkingDirectory '{tmp_path}' -TimeoutSeconds 3600")
    runner = subprocess.Popen([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script])
    pids = _pids(pidfile)
    assert len(_alive(pids)) == 2
    runner.kill()                                   # what Task Scheduler's execution limit does to the runner
    runner.wait(30)
    t0 = time.time()
    while _alive(pids) and time.time() - t0 < 15:
        time.sleep(0.5)
    assert _alive(pids) == [], f"orphans survived the runner: {_alive(pids)}"
