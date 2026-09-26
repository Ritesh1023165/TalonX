"""
Runtime registry, component lifecycle and DEPLOYMENT / CHANGE BOUNDARIES (REQ S14-03, S14-04).

runtime.db (shared registry; each component writes only its OWN rows):
  components          one row per component: pid, state, heartbeat, version, config fingerprint, commit
  component_events    START / STOP / CRASH / DEGRADED history
  deployment_events   one row per component start whose (version, config fingerprints) differ from the previous
                      start -- or a restart with nothing changed (OPERATIONS_ONLY, ``restart_only=1``)
  change_declarations operator-declared classification/reason for the NEXT start of a component

Classification rules at start (deterministic, conservative):
  * nothing changed                         -> OPERATIONS_ONLY restart (comparability intact)
  * a CONFIG fingerprint changed            -> the component's material class (e.g. STRATEGY_MATERIAL for discovery);
                                               a declaration can never downgrade it
  * only code changed, declaration present  -> the declared class (reason required)
  * only code changed, no declaration       -> the component's DEFAULT class (conservative)
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from talonx_opportunity.db import REPO_ROOT, connect, iso, j, root_dir, unj, utcnow

CLASSIFICATIONS = ("OPERATIONS_ONLY", "DATA_FIX", "ROUTING_FIX", "UI_ONLY", "STRATEGY_MATERIAL",
                   "EXECUTION_MATERIAL", "REPORTING_ONLY")

# Reporting-impact contract (B8). Keys are the metrics a boundary may make non-comparable.
IMPACT_KEYS = ("detection", "classification", "execution", "notification", "candidate_counts", "alert_counts",
               "paper_trades", "cash_equity", "pnl", "win_rate", "mfe_mae", "missed_opportunity",
               "provider_coverage", "delivery_metrics", "profitability_analysis")
CLASS_IMPACT: dict[str, set[str]] = {
    "OPERATIONS_ONLY": set(),
    "UI_ONLY": set(),
    "REPORTING_ONLY": set(),
    "ROUTING_FIX": {"notification", "alert_counts", "delivery_metrics"},
    "DATA_FIX": {"detection", "classification", "candidate_counts", "alert_counts", "mfe_mae", "missed_opportunity",
                 "provider_coverage", "profitability_analysis"},
    "STRATEGY_MATERIAL": {"detection", "classification", "candidate_counts", "alert_counts", "notification",
                          "mfe_mae", "win_rate", "missed_opportunity", "pnl", "profitability_analysis"},
    "EXECUTION_MATERIAL": {"execution", "paper_trades", "cash_equity", "pnl", "win_rate", "profitability_analysis"},
}
# Component-specific extra impact (e.g. an outcome-model change changes MFE/MAE even if classed REPORTING_ONLY).
COMPONENT_EXTRA_IMPACT: dict[str, set[str]] = {"outcomes": {"mfe_mae", "win_rate", "profitability_analysis"}}

COMPONENT_DEFAULT_CLASS = {
    "ingestion": "DATA_FIX", "discovery": "STRATEGY_MATERIAL", "notifier": "ROUTING_FIX",
    "outcomes": "REPORTING_ONLY", "reporting": "REPORTING_ONLY",
    # 2026-09-26 (F-P1): the supervisor loop and the Sentinel command poller only spawn / answer operator commands --
    # neither can change detection, classification, notification or execution, so an undeclared code change of either
    # is an operations restart (it used to fall through to the STRATEGY_MATERIAL fallback).
    "supervisor": "OPERATIONS_ONLY", "sentinel": "OPERATIONS_ONLY",
    "evaluator:INTRADAY": "STRATEGY_MATERIAL", "evaluator:SAME_DAY": "STRATEGY_MATERIAL",
    "evaluator:SHORT_TERM": "STRATEGY_MATERIAL", "evaluator:LONG_TERM": "STRATEGY_MATERIAL",
}
# Class a CONFIG-fingerprint change forces (cannot be declared down).
COMPONENT_CONFIG_CLASS = {"discovery": "STRATEGY_MATERIAL", "notifier": "ROUTING_FIX", "ingestion": "DATA_FIX",
                          "outcomes": "REPORTING_ONLY", "sentinel": "OPERATIONS_ONLY"}
# Closed list of config keys that are NOT strategy-material for their component, with the class they map to. Used only
# when EVERY changed key is listed here AND an operator declaration of exactly that class is present; otherwise the
# forced class above stands (so an unlisted or undeclared change can never be downgraded).
# 2026-09-26: the SEC catalyst cache mode serves the same submissions under the same 600 s freshness bound (parity
# tested); switching it changes latency, not classification -> DATA_FIX.
CONFIG_KEY_CLASS: dict[str, dict[str, str]] = {"discovery": {"SEC_CATALYST_CACHE": "DATA_FIX"}}

_P = "talonx_opportunity/"
_SHARED = [_P + "db.py", _P + "runtime.py", _P + "phases.py", _P + "config.py"]
COMPONENT_SOURCES: dict[str, list[str]] = {
    "ingestion": [_P + "ingestion.py", _P + "aggregates.py", _P + "capabilities.py", "talonx_premarket/alpaca_data.py",
                  "talonx_premarket/universe.py"],
    "discovery": [_P + "discovery.py", _P + "aggregates.py", _P + "capabilities.py", "talonx_premarket/features.py",
                  "talonx_premarket/scoring.py", "talonx_premarket/alerts.py", "talonx_premarket/catalysts.py",
                  "talonx_premarket/config.py", _P + "sec_refresh.py"],
    "notifier": [_P + "notifier.py", "talonx_ops/notify/__init__.py", "talonx_ops/notify/outbox.py",
                 "talonx_ops/notify/worker.py"],
    "outcomes": [_P + "outcome_tracker.py", "talonx_premarket/outcomes.py", "talonx_premarket/alpaca_data.py"],
    "reporting": [_P + "reporting.py"],
    "sentinel": ["talonx_ops/operator_control/__init__.py", "talonx_ops/operator_control/commands.py",
                 "talonx_ops/operator_control/scanned.py", "talonx_ops/operator_control/sentinel.py",
                 "talonx_ops/operator_control/store.py", _P + "sentinel_component.py"],
    **{f"evaluator:{h}": [_P + "evaluators.py"] for h in ("INTRADAY", "SAME_DAY", "SHORT_TERM", "LONG_TERM")},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS components (
    name TEXT PRIMARY KEY, pid INTEGER, state TEXT, started_utc TEXT, heartbeat_utc TEXT, version TEXT,
    config_fps_json TEXT, commit_sha TEXT, detail_json TEXT, restarts INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS component_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at_utc TEXT, component TEXT, event TEXT, pid INTEGER, detail_json TEXT);
CREATE TABLE IF NOT EXISTS deployment_events (
    deployment_id TEXT PRIMARY KEY, at_utc TEXT, component TEXT, old_version TEXT, new_version TEXT, commit_sha TEXT,
    old_config_fps_json TEXT, config_fps_json TEXT, reason TEXT, classification TEXT, restart_only INTEGER,
    affects_detection INTEGER, affects_classification INTEGER, affects_execution INTEGER,
    affects_notification INTEGER, affects_candidate_counts INTEGER, affects_pnl INTEGER,
    affects_profitability_analysis INTEGER, impact_json TEXT, declared INTEGER, decided_by TEXT);
CREATE INDEX IF NOT EXISTS ix_dep_at ON deployment_events(at_utc);
CREATE TABLE IF NOT EXISTS change_declarations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at_utc TEXT, component TEXT, classification TEXT, reason TEXT,
    consumed_by TEXT, expected_version TEXT);
"""


