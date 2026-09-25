"""
Read-only operator view of the Continuous Opportunity Engine (dashboard :8787, /ping, CLI ``status``).

Pure sqlite ``mode=ro`` + JSON reads of results/opportunity/*. It deliberately does NOT import ``talonx_opportunity``
(the frozen release never imports a research lane) and never writes anything. A missing store is reported as
NOT_RUNNING / NO_DATA, never as an error that could break the dashboard.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HEARTBEAT_STALE_S = 180.0
COMPONENTS = ("ingestion", "discovery", "evaluator:INTRADAY", "evaluator:SAME_DAY", "evaluator:SHORT_TERM",
              "evaluator:LONG_TERM", "notifier", "outcomes", "reporting")
LOGICAL = {"ingestion": "DATA_INGESTION", "discovery": "DISCOVERY", "evaluator:INTRADAY": "INTRADAY_EVALUATOR",
           "evaluator:SAME_DAY": "SAME_DAY_EVALUATOR", "evaluator:SHORT_TERM": "SHORT_TERM_EVALUATOR",
           "evaluator:LONG_TERM": "LONG_TERM_EVALUATOR", "notifier": "NOTIFICATION_WORKER",
           "outcomes": "OUTCOME_TRACKING", "reporting": "REPORTING"}


def opp_root(root: str | Path | None = None) -> Path:
    return Path(root or os.environ.get("TALONX_OPP_ROOT") or (REPO_ROOT / "results" / "opportunity"))


def _ro(p: Path):
    if not p.exists():
        return None
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5.0)
    con.row_factory = sqlite3.Row
    return con


def _j(s, d=None):
    try:
        return json.loads(s) if s else d
    except (TypeError, ValueError):
        return d


def _age(ts: str | None, now: datetime) -> float | None:
    if not ts:
        return None
    try:
        return round((now - datetime.fromisoformat(ts)).total_seconds(), 1)
    except ValueError:
        return None


def _pid_alive(pid) -> bool | None:
    try:
        import psutil
        return bool(pid) and psutil.pid_exists(int(pid))
    except Exception:  # noqa: BLE001
        return None


# A component heartbeats BETWEEN ticks, so one long tick (e.g. a discovery scan paying an SEC cache-refresh wave) ages
# the heartbeat while the process is alive and holding its lock. 2026-09-25: that was reported as DOWN. Reporting only.
BUSY_CEILING_S = 900.0          # 3x the 300 s cadence: beyond this an alive process is treated as possibly hung
LIVE_STATES = ("UP", "DEGRADED", "BUSY_LONG_SCAN")


def _lock_held_by(root: Path | None, name: str | None, pid) -> bool | None:
    """True if the component's lock file names this (alive) pid; None when it cannot be read."""
    if root is None or not name:
        return None
    try:
        v = int((root / "locks" / (name.replace(":", "_") + ".lock")).read_text().strip() or 0)
    except (OSError, ValueError):
        return None
    return bool(pid) and v == int(pid)


def component_health(row: dict | None, now: datetime, *, root: Path | None = None) -> str:
    """NOT_STARTED | STOPPED | CRASHED | DOWN (pid dead / no heartbeat) | UP | DEGRADED
    | BUSY_LONG_SCAN (alive, lock held, heartbeat 180-900 s old: a long tick in progress)
    | STALE_HEARTBEAT (alive but heartbeat > 900 s, or > 180 s without lock evidence)."""
    if row is None:
        return "NOT_STARTED"
    st, age = row.get("state"), _age(row.get("heartbeat_utc"), now)
    if st in ("STOPPED", "CRASHED"):
        return st
    alive = _pid_alive(row.get("pid"))
    if alive is False or age is None:
        return "DOWN"
    if age > HEARTBEAT_STALE_S:
        if alive and age <= BUSY_CEILING_S and _lock_held_by(root, row.get("name"), row.get("pid")) is not False:
            return "BUSY_LONG_SCAN"
        return "STALE_HEARTBEAT"
    return "DEGRADED" if st == "DEGRADED" else "UP"


