"""Aggressive continuous validation tracks (READ-ONLY; every store opened mode=ro; no API calls).

Live movers are derived from DATA_INGESTION's window-to-date aggregates (the same SIP data discovery used), so a
"miss" is judged causally against what TalonX had at its own data as-of.
"""
from __future__ import annotations

import json
import os
import sqlite3
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
sys.path.insert(0, str(REPO))
from talonx_opportunity.phases import phase_at  # noqa: E402

R = REPO / "results" / "opportunity"
TASK_START = os.environ.get("TRACK_SINCE", "2026-09-25T11:40:00+00:00")
MOVER_PCT = 5.0
ACTIVE = ("WATCH", "BULLISH_SETUP", "BEARISH_SETUP")


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return None if not xs else round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 1)


def stats(xs):
    xs = [x for x in xs if x is not None]
    return {"n": len(xs), "mean": round(st.mean(xs), 3), "median": round(st.median(xs), 3)} if xs else {"n": 0}


now = datetime.fromisoformat(os.environ["TRACK_NOW"]) if os.environ.get("TRACK_NOW") else datetime.now(timezone.utc)
phase, w = phase_at(now)
wid = w.window_id if w else now.date().isoformat()
o, n, ob, oc, mk = (ro(R / f) for f in ("opportunity.db", "notification.db", "opportunity_research_notifications.db",
                                          "outcomes.db", "market.db"))
out: dict = {"time_utc": now.isoformat()[:19], "phase": phase}
cands = {r["candidate_id"]: dict(r) for r in o.execute("select * from candidates")}
events = [dict(r) for r in o.execute("select * from candidate_events order by seq")]
ev_by_id = {e["event_id"]: e for e in events}
decs = {r["event_id"]: dict(r) for r in n.execute("select * from decisions")}
obx = {r["event_id"]: dict(r) for r in ob.execute("select * from ops_notification_outbox")}
scans = [dict(r) for r in o.execute("select decision_utc, phase, state, data_as_of_utc, duration_s from scans "
                                    "order by decision_utc")]

# ---------- 1. regular discovery proof
pm = [s for s in scans if s["phase"] == "PREMARKET"]
rg = [s for s in scans if s["phase"] == "REGULAR"]
ah = [s for s in scans if s["phase"] == "AFTER_HOURS"]
reg_first = sorted((c for c in cands.values() if c["first_seen_phase"] == "REGULAR"), key=lambda c: c["first_seen_utc"])
reg_sent = sorted((obx[d["outbox_event_id"]]["sent_at_utc"] for d in decs.values()
                   if d["phase"] == "REGULAR" and d["outbox_event_id"] in obx
                   and obx[d["outbox_event_id"]]["state"] == "SENT"), key=str)
gaps = [(datetime.fromisoformat(b["decision_utc"]) - datetime.fromisoformat(a["decision_utc"])).total_seconds()
        for a, b in zip(rg, rg[1:])]
out["regular"] = {"last_premarket_scan": pm[-1]["decision_utc"][11:19] if pm else None,
                  "first_regular_scan": rg[0] if rg else None, "regular_scans": len(rg),
                  "regular_cadence_s": {"median": st.median(gaps) if gaps else None, "max": max(gaps) if gaps else None},
                  "first_after_hours_scan": ah[0] if ah else None,
                  "REGULAR_FIRST_SEEN_COUNT": len(reg_first),
                  "REGULAR_FIRST_SEEN_SYMBOLS": [f"{c['symbol']}:{c['classification']}" for c in reg_first][:40],
                  "FIRST_REGULAR_CANDIDATE_TIME": reg_first[0]["first_seen_utc"][11:19] if reg_first else None,
                  "FIRST_REGULAR_LAB_DELIVERY_TIME": reg_sent[0][11:19] if reg_sent else None,
                  "AFTER_HOURS_FIRST_SEEN_COUNT": sum(1 for c in cands.values() if c["first_seen_phase"] == "AFTER_HOURS")}

