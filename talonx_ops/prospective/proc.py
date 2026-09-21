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
import threading
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


from talonx_ops.prospective.lock import (  # noqa: E402
    ConcurrentStartError, LockStateUnknownError, SingleWriterLock, StaleLockError,
)


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


#: components that MUST be up for READY (a missing one is never cosmetic).
MANDATORY_STARTUP = ("supervisor_alive", "v2_companion_alive", "dashboard_8787")


def startup_verdict(info: dict[str, Any], verify: dict[str, Any], *,
                    heartbeat_fresh: bool, within_grace: bool) -> str:
    """One of NOT_STARTED / STARTING / READY / FAILED_WITH_RESIDUALS.

    READY requires EVERY mandatory component (supervisor, V2 companion,
    the :8787 dashboard) AND a fresh first-tick heartbeat -- not merely a
    live supervisor + companion. A missing mandatory component is never a
    cosmetic warning: STARTING while in grace, FAILED_WITH_RESIDUALS after.
    """
    sup = bool(verify.get("supervisor_alive"))
    comp = bool(verify.get("v2_companion_alive"))
    dash = bool(verify.get("dashboard_8787"))
    mandatory_up = sup and comp and dash
    residual = bool(_live_prior_stack())

    if mandatory_up and heartbeat_fresh:
        return "READY"
    if not sup and not comp:
        return "FAILED_WITH_RESIDUALS" if residual else "NOT_STARTED"
    # something is up but not everything mandatory (incl. dashboard / heartbeat)
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
                enable_broad_discovery: bool = False,
                allow_when_running: bool = False, release: bool = False) -> dict[str, Any]:
    if release:
        # FINAL ACCEPTANCE: the release profile is explicit -- SIP pricing, Signal delivery on Telegram.
        from talonx_v2.release_gate import resolve_pricing_mode
        pricing_mode = resolve_pricing_mode(pricing_mode if pricing_mode != "csv" else None, release=True)
        if not deliver or transport != "telegram":
            raise ValueError("release profile requires --deliver --transport telegram")
    sd = Path(session_dir)
    sd.mkdir(parents=True, exist_ok=True)
    logs = sd / "logs"
    py = sys.executable

    # D4 / Section 3: ATOMIC single-writer guard. os.open(O_CREAT|O_EXCL) keyed
    # on the V2 ledger identity -- two racing starts: exactly one creates the
    # lock, the other sees a LIVE owner and refuses. --force (allow_when_running)
    # breaks a STALE lock (owner verified gone) but NEVER a live one, and NEVER
    # an 'unknown' (corrupt/incomplete) one either.
    #
    # Lifecycle: acquired here by this short-lived CLI process, then REBOUND
    # (inside _start_stack_locked) to the pid of the actual long-lived ledger
    # writer -- the V2 companion -- before this command returns, so the lock's
    # liveness tracks the writer even after 'start' itself exits. The
    # owner_token travels across that rebind; only a holder of the matching
    # token may ever release it (see stop_stack).
    _lock = SingleWriterLock(V2_DB_PATH)
    try:
        _lock.acquire(force=allow_when_running, break_stale=allow_when_running)
    except LockStateUnknownError:
        raise  # never silently bypassed by --force; needs explicit recovery
    try:
        # secondary, best-effort process scan (covers a stack started without
        # the lock, e.g. a stale-lock break where the old owner is somehow back)
        if not allow_when_running:
            live = _live_prior_stack()
            if live:
                raise ConcurrentStartError(
                    "process scan found a live prospective stack: "
                    + "; ".join(f"pid {h['pid']}" for h in live))
    except BaseException:
        _lock.release()          # nothing spawned yet -- always safe here
        raise
    # From here on, _start_stack_locked owns the release-or-keep decision on
    # failure (it may have spawned processes that need ownership-verified
    # rollback before the lock can be safely released).
    return _start_stack_locked(
        sd, logs, py, env=env, tick_seconds=tick_seconds,
        heartbeat_seconds=heartbeat_seconds, live_lookback_days=live_lookback_days,
        with_dashboard=with_dashboard, with_checkpoint_daemon=with_checkpoint_daemon,
        checkpoint_every_s=checkpoint_every_s, pricing_mode=pricing_mode,
        execution_scope=execution_scope, deliver=deliver, transport=transport,
        enable_broad_discovery=enable_broad_discovery,
        lock=_lock, release=release,
    )


