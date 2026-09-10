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


class ConcurrentStartError(RuntimeError):
    """A live prospective stack (supervisor or V2 companion) already owns the
    V2 lane -- starting again would create a second ledger writer."""


def _live_prior_stack() -> list[dict]:
    """Any RUNNING process that would collide with a fresh start: a
    ``talonx_v2.run --mode live`` companion (a second ``v2_lane.db`` writer),
    a ``talonx_ops.supervisor run``, or a ``prospective session-loop``.
    Best-effort; empty if psutil is unavailable."""
    hits: list[dict] = []
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return hits
    markers = (
        ("talonx_v2.run", "--mode"),        # the live V2 companion (ledger writer)
        ("talonx_ops.supervisor", "run"),
        ("talonx_ops.prospective", "session-loop"),
    )
    self_pid = os.getpid()
    for p in psutil.process_iter(["pid", "cmdline", "create_time"]):
        if p.pid == self_pid:
            continue
        try:
            cl = " ".join(p.info.get("cmdline") or [])
        except Exception:  # noqa: BLE001
            continue
        if not cl or "pytest" in cl:
            continue
        for a, b in markers:
            if a in cl and b in cl:
                hits.append({"pid": p.pid, "cmd": cl[:160],
                             "create_time": p.info.get("create_time")})
                break
    return hits


def assert_no_live_prior_stack() -> None:
    live = _live_prior_stack()
    if live:
        raise ConcurrentStartError(
            "refusing to start: a prospective stack is already running -- "
            + "; ".join(f"pid {h['pid']} ({h['cmd']})" for h in live)
        )


def startup_verdict(info: dict[str, Any], verify: dict[str, Any], *,
                    heartbeat_fresh: bool, within_grace: bool) -> str:
    """One of NOT_STARTED / STARTING / READY / FAILED_WITH_RESIDUALS.

    A missing MANDATORY component (supervisor OR companion) is never a
    cosmetic warning -- it makes the verdict STARTING (still in grace) or
    FAILED_WITH_RESIDUALS (grace elapsed and something is left running).
    """
    sup = bool(verify.get("supervisor_alive"))
    comp = bool(verify.get("v2_companion_alive"))
    residual = bool(_live_prior_stack())
    if sup and comp and heartbeat_fresh:
        return "READY"
    if not sup and not comp:
        return "FAILED_WITH_RESIDUALS" if residual else "NOT_STARTED"
    # partial: some mandatory component up, some not
    if within_grace:
        return "STARTING"
    return "FAILED_WITH_RESIDUALS"


def start_stack(session_dir: str | Path, *, env: dict[str, str],
                tick_seconds: int = 300, heartbeat_seconds: int = 30,
                live_lookback_days: int = 45, with_dashboard: bool = True,
                with_checkpoint_daemon: bool = True,
                checkpoint_every_s: int = 1800,
                pricing_mode: str = "csv", execution_scope: str = "none",
                deliver: bool = False, transport: str = "dryrun",
                allow_when_running: bool = False) -> dict[str, Any]:
    sd = Path(session_dir)
    sd.mkdir(parents=True, exist_ok=True)
    logs = sd / "logs"
    py = sys.executable

    # D4: a repeated / concurrent ``prospective start`` must not spawn a second
    # supervisor + companion (a second v2_lane.db writer).
    if not allow_when_running:
        assert_no_live_prior_stack()

    sup_argv = [py, "-m", "talonx_ops.supervisor", "run"]
    if not with_dashboard:
        sup_argv.append("--no-dashboard")
    sup_pid = _spawn(sup_argv, log_path=logs / "supervisor.log", env=env)

    time.sleep(2.0)  # let the supervisor claim the Telegram poller before the companion

    # the ONE V2 companion (Task 112T T1: never supervisor include_v2).  Task 117
    # final activation: the deployment pricing / execution-scope / delivery flags
    # are passed HERE so 'prospective start' launches the correctly-configured
    # companion -- no second manual companion, no scope-unenforced process.
    v2_argv = [py, "-m", "talonx_v2.run", "--mode", "live", "--form4-source", "insider",
               "--db", str(V2_DB_PATH), "--status-path", str(V2_STATUS_PATH),
               "--tick-seconds", str(tick_seconds), "--heartbeat-seconds", str(heartbeat_seconds),
               "--live-lookback-days", str(live_lookback_days),
               "--pricing-mode", pricing_mode, "--execution-scope", execution_scope]
    if deliver:
        v2_argv += ["--deliver", "--transport", transport]
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


_TALONX_MARKERS = ("run_talonx.py", "talonx_v2.run", "talonx_ops.supervisor",
                   "talonx_ops.prospective", "talonx_signals.run",
                   "talonx_ingest.intelligence.service", "dashboard_web.py")


def _owned_tree(pid: int) -> list[dict]:
    """Snapshot pid + every live descendant as {pid, create_time, cmd}.

    Windows ``TerminateProcess`` / ``CTRL_BREAK`` do NOT cascade to a child
    spawned ``CREATE_NEW_PROCESS_GROUP`` (each supervisor child is its own
    group leader and its .venv shim spawns the real worker as a grandchild).
    So the caller must know the descendants up-front to reap the orphans
    it owns -- and ONLY those (verified by create_time + cmdline).
    """
    out: list[dict] = []
    try:
        import psutil
        root = psutil.Process(pid)
        procs = [root] + root.children(recursive=True)
        for p in procs:
            try:
                out.append({"pid": p.pid, "create_time": p.create_time(),
                            "cmd": " ".join(p.cmdline()[:6])})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:  # noqa: BLE001
        pass
    return out