def runtime_db(root=None) -> Path:
    return root_dir(root) / "runtime.db"


def commit_sha() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=REPO_ROOT, capture_output=True,
                             text=True, timeout=10).stdout.strip() or "unknown"
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO_ROOT,
                               capture_output=True, text=True, timeout=10).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        return "unknown"


# Shared runtime modules whose changes can never alter what a component detects / classifies / notifies / executes
# (registry, boundaries, hashing). A component whose ONLY source differences since its last recorded deployment are in
# this list may be declared OPERATIONS_ONLY by ``plan_shared_runtime_declarations`` (F-P2, 2026-09-26). Closed list.
SHARED_RUNTIME_OPS_FILES = (_P + "runtime.py",)


def component_sources(component: str) -> list[str]:
    return sorted(set(COMPONENT_SOURCES.get(component, []) + _SHARED))


def component_version(component: str) -> str:
    """Content hash of the component's own source (+ shared runtime modules), LF-normalised so a Windows checkout
    and git blobs agree. A pure restart keeps the same version."""
    h = hashlib.sha256()
    for rel in sorted(set(COMPONENT_SOURCES.get(component, []) + _SHARED)):
        p = REPO_ROOT / rel
        h.update(rel.encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n") if p.exists() else b"MISSING")
    return h.hexdigest()[:12]


def _mapped_config_class(component: str, old_fps: dict, new_fps: dict, decl) -> bool:
    """True iff every changed config key is in CONFIG_KEY_CLASS[component] and the pending declaration names exactly
    the class those keys map to."""
    changed = {k for k in set(old_fps) | set(new_fps) if old_fps.get(k) != new_fps.get(k)}
    mapped = CONFIG_KEY_CLASS.get(component, {})
    if decl is None or not changed or not changed <= set(mapped):
        return False
    return {mapped[k] for k in changed} == {decl["classification"]}


def impact_for(classification: str, component: str) -> dict[str, bool]:
    keys = set(CLASS_IMPACT.get(classification, set()))
    if classification != "OPERATIONS_ONLY":
        keys |= COMPONENT_EXTRA_IMPACT.get(component, set())
    return {k: (k in keys) for k in IMPACT_KEYS}


def _git_blob(commit: str, rel: str) -> bytes | None:
    r = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=REPO_ROOT, capture_output=True, timeout=30)
    return r.stdout if r.returncode == 0 else None


