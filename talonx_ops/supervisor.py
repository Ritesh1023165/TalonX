"""talonx_ops.supervisor -- Task 100B Phases 1-3, 8-9, 14-15, 17.

A THIN runtime supervision layer for TalonX. "Unified runtime" here means
unified *ownership / control semantics*, not one Python process -- process
boundaries that improve failure isolation are preserved (Phase 1).

The supervisor owns only: start, health, restart policy, controlled stop,
dependency/order semantics, aggregate lifecycle status. It never imports or
runs any strategy / execution / ingest business logic -- it launches the
existing entrypoints as child processes and watches them:

    ORIGINAL      python run_talonx.py                         (MANDATORY)
    EXPERIMENTAL  python -m talonx_signals.run                 (OPTIONAL)
    INTELLIGENCE  python -m talonx_ingest.intelligence.service poll --with-backfill   (OPTIONAL)
    DASHBOARD     python dashboard_web.py                      (OPTIONAL)

Design split so the whole state machine is deterministically unit-testable
offline:

* pure model -- ``ComponentState``, ``ComponentSpec``, ``RestartPolicy``,
  ``SupervisedComponent``, ``Supervisor`` (state transitions, startup order,
  restart backoff, health aggregation).
* process layer -- ``SubprocessRunner`` (the only thing that touches the OS);
  tests inject a fake runner and a fake clock.

Nothing here writes to any strategy store. The one durable write it *drives*
(never re-orders) is the Phase 13 EOD reconciliation upsert, at controlled
shutdown, reading every producer's already-final state.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

logger = logging.getLogger("talonx_ops.supervisor")

_REPO_ROOT = Path(__file__).resolve().parent.parent

# component argv markers -- a supervised child (and its .venv-shim grandchild)
# always carries one of these in its command line.  Used to make the recursive
# stop OWNERSHIP-SAFE: an unrelated process that happens to be a descendant, or a
# reused PID, is never signalled (Task 117 Phase 0 Phase 7 / L2).
_COMPONENT_MARKERS = ("run_talonx.py", "talonx_v2.run", "talonx_signals.run",
                      "talonx_ingest.intelligence.service", "dashboard_web.py")


def _owned_descendants(pid: int | None) -> list[dict]:
    """Snapshot every live descendant of ``pid`` as {pid, create_time, cmd}.

    On Windows ``Popen.terminate()`` (= ``TerminateProcess``) does NOT cascade to
    a child spawned ``CREATE_NEW_PROCESS_GROUP`` whose ``.venv`` launcher re-execs
    the real worker as a grandchild -- so the caller must know the tree up front to
    reap the orphan it owns, and only that one (verified by create_time + cmdline).
    """
    if not pid:
        return []
    out: list[dict] = []
    try:
        import psutil
        for p in psutil.Process(pid).children(recursive=True):
            try:
                out.append({"pid": p.pid, "create_time": p.create_time(),
                            "cmd": " ".join(p.cmdline()[:6])})
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception:  # noqa: BLE001 -- psutil absent / pid gone -> nothing owned
        pass
    return out


def _same_owned_component(entry: dict) -> bool:
    """True iff the snapshotted pid is still alive, still the same process
    (create_time match -> not a reused PID) AND still a supervised component."""
    try:
        import psutil
        p = psutil.Process(entry["pid"])
        if abs(p.create_time() - entry["create_time"]) > 1.0:
            return False
        cl = " ".join(p.cmdline())
        return any(m in cl for m in _COMPONENT_MARKERS)
    except Exception:  # noqa: BLE001
        return False


def _reap_owned_descendants(snapshot: list[dict], *, budget_s: float) -> dict[str, Any]:
    """Ownership-gated tree reap of orphaned grandchildren AFTER the parent has
    been terminated.  Graceful terminate -> wait within ``budget_s`` -> kill the
    residue.  Only members that pass ``_same_owned_component`` are ever touched."""
    live = [e for e in snapshot if _same_owned_component(e)]
    if not live:
        return {"orphans_reaped": [], "orphans_killed": [], "residual": [], "mode": "none"}
    import psutil
    for e in live:
        try:
            psutil.Process(e["pid"]).terminate()
        except Exception:  # noqa: BLE001
            pass
    deadline = time.monotonic() + max(1.0, budget_s)
    while time.monotonic() < deadline:
        if not any(_same_owned_component(e) for e in live):
            break
        time.sleep(0.25)
    killed = []
    for e in live:
        if _same_owned_component(e):
            try:
                psutil.Process(e["pid"]).kill()
                killed.append(e["pid"])
            except Exception:  # noqa: BLE001
                pass
    time.sleep(0.2)
    residual = [{"pid": e["pid"], "cmd": e["cmd"]}
                for e in live if _same_owned_component(e)]
    return {"orphans_reaped": [e["pid"] for e in live if e["pid"] not in killed],
            "orphans_killed": killed, "residual": residual,
            "mode": "forced" if killed else "graceful"}


# --------------------------------------------------------------------------- #
# Pure model
# --------------------------------------------------------------------------- #
class ComponentState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    STARTING = "STARTING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    RESTARTING = "RESTARTING"


class Classification(str, Enum):
    MANDATORY = "MANDATORY"      # failure blocks runtime readiness / marks overall FAILED
    OPTIONAL = "OPTIONAL"        # failure => DEGRADED only; never kills Original or the supervisor


@dataclass(frozen=True)
class RestartPolicy:
    """Bounded exponential backoff. ``max_restarts=None`` => retry forever
    (used for the OPTIONAL always-on components, per Task 99L's "unbounded
    retries, never escalate" rule) -- the component simply stays DEGRADED /
    RESTARTING and never reaches FAILED."""
    max_restarts: int | None = 5
    backoff_base_s: float = 5.0
    backoff_factor: float = 2.0
    backoff_cap_s: float = 300.0
    stable_reset_s: float = 300.0        # a component up this long resets its restart counter

    def backoff_for(self, attempt: int) -> float:
        # attempt is 1-based
        raw = self.backoff_base_s * (self.backoff_factor ** max(0, attempt - 1))
        return min(raw, self.backoff_cap_s)


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    argv: list[str]
    classification: Classification
    start_order: int
    stop_order: int
    cwd: str | None = None
    env: dict[str, str] | None = None
    readiness_timeout_s: float = 45.0
    # readiness_probe() -> True once the component is serving. None => "process
    # stayed alive for readiness_grace_s" is the readiness criterion.
    readiness_probe: Callable[[], bool] | None = None
    readiness_grace_s: float = 3.0
    # health_probe() -> ComponentState (READY / DEGRADED). Called while running.
    health_probe: Callable[[], ComponentState] | None = None
    restart_policy: RestartPolicy = field(default_factory=RestartPolicy)
    graceful_stop_s: float = 20.0


class ProcessHandle(Protocol):
    pid: int
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


class ProcessRunner(Protocol):
    def spawn(self, spec: ComponentSpec) -> ProcessHandle: ...


class SubprocessRunner:
    """The only OS-touching part. One child process per spec."""

    def __init__(self, *, log_dir: Path | None = None) -> None:
        self.log_dir = log_dir
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)

    def spawn(self, spec: ComponentSpec) -> ProcessHandle:
        env = dict(os.environ)
        if spec.env:
            env.update(spec.env)
        stdout = stderr = None
        if self.log_dir is not None:
            f = open(self.log_dir / f"{spec.name}.log", "ab", buffering=0)  # noqa: SIM115
            stdout = stderr = f
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(  # noqa: S603
            spec.argv,
            cwd=spec.cwd or str(_REPO_ROOT),
            env=env,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )


# --------------------------------------------------------------------------- #
@dataclass
class SupervisedComponent:
    spec: ComponentSpec
    state: ComponentState = ComponentState.NOT_STARTED
    handle: ProcessHandle | None = None
    pid: int | None = None
    start_time: float | None = None          # monotonic
    start_time_utc: str | None = None
    ready_time: float | None = None
    last_health: ComponentState | None = None
    restart_count: int = 0
    last_error: str | None = None
    last_exit_code: int | None = None
    last_stop_mode: str | None = None        # graceful | forced | forced_descendant
    _restart_at: float | None = None         # monotonic deadline for the pending respawn

    @property
    def name(self) -> str:
        return self.spec.name

    def identity(self) -> dict[str, Any]:
        return {
            "component_name": self.name,
            "classification": self.spec.classification.value,
            "pid": self.pid,
            "state": self.state.value,
            "start_time": self.start_time_utc,
            "last_health": self.last_health.value if self.last_health else None,
            "restart_count": self.restart_count,
            "last_error": self.last_error,
            "last_exit_code": self.last_exit_code,
        }


class SupervisorStartError(RuntimeError):
    """A MANDATORY component failed to reach readiness within its window."""


class DuplicateTelegramOwnerError(RuntimeError):
    """Refused to start Original: another get_updates poller already owns receive."""


# --------------------------------------------------------------------------- #
class Supervisor:
    def __init__(
        self,
        components: list[ComponentSpec],
        *,
        runner: ProcessRunner | None = None,
        clock: Callable[[], float] | None = None,
        utcclock: Callable[[], datetime] | None = None,
        telegram_owner_probe: Callable[[], int] | None = None,
        on_shutdown_persist_eod: Callable[[], Any] | None = None,
    ) -> None:
        self.runner = runner or SubprocessRunner()
        self.clock = clock or time.monotonic
        self.utcclock = utcclock or (lambda: datetime.now(timezone.utc))
        self._telegram_owner_probe = telegram_owner_probe or count_telegram_get_updates_owners
        self._on_shutdown_persist_eod = on_shutdown_persist_eod
        self.components: dict[str, SupervisedComponent] = {
            s.name: SupervisedComponent(spec=s) for s in components
        }
        self._start_order = [s.name for s in sorted(components, key=lambda s: s.start_order)]
        self._stop_order = [s.name for s in sorted(components, key=lambda s: s.stop_order)]
        self.mandatory_failed = False
        self._stop_requested = False
        self._eod_persisted = False

    # ---- helpers -------------------------------------------------------- #
    def _mandatory(self) -> list[SupervisedComponent]:
        return [c for c in self.components.values() if c.spec.classification is Classification.MANDATORY]

    def _spawn(self, c: SupervisedComponent) -> None:
        c.handle = self.runner.spawn(c.spec)
        c.pid = getattr(c.handle, "pid", None)
        c.state = ComponentState.STARTING
        c.start_time = self.clock()
        c.start_time_utc = self.utcclock().isoformat()
        c.ready_time = None
        c._restart_at = None
        logger.info("spawned %s pid=%s state=STARTING", c.name, c.pid)

    def _await_ready(self, c: SupervisedComponent) -> bool:
        spec = c.spec
        deadline = self.clock() + spec.readiness_timeout_s
        while self.clock() < deadline:
            code = c.handle.poll() if c.handle is not None else 0
            if code is not None:
                c.last_exit_code = code
                c.last_error = f"exited with code {code} during startup"
                c.state = ComponentState.FAILED
                return False
            if spec.readiness_probe is not None:
                try:
                    if spec.readiness_probe():
                        c.state = ComponentState.READY
                        c.ready_time = self.clock()
                        return True
                except Exception as exc:  # noqa: BLE001 -- a probe error is not a component error
                    c.last_error = f"readiness probe error: {exc!r}"
            elif c.start_time is not None and (self.clock() - c.start_time) >= spec.readiness_grace_s:
                c.state = ComponentState.READY
                c.ready_time = self.clock()
                return True
            time.sleep(min(0.25, spec.readiness_timeout_s))
        # timed out
        if c.handle is not None and c.handle.poll() is None:
            # process is alive but not "ready" -- OPTIONAL => DEGRADED, MANDATORY => caller decides
            c.state = ComponentState.DEGRADED
            c.last_error = "did not signal readiness within window (process alive)"
        else:
            c.state = ComponentState.FAILED
            c.last_error = "did not reach readiness (process not alive)"
        return False

    # ---- startup (Phase 3) ------------------------------------------------ #
    def start_all(self) -> None:
        # Phase 4: never allow a second get_updates owner.
        if any(c.spec.name == "original" for c in self.components.values()):
            existing = self._telegram_owner_probe()
            if existing and existing >= 1:
                raise DuplicateTelegramOwnerError(
                    f"refusing to start Original: {existing} Telegram get_updates owner(s) already running"
                )
        started: list[SupervisedComponent] = []
        for name in self._start_order:
            c = self.components[name]
            self._spawn(c)
            ready = self._await_ready(c)
            started.append(c)
            if not ready and c.spec.classification is Classification.MANDATORY:
                logger.error("MANDATORY component %s failed readiness -- aborting startup", name)
                self._teardown(started)
                self.mandatory_failed = True
                raise SupervisorStartError(f"{name}: {c.last_error}")
            if not ready:
                logger.warning("OPTIONAL component %s started DEGRADED: %s", name, c.last_error)
        logger.info("start_all complete: %s", {n: self.components[n].state.value for n in self._start_order})

    def _teardown(self, comps: list[SupervisedComponent]) -> None:
        for c in reversed(comps):
            self._stop_component(c)

    # ---- monitor loop (Phase 15) --------------------------------------- #
    def poll_once(self) -> None:
        now = self.clock()
        for c in self.components.values():
            if c.state in (ComponentState.STOPPED, ComponentState.NOT_STARTED, ComponentState.FAILED):
                continue
            if c.state is ComponentState.RESTARTING:
                if c._restart_at is not None and now >= c._restart_at:
                    logger.info("restarting %s (attempt %d)", c.name, c.restart_count)
                    self._spawn(c)
                    self._await_ready(c)
                continue
            if c.handle is None:
                continue
            code = c.handle.poll()
            if code is not None:
                c.last_exit_code = code
                if c.state is ComponentState.STOPPING:
                    c.state = ComponentState.STOPPED
                    continue
                # unexpected exit
                c.last_error = f"unexpected exit (code {code})"
                logger.warning("%s exited unexpectedly code=%s", c.name, code)
                self._schedule_restart(c)
                continue
            # alive -- refresh health
            if c.state in (ComponentState.READY, ComponentState.DEGRADED):
                if c.start_time is not None and (now - c.start_time) >= c.spec.restart_policy.stable_reset_s:
                    c.restart_count = 0
                if c.spec.health_probe is not None:
                    try:
                        h = c.spec.health_probe()
                        c.last_health = h
                        c.state = h if h in (ComponentState.READY, ComponentState.DEGRADED) else c.state
                    except Exception as exc:  # noqa: BLE001
                        c.last_error = f"health probe error: {exc!r}"
                        c.state = ComponentState.DEGRADED

    def _schedule_restart(self, c: SupervisedComponent) -> None:
        pol = c.spec.restart_policy
        c.restart_count += 1
        if pol.max_restarts is not None and c.restart_count > pol.max_restarts:
            c.state = ComponentState.FAILED
            c.last_error = f"exceeded max_restarts ({pol.max_restarts}); last: {c.last_error}"
            logger.error("%s FAILED permanently: %s", c.name, c.last_error)
            if c.spec.classification is Classification.MANDATORY:
                self.mandatory_failed = True
            return
        delay = pol.backoff_for(c.restart_count)
        c.state = ComponentState.RESTARTING
        c._restart_at = self.clock() + delay
        c.handle = None
        c.pid = None
        logger.info("%s scheduled for restart in %.1fs (attempt %d)", c.name, delay, c.restart_count)

    # ---- controlled shutdown (Phase 14) ------------------------------- #
    def stop_all(self) -> dict[str, Any]:
        """Task 99L shutdown contract, mapped onto process-level stops.

        Semantic order (spec Phase 14 steps 1-10) vs what the supervisor can
        actually sequence -- several sub-steps happen *inside* Original's own
        unchanged ``finally`` block and cannot be re-ordered from out here:

          1-2  stop new external alert work / Telegram receive  -> inside Original's
               own shutdown (``decision_engine.stop()`` precedes
               ``dispatch_agent.stop()`` precedes paper) -- unchanged
          3    stop Experimental alert generation               -> stop EXPERIMENTAL first (here)
          4    flush forward telemetry/persistence              -> Experimental's own finally
          5    stop / flush Intelligence                        -> stop INTELLIGENCE next (here)
          6-7  reconcile paper state / persist EOD              -> after all producers exit, read
               their final stores (here, once)
          8-9  stop Original consumers / market feed            -> inside Original's own finally
          10   verify supervised children exited                -> here
        """
        self._stop_requested = True
        order = ["experimental", "intelligence", "original", "dashboard"]
        seq = [n for n in order if n in self.components]
        seq += [n for n in self._stop_order if n not in seq]
        for name in seq:
            self._stop_component(self.components[name])
        # steps 6-7: EOD reconciliation, once, reading now-final producer state
        eod_result = None
        if not self._eod_persisted and self._on_shutdown_persist_eod is not None:
            try:
                eod_result = self._on_shutdown_persist_eod()
                self._eod_persisted = True
            except Exception as exc:  # noqa: BLE001 -- EOD persistence must never crash shutdown
                logger.warning("EOD reconciliation persist failed: %s", exc)
        # step 10: verify -- direct children AND any owned descendant that
        # outlived its parent (Task 117 Phase 0 L2: the old check saw only the
        # direct handle and was blind to an orphaned .venv-shim grandchild).
        orphans = [c.name for c in self.components.values()
                   if c.handle is not None and c.handle.poll() is None]
        residual_descendants: list[dict] = []
        if os.name == "nt":
            for c in self.components.values():
                for e in _owned_descendants(c.pid):
                    if _same_owned_component(e):
                        residual_descendants.append({"component": c.name, **e})
        if orphans or residual_descendants:
            logger.error("orphan children after stop_all: direct=%s descendants=%s",
                         orphans, residual_descendants)
        stop_modes = {c.name: c.last_stop_mode for c in self.components.values()
                      if c.last_stop_mode}
        return {"stopped": seq, "orphans": orphans,
                "residual_descendants": residual_descendants,
                "stop_modes": stop_modes, "eod": eod_result}

    def _stop_component(self, c: SupervisedComponent) -> None:
        if c.handle is None or c.state in (ComponentState.STOPPED, ComponentState.NOT_STARTED):
            c.state = ComponentState.STOPPED if c.state is not ComponentState.NOT_STARTED else c.state
            return
        if c.handle.poll() is not None:
            c.state = ComponentState.STOPPED
            return
        c.state = ComponentState.STOPPING
        logger.info("stopping %s pid=%s", c.name, c.pid)
        # Task 117 Phase 0 L2: snapshot the descendant tree BEFORE signalling --
        # Popen.terminate() only hits the direct child; a .venv-shim grandchild
        # orphans.  We reap exactly the owned orphans afterwards (create_time +
        # component-cmdline verified).  On the fake-runner unit tests this is a
        # no-op (psutil finds nothing), so existing behaviour is unchanged.
        tree_snapshot = _owned_descendants(c.pid) if os.name == "nt" else []
        stop_mode = "graceful"
        try:
            c.handle.terminate()
        except Exception as exc:  # noqa: BLE001
            logger.warning("terminate(%s) raised: %s", c.name, exc)
        try:
            c.handle.wait(timeout=c.spec.graceful_stop_s)
        except Exception:  # noqa: BLE001 -- TimeoutExpired or platform variant
            logger.warning("%s did not exit in %.0fs -- killing", c.name, c.spec.graceful_stop_s)
            stop_mode = "forced"
            try:
                c.handle.kill()
                c.handle.wait(timeout=5)
            except Exception as exc:  # noqa: BLE001
                logger.error("kill(%s) failed: %s", c.name, exc)
        if tree_snapshot:
            reap = _reap_owned_descendants(tree_snapshot, budget_s=max(2.0, c.spec.graceful_stop_s))
            if reap["mode"] != "none":
                logger.info("%s: reaped orphan descendants %s (mode=%s)",
                            c.name, reap["orphans_reaped"] + reap["orphans_killed"], reap["mode"])
            if reap["mode"] == "forced" and stop_mode == "graceful":
                stop_mode = "forced_descendant"
            if reap["residual"]:
                c.last_error = f"residual descendants after stop: {reap['residual']}"
                logger.error("%s: %s", c.name, c.last_error)
        c.last_stop_mode = stop_mode
        c.last_exit_code = c.handle.poll()
        c.state = ComponentState.STOPPED

    # ---- health aggregation (Phase 17) ------------------------------- #
    def aggregate_health(
        self,
        *,
        read_model: Any | None = None,
        market_view: Any | None = None,
        eod_status: str | None = None,
    ) -> dict[str, Any]:
        """One aggregate runtime health projection. Rules are explicit and
        Original is never FAILED merely because an OPTIONAL component is down."""
        def cstate(name: str) -> str:
            c = self.components.get(name)
            return c.state.value if c else "NOT_STARTED"

        original = cstate("original")
        experimental = cstate("experimental")
        intelligence = cstate("intelligence")
        dashboard = cstate("dashboard")

        # market
        market = "UNKNOWN"
        if market_view is not None:
            m = getattr(market_view, "state", None) or (market_view.get("state") if isinstance(market_view, dict) else None)
            market = {
                "HEALTHY": "HEALTHY", "IDLE": "HEALTHY",
                "STALE": "DEGRADED", "DISCONNECTED": "FAILED", "UNKNOWN": "UNKNOWN",
            }.get(str(m), "UNKNOWN")

        # telegram receive: the invariant is "exactly one get_updates owner".
        # A probe result > 1 is a real violation (DEGRADED). 0 / 1 / None while
        # Original is up all read READY -- 0 just means the process probe cannot
        # see the in-process poller (psutil missing, or a fake-runner test).
        try:
            owners = self._telegram_owner_probe()
        except Exception:  # noqa: BLE001
            owners = None
        if original not in ("READY", "DEGRADED"):
            telegram_receive = "DOWN"
        elif owners is not None and owners > 1:
            telegram_receive = "DEGRADED"
        else:
            telegram_receive = "READY"

        # telegram send: from the official-alerts audit view if available
        telegram_send = "READY"
        if read_model is not None:
            try:
                oa = read_model.official_alerts().values
                if oa.get("failed_today") and not oa.get("sent_today"):
                    telegram_send = "DEGRADED"
            except Exception:  # noqa: BLE001
                pass

        # forward outcomes track the Experimental lane
        forward_outcomes = {
            "READY": "READY", "DEGRADED": "DEGRADED", "RESTARTING": "DEGRADED",
            "FAILED": "DOWN", "STOPPED": "DOWN", "STOPPING": "DEGRADED",
            "NOT_STARTED": "NOT_STARTED", "STARTING": "STARTING",
        }.get(experimental, "UNKNOWN")

        eod = eod_status or "NOT_DUE"

        # overall
        if self.mandatory_failed or original == "FAILED":
            overall = "FAILED"
        elif (original not in ("READY",) or market in ("DEGRADED", "FAILED")
              or experimental not in ("READY",) or intelligence not in ("READY",)
              or telegram_receive != "READY" or telegram_send != "READY"):
            overall = "DEGRADED"
        else:
            overall = "HEALTHY"

        return {
            "overall": overall,
            "original": original,
            "market": market,
            "experimental": experimental,
            "intelligence": intelligence,
            "dashboard": dashboard,
            "telegram_send": telegram_send,
            "telegram_receive": telegram_receive,
            "forward_outcomes": forward_outcomes,
            "eod": eod,
            "mandatory_failed": self.mandatory_failed,
            "telegram_get_updates_owners": owners,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "generated_at": self.utcclock().isoformat(),
            "start_order": self._start_order,
            "stop_order": self._stop_order,
            "mandatory_failed": self.mandatory_failed,
            "components": {n: c.identity() for n, c in self.components.items()},
        }

    # ---- run loop ---------------------------------------------------- #
    def run(self, *, tick_interval_s: float = 2.0, max_ticks: int | None = None) -> None:
        import signal as _signal

        def _request_stop(*_a: Any) -> None:
            self._stop_requested = True

        for sig in (getattr(_signal, "SIGINT", None), getattr(_signal, "SIGTERM", None)):
            if sig is not None:
                try:
                    _signal.signal(sig, _request_stop)
                except (ValueError, OSError):
                    pass
        self.start_all()
        ticks = 0
        try:
            while not self._stop_requested:
                self.poll_once()
                ticks += 1
                if max_ticks is not None and ticks >= max_ticks:
                    break
                time.sleep(tick_interval_s)
        finally:
            self.stop_all()


# --------------------------------------------------------------------------- #
# process-scan helpers (Phase 4)
# --------------------------------------------------------------------------- #
def count_telegram_get_updates_owners() -> int:
    """How many LOGICAL processes host the ONE Telegram ``get_updates`` poller.

    The poller lives inside ``run_talonx.py``'s ``DispatchAgent`` -- so this
    counts live ``run_talonx.py`` processes that did not disable dispatch.

    D2: on Windows a venv launcher (``.venv/Scripts/python.exe run_talonx.py``)
    spawns a worker child under a different interpreter that ALSO matches
    ``run_talonx.py``. That shim+worker pair is ONE logical poller -- a match
    whose parent (or grandparent) is itself a match is a shim child and is not
    counted. Best effort: returns 0 if ``psutil`` is unavailable.
    """
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return 0

    matched: dict[int, "psutil.Process"] = {}
    for p in psutil.process_iter(["cmdline", "pid", "name"]):
        try:
            parts = p.info.get("cmdline") or []
        except Exception:  # noqa: BLE001
            continue
        cl = " ".join(parts)
        # a real launch has ``run_talonx.py`` as its own argv token (or a path
        # ending in it) -- not merely a substring of some other command line
        # that happens to mention it (e.g. this probe, a shell wrapper).
        is_launch = any(
            tok == "run_talonx.py" or tok.replace("\\", "/").endswith("/run_talonx.py")
            for tok in parts
        )
        if is_launch and "--skip-dispatch" not in cl:
            matched[p.pid] = p

    if len(matched) <= 1:
        return len(matched)

    logical = 0
    for pid, proc in matched.items():
        anc = proc
        is_shim_child = False
        for _ in range(6):  # bounded ancestor walk
            try:
                anc = anc.parent()
            except Exception:  # noqa: BLE001
                anc = None
            if anc is None:
                break
            if anc.pid in matched:
                is_shim_child = True
                break
        if not is_shim_child:
            logical += 1
    return logical or 1


def assert_single_telegram_owner() -> None:
    n = count_telegram_get_updates_owners()
    if n > 1:
        raise DuplicateTelegramOwnerError(f"{n} Telegram get_updates owners running (invariant: exactly 1)")


# --------------------------------------------------------------------------- #
# default component set
# --------------------------------------------------------------------------- #
def default_talonx_components(
    *,
    python: str | None = None,
    include_dashboard: bool = True,
    with_backfill: bool = True,
    include_v2: bool = False,
    v2_db: str | None = None,
    v2_tick_seconds: int = 300,
) -> list[ComponentSpec]:
    py = python or sys.executable
    intel_argv = [py, "-m", "talonx_ingest.intelligence.service", "poll"]
    if with_backfill:
        intel_argv.append("--with-backfill")
    specs = [
        ComponentSpec(
            name="original",
            argv=[py, "run_talonx.py"],
            classification=Classification.MANDATORY,
            start_order=10,
            stop_order=30,
            readiness_timeout_s=90.0,
            readiness_probe=_original_ready_probe,
            restart_policy=RestartPolicy(max_restarts=3, backoff_base_s=10.0),
            graceful_stop_s=45.0,
        ),
        ComponentSpec(
            name="experimental",
            argv=[py, "-m", "talonx_signals.run"],
            classification=Classification.OPTIONAL,
            start_order=20,
            stop_order=10,
            readiness_timeout_s=45.0,
            readiness_grace_s=5.0,
            restart_policy=RestartPolicy(max_restarts=None, backoff_base_s=10.0),
            graceful_stop_s=25.0,
        ),
        ComponentSpec(
            name="intelligence",
            argv=intel_argv,
            classification=Classification.OPTIONAL,
            start_order=30,
            stop_order=20,
            readiness_timeout_s=60.0,
            readiness_probe=_intelligence_ready_probe,
            restart_policy=RestartPolicy(max_restarts=None, backoff_base_s=15.0, backoff_cap_s=900.0),
            graceful_stop_s=30.0,
        ),
    ]
    if include_v2:
        # Task 112: the ACTIVE_PAPER_V2 companion lane (INSIDER_BUY_CLUSTER_V2).
        # OPTIONAL / additive -- its failure never affects Original (same
        # isolation posture as experimental / intelligence).  It owns only
        # its own v2_lane.db; no broker, no real capital, no Telegram poller.
        v2_argv = [py, "-m", "talonx_v2.run", "--mode", "live",
                   "--tick-seconds", str(v2_tick_seconds)]
        if v2_db:
            v2_argv += ["--db", v2_db]
        specs.append(
            ComponentSpec(
                name="v2",
                argv=v2_argv,
                classification=Classification.OPTIONAL,
                start_order=25,          # after experimental, before intelligence
                stop_order=8,            # stop early in shutdown, before intelligence/original
                readiness_timeout_s=60.0,
                readiness_grace_s=5.0,
                readiness_probe=_v2_ready_probe,
                restart_policy=RestartPolicy(max_restarts=None, backoff_base_s=15.0),
                graceful_stop_s=30.0,
            )
        )
    if include_dashboard:
        specs.append(
            ComponentSpec(
                name="dashboard",
                argv=[py, "dashboard_web.py"],
                classification=Classification.OPTIONAL,
                start_order=40,
                stop_order=5,
                readiness_timeout_s=30.0,
                readiness_grace_s=3.0,
                restart_policy=RestartPolicy(max_restarts=10, backoff_base_s=5.0),
                graceful_stop_s=10.0,
            )
        )
    return specs


def _v2_ready_probe() -> bool:
    """V2 lane is 'ready' once its status file has a fresh heartbeat and
    the expected strategy version."""
    try:
        import json as _json
        import os as _os
        from datetime import datetime as _dt, timezone as _tz

        path = _os.environ.get("TALONX_V2_STATUS_PATH") or "v2_service_status.json"
        s = _json.loads(open(path).read())
        age = (_dt.now(_tz.utc) - _dt.fromisoformat(s["heartbeat_utc"])).total_seconds()
        return age < float(s.get("heartbeat_ttl_s", 180)) and \
            s.get("strategy_version") == "INSIDER_BUY_CLUSTER_V2@1"
    except Exception:  # noqa: BLE001
        return False


def _original_ready_probe() -> bool:
    """Original is 'ready' once runtime_metadata.json exists with a live pid."""
    try:
        from talonx_ops.authoritative_read_model import AuthoritativeReadModel

        return bool(AuthoritativeReadModel().original_producer().get("live"))
    except Exception:  # noqa: BLE001
        return False


def _intelligence_ready_probe() -> bool:
    """Intelligence is 'ready' once its heartbeat file is fresh."""
    try:
        from talonx_ops.authoritative_read_model import AuthoritativeReadModel

        return bool(AuthoritativeReadModel().intelligence_producer().get("live"))
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _status_snapshot() -> dict[str, Any]:
    """Read-only status without a running Supervisor object: process scan +
    authoritative read model + EOD store."""
    out: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat()}
    out["telegram_get_updates_owners"] = count_telegram_get_updates_owners()
    try:
        from talonx_ops.authoritative_read_model import AuthoritativeReadModel

        arm = AuthoritativeReadModel()
        out["producers"] = {
            "original": arm.original_producer(),
            "experimental": arm.experimental_producer(),
            "intelligence": arm.intelligence_producer(),
        }
    except Exception as exc:  # noqa: BLE001
        out["producers_error"] = repr(exc)
    try:
        from talonx_ops.market_health import MarketHealth

        out["market"] = MarketHealth().view().to_dict()
    except Exception as exc:  # noqa: BLE001
        out["market_error"] = repr(exc)
    try:
        from talonx_ops.eod_reconciliation import EodReconciliationStore

        st = EodReconciliationStore(read_only=True)
        latest = st.latest()
        st.close()
        out["eod_latest"] = latest.to_dict() if latest else None
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out["eod_reconciled_today"] = bool(latest and latest.session_date == today)
    except Exception as exc:  # noqa: BLE001
        out["eod_error"] = repr(exc)

    # Task 102 Phase 14: the operator's one-glance answers -- running? ready?
    # feed healthy? shadow/intelligence alive? telegram? positions? EOD? URL?
    try:
        from talonx_ops.authoritative_read_model import AuthoritativeReadModel

        arm = AuthoritativeReadModel()
        op = arm.original_paper().values
        ep = arm.experimental_paper().values
        oa = arm.official_alerts().values
        prod = out.get("producers", {})
        mstate = (out.get("market") or {}).get("state", "UNKNOWN")
        out["answers"] = {
            "talonx_running": bool(prod.get("original", {}).get("live")),
            "original_ready": bool(prod.get("original", {}).get("live")),
            "market_feed_healthy": mstate in ("HEALTHY", "IDLE"),
            "market_feed_state": mstate,
            "experimental_shadow_alive": bool(prod.get("experimental", {}).get("live")),
            "intelligence_alive": bool(prod.get("intelligence", {}).get("live")),
            "telegram_send_ok": not (oa.get("failed_today") and not oa.get("sent_today")),
            "telegram_receive_owner_count": out.get("telegram_get_updates_owners"),
            "original_open_positions": op.get("open_positions"),
            "experimental_open_positions": ep.get("open_positions"),
            "eod_reconciled_today": out.get("eod_reconciled_today", False),
            "dashboard_url": "http://localhost:8787",
            "intelligence_deep_viewer": "http://localhost:8760",
        }
    except Exception as exc:  # noqa: BLE001
        out["answers_error"] = repr(exc)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="talonx-supervisor", description=__doc__)
    p.add_argument("mode", choices=["run", "status", "start"], help="run=start+monitor+stop; status=read-only")
    p.add_argument("--no-dashboard", action="store_true")
    p.add_argument("--no-backfill", action="store_true")
    p.add_argument("--tick", type=float, default=2.0)
    p.add_argument("--max-ticks", type=int, default=None)
    args = p.parse_args(argv)

    if args.mode == "status":
        print(json.dumps(_status_snapshot(), indent=2, default=str))
        return 0

    def _persist_eod() -> Any:
        from talonx_ops.eod_reconciliation import run_and_persist

        rec = run_and_persist()
        return {"session_date": rec.session_date, "status": rec.status}

    sup = Supervisor(
        default_talonx_components(
            include_dashboard=not args.no_dashboard,
            with_backfill=not args.no_backfill,
        ),
        runner=SubprocessRunner(log_dir=_REPO_ROOT / "results" / "task100b_runtime_integration" / "_supervisor_logs"),
        on_shutdown_persist_eod=_persist_eod,
    )
    if args.mode == "start":
        sup.start_all()
        print(json.dumps(sup.snapshot(), indent=2, default=str))
        return 0
    try:
        sup.run(tick_interval_s=args.tick, max_ticks=args.max_ticks)
    except SupervisorStartError as exc:
        logger.error("startup aborted: %s", exc)
        return 1
    print(json.dumps(sup.snapshot(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