def _start_stack_locked(sd, logs, py, *, env, tick_seconds, heartbeat_seconds,
                        live_lookback_days, with_dashboard, with_checkpoint_daemon,
                        checkpoint_every_s, pricing_mode, execution_scope, deliver,
                        transport, enable_broad_discovery=False,
                        lock: "SingleWriterLock", release: bool = False) -> dict[str, Any]:
    lock_path = str(lock.lock_path)
    spawned: list[tuple[str, int]] = []
    # Task 118A: stop_stack() writes <session_dir>/stop.flag so a running
    # session_loop checkpoint daemon notices and exits promptly. A same-
    # session restart (stop, then start again in the SAME session_dir --
    # exactly the controlled-restart flow this task exercised) previously
    # never cleared that sentinel: the freshly spawned checkpoint daemon
    # would see the STALE flag on its very first check
    # (session_loop.py:70) and exit immediately (clean exit 0, no log
    # output -- easily mistaken for "still starting" rather than "already
    # stopped again"). Cleared here, once, before anything is spawned, so
    # a fresh start always begins from a clean stop-sentinel state.
    stop_flag = sd / "stop.flag"
    if stop_flag.exists():
        stop_flag.unlink()
    # Task 140 (found during a live /ping investigation): --enable-broad-
    # discovery already threaded correctly into the V2 companion's own
    # argv below, but Intelligence's broad-discovery mode
    # (talonx_ingest/intelligence/service/broad_discovery.py) is
    # controlled ONLY by TALONX_INTEL_ENABLE_BROAD_DISCOVERY -- there is
    # no CLI flag for it (poll has none) and it was never in the .env
    # Task 132 already wired load_dotenv() for. The only way it was ever
    # active was an ad-hoc interactive shell export before the FIRST
    # `prospective start` of a campaign -- invisible to, and NOT restored
    # by, a subsequent restart/reboot recovery. Setting it in `env` here
    # (merged into supervisor's own os.environ, which every child
    # supervisor spawns -- Original/Experimental/Intelligence/Dashboard --
    # inherits via the SAME {**os.environ, **env} pattern _spawn() already
    # uses everywhere) makes ONE flag govern both V2's execution scope AND
    # Intelligence's actual collection scope consistently, through the
    # real launcher, matching what "broad discovery" means to an operator.
    # A real shell-exported value still wins (env only ADDS the key when
    # requested, never overwrites one already present).
    if (enable_broad_discovery and "TALONX_INTEL_ENABLE_BROAD_DISCOVERY" not in env
            and "TALONX_INTEL_ENABLE_BROAD_DISCOVERY" not in os.environ):
        env = {**env, "TALONX_INTEL_ENABLE_BROAD_DISCOVERY": "1"}
    # Task 140 (found live, same investigation as the broad-discovery fix
    # above -- this ledger.md's own EXACT sibling gap): `--deliver
    # --transport telegram` on `prospective start` is ALSO wired ONLY into
    # the V2 companion's own argv below, never into Intelligence's card-
    # delivery enablement (talonx_ingest/intelligence/service/config.py's
    # deliver_intelligence_cards/dry_run_delivery, read from
    # TALONX_INTEL_DELIVER_CARDS / TALONX_INTEL_DRY_RUN_DELIVERY -- Task
    # 132's own investigation deliberately chose env-var inheritance over
    # a CLI flag on `poll` for this, per
    # tests/test_task117_supervised_intelligence.py::test_intelligence_
    # argv_never_includes_a_second_send_flag). Same root cause, same fix
    # shape: only ever set via an ad-hoc interactive shell export, never
    # in .env, invisible to and not restored by any restart including a
    # reboot. Reusing the SAME `--deliver`/`--transport` flags an operator
    # already passes for V2 (not inventing a third), since "deliver to the
    # established Telegram destination" is a single operator intent that
    # should govern both lanes together, not two separately-remembered
    # switches. `--transport dryrun` intentionally does NOT flip these
    # (dry-run stays dry-run for Intelligence too).
    if transport == "telegram" and deliver:
        if "TALONX_INTEL_DELIVER_CARDS" not in env and "TALONX_INTEL_DELIVER_CARDS" not in os.environ:
            env = {**env, "TALONX_INTEL_DELIVER_CARDS": "1"}
        if "TALONX_INTEL_DRY_RUN_DELIVERY" not in env and "TALONX_INTEL_DRY_RUN_DELIVERY" not in os.environ:
            env = {**env, "TALONX_INTEL_DRY_RUN_DELIVERY": "0"}
    try:
        sup_argv = [py, "-m", "talonx_ops.supervisor", "run"]
        if not with_dashboard:
            sup_argv.append("--no-dashboard")
        sup_pid = _spawn(sup_argv, log_path=logs / "supervisor.log", env=env)
        spawned.append(("supervisor", sup_pid))

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
        if release:
            v2_argv += ["--release"]
        if deliver:
            v2_argv += ["--deliver", "--transport", transport]
        if enable_broad_discovery:
            # Task 132: additively union the frozen 626-name Discovery
            # Universe v1 into the companion's own execution scope and tag
            # those symbols' trading-lane alerts BROAD_DISCOVERY origin
            # (talonx_v2.run's own flag -- see its help text). OFF by
            # default; the original watchlist scope is unaffected unless
            # explicitly requested here.
            v2_argv += ["--enable-broad-discovery"]
        v2_pid = _spawn(v2_argv, log_path=logs / "v2_companion.log", env=env)
        spawned.append(("v2_companion", v2_pid))

        # Rebind the lock to the ACTUAL ledger writer's pid (+ its own
        # create_time) now that it exists. From this instant the lock's
        # liveness no longer depends on this 'start' CLI process staying
        # alive -- a second 'start' (or --force) sees the companion, not a
        # stale CLI pid, and correctly refuses.
        lock.rebind_owner(pid=v2_pid)

        daemon_pid = None
        if with_checkpoint_daemon:
            d_argv = [py, "-m", "talonx_ops.prospective", "session-loop",
                      "--session-dir", str(sd), "--every", str(checkpoint_every_s)]
            daemon_pid = _spawn(d_argv, log_path=logs / "checkpoint_daemon.log", env=env)
            spawned.append(("checkpoint_daemon", daemon_pid))

        info = {"supervisor_pid": sup_pid, "v2_companion_pid": v2_pid,
                "checkpoint_daemon_pid": daemon_pid,
                "started_utc": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc).isoformat(),
                "v2_argv": v2_argv,
                "startlock_path": lock_path,
                "startlock_owner_token": lock._owner_token}
        atomic_write(_pids_file(sd), json.dumps(info, indent=2))
        return info
    except BaseException:
        # Bounded rollback (Task 117 final-activation correction, item 4e):
        # terminate exactly what THIS start attempt spawned, ownership-verified,
        # within a bounded grace period per process. Only release the lock if
        # the rollback actually leaves no residual writer -- otherwise a
        # second start could still race a surviving companion onto the same
        # ledger, so the lock is deliberately KEPT (protection remains).
        residual: list[dict] = []
        for _name, pid in spawned:
            r = _terminate(pid, grace_s=10.0)
            residual.extend(r.get("residual", []))
        if not residual:
            lock.release()
        raise


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


