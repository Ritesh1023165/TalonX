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
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HEARTBEAT_STALE_S = 180.0
COMPONENTS = ("ingestion", "discovery", "evaluator:INTRADAY", "evaluator:SAME_DAY", "evaluator:SHORT_TERM",
              "evaluator:LONG_TERM", "notifier", "outcomes", "reporting", "promotion", "sentinel")
LOGICAL = {"ingestion": "DATA_INGESTION", "discovery": "DISCOVERY", "evaluator:INTRADAY": "INTRADAY_EVALUATOR",
           "evaluator:SAME_DAY": "SAME_DAY_EVALUATOR", "evaluator:SHORT_TERM": "SHORT_TERM_EVALUATOR",
           "evaluator:LONG_TERM": "LONG_TERM_EVALUATOR", "notifier": "NOTIFICATION_WORKER",
           "outcomes": "OUTCOME_TRACKING", "reporting": "REPORTING", "promotion": "PAPER_PROMOTION",
           "sentinel": "SENTINEL_COMMANDS"}


def _mode_fields(name: str, c: dict | None, det: dict) -> dict:
    """Operator-relevant mode of the two downstream components (read-only; from their own registry rows)."""
    if not c:
        return {}
    fps = _j(c.get("config_fps_json"), {}) or {}
    if name == "promotion":
        return {"mode": fps.get("mode"), "config_fp": fps.get("PROMOTION_POLICY"),
                "signal_delivery": det.get("signal_delivery") or fps.get("signal_delivery"),
                "requested_mode": det.get("requested_mode")}
    if name == "sentinel":
        return {"mode": "ENABLED" if det.get("enabled", fps.get("enabled") == "1") else "DISABLED",
                "mutation_mode": det.get("mutation_mode") or fps.get("mutation_mode"), "bot": det.get("bot"),
                "last_error": det.get("last_error")}
    return {}


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


# The promotion (PAPER_SIGNAL) stream's latest accepted research verdict, shown next to its delivery counts so that
# no operator mistakes a delivery count for evidence of value. Source: committed evidence only (descriptive constant).
PAPER_SIGNAL_VERDICT = {
    "status": "NEGATIVE",
    "statement": "Not a validated profitable strategy. Measured negative after costs. Signal-bot delivery was "
                 "paused 2026-10-07 and is restored only as UNVALIDATED research-review alerts (owner direction): "
                 "review items, not trade events, not buy instructions, independent of any paper admission.",
    "verdict": "INTRADAY_PREMISE_FAILURE_SUPPORTED / NO_EDGE_OBSERVED",
    "evidence": "VR replay 2026-09-28..29, CONTROL_VR_LIFECYCLE n=297: gross -0.094%, net -0.608%, PF 0.29",
    "cost_model": "max(20 bps, measured entry spread) per round trip",
    "source": "docs/research/evidence/2026-09-30_vr_paper_replay.md (commit 5be6528); forward 2026-09-30 "
              "(n=156, net -0.463%) in docs/research/evidence/forward_alpha_validation.md",
    "as_of": "2026-09-30",
}
LONDON_NOTE = "UTC; London = UTC+1 (BST) until 2026-10-25, then UTC+0 (GMT)"
_STATES = ("PENDING", "RETRY", "HELD", "SENT", "AMBIGUOUS", "FAILED", "EXPIRED")


def _period_start(now: datetime) -> datetime:
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _lane_counts(con, table: str, *, created: str, where: str = "", args=(), since: str) -> dict:
    """Rows (= notifications, one row per logical message) by state, all-time and for the period. Send ATTEMPTS are
    reported separately and never added to a notification count. SENT = confirmed by the transport; AMBIGUOUS = a send
    whose outcome is unknown (never counted as SENT)."""
    w = f" WHERE {where}" if where else ""
    hist = {s: 0 for s in _STATES}
    hist.update(dict(con.execute(f"SELECT state, COUNT(*) FROM {table}{w} GROUP BY 1", args).fetchall()))
    pw = f"{w} AND {created} >= ?" if w else f" WHERE {created} >= ?"
    per = {s: 0 for s in _STATES}
    per.update(dict(con.execute(f"SELECT state, COUNT(*) FROM {table}{pw} GROUP BY 1", (*args, since)).fetchall()))
    a = con.execute(f"SELECT COALESCE(SUM(attempts),0), MIN({created}), MAX({created}), "
                    f"MAX(CASE WHEN state='SENT' THEN sent_at_utc END) FROM {table}{w}", args).fetchone()
    return {"history": hist, "period": per, "send_attempts_total": a[0], "first_created_utc": a[1],
            "last_created_utc": a[2], "last_confirmed_send_utc": a[3]}