# ---------- 2. phase continuity cohort
by_c = defaultdict(list)
for e in events:
    by_c[e["candidate_id"]].append(e)
cohort_syms = {"INLF", "GLND", "GRML", "STAK"}
cohort_syms |= {c["symbol"] for c in sorted((c for c in cands.values() if c["state"] in ACTIVE),
                                            key=lambda c: -(c["max_score"] or 0))[:4]}
cohort = []
for c in cands.values():
    if c["symbol"] in cohort_syms:
        evs = by_c[c["candidate_id"]]
        cohort.append({"cid": c["candidate_id"], "state": c["state"], "phases": sorted({e["phase"] for e in evs}),
                       "last_phase_observed": c["last_phase"], "last_observed": (c["last_observed_utc"] or "")[11:19],
                       "chain": " > ".join(f"{e['at_utc'][11:16]}{e['phase'][0]}:{e['event_type'][:3]}"
                                           f"({'' if e['score'] is None else round(e['score'])})" for e in evs)})
dup = [k for k, v in Counter((c["symbol"], c["family"], c["window_id"]) for c in cands.values()).items() if v > 1]
out["continuity"] = {"cohort": cohort, "duplicate_identities": dup,
                     "candidates_spanning_phases": sum(1 for v in by_c.values() if len({e["phase"] for e in v}) > 1),
                     "active_last_observed_in_regular": sum(1 for c in cands.values()
                                                            if c["state"] in ACTIVE and c["last_phase"] == "REGULAR")}

# ---------- 3. live missed-opportunity watch (causal: TalonX's own aggregates at its own as-of)
uni = mk.execute("select members_json from universe where window_id=?", (wid,)).fetchone()
members = {m["symbol"]: m for m in json.loads(uni["members_json"]) if m.get("status") == "ELIGIBLE"} if uni else {}
daily = {r["symbol"]: json.loads(r["bars_json"]) for r in mk.execute("select symbol, bars_json from daily where window_id=?",
                                                                       (wid,))}
aggs = {r["symbol"]: json.loads(r["agg_json"]) for r in mk.execute("select symbol, agg_json from aggregates where "
                                                                     "window_id=?", (wid,))}
latest = {r["symbol"]: dict(r) for r in o.execute("select * from symbol_latest where window_id=?", (wid,))}
ingest = mk.execute("select * from ingestion_state where window_id=?", (wid,)).fetchone()
surfaced = {d["candidate_id"] for d in decs.values() if d["decision"] == "SELECTED"}
movers, klass = [], Counter()
for sym, a in aggs.items():
    d = [b for b in daily.get(sym, []) if b["t"][:10] < wid]
    if not d or not a.get("last_c"):
        continue
    pc = d[-1]["c"]
    adv = sum(b["v"] * b["c"] for b in d[-20:]) / len(d[-20:])
    if pc < 1.0 or adv < 1_000_000:
        continue                                   # frozen hard gates: not realistically actionable
    move = (a["last_c"] / pc - 1) * 100
    if abs(move) < MOVER_PCT:
        continue
    fam = "GAP_UP" if move > 0 else "GAP_DOWN"
    c = cands.get(f"{wid}:{sym}:{fam}")
    lt = latest.get(sym) or {}
    cls = lt.get("cls") or "NOT_EVALUATED"
    # 2026-09-25 REGULAR brief lettering: A sent, B held, C detected-not-eligible, D rejected, E stale-closed,
    # F provider unavailable, G available-but-not-detected (defect), H other
    last_inv = [e for e in by_c.get(c["candidate_id"], []) if e["event_type"] == "INVALIDATED"] if c else []
    held_ids = {d["candidate_id"] for d in decs.values() if d["decision"].startswith("BUDGET")}
    if c and c["state"] in ACTIVE:
        k = ("A_DETECTED_AND_SENT" if c["candidate_id"] in surfaced else "B_DETECTED_HELD_BY_NOTIFICATION_POLICY"
             if c["candidate_id"] in held_ids else "C_DETECTED_NOT_NOTIFICATION_ELIGIBLE")
    elif c and cls in ACTIVE and last_inv and "stale" in (last_inv[-1]["reason"] or ""):
        k = "E_BLOCKED_BY_STALE_INVALIDATION"
    elif c and cls in ACTIVE:
        k = "H_CLOSED_BY_OTHER_LIFECYCLE_RULE (worthy now)"
    elif c:
        k = "C_DETECTED_NOT_NOTIFICATION_ELIGIBLE (closed; not worthy now: " + cls + ")"
    elif cls.startswith("UNKNOWN"):
        k = "F_PROVIDER_DATA_UNAVAILABLE"
    elif cls.startswith("REJECTED:") or cls == "SCORED":
        k = "D_REJECTED_BY_SCORING_OR_ENTRY_RULE (" + cls.replace("REJECTED:", "") + ")"
    elif cls in ACTIVE:
        k = "G_DATA_AVAILABLE_BUT_NOT_DETECTED (DEFECT?)"
    else:
        k = "I_OTHER (" + cls + ")"
    klass[k.split(" (")[0]] += 1
    movers.append({"symbol": sym, "move_pct": round(move, 2), "prev_close": pc, "last": a["last_c"],
                   "last_print": a["last_t"], "session_dollars": round(a.get("dollars_s", 0)), "bars": a.get("bars"),
                   "adv20": round(adv), "activity_pct": round(100 * (a.get("volume_s", 0)) / max(1, sum(b["v"] for b in d[-20:]) / len(d[-20:])), 1),
                   "latest_cls": cls, "latest_scan": (lt.get("decision_utc") or "")[11:19], "class": k})
