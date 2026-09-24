"""
REPORTING component (REQ S14-04 / B8) -- deployment-boundary aware session reports. Read-only over every store;
writes only results/opportunity/reports/<window>/session_report.{json,md}.

A boundary is MATERIAL for a metric family when its impact flags touch it. Candidate / classification / outcome
statistics are SEGMENTED at every material boundary inside the window and never blended into one figure; an
OPERATIONS_ONLY / UI_ONLY / REPORTING_ONLY / pure-restart boundary is listed explicitly with
"comparability intact". The first recorded start of a component is a baseline, not a mid-window change.
"""
from __future__ import annotations

import json
import os
import statistics as st
from datetime import date
from pathlib import Path

from talonx_opportunity.db import connect, iso, root_dir, unj
from talonx_opportunity.evaluators import HORIZONS, evaluator_db, v2_status
from talonx_opportunity.notifier import notification_db
from talonx_opportunity.outcome_tracker import outcomes_db
from talonx_opportunity.phases import trading_window
from talonx_opportunity.runtime import IMPACT_KEYS, RuntimeStore, runtime_db
from talonx_opportunity.store import opportunity_db

MATERIAL_FOR_CANDIDATES = ("detection", "classification", "candidate_counts")
MATERIAL_FOR_OUTCOMES = ("detection", "classification", "mfe_mae", "win_rate", "profitability_analysis")
MATERIAL_FOR_ALERTS = ("notification", "alert_counts", "delivery_metrics")
MATERIAL_FOR_PAPER = ("execution", "paper_trades", "cash_equity", "pnl")


def _ro(path: Path):
    return connect(path, readonly=True) if path.exists() else None


def _stats(xs):
    xs = [x for x in xs if x is not None]
    return {"n": len(xs), "mean": round(st.mean(xs), 3), "median": round(st.median(xs), 3)} if xs else {"n": 0}


def classify_boundaries(deps: list[dict]) -> list[dict]:
    out = []
    for d in deps:
        imp = unj(d.get("impact_json"), {}) or {}
        baseline = d.get("decided_by") == "FIRST_START"
        touched = [k for k in IMPACT_KEYS if imp.get(k)]
        out.append({**{k: d[k] for k in ("deployment_id", "at_utc", "component", "old_version", "new_version",
                                          "commit_sha", "classification", "reason", "decided_by")},
                    "restart_only": bool(d["restart_only"]), "baseline": baseline, "impact": touched,
                    "splits": {"candidates": not baseline and any(imp.get(k) for k in MATERIAL_FOR_CANDIDATES),
                               "outcomes": not baseline and any(imp.get(k) for k in MATERIAL_FOR_OUTCOMES),
                               "alerts": not baseline and any(imp.get(k) for k in MATERIAL_FOR_ALERTS),
                               "paper": not baseline and any(imp.get(k) for k in MATERIAL_FOR_PAPER)},
                    "comparability": "INTACT" if baseline or not touched else "SPLIT:" + ",".join(touched)})
    return out


def _segments(start: str, end: str, cuts: list[str]) -> list[tuple[str, str]]:
    pts = [start] + sorted(c for c in set(cuts) if start < c < end) + [end]
    return list(zip(pts[:-1], pts[1:]))