def _still_the_same(entry: dict) -> bool:
    """True iff `entry`'s pid is alive AND is the same process we snapshotted
    (create_time match) AND still looks like a TalonX component -- guards
    against PID reuse and against touching an unrelated process."""
    try:
        import psutil
        p = psutil.Process(entry["pid"])
        if abs(p.create_time() - entry["create_time"]) > 1.0:
            return False                       # PID reused
        cl = " ".join(p.cmdline())
        return any(m in cl for m in _TALONX_MARKERS)
    except Exception:  # noqa: BLE001
        return False


def _terminate(pid: int | None, *, grace_s: float = 30.0,
               tree: list[dict] | None = None) -> dict:
    """Ownership-verified, tree-aware stop of one session-owned process.

    Returns {status, signalled, tree_size, reaped, residual}.  A single
    ``grace_s`` budget covers the whole tree.  Only processes present in
    ``tree`` (or discovered as descendants) that pass ``_still_the_same``
    are ever terminated/killed.
    """
    if not pid or not _alive(pid):
        return {"status": "not_running", "signalled": pid, "tree_size": 0,
                "reaped": [], "residual": []}
    import psutil
    snapshot = tree if tree is not None else _owned_tree(pid)
    deadline = time.monotonic() + grace_s

    # OWNERSHIP GATE: only act on `pid` if it is still a TalonX component we
    # snapshotted (create_time + cmdline).  A stale / reused registry pid for
    # an unrelated process is left completely untouched.
    root_entry = next((e for e in snapshot if e["pid"] == pid), None)
    if root_entry is None or not _still_the_same(root_entry):
        return {"status": "not_running", "signalled": pid, "tree_size": len(snapshot),
                "reaped": [], "residual": [],
                "note": "pid not a live TalonX component (stale/reused registry) -- untouched"}
    try:
        p = psutil.Process(pid)
        if _IS_WIN:
            try:
                p.send_signal(signal.CTRL_BREAK_EVENT)  # noqa: PLE1507
            except Exception:  # noqa: BLE001
                pass
    except psutil.NoSuchProcess:
        pass

    # graceful: terminate every owned tree member, wait within budget
    for e in snapshot:
        if _still_the_same(e):
            try:
                psutil.Process(e["pid"]).terminate()
            except Exception:  # noqa: BLE001
                pass
    while time.monotonic() < deadline:
        if not any(_still_the_same(e) for e in snapshot):
            break
        time.sleep(0.5)

    # escalate: kill whatever owned tree member is still alive
    killed = []
    for e in snapshot:
        if _still_the_same(e):
            try:
                psutil.Process(e["pid"]).kill()
                killed.append(e["pid"])
            except Exception:  # noqa: BLE001
                pass
    time.sleep(0.3)
    residual = [e for e in snapshot if _still_the_same(e)]
    status = ("stopped" if not residual and not killed else
              "killed" if not residual else "residual")
    return {"status": status, "signalled": pid, "tree_size": len(snapshot),
            "reaped": killed, "residual": [{"pid": e["pid"], "cmd": e["cmd"]} for e in residual]}


def stop_stack(session_dir: str | Path, *, grace_s: float = 45.0,
               overall_budget_s: float = 120.0) -> dict[str, Any]:
    """Bounded, ownership-verified teardown of the session-owned processes.

    Windows note (Task 117 Phase 0 Phase 6): the supervisor spawns each
    component with ``CREATE_NEW_PROCESS_GROUP`` and the .venv launcher
    re-execs the real worker as a grandchild, so terminating the supervisor
    (or its shim) reaps neither the worker nor the sibling stacks -- they
    orphan and linger.  We therefore snapshot each session PID's descendant
    tree BEFORE signalling and reap exactly those (verified by create_time +
    cmdline), within one overall budget.
    """
    sd = Path(session_dir)
    info = read_pids(sd)
    (sd / "stop.flag").write_text("stop", encoding="utf-8")

    order = [("checkpoint_daemon", info.get("checkpoint_daemon_pid"), min(15.0, grace_s)),
             ("v2_companion", info.get("v2_companion_pid"), grace_s),
             ("supervisor", info.get("supervisor_pid"), grace_s)]
    # snapshot every owned tree up-front (before anything is signalled)
    trees = {name: _owned_tree(pid) for name, pid, _ in order if pid}

    started = time.monotonic()
    res: dict[str, Any] = {}
    for name, pid, budget in order:
        remaining = overall_budget_s - (time.monotonic() - started)
        res[name] = _terminate(pid, grace_s=max(2.0, min(budget, remaining)),
                               tree=trees.get(name))
    time.sleep(1.0)

    # residual = union of all owned tree members still alive (ownership-checked)
    residual = []
    for name, members in trees.items():
        for e in members:
            if _still_the_same(e):
                residual.append({"pid": e["pid"], "cmd": e["cmd"], "owner": name})
    res["residual_talonx_processes"] = residual
    res["overall_budget_s"] = overall_budget_s
    res["elapsed_s"] = round(time.monotonic() - started, 1)
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