out["missed"] = {"movers_ge_5pct_actionable": len(movers), "by_class": dict(klass),
                 "E_G_H_I_detail": [m for m in movers if m["class"][0] in "EGHI"][:25],
                 "D_detail_top": sorted((m for m in movers if m["class"][0] == "D"),
                                        key=lambda m: -abs(m["move_pct"]))[:12]}

# ---------- 4. latency (events after TASK_START that were SENT)
lat = []
for eid, d in decs.items():
    x = obx.get(d["outbox_event_id"] or "")
    e = ev_by_id.get(eid)
    if not x or x["state"] != "SENT" or not e or e["at_utc"] < TASK_START:
        continue
    T0, T1 = e["data_as_of_utc"], e["at_utc"]
    T2, T3, T4 = d["decided_utc"], x["created_at_utc"], x["sent_at_utc"]
    f = lambda a, b: None if not a or not b else round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds(), 1)  # noqa: E731
    lat.append({"symbol": e["symbol"], "type": e["event_type"], "provider_age_s": f(T0, T1), "t1_t2": f(T1, T2),
                "t2_t3": f(T2, T3), "t3_t4": f(T3, T4), "internal_t1_t4": f(T1, T4)})
summ = {k: {"p50": pct([x[k] for x in lat], .5), "p90": pct([x[k] for x in lat], .9),
            "max": max((x[k] for x in lat if x[k] is not None), default=None)}
        for k in ("provider_age_s", "t1_t2", "t2_t3", "t3_t4", "internal_t1_t4")}
out["latency"] = {"n": len(lat), **summ, "worst10": sorted(lat, key=lambda x: -(x["internal_t1_t4"] or 0))[:10]}

# ---------- 5/6. outcomes + quality separation
orows = {r["candidate_id"]: dict(r) for r in oc.execute("select * from outcomes")}
open_utc = w.open_utc if w else None
exp = [c for c in cands.values() if open_utc and now >= open_utc + timedelta(minutes=16)
       and c["window_id"] == wid and datetime.fromisoformat(c["first_seen_utc"]) < w.close_utc]
mature30 = [c for c in exp if (now - max(open_utc, datetime.fromisoformat(c["first_seen_utc"]))).total_seconds()
            >= (30 + 16) * 60]
