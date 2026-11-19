"""
Independent process management (REQ S14-03).

Every component is its own OS process (``python -m talonx_opportunity component <name>``) with its own lock,
heartbeat, stop flag and store. ``up`` starts the missing ones; ``--supervise`` keeps restarting ONLY the component
that died (bounded exponential backoff), never touching the others. ``restart <name>`` stops and starts exactly one
component. If the supervisor itself dies, the components keep running (they are detached), and a second copy of a
component cannot start (lock).

2026-10-01 (P0 runtime hardening):
  * ownership/liveness = the component's exclusive OS lock (runtime.ComponentLock); the PID file is display only;
  * restart() spawns ONLY after stop() confirmed the old owner released its lock, else RESTART_ABORTED_STOP_FAILED;
  * ONE restart authority: while a supervisor heartbeat is fresh, ``restart <c>`` only writes control/<c>.restart and
    the supervise loop performs it with its own environment; a direct CLI spawn happens only with no live supervisor;
  * the supervisor holds its own OS lock (one supervisor) and writes a non-fatal heartbeat every loop.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

from talonx_opportunity.db import REPO_ROOT, iso, root_dir
from talonx_opportunity.runtime import (AlreadyRunning, ComponentLock, RuntimeStore, _beat, lock_held, lock_path,
                                        read_pid, stop_flag)

COMPONENTS = ("ingestion", "discovery", "evaluator:INTRADAY", "evaluator:SAME_DAY", "evaluator:SHORT_TERM",
              "evaluator:LONG_TERM", "notifier", "outcomes", "reporting",
              # 2026-09-26 (P0 package 2A): supervised like every other component (one instance via its lock,
              # heartbeat, respawn only after an unrequested death). Mode/enable flags come from the supervisor env.
              "promotion", "sentinel")
HEARTBEAT_STALE_S = 180.0
# A just-spawned component needs a few seconds (imports) before it writes its lock; judging it "dead" earlier made the
# supervisor spawn a second copy (refused by the lock, but logged as a spurious SUPERVISOR_RESTART). 2026-09-25 fix.
STARTUP_GRACE_S = 90.0
_SPAWNED_AT: dict[str, float] = {}
SUPERVISOR_SOURCES = ("talonx_opportunity/supervise.py", "talonx_opportunity/__main__.py")
SUPERVISOR = "supervisor"
SUPERVISOR_FRESH_S = 60.0          # a supervisor heartbeat younger than this makes the supervisor the restart authority


def _lock_pid(root, name: str) -> int | None:
    """PID of the CURRENT lock owner (display / targeted kill). None when nobody holds the lock -- the PID file alone
    is never trusted (it may name a reused PID after a reboot)."""
    return read_pid(root, name) if lock_held(root, name) else None


def is_running(root, name: str) -> bool:
    return lock_held(root, name)


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
    _SPAWNED_AT[name] = time.monotonic()
    return p.pid


def in_startup_grace(name: str, grace_s: float = STARTUP_GRACE_S) -> bool:
    t = _SPAWNED_AT.get(name)
    return t is not None and time.monotonic() - t < grace_s


def supervisor_version() -> str:
    import hashlib
    h = hashlib.sha256()
    for rel in SUPERVISOR_SOURCES:
        f = REPO_ROOT / rel
        h.update(rel.encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n") if f.exists() else b"MISSING")
    return h.hexdigest()[:12]


def request_stop(root, name: str) -> None:
    stop_flag(root, name).write_text(datetime.now(timezone.utc).isoformat())


def wait_stopped(root, name: str, timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not is_running(root, name):
            return True
        time.sleep(1.0)
    return False


def _is_component_process(pid: int, name: str) -> bool:
    """Force-kill guard: only a process whose command line is THIS component may be killed (never a reused PID)."""
    try:
        import psutil
        cmd = psutil.Process(pid).cmdline()
    except Exception:  # noqa: BLE001
        return False
    return "talonx_opportunity" in cmd and "component" in cmd and name in cmd


def stop(root, name: str, timeout_s: float = 60.0, *, force: bool = True) -> bool:
    """True only when the component's OS lock is confirmed released (the old owner is gone)."""
    request_stop(root, name)
    if wait_stopped(root, name, timeout_s):
        return True
    pid = _lock_pid(root, name)
    if force and pid and _is_component_process(pid, name):
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