def version_at_commit(component: str, commit: str) -> str:
    """Rebuild ``component_version`` from the git blobs of ``commit`` (same file list, same LF normalisation)."""
    h = hashlib.sha256()
    for rel in component_sources(component):
        b = _git_blob(commit, rel)
        h.update(rel.encode())
        h.update(b.replace(b"\r\n", b"\n") if b is not None else b"MISSING")
    return h.hexdigest()[:12]


def changed_sources_since(component: str, commit: str) -> list[str]:
    out = []
    for rel in component_sources(component):
        b = _git_blob(commit, rel)
        f = REPO_ROOT / rel
        cur = f.read_bytes().replace(b"\r\n", b"\n") if f.exists() else None
        old = b.replace(b"\r\n", b"\n") if b is not None else None
        if cur != old:
            out.append(rel)
    return out


class RuntimeStore:
    def __init__(self, root=None, *, readonly: bool = False):
        self.path = runtime_db(root)
        self.con = connect(self.path, readonly=readonly, schema=None if readonly else SCHEMA)
        if not readonly and "expected_version" not in {r[1] for r in self.con.execute(
                "PRAGMA table_info(change_declarations)")}:
            self.con.execute("ALTER TABLE change_declarations ADD COLUMN expected_version TEXT")  # additive (F-P2)
            self.con.commit()

    # -- deployment boundaries ------------------------------------------------------------------------------------
    def declare_change(self, component: str, classification: str, reason: str,
                       expected_version: str | None = None) -> int:
        """Record the classification of the NEXT start of ``component``. With ``expected_version`` the declaration
        applies ONLY if that start runs exactly this version (any further code change is classified normally)."""
        if classification not in CLASSIFICATIONS:
            raise ValueError(f"unknown classification {classification!r}; one of {CLASSIFICATIONS}")
        if not reason.strip():
            raise ValueError("a declaration needs a reason")
        cur = self.con.execute("INSERT INTO change_declarations(at_utc, component, classification, reason, "
                               "expected_version) VALUES (?,?,?,?,?)",
                               (iso(), component, classification, reason.strip(), expected_version))
        self.con.commit()
        return int(cur.lastrowid)

    def plan_shared_runtime_declarations(self, components: list[str] | None = None) -> list[dict]:
        """F-P2: for each component, compare its hash sources at the commit of its LAST recorded deployment with the
        working tree. ELIGIBLE (OPERATIONS_ONLY) only if (a) that commit is clean, (b) rebuilding the version from the
        commit reproduces the recorded version, and (c) every changed source is in SHARED_RUNTIME_OPS_FILES.
        Anything else is REFUSED (classified normally at the next start) or NOT_NEEDED (version unchanged)."""
        names = components or [r["component"] for r in self.con.execute(
            "SELECT DISTINCT component FROM deployment_events ORDER BY component")]
        plan = []
        for c in names:
            last = self._last_deployment(c)
            if last is None:
                plan.append({"component": c, "status": "REFUSED", "why": "no recorded deployment"})
                continue
            recorded, commit = last["new_version"], (last["commit_sha"] or "")
            if c == "supervisor":
                plan.append({"component": c, "status": "NOT_APPLICABLE",
                             "why": "supervisor default class is OPERATIONS_ONLY"})
                continue
            now_v = component_version(c)
            row = {"component": c, "recorded_version": recorded, "recorded_commit": commit, "current_version": now_v}
            if now_v == recorded:
                plan.append({**row, "status": "NOT_NEEDED", "why": "version unchanged"})
                continue
            if not commit or commit == "unknown" or commit.endswith("-dirty"):
                plan.append({**row, "status": "REFUSED", "why": f"recorded commit {commit!r} is not verifiable"})
                continue
            rebuilt = version_at_commit(c, commit)
            if rebuilt != recorded:
                plan.append({**row, "status": "REFUSED",
                             "why": f"version rebuilt from {commit} is {rebuilt}, not the recorded {recorded}"})
                continue
            changed = changed_sources_since(c, commit)
            other = [f for f in changed if f not in SHARED_RUNTIME_OPS_FILES]
            if not changed or other:
                plan.append({**row, "status": "REFUSED", "changed": changed,
                             "why": "component source changed: " + ", ".join(other) if other else "no source diff"})
                continue
            plan.append({**row, "status": "ELIGIBLE", "changed": changed,
                         "reason": f"shared runtime only: {', '.join(changed)} changed since {commit} "
                                   f"({recorded} -> {now_v}); no component source changed (verified from git)"})
        return plan

    def declare_shared_runtime_changes(self, components: list[str] | None = None) -> list[dict]:
        plan = self.plan_shared_runtime_declarations(components)
        for p in plan:
            if p["status"] == "ELIGIBLE":
                p["declaration_id"] = self.declare_change(p["component"], "OPERATIONS_ONLY", p["reason"],
                                                          expected_version=p["current_version"])
        return plan

    def _last_deployment(self, component: str):
        return self.con.execute("SELECT * FROM deployment_events WHERE component=? ORDER BY at_utc DESC, rowid DESC "
                                "LIMIT 1", (component,)).fetchone()

    def record_start(self, component: str, *, version: str, config_fps: dict[str, str], commit: str,
                     reason: str = "") -> dict:
        prev = self._last_deployment(component)
        old_v = prev["new_version"] if prev else None
        old_fps = unj(prev["config_fps_json"], {}) if prev else {}
        decl = self.con.execute("SELECT * FROM change_declarations WHERE component=? AND consumed_by IS NULL "
                                "ORDER BY id DESC LIMIT 1", (component,)).fetchone()
        if decl is not None and decl["expected_version"] and decl["expected_version"] != version:
            decl = None                              # bound to another version: never applies to this start
        config_changed = prev is not None and old_fps != config_fps
        code_changed = prev is not None and old_v != version
        if prev is None:
            cls, restart_only, decided = COMPONENT_DEFAULT_CLASS.get(component, "OPERATIONS_ONLY"), 0, "FIRST_START"
            why = reason or "first recorded start (baseline)"
        elif not (config_changed or code_changed):
            cls, restart_only, decided = "OPERATIONS_ONLY", 1, "RULE:UNCHANGED_RESTART"
            why = reason or (decl["reason"] if decl else "restart, no code/config change")
        elif config_changed and _mapped_config_class(component, old_fps, config_fps, decl):
            cls, restart_only, decided, why = decl["classification"], 0, "RULE:CONFIG_KEY_MAPPED+DECLARED", decl["reason"]
        elif config_changed:
            cls = COMPONENT_CONFIG_CLASS.get(component, COMPONENT_DEFAULT_CLASS.get(component, "STRATEGY_MATERIAL"))
            restart_only, decided = 0, "RULE:CONFIG_FINGERPRINT_CHANGED"
            why = (decl["reason"] if decl else reason) or "config fingerprint changed"
        elif decl is not None:
            cls, restart_only, decided, why = decl["classification"], 0, "DECLARED", decl["reason"]
        else:
            cls = COMPONENT_DEFAULT_CLASS.get(component, "STRATEGY_MATERIAL")
            restart_only, decided = 0, "RULE:UNDECLARED_CODE_CHANGE_DEFAULT"
            why = reason or "code changed without a declaration (conservative default class)"
        dep_id = f"{utcnow():%Y%m%dT%H%M%SZ}-{component}-{uuid.uuid4().hex[:6]}"
        imp = impact_for(cls, component)
        self.con.execute(
            "INSERT INTO deployment_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (dep_id, iso(), component, old_v, version, commit, j(old_fps), j(config_fps), why, cls, restart_only,
             int(imp["detection"]), int(imp["classification"]), int(imp["execution"]), int(imp["notification"]),
             int(imp["candidate_counts"]), int(imp["pnl"]), int(imp["profitability_analysis"]), j(imp),
             int(decl is not None and decided in ("DECLARED", "RULE:CONFIG_KEY_MAPPED+DECLARED")), decided))
        if decl is not None and (config_changed or code_changed or restart_only):
            self.con.execute("UPDATE change_declarations SET consumed_by=? WHERE id=?", (dep_id, decl["id"]))
        self.con.commit()
        return {"deployment_id": dep_id, "classification": cls, "restart_only": bool(restart_only),
                "decided_by": decided, "impact": imp}

    def deployments(self, since_utc: str | None = None, until_utc: str | None = None) -> list[dict]:
        q, a = "SELECT * FROM deployment_events WHERE 1=1", []
        if since_utc:
            q += " AND at_utc >= ?"
            a.append(since_utc)
        if until_utc:
            q += " AND at_utc < ?"
            a.append(until_utc)
        return [dict(r) for r in self.con.execute(q + " ORDER BY at_utc, rowid", a)]

    # -- component registry -----------------------------------------------------------------------------------------
    def set_component(self, name: str, **kw) -> None:
        cols = ("pid", "state", "started_utc", "heartbeat_utc", "version", "config_fps_json", "commit_sha",
                "detail_json")
        row = self.con.execute("SELECT name FROM components WHERE name=?", (name,)).fetchone()
        if row is None:
            self.con.execute("INSERT INTO components(name) VALUES (?)", (name,))
        sets = [(c, kw[c]) for c in cols if c in kw]
        if sets:
            self.con.execute(f"UPDATE components SET {', '.join(c + '=?' for c, _ in sets)} WHERE name=?",
                             [v for _, v in sets] + [name])
        if kw.get("bump_restarts"):
            self.con.execute("UPDATE components SET restarts = COALESCE(restarts,0)+1 WHERE name=?", (name,))
        self.con.commit()

    def event(self, component: str, event: str, detail=None) -> None:
        self.con.execute("INSERT INTO component_events(at_utc, component, event, pid, detail_json) VALUES (?,?,?,?,?)",
                         (iso(), component, event, os.getpid(), j(detail or {})))
        self.con.commit()

    def components(self) -> list[dict]:
        return [dict(r) for r in self.con.execute("SELECT * FROM components ORDER BY name")]

    def close(self) -> None:
        self.con.close()


