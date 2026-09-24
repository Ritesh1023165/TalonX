"""
Independent process management (REQ S14-03).

Every component is its own OS process (``python -m talonx_opportunity component <name>``) with its own lock,
heartbeat, stop flag and store. ``up`` starts the missing ones; ``--supervise`` keeps restarting ONLY the component
that died (bounded exponential backoff), never touching the others. ``restart <name>`` stops and starts exactly one
component. If the supervisor itself dies, the components keep running (they are detached), and a second copy of a
component cannot start (lock).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from talonx_opportunity.db import REPO_ROOT, root_dir
from talonx_opportunity.runtime import RuntimeStore, _pid_alive, lock_path, stop_flag

COMPONENTS = ("ingestion", "discovery", "evaluator:INTRADAY", "evaluator:SAME_DAY", "evaluator:SHORT_TERM",
              "evaluator:LONG_TERM", "notifier", "outcomes", "reporting")
HEARTBEAT_STALE_S = 180.0


def _lock_pid(root, name: str) -> int | None:
    p = lock_path(root, name)
    try:
        pid = int(p.read_text().strip() or 0)
    except (OSError, ValueError):
        return None
    return pid if pid and _pid_alive(pid) else None


def is_running(root, name: str) -> bool:
    return _lock_pid(root, name) is not None


def spawn(root, name: str, *, env: dict | None = None) -> int:
    logs = root_dir(root) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = open(logs / (name.replace(":", "_") + ".log"), "ab", buffering=0)  # noqa: SIM115
    e = dict(os.environ if env is None else env)
    if root:
        e["TALONX_OPP_ROOT"] = str(root)
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008      # DETACHED_PROCESS
    p = subprocess.Popen([sys.executable, "-m", "talonx_opportunity", "component", name], cwd=str(REPO_ROOT),
                         stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=e,
                         creationflags=flags, close_fds=True)
    return p.pid


def request_stop(root, name: str) -> None:
    stop_flag(root, name).write_text(datetime.now(timezone.utc).isoformat())


def wait_stopped(root, name: str, timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not is_running(root, name):
            return True
        time.sleep(1.0)
    return False


def stop(root, name: str, timeout_s: float = 60.0, *, force: bool = True) -> bool:
    request_stop(root, name)
    if wait_stopped(root, name, timeout_s):
        return True
    pid = _lock_pid(root, name)
    if force and pid:
        try:
            import psutil
            proc = psutil.Process(pid)
            for ch in proc.children(recursive=True):
                ch.kill()
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        RuntimeStore(root).event(name, "FORCE_KILLED", {"pid": pid})
    return wait_stopped(root, name, 10.0)


def restart(root, name: str, *, env: dict | None = None) -> int:
    stop(root, name)
    try:
        stop_flag(root, name).unlink()
    except OSError:
        pass
    return spawn(root, name, env=env)


def up(root, names=COMPONENTS, *, env: dict | None = None) -> dict[str, str]:
    out = {}
    for n in names:
        if is_running(root, n):
            out[n] = "ALREADY_RUNNING"
            continue
        try:
            stop_flag(root, n).unlink()
        except OSError:
            pass
        out[n] = f"STARTED pid={spawn(root, n, env=env)}"
    return out


def supervise(root, names=COMPONENTS, *, env: dict | None = None, poll_s: float = 15.0,
              max_backoff_s: float = 600.0, should_stop=lambda: False) -> None:
    """Restart ONLY a component that died without being asked to stop. Others are never touched."""
    fails: dict[str, int] = {}
    next_ok: dict[str, float] = {}
    rt = RuntimeStore(root)
    while not should_stop():
        for n in names:
            if is_running(root, n) or stop_flag(root, n).exists():
                continue
            if time.monotonic() < next_ok.get(n, 0.0):
                continue
            fails[n] = fails.get(n, 0) + 1
            pid = spawn(root, n, env=env)
            rt.event(n, "SUPERVISOR_RESTART", {"pid": pid, "attempt": fails[n]})
            next_ok[n] = time.monotonic() + min(max_backoff_s, 15.0 * 2 ** min(fails[n] - 1, 6))
        time.sleep(poll_s)