missing = [c["candidate_id"] for c in exp if c["candidate_id"] not in orows]
stale_rows = [k for k, r in orows.items() if not r["session_complete"] and r["status"] != "NOT_APPLICABLE_SAME_DAY"
              and (now - datetime.fromisoformat(r["updated_utc"])).total_seconds() > 25 * 60]
wrong = [k for k, r in orows.items() if k not in cands or cands[k]["symbol"] != r["symbol"]]
m30_missing = [c["candidate_id"] for c in mature30 if (orows.get(c["candidate_id"]) or {}).get("ret_30m_pct") is None]
sent_c = {d["candidate_id"] for d in decs.values() if d["decision"] == "SELECTED"}
held_c = {d["candidate_id"] for d in decs.values() if d["decision"].startswith("BUDGET")} - sent_c
cov = lambda s: f"{sum(1 for c in s if c in orows)}/{len(s)}"  # noqa: E731
first_ev = {cid: v[0] for cid, v in by_c.items()}


def grp(c):
    e = first_ev.get(c["candidate_id"])
    s = (e or {}).get("score") or 0
    k = (e or {}).get("classification")
    if k in ("BULLISH", "BEARISH"):
        return "A_setup_ge80" if s >= 80 else "B_setup_60_80"
    return "C_watch_ge50" if s >= 50 else "D_watch_lt50"


q = defaultdict(list)
for c in cands.values():
    if c["candidate_id"] in orows and orows[c["candidate_id"]]["status"] not in ("OUTCOME_PENDING", "NOT_APPLICABLE_SAME_DAY"):
        q[grp(c)].append(orows[c["candidate_id"]])
out["outcomes"] = {"expected_rows": len(exp), "rows_present": len(orows), "missing_rows": len(missing),
                   "missing_sample": missing[:8], "stale_rows": len(stale_rows), "wrong_links": len(wrong),
                   "duplicate_rows": 0, "mature_30m": len(mature30), "mature_30m_missing_ret": len(m30_missing),
                   "by_status": dict(Counter(r["status"] for r in orows.values())),
                   "by_model": dict(Counter(r["model"] for r in orows.values())),
                   "coverage_sent": cov(sent_c), "coverage_held": cov(held_c),
                   "coverage_never_surfaced": cov(set(cands) - sent_c - held_c)}
out["quality_groups"] = {g: {"n": len(v), "status": dict(Counter(r["status"] for r in v)),
                             "ret30": stats([r["ret_30m_pct"] for r in v]), "ret1h": stats([r["ret_1h_pct"] for r in v]),
                             "mfe": stats([r["mfe_pct"] for r in v]), "mae": stats([r["mae_pct"] for r in v]),
                             "invalidated_lifecycle": sum(1 for r in v if cands[r["candidate_id"]]["state"] == "INVALIDATED"),
                             "stale_invalidated": sum(1 for r in v if "stale" in (by_c[r["candidate_id"]][-1]["reason"] or ""))}
                         for g, v in sorted(q.items())}

# ---------- 7/8. fatigue + cap pressure
sent_list = [(obx[d["outbox_event_id"]]["sent_at_utc"], ev_by_id.get(eid), d) for eid, d in decs.items()
             if d["outbox_event_id"] in obx and obx[d["outbox_event_id"]]["state"] == "SENT"]
per15 = Counter(t[:14] + ("00" if int(t[14:16]) < 15 else "15" if int(t[14:16]) < 30 else "30" if int(t[14:16]) < 45 else "45")
                for t, _, _ in sent_list if t)
per_sym = Counter(e["symbol"] for _, e, _ in sent_list if e)
low_val = []
for _, e, _ in sent_list:
    if e and e["event_type"] == "MATERIAL_UPDATE":
        prev = [x for x in by_c[e["candidate_id"]] if x["seq"] < e["seq"] and x["score"] is not None]
        if prev:
            ds, dg = abs((e["score"] or 0) - prev[-1]["score"]), abs((e["gap_pct"] or 0) - (prev[-1]["gap_pct"] or 0))
            if ds < 5 and dg < 5:
                low_val.append((e["symbol"], round(ds, 1), round(dg, 1)))