def _promotion_lane(r: Path, comp: dict | None, since: str) -> dict:
    lane = {"lane": "PAPER_SIGNAL_PROMOTION", "label": "Opportunity promotion: research-review alerts",
            "alert_class": "RESEARCH_REVIEW (not a trade event)",
            "destination": "TRADE_EVENT", "bot": "Signal", "source": "results/opportunity/"
            "promotion_signal_notifications.db + promotion.db", "research_status": PAPER_SIGNAL_VERDICT}
    det = _j((comp or {}).get("detail_json"), {}) or {}
    fps = _j((comp or {}).get("config_fps_json"), {}) or {}
    loaded = det.get("signal_delivery") or fps.get("signal_delivery")
    if not loaded and fps.get("mode") in ("PAPER_SIGNAL", "SHADOW"):     # runtime predating the pause control
        loaded = "ACTIVE" if fps["mode"] == "PAPER_SIGNAL" else "OFF"
    cfg = None
    pf = r / "control" / "promotion_signal_delivery.json"
    if pf.exists():
        d = _j(pf.read_text(encoding="utf-8"), None)
        cfg = {k: d.get(k) for k in ("paused", "effective_utc", "effective_local", "decision", "policy_id",
                                     "delivery_mode", "delivery_boundary_utc", "delivery_boundary_local")} \
            if isinstance(d, dict) else {"paused": True, "decision": "UNREADABLE_CONTROL_FILE_FAIL_SAFE"}
    cfg_paused = bool(cfg and cfg.get("paused") is True)
    if loaded and loaded.startswith("RESEARCH_REVIEW"):
        loaded = "RESEARCH_REVIEW"
    if comp is None or not loaded:
        mode = "UNKNOWN (no runtime evidence from the promotion component)"
    elif loaded == "RESEARCH_REVIEW" and cfg_paused:
        mode = "PAUSE_CONFIGURED_NOT_YET_LOADED (component restart pending)"
    elif loaded == "RESEARCH_REVIEW":
        mode = ("RESEARCH_REVIEW_DELIVERY_ENABLED (UNVALIDATED review alerts to the Signal bot since "
                f"{det.get('delivery_boundary_utc') or (cfg or {}).get('delivery_boundary_utc') or 'UNKNOWN'})")
    elif cfg and cfg.get("delivery_mode") == "RESEARCH_REVIEW" and not cfg_paused and loaded == "PAUSED":
        mode = "REVIEW_DELIVERY_CONFIGURED_NOT_YET_LOADED (still paused until the component restarts)"
    elif loaded == "PAUSED":
        mode = "PAUSED (record-only: promotions recorded, no Signal-bot delivery)"
    elif cfg_paused:
        mode = "PAUSE_CONFIGURED_NOT_YET_LOADED (component restart pending)"
    else:
        mode = {"ACTIVE": "ACTIVE (delivering to the Signal bot)", "OFF": "SHADOW (record-only)"}.get(loaded, loaded)
    lane.update(mode=mode, loaded_signal_delivery=loaded, configured_pause=cfg)
    ob = _ro(r / "promotion_signal_notifications.db")
    if ob:
        lane["notifications"] = _lane_counts(ob, "ops_notification_outbox", created="created_at_utc",
                                             where="event_type IN ('PAPER_OPPORTUNITY','RESEARCH_OPPORTUNITY')",
                                             since=since)
        lane["notifications"]["by_event_type"] = {
            et: _lane_counts(ob, "ops_notification_outbox", created="created_at_utc", where="event_type=?",
                             args=(et,), since=since)["history"]
            for et in ("PAPER_OPPORTUNITY", "RESEARCH_OPPORTUNITY")}
        lane["notifications"]["suppressed_by_policy"] = ob.execute(
            "SELECT COUNT(*) FROM ops_notification_outbox WHERE last_error LIKE 'SUPPRESSED_POLICY_PAUSE%'").fetchone()[0]
        ob.close()
    pc = _ro(r / "promotion.db")
    if pc:
        lane["promotions"] = {
            "history": dict(pc.execute("SELECT state, COUNT(*) FROM promotions GROUP BY 1").fetchall()),
            "period": dict(pc.execute("SELECT state, COUNT(*) FROM promotions WHERE queued_utc >= ? GROUP BY 1",
                                      (since,)).fetchall()),
            "recorded_while_paused": pc.execute("SELECT COUNT(*) FROM promotions WHERE reason_code="
                                                "'SIGNAL_DELIVERY_PAUSED'").fetchone()[0],
            "review_alerts_promoted": pc.execute("SELECT COUNT(*) FROM promotions WHERE reason_code="
                                                 "'RESEARCH_REVIEW_ALERT'").fetchone()[0],
            "pre_restoration_record_only": pc.execute("SELECT COUNT(*) FROM promotions WHERE reason_code="
                                                      "'PRE_RESTORATION_RECORD_ONLY'").fetchone()[0]}
        pc.close()
    return lane