def restart(root, name: str, *, env: dict | None = None) -> dict:
    """Stop, and spawn ONLY if the stop is confirmed (lock released). Never two owners, never a blind spawn."""
    if not stop(root, name):
        detail = {"reason": "stop() did not confirm the old process is gone (lock still held)",
                  "pid_file": read_pid(root, name)}
        RuntimeStore(root).event(name, "RESTART_ABORTED_STOP_FAILED", detail)
        return {"ok": False, **detail}
    try:
        stop_flag(root, name).unlink()
    except OSError:
        pass
    pid = spawn(root, name, env=env)
    RuntimeStore(root).event(name, "RESTARTED", {"pid": pid})
    return {"ok": True, "pid": pid}


def restart_request_path(root, name: str):
    return stop_flag(root, name).with_suffix(".restart")


def supervisor_alive(root, fresh_s: float = SUPERVISOR_FRESH_S) -> bool:
    """A supervisor whose heartbeat is fresher than ``fresh_s`` is the single restart authority."""
    try:
        rt = RuntimeStore(root, readonly=True)
    except Exception:  # noqa: BLE001 -- no registry yet: no supervisor
        return False
    try:
        row = rt.con.execute("SELECT state, heartbeat_utc FROM components WHERE name=?", (SUPERVISOR,)).fetchone()
    finally:
        rt.close()
    if row is None or row["state"] != "RUNNING" or not row["heartbeat_utc"]:
        return False
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["heartbeat_utc"])).total_seconds()
    return age <= fresh_s


def request_restart(root, name: str) -> dict:
    """CLI side: hand the restart to the live supervisor (it restarts with its OWN environment)."""
    restart_request_path(root, name).write_text(json.dumps({"requested_utc": iso(), "by_pid": os.getpid()}))
    RuntimeStore(root).event(name, "RESTART_REQUESTED", {"by_pid": os.getpid()})
    return {"ok": True, "requested": True}


def cli_restart(root, name: str, *, env: dict | None = None) -> dict:
    """One restart authority: a fresh supervisor performs it; a direct spawn only when no supervisor is alive."""
    if supervisor_alive(root):
        return request_restart(root, name)
    return {**restart(root, name, env=env), "direct": True}


def _process_restart_requests(root, names, env, rt) -> None:
    for n in names:
        req = restart_request_path(root, n)
        if not req.exists():
            continue
        try:
            body = req.read_text()
            req.unlink()                                  # consume first: a request is performed at most once
        except OSError:
            continue
        res = restart(root, n, env=env)
        rt.event(n, "SUPERVISOR_PERFORMED_RESTART", {"request": body, "result": res})


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
    """Restart ONLY a component that died without being asked to stop. Others are never touched. Also performs
    operator restart requests (control/<c>.restart) -- the single restart authority while it is alive."""
    fails: dict[str, int] = {}
    next_ok: dict[str, float] = {}
    lk = ComponentLock(lock_path(root, SUPERVISOR))
    if not lk.try_acquire():
        raise AlreadyRunning(f"a supervisor is already running (pid file says {read_pid(root, SUPERVISOR)})")
    rt = RuntimeStore(root)
    try:
        # the supervisor records its own deployment boundary (OPERATIONS_ONLY; never part of any component's version)
        from talonx_opportunity.runtime import commit_sha
        rt.record_start(SUPERVISOR, version=supervisor_version(),
                        config_fps={"deliver": (env or os.environ).get("TALONX_OPP_DELIVER", "0")}, commit=commit_sha())
        _beat(rt, SUPERVISOR, pid=os.getpid(), state="RUNNING", started_utc=iso(), heartbeat_utc=iso())
        while not should_stop():
            _process_restart_requests(root, names, env, rt)
            for n in names:
                if is_running(root, n) or stop_flag(root, n).exists() or in_startup_grace(n):
                    continue
                if time.monotonic() < next_ok.get(n, 0.0):
                    continue
                fails[n] = fails.get(n, 0) + 1
                pid = spawn(root, n, env=env)
                rt.event(n, "SUPERVISOR_RESTART", {"pid": pid, "attempt": fails[n]})
                next_ok[n] = time.monotonic() + min(max_backoff_s, 15.0 * 2 ** min(fails[n] - 1, 6))
            _beat(rt, SUPERVISOR, pid=os.getpid(), state="RUNNING", heartbeat_utc=iso())   # non-fatal
            time.sleep(poll_s)
    finally:
        _beat(rt, SUPERVISOR, state="STOPPED", heartbeat_utc=iso())
        rt.close()
        lk.release()

