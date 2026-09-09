"""
Detached process start/stop for the prospective operator (Windows-first).

The base stack is owned by the existing ``talonx_ops.supervisor run``
process (which itself owns Phase-14 controlled shutdown).  The V2
companion and the checkpoint daemon are separate detached children.
PIDs are tracked in ``<session_dir>/session.pids.json``.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from talonx_ops.prospective.paths import REPO_ROOT, V2_DB_PATH, V2_STATUS_PATH, atomic_write

_IS_WIN = os.name == "nt"
_DETACH = 0
if _IS_WIN:
    _DETACH = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)


def _spawn(argv: list[str], *, log_path: Path, env: dict[str, str] | None = None) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log_path, "ab", buffering=0)
    full_env = {**os.environ, **(env or {})}
    kw: dict[str, Any] = dict(cwd=str(REPO_ROOT), stdout=fh, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, env=full_env)
    if _IS_WIN:
        kw["creationflags"] = _DETACH
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen(argv, **kw)  # noqa: S603
    return p.pid


def _pids_file(session_dir: Path) -> Path:
    return session_dir / "session.pids.json"


def read_pids(session_dir: str | Path) -> dict[str, Any]:
    p = _pids_file(Path(session_dir))
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except Exception:  # noqa: BLE001
        return False


def start_stack(session_dir: str | Path, *, env: dict[str, str],
                tick_seconds: int = 300, heartbeat_seconds: int = 30,
                live_lookback_days: int = 45, with_dashboard: bool = True,
                with_checkpoint_daemon: bool = True,
                checkpoint_every_s: int = 1800) -> dict[str, Any]:
    sd = Path(session_dir)
    sd.mkdir(parents=True, exist_ok=True)
    logs = sd / "logs"
    py = sys.executable

    sup_argv = [py, "-m", "talonx_ops.supervisor", "run"]
    if not with_dashboard:
        sup_argv.append("--no-dashboard")
    sup_pid = _spawn(sup_argv, log_path=logs / "supervisor.log", env=env)

    time.sleep(2.0)  # let the supervisor claim the Telegram poller before the companion

    v2_argv = [py, "-m", "talonx_v2.run", "--mode", "live", "--form4-source", "insider",
               "--db", str(V2_DB_PATH), "--status-path", str(V2_STATUS_PATH),
               "--tick-seconds", str(tick_seconds), "--heartbeat-seconds", str(heartbeat_seconds),
               "--live-lookback-days", str(live_lookback_days)]
    v2_pid = _spawn(v2_argv, log_path=logs / "v2_companion.log", env=env)

    daemon_pid = None
    if with_checkpoint_daemon:
        d_argv = [py, "-m", "talonx_ops.prospective", "session-loop",
                  "--session-dir", str(sd), "--every", str(checkpoint_every_s)]
        daemon_pid = _spawn(d_argv, log_path=logs / "checkpoint_daemon.log", env=env)

    info = {"supervisor_pid": sup_pid, "v2_companion_pid": v2_pid,
            "checkpoint_daemon_pid": daemon_pid,
            "started_utc": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
            "v2_argv": v2_argv}
    atomic_write(_pids_file(sd), json.dumps(info, indent=2))
    return info


def _terminate(pid: int | None, *, grace_s: float = 30.0) -> str:
    if not pid or not _alive(pid):
        return "not_running"
    try:
        import psutil
        p = psutil.Process(pid)
        if _IS_WIN:
            try:
                p.send_signal(signal.CTRL_BREAK_EVENT)  # noqa: PLE1507
            except Exception:  # noqa: BLE001
                p.terminate()
        else:
            p.terminate()
        gone, alive = psutil.wait_procs([p], timeout=grace_s)
        if alive:
            for a in alive:
                a.kill()
            return "killed"
        return "stopped"
    except Exception as exc:  # noqa: BLE001
        return f"error:{type(exc).__name__}"


def stop_stack(session_dir: str | Path, *, grace_s: float = 45.0) -> dict[str, Any]:
    sd = Path(session_dir)
    info = read_pids(sd)
    # order: checkpoint daemon -> V2 companion -> supervisor (which does Phase-14)
    (sd / "stop.flag").write_text("stop", encoding="utf-8")
    res = {"checkpoint_daemon": _terminate(info.get("checkpoint_daemon_pid"), grace_s=15),
           "v2_companion": _terminate(info.get("v2_companion_pid"), grace_s=grace_s),
           "supervisor": _terminate(info.get("supervisor_pid"), grace_s=grace_s)}
    time.sleep(2.0)
    # sweep for any residual talonx python
    residual = []
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            cl = " ".join(p.info.get("cmdline") or [])
            if p.info.get("name", "").lower().startswith("python") and any(
                    x in cl for x in ("run_talonx.py", "talonx_v2.run", "talonx_ops.supervisor",
                                      "talonx_signals.run", "talonx_ingest.intelligence.service",
                                      "dashboard_web.py")):
                residual.append({"pid": p.info["pid"], "cmd": cl[:90]})
    except Exception:  # noqa: BLE001
        pass
    res["residual_talonx_processes"] = residual
    res["ports"] = {str(port): _port_open(port) for port in (8787, 8760, 8770, 8501)}
    # PID registry
    pidf = REPO_ROOT / ".run" / "talonx.pids.json"
    res["pid_registry_cleared"] = not pidf.exists()
    res["v2_lane_db_intact"] = Path(V2_DB_PATH).exists()
    return res


def _port_open(p: int) -> bool:
    import socket
    s = socket.socket()
    s.settimeout(0.4)
    try:
        return s.connect_ex(("127.0.0.1", p)) == 0
    finally:
        s.close()


def verify_running(session_dir: str | Path, *, retries: int = 10,
                  delay_s: float = 3.0) -> dict[str, Any]:
    """Bounded retry over the ACTUAL required components (Task 117 Phase 0 4.1).

    Startup is not "done" the moment a heartbeat file appears -- the
    dashboard port bind, the supervisor, the companion process and the
    checkpoint daemon each come up on their own schedule.  Poll until all
    required signals are up or ``retries`` is exhausted; report per-check
    plus how many attempts it took and whether it is ``ready``.
    """
    info = read_pids(session_dir)
    req = ("supervisor_pid", "v2_companion_pid")   # checkpoint daemon + port are best-effort
    attempt = 0
    checks: dict[str, Any] = {}
    for attempt in range(1, max(1, retries) + 1):
        checks = {
            "supervisor_alive": _alive(info.get("supervisor_pid")),
            "v2_companion_alive": _alive(info.get("v2_companion_pid")),
            "checkpoint_daemon_alive": _alive(info.get("checkpoint_daemon_pid")),
            "dashboard_8787": _port_open(8787),
        }
        if all(_alive(info.get(k)) for k in req):
            break
        if attempt < retries:
            time.sleep(delay_s)
    checks["attempts"] = attempt
    checks["ready"] = all(_alive(info.get(k)) for k in req)
    return checks