def vr_entry_collection(vr: Path) -> dict:
    """VR_PAPER_V1 entry control as configured (entry_control.json) and as last reported by the tracker heartbeat."""
    out = {"entry_control_configured": "NONE", "entry_control_loaded": "UNKNOWN"}
    f = vr / "entry_control.json"
    if f.exists():
        d = _j(f.read_text(encoding="utf-8"), None)
        out["entry_control_configured"] = (("ENTRIES_BLOCKED since " + str(d.get("boundary_utc")))
                                           if isinstance(d, dict) and d.get("entries_blocked") is True else
                                           "ENTRIES_OPEN" if isinstance(d, dict) and d.get("entries_blocked") is False
                                           else "MALFORMED (tracker blocks all new entries)")
    con = _ro(vr / "vr_live.db")
    if con:
        r = con.execute("SELECT at_utc, detail_json FROM heartbeat WHERE component='vr_paper'").fetchone()
        con.close()
        if r:
            det = _j(r[1], {}) or {}
            out["entry_control_loaded"] = det.get("entry_control") or "NOT_REPORTED (tracker predates the control)"
            out["tracker_heartbeat_utc"] = r[0]
    out["mode"] = ("ENTRY COLLECTION INTERRUPTED (both arms; open positions still managed)"
                   if out["entry_control_loaded"] in ("BLOCKED", "MALFORMED_BLOCKING")
                   else f"ENTRY CONTROL {out['entry_control_loaded']} (configured: {out['entry_control_configured']})")
    return out


def notification_lanes(root=None, *, now: datetime | None = None, repo: Path | None = None,
                       home: Path | None = None) -> dict:
    """Every Telegram notification lane, each counted from its OWN store (read-only). Lanes sharing a bot are listed
    separately and never merged into one total."""
    r, repo = opp_root(root), Path(repo or REPO_ROOT)
    home = Path(home or os.environ.get("TALONX_HOME") or (Path.home() / ".talonx"))
    now = now or datetime.now(timezone.utc)
    start = _period_start(now)
    since = start.isoformat()
    lanes = []
    rt = _ro(r / "runtime.db")
    comp = None
    if rt:
        row = rt.execute("SELECT * FROM components WHERE name='promotion'").fetchone()
        comp = dict(row) if row else None
        rt.close()
    lanes.append(_promotion_lane(r, comp, since))
    specs = [
        ("INTELLIGENCE_CARDS", "Intelligence cards (SEC filings)", "TRADE_EVENT", "Signal",
         home / "ingestion_ledger.db", "intelligence_delivery", "enqueued_at_utc", ""),
        ("V2_ACTIONABLE", "V2 INSIDER_BUY_CLUSTER_V2 paper alerts", "TRADE_EVENT", "Signal",
         repo / "v2_release_rc1.db", "v2_alert_outbox", "created_at_utc", ""),
        ("OPERATIONS", "Operations / Sentinel health", "OPERATIONS", "Sentinel",
         repo / "v2_release_rc1_notifications.db", "ops_notification_outbox", "created_at_utc", ""),
        ("LAB_RESEARCH", "Opportunity Lab research", "RESEARCH", "Lab",
         r / "opportunity_research_notifications.db", "ops_notification_outbox", "created_at_utc", ""),
        ("VR_PAPER", "VR_PAPER_V1 paper entry/exit (research)", "RESEARCH", "Lab",
         repo / "results" / "vr_paper" / "vr_paper_notifications.db", "ops_notification_outbox", "created_at_utc", ""),
    ]
    for key, label, dest, bot, path, table, created, where in specs:
        lane = {"lane": key, "label": label, "destination": dest, "bot": bot, "source": path.name}
        try:
            con = _ro(path)
            if con is None:
                lane["mode"] = "NO_STORE"
            else:
                cols = {c[1] for c in con.execute(f"PRAGMA table_info({table})")}
                if not cols:
                    lane["mode"] = "NO_TABLE"
                else:
                    if "attempts" not in cols or "sent_at_utc" not in cols or created not in cols:
                        lane["mode"] = "UNKNOWN_SCHEMA"
                    else:
                        lane["notifications"] = _lane_counts(con, table, created=created, where=where, since=since)
                        if key == "INTELLIGENCE_CARDS":
                            lane["by_route"] = {f"{rt_}:{st}": n for rt_, st, n in con.execute(
                                "SELECT route, state, COUNT(*) FROM intelligence_delivery GROUP BY 1, 2")}
                con.close()
        except sqlite3.Error as exc:
            lane["mode"] = f"UNREADABLE ({type(exc).__name__})"
        if key == "VR_PAPER":
            lane.update(vr_entry_collection(repo / "results" / "vr_paper"))
        lanes.append(lane)
    return {"period": {"start_utc": since, "end_utc": now.isoformat(), "label": f"{start.date()} UTC day so far",
                       "timezone": LONDON_NOTE},
            "history_note": "history = every row ever recorded in the lane's store (never pruned by this view)",
            "count_unit": "one notification = one outbox row; send attempts are reported separately",
            "lanes": lanes}