def read_opportunity_status(root=None, *, now: datetime | None = None) -> dict:
    r = opp_root(root)
    now = now or datetime.now(timezone.utc)
    out: dict = {"available": r.exists(), "root": str(r)}
    rt = _ro(r / "runtime.db")
    comps = {c["name"]: dict(c) for c in rt.execute("SELECT * FROM components")} if rt else {}
    deps = [dict(d) for d in rt.execute("SELECT * FROM deployment_events ORDER BY at_utc DESC LIMIT 20")] if rt else []
    errs = [dict(e) for e in rt.execute("SELECT * FROM component_events WHERE event IN "
                                        "('TICK_ERROR','CRASH','FORCE_KILLED','SUPERVISOR_RESTART') "
                                        "ORDER BY id DESC LIMIT 10")] if rt else []
    components = []
    for n in COMPONENTS:
        c = comps.get(n)
        det = _j(c.get("detail_json"), {}) if c else {}
        components.append({"component": n, "logical": LOGICAL[n], "health": component_health(c, now, root=r),
                           "state": c.get("state") if c else None, "pid": c.get("pid") if c else None,
                           "heartbeat_age_s": _age(c.get("heartbeat_utc"), now) if c else None,
                           "version": c.get("version") if c else None, "restarts": c.get("restarts") if c else 0,
                           "detail": det})
    healths = [c["health"] for c in components]
    if not comps:
        overall = "NOT_RUNNING"
    elif all(h in ("UP", "BUSY_LONG_SCAN") for h in healths):
        overall = "HEALTHY"
    elif all(h in ("DOWN", "STOPPED", "CRASHED", "NOT_STARTED") for h in healths):
        overall = "DOWN"
    else:
        overall = "DEGRADED"
    latest = deps[0] if deps else None
    out["system"] = {"overall": overall, "commit": next((c.get("commit_sha") for c in comps.values()
                                                         if c.get("commit_sha")), None),
                     "latest_deployment": {k: latest[k] for k in ("deployment_id", "at_utc", "component",
                                                                  "classification", "reason")} if latest else None,
                     "recent_errors": errs}
    out["components"] = components

    mk = _ro(r / "market.db")
    data = {"ingestion": None, "probes": {}, "last_cycle": None}
    if mk:
        st = mk.execute("SELECT * FROM ingestion_state ORDER BY cycle_utc DESC LIMIT 1").fetchone()
        if st:
            data["ingestion"] = {"window_id": st["window_id"], "as_of_utc": st["as_of_utc"], "phase": st["phase"],
                                 "symbols": st["symbols"], "incomplete": len(_j(st["incomplete_json"], [])),
                                 "last_cycle_age_s": _age(st["cycle_utc"], now)}
        for p in mk.execute("SELECT * FROM probes ORDER BY id"):
            data["probes"][p["phase"]] = {"ok": bool(p["ok"]), "at_utc": p["at_utc"], "feed": p["feed"],
                                          "detail": p["detail"]}
        lc = mk.execute("SELECT * FROM cycles ORDER BY id DESC LIMIT 1").fetchone()
        data["last_cycle"] = dict(lc) if lc else None
        mk.close()
    oc = _ro(r / "opportunity.db")
    disc: dict = {"last_scan": None}
    if oc:
        s = oc.execute("SELECT * FROM scans ORDER BY decision_utc DESC LIMIT 1").fetchone()
        if s:
            f = _j(s["funnel_json"], {})
            disc["last_scan"] = {"decision_utc": s["decision_utc"], "phase": s["phase"], "state": s["state"],
                                 "data_as_of_utc": s["data_as_of_utc"], "age_s": _age(s["decision_utc"], now),
                                 "universe": f.get("UNIVERSE"), "eligible": f.get("ELIGIBLE"),
                                 "data_ready": f.get("DATA_READY"), "alert_worthy": f.get("ALERT_WORTHY"),
                                 "events": f.get("EVENTS")}
            data["capability"] = _j(s["capability_json"], {})
        disc["candidates_persisted_total"] = oc.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        disc["candidates_active"] = oc.execute("SELECT COUNT(*) FROM candidates WHERE state NOT IN "
                                               "('INVALIDATED','EXPIRED')").fetchone()[0]
        wid = s["window_id"] if s else None
        disc["window_id"] = wid
        disc["candidates_this_window"] = oc.execute("SELECT COUNT(*) FROM candidates WHERE window_id=?",
                                                    (wid,)).fetchone()[0] if wid else 0
        disc["by_classification"] = dict(oc.execute("SELECT classification, COUNT(*) FROM candidates WHERE "
                                                    "window_id=? GROUP BY 1", (wid,)).fetchall()) if wid else {}
        oc.close()
    out["data"], out["discovery"] = data, disc

    out["horizons"] = {}
    for h in ("INTRADAY", "SAME_DAY", "SHORT_TERM", "LONG_TERM"):
        comp = next(c for c in components if c["component"] == f"evaluator:{h}")
        ec = _ro(r / f"evaluator_{h.lower()}.db")
        recs = ec.execute("SELECT COUNT(*) FROM records").fetchone()[0] if ec else 0
        bs = ec.execute("SELECT COUNT(*) FROM records WHERE action_state IN ('BUY','SELL')").fetchone()[0] if ec else 0
        if ec:
            ec.close()
        out["horizons"][h] = {"health": comp["health"], "state": comp["detail"].get("state") or comp["state"],
                              "last_tick_age_s": comp["heartbeat_age_s"], "records": recs, "buy_sell": bs,
                              "external_strategy": comp["detail"].get("external_strategy_v2")}
    nc = _ro(r / "notification.db")
    notif: dict = {"lab": {}, "policy": None}
    if nc:
        notif["lab"]["decisions"] = dict(nc.execute("SELECT decision, COUNT(*) FROM decisions GROUP BY 1").fetchall())
        notif["lab"]["delivery"] = dict(nc.execute("SELECT delivery_state, COUNT(*) FROM decisions WHERE "
                                                   "delivery_state IS NOT NULL GROUP BY 1").fetchall())
        p = nc.execute("SELECT policy_version, policy_fp FROM decisions ORDER BY decided_utc DESC LIMIT 1").fetchone()
        notif["policy"] = dict(p) if p else None
        nc.close()
    notif["signal_sentinel"] = "owned by the V2 release outbox (see V2/Operations sections); untouched by research"
    out["notification"] = notif
    rep = None
    rd = r / "reports"
    if rd.exists():
        latest_dir = max((d for d in rd.iterdir() if d.is_dir()), default=None, key=lambda d: d.name)
        if latest_dir and (latest_dir / "session_report.json").exists():
            rj = _j((latest_dir / "session_report.json").read_text(encoding="utf-8"), {})
            rep = {"window_id": rj.get("window_id"), "generated_utc": rj.get("generated_utc"),
                   "material_changes": len(rj.get("material_changes", [])),
                   "operations_only_restarts": len(rj.get("operations_only_restarts", [])),
                   "aggregatable": rj.get("aggregatable"), "warnings": rj.get("comparability_warnings", [])}
    out["reporting"] = rep
    shortterm = out["horizons"]["SHORT_TERM"].get("external_strategy") or {}
    out["paper"] = {"component": "frozen V2 companion (observed read-only)", "v2": shortterm or None,
                    "research_lane_paper_orders": 0}
    for c in (rt,):
        if c:
            c.close()
    return out