def _run_bounded(fn, timeout_s: float, default):
    """Run ``fn`` (no args) in a daemon thread and wait up to ``timeout_s``.

    Returns ``fn()``'s result, or ``default`` if it did not finish in time --
    the thread is abandoned (daemon, so it never blocks process exit) rather
    than joined forever. Needed because some ``psutil`` Windows queries have
    no native timeout and have been observed (see ``_still_the_same``) to
    block indefinitely under specific process-lifecycle timing."""
    box: dict = {"done": False, "value": default}

    def _worker():
        try:
            box["value"] = fn()
        except Exception:  # noqa: BLE001
            box["value"] = default
        finally:
            box["done"] = True

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout_s)
    return box["value"] if box["done"] else default


def _still_the_same(entry: dict, *, cache: dict | None = None) -> bool:
    """True iff `entry`'s pid is alive AND is the same process we snapshotted
    (create_time match) AND still looks like a TalonX component -- guards
    against PID reuse and against touching an unrelated process.

    Two Windows-specific hazards, both confirmed by direct reproduction
    during Task 117 final-activation testing (real ``.venv``-shim +
    re-exec'd grandchild processes, the exact shape the supervisor/V2
    companion spawn as):

    1. The cmdline check reads the target process's memory, which can block
       if the target is concurrently being torn down -- so the cmdline
       verdict is computed AT MOST ONCE per ``(pid, create_time)`` and
       cached. Pass the SAME ``cache`` dict across every call within one
       polling loop (``_terminate`` and ``stop_stack``'s residual check do
       this) so only the very first, pre-termination read ever touches the
       target's memory.
    2. Even a bare ``psutil.Process(pid)`` construction / liveness query can
       itself block indefinitely -- observed specifically right after a
       process's PARENT has just fully exited (Windows reparenting timing).
       So the whole liveness+identity check runs under a bounded timeout; on
       timeout we conservatively report "still present" (never silently
       "gone", never silently "clean") so a caller reports an honest
       residual/keeps polling instead of freezing."""
    pid = entry["pid"]

    def _check() -> bool:
        try:
            import psutil
            if not (psutil.pid_exists(pid) and psutil.Process(pid).is_running()):
                return False
            p = psutil.Process(pid)
            ct = p.create_time()
            if abs(ct - entry["create_time"]) > 1.0:
                return False                       # PID reused
        except Exception:  # noqa: BLE001
            return False
        key = (pid, round(ct, 3))
        if cache is not None and key in cache:
            return cache[key]
        try:
            cl = " ".join(p.cmdline())
            ok = any(m in cl for m in _TALONX_MARKERS)
        except Exception:  # noqa: BLE001
            ok = False
        if cache is not None:
            cache[key] = ok
        return ok

    return _run_bounded(_check, 2.0, True)