def _git(repo: Path, *args) -> str | None:
    try:
        p = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=5)
        return p.stdout if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _component_sources(repo: Path) -> tuple[list, dict] | None:
    """(_SHARED, COMPONENT_SOURCES) parsed STATICALLY out of the research lane's runtime.py (AST; the research lane is never
    imported). Only list/dict/str literals, ``+`` and earlier module names are evaluated; anything else -> None."""
    import ast
    try:
        tree = ast.parse((repo / "talonx_opportunity" / "runtime.py").read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    env: dict = {}

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.Name):
            return env[n.id]
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            return ev(n.left) + ev(n.right)
        if isinstance(n, (ast.List, ast.Tuple)):
            return [ev(e) for e in n.elts]
        if isinstance(n, ast.JoinedStr):                     # f"evaluator:{h}"
            return "".join(ev(v.value) if isinstance(v, ast.FormattedValue) else ev(v) for v in n.values)
        if isinstance(n, ast.Dict):
            d = {}
            for k, v in zip(n.keys, n.values):
                d.update(ev(v) if k is None else {ev(k): ev(v)})  # k None = **{...}
            return d
        if isinstance(n, ast.DictComp) and len(n.generators) == 1 and isinstance(n.generators[0].target, ast.Name):
            g, out = n.generators[0], {}
            for item in ev(g.iter):
                env[g.target.id] = item
                out[ev(n.key)] = ev(n.value)
            env.pop(g.target.id, None)
            return out
        raise ValueError(type(n).__name__)
    for node in tree.body:
        tgt = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else \
            node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(tgt, ast.Name) and tgt.id in ("_P", "_SHARED", "COMPONENT_SOURCES") and node.value is not None:
            try:
                env[tgt.id] = ev(node.value)
            except (KeyError, ValueError):
                return None
    if "_SHARED" not in env or "COMPONENT_SOURCES" not in env:
        return None
    return env["_SHARED"], env["COMPONENT_SOURCES"]