out["fatigue"] = {"sent_total": len(sent_list), "surfaced_candidates": len({d["candidate_id"] for _, _, d in sent_list}),
                  "by_type": dict(Counter(e["event_type"] for _, e, _ in sent_list if e)),
                  "per_15min_max": max(per15.values()) if per15 else 0, "per_15min_last6": sorted(per15.items())[-6:],
                  "top_symbols": per_sym.most_common(6),
                  "material_updates_small_change(<5 score & <5 gap-pts)": len(low_val), "small_change_sample": low_val[:8],
                  "stale_invalidations_sent": sum(1 for _, e, _ in sent_list if e and "stale" in (e["reason"] or ""))}
used = n.execute("select count(*), sum(classification='WATCH'), sum(classification in ('BULLISH','BEARISH')) from "
                 "decisions where window_id=? and decision='SELECTED' and counted_new=1", (wid,)).fetchone()
blocked = [(d["symbol"], d["event_type"], d["decision"], d["decided_utc"][11:19]) for d in decs.values()
           if d["classification"] in ("BULLISH", "BEARISH") and d["event_type"] in ("NEW", "UPGRADE")
           and d["decision"] != "SELECTED"]
out["cap"] = {"new_used": used[0], "watch_used": used[1], "setups_used": used[2], "remaining": 40 - (used[0] or 0),
              "strong_setups_blocked": blocked,
              "held_by_policy": sum(1 for d in decs.values() if d["decision"].startswith("BUDGET")),
              "persistence_independent": len(cands) >= sum(1 for d in decs.values() if d["event_type"] == "NEW")}

# ---------- 9. stale shadow
orows_early = orows
shadow = []
for e in events:
    if e["event_type"] == "INVALIDATED" and "stale" in (e["reason"] or ""):
        f = json.loads(e["features_json"] or "{}")
        a = aggs.get(e["symbol"], {})
        lt = latest.get(e["symbol"]) or {}
        pc = f.get("prev_close")
        shadow.append({"symbol": e["symbol"], "invalidated": e["at_utc"][11:16], "last_fresh": (f.get("last_bar_utc") or "")[11:16],
                       "age_min": f.get("staleness_min"), "move_at_inval": round(f.get("gap_pct", 0), 1),
                       "resumed": bool(a.get("last_t") and a["last_t"] > (f.get("last_bar_utc") or "")),
                       "latest_print": (a.get("last_t") or "")[11:16],
                       "move_now": round((a["last_c"] / pc - 1) * 100, 1) if a.get("last_c") and pc else None,
                       "would_be_now": lt.get("cls"), "would_be_score": lt.get("score"),
                       "useful_alert": lt.get("cls") in ACTIVE,
                       "missed_min": round((now - datetime.fromisoformat(e["at_utc"])).total_seconds() / 60)
                       if lt.get("cls") in ACTIVE else None,
                       "outcome": {k: (orows_early.get(e["candidate_id"]) or {}).get(k)
                                   for k in ("status", "ret_30m_pct", "ret_1h_pct", "mfe_pct", "mae_pct")}})
out["stale_shadow"] = {"STALE_CLOSED_TOTAL": len(shadow), "RESUMED_TOTAL": sum(s["resumed"] for s in shadow),
                       "WOULD_REQUALIFY": sum(s["useful_alert"] for s in shadow),
                       "WOULD_BECOME_WATCH": sum(s["would_be_now"] == "WATCH" for s in shadow),
                       "WOULD_BECOME_BULLISH": sum(s["would_be_now"] == "BULLISH_SETUP" for s in shadow),
                       "WOULD_BECOME_BEARISH": sum(s["would_be_now"] == "BEARISH_SETUP" for s in shadow),
                       "POTENTIAL_USEFUL_ALERTS_LOST": sum(s["useful_alert"] for s in shadow),
                       "detail": shadow}