def ping_lines(root=None) -> list[str]:
    """Compact /ping block."""
    s = read_opportunity_status(root)
    if not s["available"] or s["system"]["overall"] == "NOT_RUNNING":
        return ["\U0001F50E OPPORTUNITY ENGINE: not running"]
    L = ["\U0001F50E OPPORTUNITY ENGINE", f"  overall: {s['system']['overall']}"]
    down = [c["component"] for c in s["components"] if c["health"] not in ("UP", "BUSY_LONG_SCAN")]
    busy = [c["component"] for c in s["components"] if c["health"] == "BUSY_LONG_SCAN"]
    if down:
        L.append(f"  not UP: {', '.join(down)}")
    if busy:
        L.append(f"  busy (long tick, alive): {', '.join(busy)}")
    ls = s["discovery"].get("last_scan")
    if ls:
        L.append(f"  discovery: {ls['phase']} {ls['state']} as-of {str(ls['data_as_of_utc'])[11:16]}Z "
                 f"worthy={ls['alert_worthy']}")
    L.append(f"  candidates: {s['discovery'].get('candidates_this_window', 0)} this window "
             f"(persisted total {s['discovery'].get('candidates_persisted_total', 0)}, uncapped)")
    lab = s["notification"]["lab"]
    if lab:
        L.append(f"  lab delivery: {lab.get('delivery', {})}")
    rep = s.get("reporting") or {}
    if rep.get("material_changes"):
        L.append(f"  WARNING: {rep['material_changes']} material deployment boundary(ies) this window")
    return L