def build_report(root, window_id: str) -> dict:
    w = trading_window(date.fromisoformat(window_id))
    start, end = w.start_utc.isoformat(), w.after_hours_end_utc.isoformat()
    rep: dict = {"window_id": window_id, "window_utc": [start, end], "generated_utc": iso(),
                 "reference_session": w.reference_session.isoformat()}
    rt = RuntimeStore(root, readonly=True) if runtime_db(root).exists() else None
    deps = rt.deployments(start, end) if rt else []
    comps = rt.components() if rt else []
    b = classify_boundaries(deps)
    rep["deployment_boundaries"] = b
    rep["operations_only_restarts"] = [x for x in b if x["comparability"] == "INTACT" and not x["baseline"]]
    rep["material_changes"] = [x for x in b if x["comparability"] != "INTACT"]

    cand_cuts = [x["at_utc"] for x in b if x["splits"]["candidates"]]
    out_cuts = [x["at_utc"] for x in b if x["splits"]["outcomes"]]
    alert_cuts = [x["at_utc"] for x in b if x["splits"]["alerts"]]
    rep["aggregatable"] = {"candidates": not cand_cuts, "outcomes": not out_cuts, "alerts": not alert_cuts,
                           "paper": not any(x["splits"]["paper"] for x in b)}
    warnings = []
    for fam, cuts in (("candidate statistics", cand_cuts), ("outcome statistics", out_cuts),
                      ("alert statistics", alert_cuts)):
        if cuts:
            warnings.append(f"{fam} are SEGMENTED at {len(cuts)} material boundary(ies) and must not be "
                            f"aggregated across them")
    rep["comparability_warnings"] = warnings

    oc = _ro(opportunity_db(root))
    cands = [dict(r) for r in oc.execute("SELECT * FROM candidates WHERE window_id=?", (window_id,))] if oc else []
    evs = [dict(r) for r in oc.execute("SELECT event_type, classification, at_utc, phase FROM candidate_events "
                                       "WHERE window_id=?", (window_id,))] if oc else []
    scans = [dict(r) for r in oc.execute("SELECT phase, state, COUNT(*) n FROM scans WHERE window_id=? "
                                         "GROUP BY 1,2", (window_id,))] if oc else []
    outs = {}
    ocn = _ro(outcomes_db(root))
    if ocn:
        outs = {r["candidate_id"]: dict(r) for r in ocn.execute("SELECT * FROM outcomes WHERE window_id=?",
                                                                 (window_id,))}
    nc = _ro(notification_db(root))
    decs = [dict(r) for r in nc.execute("SELECT * FROM decisions WHERE window_id=?", (window_id,))] if nc else []

    segs = []
    for s0, s1 in _segments(start, end, cand_cuts + out_cuts):
        cs = [c for c in cands if s0 <= c["first_seen_utc"] < s1]
        os_ = [outs[c["candidate_id"]] for c in cs if c["candidate_id"] in outs]
        by_cls, by_phase, by_status = {}, {}, {}
        for c in cs:
            by_cls[c["classification"]] = by_cls.get(c["classification"], 0) + 1
            by_phase[c["first_seen_phase"]] = by_phase.get(c["first_seen_phase"], 0) + 1
        for o in os_:
            by_status[o["status"]] = by_status.get(o["status"], 0) + 1
        segs.append({"from_utc": s0, "to_utc": s1, "candidates_first_seen": len(cs),
                     "by_current_classification": by_cls, "by_first_seen_phase": by_phase,
                     "events": sum(1 for e in evs if s0 <= e["at_utc"] < s1),
                     "outcome_status": by_status,
                     "ret_30m": _stats([o["ret_30m_pct"] for o in os_]),
                     "close_ret": _stats([o["close_ret_pct"] for o in os_]),
                     "mfe": _stats([o["mfe_pct"] for o in os_]), "mae": _stats([o["mae_pct"] for o in os_])})
    rep["segments"] = segs
    rep["scans"] = scans
    dec_counts: dict[str, int] = {}
    deliv: dict[str, int] = {}
    for d in decs:
        dec_counts[d["decision"]] = dec_counts.get(d["decision"], 0) + 1
        if d["delivery_state"]:
            deliv[d["delivery_state"]] = deliv.get(d["delivery_state"], 0) + 1
    rep["notification"] = {"decisions": dec_counts, "delivery_states": deliv,
                           "note": "ENQUEUED is not SENT; only SENT rows reached Telegram"}
    rep["horizons"] = {}
    for h in HORIZONS:
        ec = _ro(evaluator_db(root, h))
        rep["horizons"][h] = {"records": ec.execute("SELECT COUNT(*) FROM records WHERE window_id=?",
                                                    (window_id,)).fetchone()[0] if ec else 0,
                              "buy_sell_emitted": ec.execute("SELECT COUNT(*) FROM records WHERE window_id=? AND "
                                                             "action_state IN ('BUY','SELL')",
                                                             (window_id,)).fetchone()[0] if ec else 0}
        if ec:
            ec.close()
    rep["paper_execution"] = {"component": "frozen V2 companion (observed read-only)", "v2": v2_status(),
                              "research_lane_paper_orders": 0}
    rep["components"] = [{k: c.get(k) for k in ("name", "state", "heartbeat_utc", "version", "restarts")}
                         for c in comps]
    for c in (oc, ocn, nc):
        if c:
            c.close()
    if rt:
        rt.close()
    return rep


def render_md(rep: dict) -> str:
    L = [f"# Opportunity engine session report: {rep['window_id']}", "",
         f"Window {rep['window_utc'][0]} -> {rep['window_utc'][1]} (reference close {rep['reference_session']}). "
         f"Research lane: no profitability claim.", "", "## Deployment boundaries", ""]
    if not rep["deployment_boundaries"]:
        L.append("None recorded in this window.")
    for x in rep["deployment_boundaries"]:
        L.append(f"- {x['at_utc'][11:19]}Z `{x['component']}` {x['old_version']} -> {x['new_version']} "
                 f"**{x['classification']}**{' (restart only)' if x['restart_only'] else ''}"
                 f"{' (baseline)' if x['baseline'] else ''}: comparability {x['comparability']}. {x['reason']}")
    L += ["", "## Comparability", ""]
    L += [f"- {k}: {'aggregatable' if v else 'SEGMENTED'}" for k, v in rep["aggregatable"].items()]
    L += [f"- WARNING: {w}" for w in rep["comparability_warnings"]]
    L += ["", "## Segments", ""]
    for s in rep["segments"]:
        L.append(f"- {s['from_utc'][11:19]}Z -> {s['to_utc'][11:19]}Z: {s['candidates_first_seen']} candidates "
                 f"{s['by_first_seen_phase']}, outcomes {s['outcome_status']}, +30m {s['ret_30m']}, close "
                 f"{s['close_ret']}")
    L += ["", "## Notification (attention only; never affects detection)", "",
          f"- decisions: {rep['notification']['decisions']}", f"- delivery: {rep['notification']['delivery_states']}",
          "", "## Horizons", ""]
    L += [f"- {h}: {v}" for h, v in rep["horizons"].items()]
    L += ["", "## Paper execution", "", f"- {rep['paper_execution']}", ""]
    return "\n".join(L)


def write_report(root, window_id: str) -> Path:
    rep = build_report(root, window_id)
    d = root_dir(root) / "reports" / window_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "session_report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    (d / "session_report.md").write_text(render_md(rep), encoding="utf-8")
    return d


class Reporter:
    def __init__(self, *, root=None, clock=None):
        from talonx_opportunity.db import utcnow
        self.root, self.clock = root, clock or utcnow
        self.last: dict = {}

    def tick(self) -> float:
        from talonx_opportunity.phases import phase_at
        _, w = phase_at(self.clock())
        if w is not None:
            p = write_report(self.root, w.window_id)
            self.last = {"window_id": w.window_id, "path": str(p)}
        return 900.0

    def detail(self) -> dict:
        return dict(self.last)


def main(argv=None) -> int:
    from talonx_opportunity.runtime import run_component
    root = os.environ.get("TALONX_OPP_ROOT")
    r = Reporter(root=root)
    run_component("reporting", tick=r.tick, root=root, detail=r.detail)
    return 0