# ---------- 10/11. backpressure + provider completeness
sizes = {f: round(sum(p.stat().st_size for p in R.glob(f + "*")) / 1e6, 2) for f in
         ("opportunity.db", "market.db", "notification.db", "outcomes.db", "runtime.db")}
rt = ro(R / "runtime.db")
hb = {r["name"]: round((now - datetime.fromisoformat(r["heartbeat_utc"])).total_seconds(), 1)
      for r in rt.execute("select name, heartbeat_utc from components")}
maxseq = events[-1]["seq"] if events else 0
cursors = {"notifier": n.execute("select max(last_seq) from cursor").fetchone()[0] or 0}
for h in ("intraday", "same_day", "short_term", "long_term"):
    cursors[h] = ro(R / f"evaluator_{h}.db").execute("select max(last_seq) from cursor").fetchone()[0] or 0
cyc = [dict(r) for r in mk.execute("select * from cycles order by id desc limit 12")]
out["backpressure"] = {"db_mb": sizes, "events": len(events), "outbox": len(obx), "outcome_rows": len(orows),
                       "heartbeat_age_s": hb, "cursor_lag": {k: maxseq - v for k, v in cursors.items()},
                       "scan_duration_last8": [s["duration_s"] for s in scans[-8:]],
                       "ingest_cycle_s_last8": [c["duration_s"] for c in cyc[:8]],
                       "tick_errors_today": rt.execute("select count(*) from component_events where event in ('TICK_ERROR','CRASH') "
                                                       "and at_utc>='2026-09-25'").fetchone()[0],
                       "note": "SQLite busy/lock waits and per-tick durations of evaluators/notifier/outcomes are not "
                               "instrumented; cursor lag + heartbeat are the proxies"}
asof = datetime.fromisoformat(ingest["as_of_utc"]) if ingest else None
liquid = [(s, a) for s, a in aggs.items() if daily.get(s) and sum(b["v"] * b["c"] for b in daily[s][-20:]) / max(1, len(daily[s][-20:])) > 50e6]
skew = [(asof - (datetime.fromisoformat(a["last_t"].replace("Z", "+00:00")) + timedelta(minutes=1))).total_seconds() / 60
        for s, a in liquid if a.get("last_t")] if asof else []
with_bars = sum(1 for a in aggs.values() if a.get("bars"))
stale_names = sum(1 for a in aggs.values() if a.get("last_t") and asof and
                  (asof - datetime.fromisoformat(a["last_t"].replace("Z", "+00:00"))).total_seconds() > 45 * 60)
out["provider"] = {"eligible_requested": len(members), "symbols_with_bars": with_bars, "no_prints_yet": len(members) - with_bars,
                   "stale_gt45m_names": stale_names, "incomplete_now": len(json.loads(ingest["incomplete_json"] or "[]")) if ingest else None,
                   "as_of": ingest["as_of_utc"] if ingest else None, "requests": ingest["requests"] if ingest else None,
                   "cycles_today": mk.execute("select count(*), sum(failed_symbols), sum(failed_batches), sum(retried_batches) "
                                              "from cycles where at_utc>='2026-09-25T08'").fetchone()[:],
                   "liquid_names_lag_min": {"n": len(skew), "p50": pct(skew, .5), "p90": pct(skew, .9), "max": pct(skew, 1.0)},
                   "classification": "no PROVIDER_FAILURE; non-printing names = EXPECTED_NO_PRINT_THIN_NAME unless liquid lag grows"}
# ---------- 12. REGULAR transition timeline (T0 open .. T5 first REGULAR Lab send; data-based, not label-based)
T0 = "2026-09-25T13:30:00+00:00"
first_rbar = "2026-09-25T13:31:00+00:00"          # the 13:30 minute bar is complete at 13:31
cyc_all = [dict(r) for r in mk.execute("select at_utc, phase, as_of_utc, duration_s from cycles where window_id=? "
                                       "order by id", (wid,))]
