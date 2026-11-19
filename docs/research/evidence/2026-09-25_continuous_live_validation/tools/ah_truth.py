"""TRUE AFTER_HOURS-data validation (generated from regular_truth.py; TARGET=AFTER_HOURS, T0=20:00Z) (READ-ONLY; every store opened mode=ro).

PROCESSING_PHASE = wall-clock phase the event was processed in (event.phase).
DATA_PHASE       = phase of the causal bar used: the symbol's own last_bar_utc (bar START time) if present, else the
                   scan's data_as_of - 1 min. A bar at t is complete at t+1 and visible under the 15-min SIP
                   entitlement at t+1+15, so the 13:30Z bar is first usable at wall 13:46Z (as_of >= 13:31Z).

usage: python regular_truth.py [--wait-first-true-setup --until ISO] [--since ISO]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
sys.path.insert(0, str(REPO))
from talonx_opportunity.phases import phase_at  # noqa: E402

R = REPO / "results" / "opportunity"
WID = "2026-09-25"
OPEN = datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc)
import os as _os
T0 = datetime.fromisoformat(_os.environ.get("AH_T0", "2026-09-25T20:00:00+00:00"))   # override only for replay tests
TARGET = _os.environ.get("AH_TARGET", "AFTER_HOURS")
FIRST_REG_BAR_COMPLETE = T0 + timedelta(minutes=1)          # T1: 13:30 bar exists (complete) at provider
FIRST_REG_BAR_VISIBLE = FIRST_REG_BAR_COMPLETE + timedelta(minutes=15)   # T2: entitlement
HELD_SETUP_COHORT = ("NCPL", "BB", "PMAX", "CIFR")
CONTINUITY = ("INLF", "GLND", "GRML", "STAK")
SETUP = ("BULLISH", "BEARISH")
LIMIT = 75   # live NEW limit since the 14:09:49Z REGULAR extension (was 40)


def ro(name):
    c = sqlite3.connect(f"file:{R / name}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def data_phase(ev) -> tuple[str, str | None]:
    f = json.loads(ev["features_json"] or "{}")
    lb = ts(f.get("last_bar_utc"))
    if lb is None and ev["data_as_of_utc"]:
        lb = ts(ev["data_as_of_utc"]) - timedelta(minutes=1)
    return (phase_at(lb)[0] if lb else "UNKNOWN"), (lb.isoformat()[:19] if lb else None)


def build(since: str):
    now = datetime.now(timezone.utc)
    o, n, ob, oc, mk = ro("opportunity.db"), ro("notification.db"), ro("opportunity_research_notifications.db"), \
        ro("outcomes.db"), ro("market.db")
    cands = {r["candidate_id"]: dict(r) for r in o.execute("select * from candidates where window_id=?", (WID,))}
    events = [dict(r) for r in o.execute("select * from candidate_events where window_id=? order by seq", (WID,))]
    by_c = defaultdict(list)
    for e in events:
        e["DATA_PHASE"], e["causal_bar"] = data_phase(e)
        by_c[e["candidate_id"]].append(e)
    decs = {r["event_id"]: dict(r) for r in n.execute("select * from decisions")}
    obx = {r["event_id"]: dict(r) for r in ob.execute("select * from ops_notification_outbox")}
    orows = {r["candidate_id"]: dict(r) for r in oc.execute("select * from outcomes")}
    scans = [dict(r) for r in o.execute("select decision_utc, data_as_of_utc, phase, state, duration_s from scans "
                                        "where window_id=? and data_as_of_utc is not null order by decision_utc", (WID,))]
    cycles = [dict(r) for r in mk.execute("select at_utc, as_of_utc, phase, duration_s, bars, failed_symbols from "
                                          "cycles where window_id=? and as_of_utc is not null order by id", (WID,))]

    def sent_at(e):
        d = decs.get(e["event_id"]) or {}
        x = obx.get(d.get("outbox_event_id") or "") or {}
        return d, x

    out = {"time_utc": now.isoformat()[:19], "PROCESSING_PHASE": phase_at(now)[0]}
    last_scan = scans[-1] if scans else None
    if last_scan:
        la = ts(last_scan["data_as_of_utc"]) - timedelta(minutes=1)
        out["LATEST_DATA_AS_OF"] = last_scan["data_as_of_utc"][11:19]
        out["LATEST_DATA_PHASE"] = phase_at(la)[0]

    # --- first-seen counters
    reg_wall, reg_data, transition = [], [], []
    for c in cands.values():
        e0 = by_c[c["candidate_id"]][0]
        if e0["phase"] == TARGET:
            reg_wall.append((c, e0))
            if e0["DATA_PHASE"] == TARGET:
                reg_data.append((c, e0))
    first_reg_scan = next((s for s in scans if ts(s["data_as_of_utc"]) >= FIRST_REG_BAR_COMPLETE), None)
    for c, e0 in reg_wall:
        if first_reg_scan is None or e0["at_utc"] <= first_reg_scan["decision_utc"]:
            transition.append({"symbol": c["symbol"], "first_seen": e0["at_utc"][11:19], "causal_bar": e0["causal_bar"],
                               "class": f"B_{TARGET}/{TARGET}" if e0["DATA_PHASE"] == TARGET else
                               f"A_{TARGET}/" + e0["DATA_PHASE"]})
    out["AH_WALLCLOCK_FIRST_SEEN"] = len(reg_wall)
    out["AH_DATA_FIRST_SEEN"] = len(reg_data)
    out["transition_cohort"] = {"TRANSITION_WALLCLOCK_ONLY_COUNT": sum(t["class"].startswith("A") for t in transition),
                                "TRANSITION_TRUE_REGULAR_COUNT": sum(t["class"].startswith("B") for t in transition),
                                "detail": transition[:30]}

    # --- forensics of every REGULAR_DATA_FIRST_SEEN candidate
    fx = []
    for c, e0 in sorted(reg_data, key=lambda x: x[1]["at_utc"]):
        f = json.loads(e0["features_json"] or "{}")
        d, x = sent_at(e0)
        fx.append({"symbol": c["symbol"], "cid": c["candidate_id"], "processed": e0["at_utc"][11:19],
                   "causal_bar": e0["causal_bar"], "processing_phase": e0["phase"], "data_phase": e0["DATA_PHASE"],
                   "move_pct": round(e0["gap_pct"] or 0, 2), "volume": f.get("pm_volume"),
                   "dollars": round(f.get("pm_dollars") or 0), "activity_vs_adv": round(f.get("activity_adv_fraction") or 0, 3),
                   "catalyst": e0["catalyst"], "score": e0["score"], "cls": e0["classification"],
                   "horizons": json.loads(c["horizons_json"] or "[]"), "decision": d.get("decision"),
                   "reason": d.get("reason"), "policy": d.get("policy_version"), "sent": (x.get("sent_at_utc") or "")[11:19] or None,
                   "reserve_slot": bool(d.get("counted_new")) and e0["classification"] in SETUP and d.get("decision") == "SELECTED",
                   "internal_latency_s": round((ts(x["sent_at_utc"]) - ts(e0["at_utc"])).total_seconds(), 1)
                   if x.get("sent_at_utc") else None,
                   "data_to_send_s": round((ts(x["sent_at_utc"]) - ts(e0["causal_bar"] + "+00:00")).total_seconds())
                   if x.get("sent_at_utc") and e0["causal_bar"] else None})
    out["regular_data_first_seen"] = {
        "TOTAL": len(fx), "WATCH": sum(r["cls"] == "WATCH" for r in fx), "BULLISH": sum(r["cls"] == "BULLISH" for r in fx),
        "BEARISH": sum(r["cls"] == "BEARISH" for r in fx), "SENT": sum(bool(r["sent"]) for r in fx),
        "HELD": sum((r["decision"] or "").startswith("BUDGET") for r in fx), "detail": fx}

    # --- true REGULAR setups (any NEW/UPGRADE setup event on REGULAR data, incl. continuing premarket identities)
    true_setups = []
    for e in events:
        if e["DATA_PHASE"] == TARGET and e["classification"] in SETUP and e["event_type"] in ("NEW", "UPGRADE"):
            d, x = sent_at(e)
            true_setups.append({"symbol": e["symbol"], "cid": e["candidate_id"], "type": e["event_type"],
                                "processed": e["at_utc"][11:19], "causal_bar": e["causal_bar"], "score": e["score"],
                                "move_pct": round(e["gap_pct"] or 0, 2), "catalyst": e["catalyst"],
                                "volume": json.loads(e["features_json"] or "{}").get("pm_volume"),
                                "decision": d.get("decision"), "reason": d.get("reason"), "counted_new": d.get("counted_new"),
                                "budget_at_decision": d.get("budget_json"), "outbox": x.get("state"),
                                "sent": (x.get("sent_at_utc") or "")[11:19] or None,
                                "latency_s": round((ts(x["sent_at_utc"]) - ts(e["at_utc"])).total_seconds(), 1)
                                if x.get("sent_at_utc") else None,
                                "persisted": e["candidate_id"] in cands})
    out["true_regular_setups"] = true_setups

    # --- T0..T6 timeline
    T3 = next((c for c in cycles if c["as_of_utc"] and ts(c["as_of_utc"]) >= FIRST_REG_BAR_COMPLETE), None)
    T4 = first_reg_scan
    T5 = fx[0] if fx else None
    t6 = next((r for r in fx if r["cls"] in SETUP and r["sent"]), None)
    d = lambda a, b: None if a is None or b is None else round((b - a).total_seconds())  # noqa: E731
    t3 = ts(T3["at_utc"]) if T3 else None
    t4 = ts(T4["decision_utc"]) if T4 else None
    t5 = ts(WID + "T" + T5["processed"] + "+00:00") if T5 else None
    t6s = ts(WID + "T" + t6["sent"] + "+00:00") if t6 else None
    out["timeline"] = {"T0": T0.isoformat()[11:19], "T1_bar_exists": FIRST_REG_BAR_COMPLETE.isoformat()[11:19], "T2_visible_under_entitlement": FIRST_REG_BAR_VISIBLE.isoformat()[11:19],
                       "T3_ingested": T3 and T3["at_utc"][11:19], "T3_as_of": T3 and T3["as_of_utc"][11:19],
                       "T4_first_scan_regular_data": T4 and T4["decision_utc"][11:19],
                       "T5_first_regular_data_candidate": T5 and f"{T5['processed']} {T5['symbol']}",
                       "T6_first_regular_data_setup_send": t6 and f"{t6['sent']} {t6['symbol']}",
                       "T2-T0_provider_entitlement_s": 960, "T3-T2_ingestion_s": d(FIRST_REG_BAR_VISIBLE, t3),
                       "T4-T3_discovery_s": d(t3, t4), "T5-T4_candidate_s": d(t4, t5), "T6-T5_notification_s": d(t5, t6s),
                       "wallclock_regular_scans_before_regular_data": sum(1 for s in scans if s["phase"] == TARGET
                                                                          and ts(s["data_as_of_utc"]) < FIRST_REG_BAR_COMPLETE)}

    # --- continuity cohort: named + top-5 active premarket by score
    pm_active = sorted((c for c in cands.values() if c["first_seen_phase"] == "PREMARKET"
                        and c["state"] in ("WATCH", "BULLISH_SETUP", "BEARISH_SETUP")),
                       key=lambda c: -(c["max_score"] or 0))[:5]
    syms = set(CONTINUITY) | {c["symbol"] for c in pm_active}
    cont = []
    for c in cands.values():
        if c["symbol"] not in syms:
            continue
        evs = by_c[c["candidate_id"]]
        pre = [e for e in evs if e["DATA_PHASE"] != TARGET]
        reg = [e for e in evs if e["DATA_PHASE"] == TARGET]
        cont.append({"symbol": c["symbol"], "cid": c["candidate_id"], "state_now": c["state"],
                     "state_before_open": pre[-1]["to_state"] if pre else None, "score_before": pre[-1]["score"] if pre else None,
                     "first_regular_data_event": reg[0]["at_utc"][11:19] if reg else None,
                     "regular_events": [f"{e['at_utc'][11:16]}:{e['event_type'][:3]}:{e['to_state']}:{round(e['score'] or 0)}" for e in reg],
                     "last_observed": (c["last_observed_utc"] or "")[11:19], "last_phase": c["last_phase"],
                     "outcome": (orows.get(c["candidate_id"]) or {}).get("status")})
    dup = [k for k, v in Counter((c["symbol"], c["family"]) for c in cands.values()).items() if v > 1]
    out["continuity"] = {"cohort": cont, "duplicate_identities": dup}

    # --- MATERIAL_UPDATE usefulness (sent after `since`)
    mu = []
    for e in events:
        if e["event_type"] != "MATERIAL_UPDATE" or e["at_utc"] < since:
            continue
        d, x = sent_at(e)
        if x.get("state") != "SENT":
            continue
        prev = [p for p in by_c[e["candidate_id"]] if p["seq"] < e["seq"]]
        p = prev[-1] if prev else {}
        pf, ef = json.loads(p.get("features_json") or "{}"), json.loads(e["features_json"] or "{}")
        ds = (e["score"] or 0) - (p.get("score") or 0)
        dg = (e["gap_pct"] or 0) - (p.get("gap_pct") or 0)
        da = (ef.get("activity_adv_fraction") or 0) - (pf.get("activity_adv_fraction") or 0)
        cls_ch = e["classification"] != p.get("classification") or e["to_state"] != p.get("to_state")
        cat_ch = (e["catalyst"] or "") != (p.get("catalyst") or "")
        k = "HIGH" if cls_ch or cat_ch else "LOW" if abs(ds) < 5 and abs(dg) < 5 else "MEDIUM"
        mu.append({"symbol": e["symbol"], "at": e["at_utc"][11:16], "prior_state": p.get("to_state"), "new_state": e["to_state"],
                   "score": f"{round(p.get('score') or 0, 1)}->{round(e['score'] or 0, 1)}", "move_delta": round(dg, 2),
                   "activity_delta": round(da, 3), "catalyst_change": cat_ch, "class_change": cls_ch, "info": k})
    per_c = Counter(e["symbol"] for e in events if (sent_at(e)[1] or {}).get("state") == "SENT")
    out["material_update_audit"] = {"since": since[11:19], "MATERIAL_UPDATE_TOTAL": len(mu),
                                    "HIGH_INFORMATION": sum(m["info"] == "HIGH" for m in mu),
                                    "MEDIUM_INFORMATION": sum(m["info"] == "MEDIUM" for m in mu),
                                    "LOW_INFORMATION": sum(m["info"] == "LOW" for m in mu),
                                    "detail": mu[-15:], "messages_per_candidate_top": per_c.most_common(10)}

    # --- held-setup cohort (held before the override)
    hs = []
    for e in events:
        d = decs.get(e["event_id"]) or {}
        if (e["classification"] in SETUP and e["event_type"] in ("NEW", "UPGRADE") and (d.get("decision") or "").startswith("BUDGET")) \
                or (e["symbol"] in HELD_SETUP_COHORT and e["event_type"] == "UPGRADE"):
            c = cands.get(e["candidate_id"]) or {}
            r = orows.get(e["candidate_id"]) or {}
            later = [f"{x['at_utc'][11:16]}:{x['event_type'][:3]}:{x['to_state']}:{round(x['score'] or 0)}"
                     for x in by_c[e["candidate_id"]] if x["seq"] > e["seq"]]
            hs.append({"symbol": e["symbol"], "cid": e["candidate_id"], "upgrade_at": e["at_utc"][11:19], "score": e["score"],
                       "cls": e["classification"], "held_reason": d.get("decision"), "policy": d.get("policy_version"),
                       "state_now": c.get("state"), "evolution": later[-6:],
                       "outcome": {k: r.get(k) for k in ("status", "ret_30m_pct", "ret_1h_pct", "mfe_pct", "mae_pct")}})
    out["held_setup_cohort"] = hs

    # --- SHADOW discovery-phase semantics (production = PROCESSING_PHASE; shadow = DATA_PHASE). Read-only.
    from talonx_opportunity.discovery import _horizons
    from talonx_opportunity.config import CONTINUOUS_RESEARCH_V1 as CFG
    from talonx_opportunity.evaluators import PHASE_SCOPE
    stale_ph = set(CFG.stale_invalidates_phases)
    sh_cases, hz_diff, stale_diff, elig_diff = [], 0, 0, 0
    for e in events:
        if e["phase"] == e["DATA_PHASE"] or e["DATA_PHASE"] == "UNKNOWN" or e["at_utc"] < T0.isoformat():
            continue
        c = cands.get(e["candidate_id"]) or {}
        prod_h = json.loads(c.get("horizons_json") or "[]") if e["event_type"] == "NEW" else _horizons(e["phase"])
        sh_h = _horizons(e["DATA_PHASE"])
        prod_eval = sorted(h for h, ps in PHASE_SCOPE.items() if e["phase"] in ps)
        sh_eval = sorted(h for h, ps in PHASE_SCOPE.items() if e["DATA_PHASE"] in ps)
        sd = (e["phase"] in stale_ph) != (e["DATA_PHASE"] in stale_ph)
        hz_diff += sorted(prod_h) != sorted(sh_h)
        elig_diff += prod_eval != sh_eval
        stale_diff += sd and e["event_type"] == "INVALIDATED" and "stale" in (e["reason"] or "")
        sh_cases.append({"symbol": e["symbol"], "type": e["event_type"], "at": e["at_utc"][11:19], "PROC": e["phase"],
                         "DATA": e["DATA_PHASE"], "prod_horizons": prod_h, "shadow_horizons": sh_h,
                         "prod_evaluators": prod_eval, "shadow_evaluators": sh_eval, "stale_gate_differs": sd,
                         "cls": e["classification"]})
    # stale HOLDs in a non-invalidating processing phase while the data phase would invalidate (evening case)
    held_stale_would_invalidate = 0
    for s in scans:
        dph = phase_at(ts(s["data_as_of_utc"]) - timedelta(minutes=1))[0]
        if s["decision_utc"] >= T0.isoformat() and s["phase"] != dph and dph in stale_ph and s["phase"] not in stale_ph:
            f = json.loads(o.execute("select funnel_json from scans where decision_utc=?", (s["decision_utc"],)).fetchone()[0] or "{}")
            held_stale_would_invalidate += int(f.get("HELD_STALE_NON_INVALIDATING_PHASE", 0) or 0)
    out["discovery_phase_shadow"] = {
        "PHASE_SEMANTIC_CASES": len(sh_cases), "HORIZON_LABEL_DIFFERENCES": hz_diff,
        "STALE_DECISION_DIFFERENCES": stale_diff + held_stale_would_invalidate,
        "stale_holds_that_data_phase_would_invalidate": held_stale_would_invalidate,
        "CANDIDATE_ELIGIBILITY_DIFFERENCES(evaluator scope)": elig_diff,
        "CLASSIFICATION_DIFFERENCES": 0,
        "classification_note": "classification = frozen V1 score/decide over features; phase is not an input (verified in code)",
        "detail": sh_cases[:25]}

    # --- F3 live acceptance: candidates processed in one phase from the previous phase's data
    acc = []
    for c in cands.values():
        pp = phase_at(ts(c["first_seen_utc"]))[0]
        dp = phase_at(ts(c["first_data_as_of_utc"]) - timedelta(minutes=1))[0] if c["first_data_as_of_utc"] else "UNKNOWN"
        if pp != dp:
            r = orows.get(c["candidate_id"]) or {}
            acc.append({"symbol": c["symbol"], "processed": c["first_seen_utc"][11:19], "PROCESSING_PHASE": pp,
                        "DATA_PHASE": dp, "DATA_AS_OF": (c["first_data_as_of_utc"] or "")[11:19],
                        "expected_model": "PREMARKET_RESEARCH_V1.measure" if ts(c["first_data_as_of_utc"]) <= OPEN
                        else "N/A" if ts(c["first_data_as_of_utc"]) >= OPEN.replace(hour=20) else "SINCE_FIRST_SEEN_V1",
                        "outcome_model": r.get("model"), "status": r.get("status"), "ref_time": (r.get("ref_time_utc") or "")[11:19],
                        "ret_30m": r.get("ret_30m_pct")})
    for a_ in acc:
        a_["fix_ok"] = None if a_["outcome_model"] is None else a_["outcome_model"] == a_["expected_model"]
    out["f3_acceptance"] = {"cross_phase_candidates": len(acc), "rows_present": sum(a_["outcome_model"] is not None for a_ in acc),
                            "fix_ok": sum(a_["fix_ok"] is True for a_ in acc), "fix_wrong": [a_ for a_ in acc if a_["fix_ok"] is False],
                            "detail": acc[:20]}

    # --- phase reserve
    used = n.execute("select count(*), sum(classification='WATCH') from decisions where window_id=? and decision='SELECTED' "
                     "and counted_new=1", (WID,)).fetchone()
    ex = Counter(r[0] for r in n.execute("select phase from decisions where window_id=? and decision='SELECTED' and counted_new=1 "
                                         "and policy_version!='LAB_NOTIFY_POLICY_V1'", (WID,)))
    ph = phase_at(now)[0]
    left = LIMIT - used[0]
    blocked = [(r["symbol"], r["phase"], r["decision"], r["decided_utc"][11:19]) for r in n.execute(
        "select * from decisions where policy_version in ('LAB_NOTIFY_POLICY_V1_PHASE_RESERVED_20260925','LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925') and "
        "classification in ('BULLISH','BEARISH') and decision like 'BUDGET%'")]
    out["reserve"] = {"TOTAL_NEW_USED": f"{used[0]}/{LIMIT}", "WATCH_USED": f"{used[1]}/15",
                      "PREMARKET_EXTRA_USED": f"{ex['PREMARKET']}/5", "REGULAR_EXTRA_USED": ex["REGULAR"],
                      "REGULAR_AVAILABLE_NOW": max(0, left - 3) if ph in ("PREMARKET", "REGULAR") else 0,
                      "AFTER_HOURS_RESERVED": min(3, left), "AFTER_HOURS_EXTRA_USED": ex["AFTER_HOURS"],
                      "setups_held_under_phase_policy": blocked,
                      "DEFECT_setup_blocked_with_valid_capacity": [b for b in blocked if b[2] == "BUDGET_EXHAUSTED_TOTAL" and used[0] < LIMIT]}
    # --- scan / ingest performance since T0
    sd = [s["duration_s"] for s in scans if s["decision_utc"] >= T0.isoformat() and s["duration_s"] is not None]
    cd = [c["duration_s"] for c in cycles if c["at_utc"] >= T0.isoformat() and c["duration_s"] is not None]
    pc = lambda xs, q: None if not xs else round(sorted(xs)[min(len(xs) - 1, int(q * (len(xs) - 1) + .5))], 1)  # noqa: E731
    out["perf_since_open"] = {"scan_n": len(sd), "scan_p50": pc(sd, .5), "scan_p90": pc(sd, .9), "scan_max": max(sd, default=None),
                              "scan_warn": "CADENCE_FAILURE" if sd and max(sd) >= 300 else ">240" if sd and max(sd) > 240
                              else ">180" if sd and max(sd) > 180 else "OK",
                              "ingest_n": len(cd), "ingest_p50": pc(cd, .5), "ingest_p90": pc(cd, .9), "ingest_max": max(cd, default=None),
                              "ingest_failed_symbols": sum(c["failed_symbols"] or 0 for c in cycles if c["at_utc"] >= T0.isoformat())}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-first-true-setup", action="store_true")
    ap.add_argument("--wait-first-regular-data", action="store_true")
    ap.add_argument("--until", default="2026-09-26T00:00:00+00:00")
    ap.add_argument("--since", default="2026-09-25T19:30:00+00:00")
    a = ap.parse_args()
    until = datetime.fromisoformat(a.until)
    announced = set()
    while True:
        o = build(a.since)
        if not (a.wait_first_true_setup or a.wait_first_regular_data):
            print(json.dumps(o, indent=1, default=str))
            return
        if a.wait_first_regular_data and o["timeline"]["T4_first_scan_regular_data"] and "scan" not in announced:
            announced.add("scan")
            print("FIRST_SCAN_WITH_AH_DATA", json.dumps(o["timeline"]), flush=True)
            return
        if a.wait_first_true_setup:
            ts_ = o["true_regular_setups"]
            if ts_ and "setup" not in announced:
                announced.add("setup")
                print("FIRST_TRUE_AH_SETUP", json.dumps(ts_[0]), flush=True)
            if ts_ and (ts_[0]["outbox"] in ("SENT", "FAILED", "DEAD") or (ts_[0]["decision"] or "").startswith(("BUDGET", "NOT_", "POLICY"))):
                print("FIRST_TRUE_AH_SETUP_OUTCOME", json.dumps(ts_[0]), json.dumps(o["reserve"]), flush=True)
                return
        if datetime.now(timezone.utc) >= until:
            print("UNTIL_REACHED", json.dumps(o["timeline"]))
            return
        time.sleep(20)


if __name__ == "__main__":
    main()