def _checkout_version(repo: Path, shared: list, sources: dict, component: str) -> str:
    """Same content hash as talonx_opportunity.runtime.component_version, over the files in this checkout."""
    import hashlib
    h = hashlib.sha256()
    for rel in sorted(set(sources.get(component, []) + shared)):
        f = repo / rel
        h.update(rel.encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n") if f.exists() else b"MISSING")
    return h.hexdigest()[:12]


def version_attribution(loaded: dict, repo: Path | None = None) -> dict:
    """Per component: the source version it LOADED vs the version of its own sources in this checkout now, plus the
    commit attribution. "Stale" is decided only by the component's OWN source hash, never by HEAD moving: a later
    commit touching other code (e.g. Intelligence, or another component) leaves it CURRENT. ``-dirty`` = tracked edits
    existed at load (exact content unknown; files dirty NOW are listed). No runtime evidence -> UNKNOWN.
    ``loaded`` maps component -> {"commit_sha", "version"} (or None)."""
    repo = Path(repo or REPO_ROOT)
    head = (_git(repo, "rev-parse", "HEAD") or "").strip() or None
    dirty_now = [ln[3:] for ln in (_git(repo, "status", "--porcelain", "--untracked-files=no") or "").splitlines()]
    src = _component_sources(repo)
    out = {"repo_head": head[:12] if head else "UNKNOWN", "dirty_tracked_files_now": dirty_now, "components": {}}
    for name, row in loaded.items():
        row = row or {}
        commit, ver = row.get("commit_sha"), row.get("version")
        if not ver:
            out["components"][name] = {"loaded_commit": commit or "UNKNOWN", "loaded_version": "UNKNOWN",
                                       "status": "UNKNOWN (no runtime evidence)"}
            continue
        if src is None:
            st, now_v = "UNKNOWN (component source map unreadable)", None
        else:
            now_v = _checkout_version(repo, src[0], src[1], name)
            st = ("CURRENT (loaded sources = checkout)" if now_v == ver
                  else "SOURCES_CHANGED_SINCE_LOAD (restart would load different code)")
        c = commit or "UNKNOWN"
        out["components"][name] = {
            "loaded_commit": c, "loaded_version": ver, "checkout_version": now_v or "UNKNOWN", "status": st,
            "commit_vs_head": ("UNKNOWN" if not head or c == "UNKNOWN" else
                               "SAME_COMMIT" if head.startswith(c.removesuffix("-dirty")) else "OLDER_OR_OTHER_COMMIT"),
            "dirty_at_load": "UNKNOWN" if c == "UNKNOWN" else
                             ("YES (exact content unknown)" if c.endswith("-dirty") else "NO")}
    return out


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
                           "detail": det, **_mode_fields(n, c, det)})
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
                     "versions": version_attribution({n: comps.get(n) for n in COMPONENTS}),
                     "latest_deployment": {k: latest[k] for k in ("deployment_id", "at_utc", "component",
                                                                  "classification", "reason")} if latest else None,
                     "recent_errors": errs}
    out["components"] = components

    mk = _ro(r / "market.db")
    data = {"ingestion": None, "probes": {}, "last_cycle": None}
    if mk:
        mk.execute("BEGIN")          # 2026-10-01 (P0): one read transaction -> one committed ingestion generation
        st = mk.execute("SELECT * FROM ingestion_state ORDER BY cycle_utc DESC LIMIT 1").fetchone()
        if st:
            data["ingestion"] = {"window_id": st["window_id"], "as_of_utc": st["as_of_utc"], "phase": st["phase"],
                                 "symbols": st["symbols"], "incomplete": len(_j(st["incomplete_json"], [])),
                                 "last_cycle_age_s": _age(st["cycle_utc"], now),
                                 "generation": st["generation"] if "generation" in st.keys() else None}
        for p in mk.execute("SELECT * FROM probes ORDER BY id"):
            data["probes"][p["phase"]] = {"ok": bool(p["ok"]), "at_utc": p["at_utc"], "feed": p["feed"],
                                          "detail": p["detail"]}
        lc = mk.execute("SELECT * FROM cycles ORDER BY id DESC LIMIT 1").fetchone()
        data["last_cycle"] = dict(lc) if lc else None
        mk.rollback()
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
    # 2026-10-07: the old line said the Signal bot was "untouched by research" -- false: the promotion component sent
    # PAPER_SIGNAL messages to it. Every lane is now counted from its own store.
    notif["signal_bot_note"] = ("The Signal bot (TRADE_EVENT) carries three lanes: PAPER_SIGNAL promotion, "
                                "Intelligence cards and V2 alerts. See notification lanes; they are never merged.")
    try:
        notif["lanes"] = notification_lanes(r, now=now)
    except Exception as exc:  # noqa: BLE001 -- lane visibility must never break the dashboard
        notif["lanes"] = {"error": f"{type(exc).__name__}"}
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