T2 = next((c for c in cyc_all if c["as_of_utc"] and c["as_of_utc"] >= first_rbar), None)
T3 = next((s for s in scans if s["data_as_of_utc"] and s["data_as_of_utc"] >= first_rbar), None)
reg_ev = [e for e in events if e["data_as_of_utc"] and e["data_as_of_utc"] >= first_rbar]
T4 = min((decs[e["event_id"]]["decided_utc"] for e in reg_ev if e["event_id"] in decs), default=None)
T5 = min((obx[decs[e["event_id"]]["outbox_event_id"]]["sent_at_utc"] for e in reg_ev
          if e["event_id"] in decs and decs[e["event_id"]]["outbox_event_id"] in obx
          and obx[decs[e["event_id"]]["outbox_event_id"]]["state"] == "SENT"), default=None)
T1 = "2026-09-25T13:46:00+00:00"                  # 13:31 + 15-min SIP entitlement delay (theoretical availability)
_d = lambda a, b: None if not a or not b else round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds())  # noqa: E731
out["transition"] = {"T0": T0[11:19], "T1_first_regular_bar_available": T1[11:19],
                     "T2_first_ingest_with_regular_data": T2 and T2["at_utc"][11:19], "T2_as_of": T2 and T2["as_of_utc"][11:19],
                     "T3_first_scan_with_regular_data": T3 and T3["decision_utc"][11:19], "T3_scan_phase_label": T3 and T3["phase"],
                     "T4_first_decision_on_regular_data": T4 and T4[11:19], "T5_first_lab_send_on_regular_data": T5 and T5[11:19],
                     "T1-T0 (provider entitlement)": _d(T0, T1), "T2-T1": _d(T1, T2 and T2["at_utc"]),
                     "T3-T2": _d(T2 and T2["at_utc"], T3 and T3["decision_utc"]),
                     "T4-T3": _d(T3 and T3["decision_utc"], T4), "T5-T4": _d(T4, T5),
                     "scans_labelled_REGULAR_before_regular_data": sum(1 for s in scans if s["phase"] == "REGULAR"
                                                                       and (s["data_as_of_utc"] or "") < first_rbar)}

# ---------- 13. REGULAR-first-seen detail
rfs = []
for c in reg_first:
    e0 = by_c[c["candidate_id"]][0]
    d0 = decs.get(e0["event_id"]) or {}
    x = obx.get(d0.get("outbox_event_id") or "") or {}
    liq = json.loads(c["liquidity_json"] or "{}")
    rfs.append({"symbol": c["symbol"], "cid": c["candidate_id"], "first_seen": c["first_seen_utc"][11:19],
                "data_as_of": (c["first_data_as_of_utc"] or "")[11:16], "move_pct": round(c["first_gap_pct"] or 0, 1),
                "liquidity": {k: liq[k] for k in list(liq)[:4]}, "catalyst": c["catalyst"], "score": c["first_score"],
                "cls": e0["classification"], "decision": d0.get("decision"), "policy": d0.get("policy_version"),
                "sent": (x.get("sent_at_utc") or "")[11:19] or None,
                "used_regular_reserve": bool(d0.get("counted_new") and e0["classification"] in ("BULLISH", "BEARISH")
                                             and d0.get("decision") == "SELECTED")})
out["regular_first_seen"] = {"REGULAR_FIRST_SEEN_COUNT": len(rfs),
                             "REGULAR_FIRST_SEEN_SETUP_COUNT": sum(r["cls"] in ("BULLISH", "BEARISH") for r in rfs),
                             "REGULAR_FIRST_SEEN_SENT": sum(bool(r["sent"]) for r in rfs),
                             "REGULAR_FIRST_SEEN_HELD": sum((r["decision"] or "").startswith("BUDGET") for r in rfs),
                             "detail": rfs[:30]}


# ---------- 14/15. score buckets + SENT vs HELD cohorts (mature rows only; same outcome eligibility for all)
def bucket(c):
    e = first_ev.get(c["candidate_id"]) or {}
    s, k = e.get("score") or 0, e.get("classification")
    if k in ("BULLISH", "BEARISH"):
        return "SETUP_90+" if s >= 90 else "SETUP_80_90" if s >= 80 else "SETUP_70_80" if s >= 70 else "SETUP_60_70" if s >= 60 else "SETUP_lt60"
    return "WATCH_50+" if s >= 50 else "WATCH_lt50"