def _terminate(pid: int | None, *, grace_s: float = 30.0,
               tree: list[dict] | None = None, cache: dict | None = None) -> dict:
    """Ownership-verified, tree-aware stop of one session-owned process.

    Returns {status, signalled, tree_size, reaped, residual}.  A single
    ``grace_s`` budget covers the whole tree.  Only processes present in
    ``tree`` (or discovered as descendants) that pass ``_still_the_same``
    are ever terminated/killed.

    ``cache`` (optional) is the ``_still_the_same`` cmdline-verdict cache --
    pass the SAME dict in if a caller (``stop_stack``) will re-check these
    same entries afterward, so the risky cmdline memory-read never happens
    more than once per process even across that later check.
    """
    if not pid or not _alive(pid):
        return {"status": "not_running", "signalled": pid, "tree_size": 0,
                "reaped": [], "residual": []}
    import psutil
    snapshot = tree if tree is not None else _owned_tree(pid)
    cache = {} if cache is None else cache
    deadline = time.monotonic() + grace_s

    # OWNERSHIP GATE: only act on `pid` if it is still a TalonX component we
    # snapshotted (create_time + cmdline).  A stale / reused registry pid for
    # an unrelated process is left completely untouched. This is the ONLY
    # cmdline read every entry needs -- it happens here, before anything is
    # signalled, while every process is still definitely alive and not
    # mid-teardown; every later poll in this function reuses ``cache``.
    root_entry = next((e for e in snapshot if e["pid"] == pid), None)
    if root_entry is None or not _still_the_same(root_entry, cache=cache):
        return {"status": "not_running", "signalled": pid, "tree_size": len(snapshot),
                "reaped": [], "residual": [],
                "note": "pid not a live TalonX component (stale/reused registry) -- untouched"}
    for e in snapshot:
        _still_the_same(e, cache=cache)   # warm the cache for every entry up-front

    # Every psutil call below that manipulates or re-queries a process that
    # may be mid-teardown is bounded the same way _still_the_same() is (see
    # its docstring) -- a raw psutil.Process(pid).terminate()/.kill()/
    # .send_signal() has been observed to hang exactly like the identity
    # check did, for the same Windows process-lifecycle reason.
    def _signal_break():
        try:
            psutil.Process(pid).send_signal(signal.CTRL_BREAK_EVENT)  # noqa: PLE1507
        except Exception:  # noqa: BLE001
            pass
        return True
    if _IS_WIN:
        _run_bounded(_signal_break, 2.0, None)

    # graceful: terminate every owned tree member, wait within budget
    def _terminate_one(target_pid):
        def _do():
            try:
                psutil.Process(target_pid).terminate()
            except Exception:  # noqa: BLE001
                pass
            return True
        return _run_bounded(_do, 2.0, None)

    for e in snapshot:
        if _still_the_same(e, cache=cache):
            _terminate_one(e["pid"])
    while time.monotonic() < deadline:
        if not any(_still_the_same(e, cache=cache) for e in snapshot):
            break
        time.sleep(0.5)

    # escalate: kill whatever owned tree member is still alive
    def _kill_one(target_pid):
        def _do():
            try:
                psutil.Process(target_pid).kill()
                return True
            except Exception:  # noqa: BLE001
                return False
        return _run_bounded(_do, 2.0, False)

    killed = []
    for e in snapshot:
        if _still_the_same(e, cache=cache) and _kill_one(e["pid"]):
            killed.append(e["pid"])
    time.sleep(0.3)
    residual = [e for e in snapshot if _still_the_same(e, cache=cache)]
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
    # one _still_the_same cmdline-verdict cache PER tree, shared between the
    # _terminate() call below and the residual re-check afterward -- a
    # process's memory is only ever read once, before it is told to die
    # (Task 117 final-activation correction: re-reading cmdline on a process
    # mid-termination can block indefinitely on Windows).
    caches = {name: {} for name in trees}

    started = time.monotonic()
    res: dict[str, Any] = {}
    for name, pid, budget in order:
        remaining = overall_budget_s - (time.monotonic() - started)
        res[name] = _terminate(pid, grace_s=max(2.0, min(budget, remaining)),
                               tree=trees.get(name), cache=caches.get(name))
    time.sleep(1.0)

    # residual = union of all owned tree members still alive (ownership-checked)
    residual = []
    for name, members in trees.items():
        for e in members:
            if _still_the_same(e, cache=caches.get(name)):
                residual.append({"pid": e["pid"], "cmd": e["cmd"], "owner": name})
    res["residual_talonx_processes"] = residual
    res["overall_budget_s"] = overall_budget_s
    res["elapsed_s"] = round(time.monotonic() - started, 1)
    res["ports"] = {str(port): _port_open(port) for port in (8787, 8760, 8770, 8501)}
    # PID registry
    pidf = REPO_ROOT / ".run" / "talonx.pids.json"
    res["pid_registry_cleared"] = not pidf.exists()
    res["v2_lane_db_intact"] = Path(V2_DB_PATH).exists()

    # release the single-writer lock IFF the stack is actually down (no
    # residuals). If residuals remain, the ledger may still be being written --
    # keep the lock so a fresh start still refuses until teardown completes.
    # Release is entitlement-gated by owner_token (Task 117 final-activation
    # correction): this session may only remove the lock IT created, even
    # though the lock's recorded pid was rebound away from the 'start' CLI to
    # the V2 companion during startup -- never an unconditional path-unlink.
    lock_released = None
    if not residual:
        token = info.get("startlock_owner_token")
        try:
            if token:
                ok = SingleWriterLock.release_by_token(V2_DB_PATH, token)
                lock_released = True if ok else "token_mismatch_or_absent"
            else:
                lk = SingleWriterLock(V2_DB_PATH)
                lock_released = "absent" if not lk.lock_path.exists() else \
                    "no_owner_token_recorded -- left in place (cannot verify entitlement)"
        except Exception as exc:  # noqa: BLE001
            lock_released = f"error: {exc!r}"
    else:
        lock_released = "kept -- residuals present"
    res["startlock_released"] = lock_released
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