# ------------------------------------------------------------------------------------------------------------------
# component run loop: lock, deployment boundary, heartbeat, graceful stop flag, crash recording
# ------------------------------------------------------------------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except Exception:  # noqa: BLE001
        return False


def lock_path(root, name: str) -> Path:
    d = root_dir(root) / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d / (name.replace(":", "_") + ".lock")


def stop_flag(root, name: str) -> Path:
    d = root_dir(root) / "control"
    d.mkdir(parents=True, exist_ok=True)
    return d / (name.replace(":", "_") + ".stop")


class AlreadyRunning(RuntimeError):
    pass


def acquire_lock(root, name: str) -> Path:
    p = lock_path(root, name)
    if p.exists():
        try:
            pid = int(p.read_text().strip() or 0)
        except ValueError:
            pid = 0
        if pid and pid != os.getpid() and _pid_alive(pid):
            raise AlreadyRunning(f"component {name} already running (pid {pid})")
    p.write_text(str(os.getpid()))
    return p


def run_component(name: str, *, tick: Callable[[], float], config_fps: dict[str, str] | None = None,
                  root=None, max_ticks: int | None = None, reason: str = "",
                  sleep: Callable[[float], None] = time.sleep, detail: Callable[[], dict] | None = None) -> str:
    """Run ``tick()`` until a stop flag appears (or ``max_ticks``). ``tick`` returns seconds until the next tick.
    A tick exception is recorded (CRASH event, state DEGRADED) and the loop keeps going with backoff -- a component
    never dies silently; an unrecoverable startup error is recorded and re-raised."""
    rt = RuntimeStore(root)
    lock = acquire_lock(root, name)
    flag = stop_flag(root, name)
    if flag.exists():
        flag.unlink()
    version, commit = component_version(name), commit_sha()
    dep = rt.record_start(name, version=version, config_fps=config_fps or {}, commit=commit, reason=reason)
    rt.set_component(name, pid=os.getpid(), state="RUNNING", started_utc=iso(), heartbeat_utc=iso(),
                     version=version, config_fps_json=j(config_fps or {}), commit_sha=commit,
                     detail_json=j({"deployment": dep}), bump_restarts=True)
    rt.event(name, "START", {"deployment": dep, "argv": sys.argv})
    end_state, n, failures = "STOPPED", 0, 0
    try:
        while True:
            if flag.exists():
                end_state = "STOPPED"
                break
            try:
                wait = float(tick())
                failures = 0
                state = "RUNNING"
            except Exception as exc:  # noqa: BLE001 -- recorded, surfaced, retried with backoff
                failures += 1
                wait = min(300.0, 10.0 * 2 ** min(failures, 5))
                state = "DEGRADED"
                rt.event(name, "TICK_ERROR", {"error": f"{type(exc).__name__}: {exc}"[:500], "failures": failures})
            info = {"deployment_id": dep["deployment_id"], "consecutive_failures": failures}
            if detail is not None:
                try:
                    info.update(detail())
                except Exception as exc:  # noqa: BLE001
                    info["detail_error"] = str(exc)[:200]
            rt.set_component(name, state=state, heartbeat_utc=iso(), detail_json=j(info))
            n += 1
            if max_ticks is not None and n >= max_ticks:
                break
            # sleep in small slices so a stop flag is honoured quickly and the heartbeat stays fresh
            deadline = time.monotonic() + max(0.0, wait)
            while time.monotonic() < deadline:
                if flag.exists():
                    break
                sleep(min(5.0, max(0.0, deadline - time.monotonic())))
                rt.set_component(name, heartbeat_utc=iso())
    except KeyboardInterrupt:
        end_state = "STOPPED"
    except BaseException as exc:
        end_state = "CRASHED"
        rt.event(name, "CRASH", {"error": f"{type(exc).__name__}: {exc}"[:500]})
        raise
    finally:
        rt.set_component(name, state=end_state, heartbeat_utc=iso())
        rt.event(name, end_state, {})
        rt.close()
        try:
            if lock.exists() and lock.read_text().strip() == str(os.getpid()):
                lock.unlink()
        except OSError:
            pass
    return end_state