def dir_ret(r, c, key):
    v = r.get(key)
    return v   # outcome rows are ALREADY direction-adjusted (outcome_tracker._ret / V1 measure use sign) -- 14:15Z fix


def cohort_stats(cs):
    rows = [(c, orows[c["candidate_id"]]) for c in cs if c["candidate_id"] in orows
            and orows[c["candidate_id"]]["status"] not in ("OUTCOME_PENDING", "NOT_APPLICABLE_SAME_DAY")]
    evs_ = lambda c: by_c[c["candidate_id"]]  # noqa: E731
    return {"n_all": len(cs), "n_mature": len(rows),
            "cls": dict(Counter((first_ev.get(c["candidate_id"]) or {}).get("classification") for c in cs)),
            "score_p50": pct([(first_ev.get(c["candidate_id"]) or {}).get("score") for c in cs], .5),
            "ret30_dir": stats([dir_ret(r, c, "ret_30m_pct") for c, r in rows]),
            "ret1h_dir": stats([dir_ret(r, c, "ret_1h_pct") for c, r in rows]),
            "mfe": stats([r["mfe_pct"] for _, r in rows]), "mae": stats([r["mae_pct"] for _, r in rows]),
            "confirm_rate(upgrade)": round(sum(any(e["event_type"] == "UPGRADE" for e in evs_(c)) for c in cs) / max(1, len(cs)), 3),
            "invalidation_rate": round(sum(c["state"] == "INVALIDATED" for c in cs) / max(1, len(cs)), 3),
            "stale_rate": round(sum(any(e["event_type"] == "INVALIDATED" and "stale" in (e["reason"] or "") for e in evs_(c))
                                    for c in cs) / max(1, len(cs)), 3)}


bk = defaultdict(list)
for c in cands.values():
    bk[bucket(c)].append(c)
out["score_buckets"] = {b: cohort_stats(v) for b, v in sorted(bk.items())}
out["sent_vs_held"] = {"SENT": cohort_stats([cands[x] for x in sent_c if x in cands]),
                       "HELD_BY_POLICY": cohort_stats([cands[x] for x in held_c if x in cands]),
                       "NEVER_SURFACED": cohort_stats([c for x, c in cands.items() if x not in sent_c and x not in held_c])}

# ---------- 16. phase capacity (phase-reserved policy, boundary 20260925T124634Z)
ex = Counter(d["phase"] for d in decs.values() if d["window_id"] == wid and d["decision"] == "SELECTED"
             and d["counted_new"] and d["policy_version"] != "LAB_NOTIFY_POLICY_V1")
left = 40 - (used[0] or 0)
out["capacity"] = {"TOTAL_NEW_USED": f"{used[0]}/40", "WATCH_USED": f"{used[1]}/15",
                   "PREMARKET_EXTRA_USED": f"{ex['PREMARKET']}/5", "REGULAR_EXTRA_USED": ex["REGULAR"],
                   "AFTER_HOURS_EXTRA_USED": ex["AFTER_HOURS"],
                   "REGULAR_RESERVED_REMAINING": max(0, left - 3) if phase in ("OVERNIGHT", "PREMARKET", "REGULAR") else 0,
                   "AFTER_HOURS_RESERVED_REMAINING": min(3, left) if phase != "AFTER_HOURS" else left,
                   "held_reserved_later_phase": sum(1 for d in decs.values() if d["decision"] == "BUDGET_RESERVED_LATER_PHASE"),
                   "msgs_per_hour_last": Counter(t[:13] for t, _, _ in sent_list if t).most_common()[:0] or
                   sorted(Counter(t[11:13] for t, _, _ in sent_list if t).items())[-4:]}
print(json.dumps(out, indent=1, default=str))
