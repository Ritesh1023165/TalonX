"""
Task 117 Phase 0 Phase 6 -- ACTUAL isolated Windows lifecycle smoke test.

Real subprocesses (not mocks) driven through the real
``talonx_ops.prospective.proc`` stop path.  Disposable session dir, inert
sleeper children that mimic the .venv-shim -> real-worker grandchild
layout that defeats a naive ``TerminateProcess`` on Windows.

Covers: normal tree stop, unresponsive child -> bounded escalation,
shim/grandchild ownership (grandchild reaped), stale/reused PID record
(NOT killed), no respawn, one bounded budget.

No Redis, no network, no TalonX production component is launched.  The
marker string is passed as a REAL argv element so psutil.cmdline() (and
therefore proc._still_the_same) sees it.
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

from talonx_ops.prospective import proc as _proc

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows lifecycle smoke")

_MARK = "talonx_v2.run"          # proc._TALONX_MARKERS

_SHIM_SRC = textwrap.dedent("""
    import subprocess, sys, time
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", sys.argv[1]])
    print("SHIM_UP", flush=True)
    time.sleep(600)
""")

_DEAF_SRC = textwrap.dedent("""
    import signal, time
    for s in ("SIGTERM", "SIGBREAK", "SIGINT"):
        try:
            signal.signal(getattr(signal, s), lambda *a: None)
        except Exception:
            pass
    time.sleep(600)
""")


def _spawn(src: str, sd: Path, name: str) -> int:
    f = sd / f"{name}.py"
    f.write_text(src)
    p = subprocess.Popen([sys.executable, str(f), _MARK],
                         creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    time.sleep(2.0)   # let a grandchild come up
    return p.pid


def _alive(pid) -> bool:
    import psutil
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False


def test_stop_stack_reaps_the_whole_owned_tree(tmp_path):
    import psutil
    sup = _spawn(_SHIM_SRC, tmp_path, "sup")
    kids = [c.pid for c in psutil.Process(sup).children(recursive=True)]
    assert kids, "shim should have a grandchild worker"
    (tmp_path / "session.pids.json").write_text(json.dumps({"supervisor_pid": sup}))

    t0 = time.monotonic()
    res = _proc.stop_stack(tmp_path, grace_s=8.0, overall_budget_s=30.0)
    assert time.monotonic() - t0 < 32.0                 # one bounded budget
    assert res["residual_talonx_processes"] == []
    assert res["supervisor"]["tree_size"] >= 2
    assert not _alive(sup)
    for k in kids:
        assert not _alive(k), f"grandchild {k} orphaned"


def test_unresponsive_child_is_escalated_within_budget(tmp_path):
    deaf = _spawn(_DEAF_SRC, tmp_path, "deaf")
    (tmp_path / "session.pids.json").write_text(json.dumps({"supervisor_pid": deaf}))
    t0 = time.monotonic()
    res = _proc.stop_stack(tmp_path, grace_s=4.0, overall_budget_s=20.0)
    assert time.monotonic() - t0 < 22.0
    assert not _alive(deaf)
    assert res["supervisor"]["status"] in ("killed", "stopped")
    assert res["residual_talonx_processes"] == []


def test_stale_or_reused_pid_record_is_not_killed(tmp_path):
    # an unrelated long-lived process (NO TalonX marker) whose pid is in the registry
    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    time.sleep(0.5)
    (tmp_path / "session.pids.json").write_text(json.dumps({"supervisor_pid": victim.pid}))
    res = _proc.stop_stack(tmp_path, grace_s=3.0, overall_budget_s=10.0)
    assert _alive(victim.pid), "an unrelated process must NOT be terminated"
    assert res["supervisor"]["status"] == "not_running"
    victim.kill()


def test_no_respawn_after_stop(tmp_path):
    sup = _spawn(_SHIM_SRC, tmp_path, "sup")
    (tmp_path / "session.pids.json").write_text(json.dumps({"supervisor_pid": sup}))
    _proc.stop_stack(tmp_path, grace_s=6.0, overall_budget_s=20.0)
    time.sleep(3.0)
    v = _proc.verify_running(tmp_path, retries=1, delay_s=0)
    assert v["supervisor_alive"] is False and v["ready"] is False
