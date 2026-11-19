"""EOD evidence collector (read-only, mode=ro everywhere). usage: python eod_evidence.py > eod_evidence.json"""
from __future__ import annotations

import json
import sqlite3
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
R = REPO / "results" / "opportunity"
EV = REPO / "results" / "continuous_fullday_2026-09-25"
W = "2026-09-25"


def ro(name):
    c = sqlite3.connect(f"file:{R / name}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


out = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
o, n, p, rt = ro("opportunity.db"), ro("notification.db"), ro("promotion.db"), ro("runtime.db")

# ---- deployment boundaries
out["deployments"] = [dict(r) for r in rt.execute(
    "SELECT deployment_id, at_utc, component, classification, reason, decided_by, restart_only, commit_sha "
    "FROM deployment_events WHERE at_utc >= ? ORDER BY at_utc", (W,))]
out["components"] = [dict(r) for r in rt.execute(
    "SELECT name, pid, state, started_utc, heartbeat_utc, version, commit_sha, restarts FROM components")]

# ---- scans + skipped slots
scans = [dict(r) for r in o.execute("SELECT decision_utc, data_as_of_utc, phase, state, duration_s, funnel_json "
                                    "FROM scans WHERE window_id=? ORDER BY decision_utc", (W,))]
by_phase = {}
for s in scans:
    by_phase.setdefault(s["phase"], []).append(s["duration_s"] or 0)
out["scans"] = {"count": len(scans),
                "by_phase": {k: {"n": len(v), "p50": round(statistics.median(v), 1), "p90": round(pct(v, .9), 1),
                                 "max": round(max(v), 2), "ge_240": sum(x >= 240 for x in v),
                                 "ge_280": sum(x >= 280 for x in v), "ge_300": sum(x >= 300 for x in v)}
                             for k, v in by_phase.items()},
                "states": Counter(s["state"] for s in scans),
                "provider_incomplete_max": max((json.loads(s["funnel_json"] or "{}").get("PROVIDER_INCOMPLETE") or 0)
                                               for s in scans)}
# 5-min slot grid over data-bearing phases (08:30Z first data-bearing scan .. last scan)
starts = {ts(s["decision_utc"]).replace(second=0, microsecond=0) for s in scans}
skips = []
data_scans = [s for s in scans if s["phase"] in ("REGULAR", "AFTER_HOURS")]  # 300s cadence phases
if data_scans:
    t = ts(data_scans[0]["decision_utc"]).replace(second=0, microsecond=0)
    t = t.replace(minute=t.minute - t.minute % 5) + timedelta(minutes=5)
    end = ts(scans[-1]["decision_utc"])
    while t <= end:
        if t not in starts:
            prev = max((s for s in scans if ts(s["decision_utc"]) < t), key=lambda s: s["decision_utc"])
            pe = ts(prev["decision_utc"]) + timedelta(seconds=prev["duration_s"] or 0)
            nxt = min((s for s in scans if ts(s["decision_utc"]) > t), key=lambda s: s["decision_utc"], default=None)
            skips.append({"slot": t.strftime("%H:%M"), "phase": prev["phase"], "prev_start": prev["decision_utc"][11:19],
                          "prev_end": pe.strftime("%H:%M:%S"), "prev_duration_s": prev["duration_s"],
                          "next_scan": nxt["decision_utc"][11:19] if nxt else None,
                          "cause": "PREV_SCAN_OVERRAN" if pe > t else "OTHER"})
        t += timedelta(minutes=5)
out["skipped_slots"] = skips

# PREMARKET cadence is 900s (08:15/08:30/...), so only the 300s-cadence phases are gridded.

# ---- Lab notifier
out["lab_decisions"] = Counter(f"{r['decision']}|{r['reason'] if r['decision'] != 'SELECTED' else ''}"
                               for r in n.execute("SELECT decision, reason FROM decisions WHERE window_id=?", (W,)))
out["lab_decisions_by_phase"] = Counter(f"{r['phase']}|{r['decision']}" for r in n.execute(
    "SELECT phase, decision FROM decisions WHERE window_id=?", (W,)))
lab = ro("opportunity_research_notifications.db")
out["lab_outbox"] = {"by_dest_state": Counter(f"{r['destination']}|{r['state']}" for r in lab.execute(
    "SELECT destination, state FROM ops_notification_outbox WHERE created_at_utc >= ?", (W,))),
    "last_sent": lab.execute("SELECT MAX(sent_at_utc) FROM ops_notification_outbox WHERE state='SENT'").fetchone()[0]}
lb = n.execute("SELECT budget_json, decided_utc FROM decisions WHERE window_id=? ORDER BY seq DESC LIMIT 1", (W,)).fetchone()
out["lab_last_budget"] = dict(lb) if lb else None
# AH-reserve forensics: SELECTED decisions processed in AFTER_HOURS, with their causal data time
ah_sel = []
for r in n.execute("SELECT d.symbol, d.event_id, d.decided_utc, d.classification, d.event_type, d.reason FROM decisions d "
                   "WHERE d.window_id=? AND d.phase='AFTER_HOURS' AND d.decision='SELECTED' ORDER BY d.seq", (W,)):
    e = o.execute("SELECT data_as_of_utc, score, gap_pct, at_utc FROM candidate_events WHERE event_id=?",
                  (r["event_id"],)).fetchone()
    ah_sel.append({**dict(r), "data_as_of": e["data_as_of_utc"] if e else None, "score": e["score"] if e else None,
                   "gap_pct": e["gap_pct"] if e else None})
out["ah_selected"] = ah_sel
held_true_ah = []
for r in n.execute("SELECT d.symbol, d.event_id, d.decided_utc, d.classification, d.event_type, d.decision, d.reason "
                   "FROM decisions d WHERE d.window_id=? AND d.phase='AFTER_HOURS' AND d.decision!='SELECTED' "
                   "AND d.classification IN ('BULLISH','BEARISH') ORDER BY d.seq", (W,)):
    e = o.execute("SELECT data_as_of_utc, score, gap_pct FROM candidate_events WHERE event_id=?", (r["event_id"],)).fetchone()
    if e and e["data_as_of_utc"] and e["data_as_of_utc"] >= "2026-09-25T20:01":
        held_true_ah.append({**dict(r), "data_as_of": e["data_as_of_utc"], "score": e["score"], "gap_pct": e["gap_pct"]})
out["ah_true_setups_held"] = {"count": len(held_true_ah), "reasons": Counter(x["reason"] for x in held_true_ah),
                              "first5": held_true_ah[:5]}

# ---- AH timeline (first true AH candidate / setup from the authoritative store)
fc = o.execute("SELECT symbol, candidate_id, at_utc, data_as_of_utc, classification, score, gap_pct FROM candidate_events "
               "WHERE window_id=? AND data_as_of_utc >= '2026-09-25T20:01' ORDER BY seq LIMIT 1", (W,)).fetchone()
fs = o.execute("SELECT symbol, candidate_id, event_id, at_utc, data_as_of_utc, classification, score, gap_pct, event_type "
               "FROM candidate_events WHERE window_id=? AND data_as_of_utc >= '2026-09-25T20:01' AND classification IN "
               "('BULLISH','BEARISH') ORDER BY seq LIMIT 1", (W,)).fetchone()
out["ah_first_candidate_event"] = dict(fc) if fc else None
out["ah_first_setup_event"] = dict(fs) if fs else None
if fs:
    d = n.execute("SELECT decision, reason, budget_json, decided_utc FROM decisions WHERE event_id=?", (fs["event_id"],)).fetchone()
    out["ah_first_setup_decision"] = dict(d) if d else None
fa = o.execute("SELECT decision_utc, data_as_of_utc, duration_s FROM scans WHERE window_id=? AND data_as_of_utc >= "
               "'2026-09-25T20:02' ORDER BY decision_utc LIMIT 1", (W,)).fetchone()
out["ah_first_data_scan"] = dict(fa) if fa else None
ah_ev = o.execute("SELECT COUNT(*), COUNT(DISTINCT candidate_id), SUM(classification IN ('BULLISH','BEARISH')) FROM "
                  "candidate_events WHERE window_id=? AND data_as_of_utc >= '2026-09-25T20:01'", (W,)).fetchone()
out["ah_true_events"] = {"events": ah_ev[0], "candidates": ah_ev[1], "setup_events": ah_ev[2]}
ah_new_c = o.execute("SELECT COUNT(*) FROM candidates WHERE window_id=? AND first_data_as_of_utc >= '2026-09-25T20:01'",
                     (W,)).fetchone()[0]
out["ah_true_new_candidates"] = ah_new_c
fn = o.execute("SELECT symbol, candidate_id, first_seen_utc, first_data_as_of_utc, classification, first_score, first_gap_pct "
               "FROM candidates WHERE window_id=? AND first_data_as_of_utc >= '2026-09-25T20:01' ORDER BY first_seen_utc, "
               "first_score DESC LIMIT 1", (W,)).fetchone()
out["ah_first_new_candidate"] = dict(fn) if fn else None
out["ah_selected_counted_new"] = [dict(r) for r in n.execute(
    "SELECT symbol, event_type, classification, counted_new, decided_utc FROM decisions WHERE window_id=? AND "
    "phase='AFTER_HOURS' AND decision='SELECTED' ORDER BY seq", (W,))]

# ---- promotion
pr = [dict(r) for r in p.execute("SELECT * FROM promotions WHERE window_id=? ORDER BY decision_utc", (W,))]
sig = [x for x in pr if x["state"] == "PROMOTED_SIGNAL"]
out["promotion"] = {
    "states": Counter(x["state"] for x in pr), "reasons": Counter(f"{x['state']}|{x['reason_code']}" for x in pr),
    "signal_sent_rows": len(sig), "unique_symbols": len({x["symbol"] for x in sig}),
    "first_signal": (sig[0]["symbol"], sig[0]["decision_utc"]) if sig else None,
    "last_signal": (sig[-1]["symbol"], sig[-1]["decision_utc"]) if sig else None,
    "after_2000": sum(1 for x in pr if (x["decision_utc"] or "") >= "2026-09-25T20:00" and x["state"].startswith("PROMOTED")),
    "dup_symbols": [s for s, k in Counter(x["symbol"] for x in sig).items() if k > 1],
    "directions": Counter(x["direction"] for x in sig), "phases": Counter(x["processing_phase"] for x in sig),
    "eval_decisions": Counter(r[0] for r in p.execute("SELECT reason_code FROM evaluations")),
    "evals_after_2000": Counter(r[0] for r in p.execute(
        "SELECT reason_code FROM evaluations WHERE evaluated_utc >= '2026-09-25T20:00'")),
    "meta": {r["k"]: r["v"] for r in p.execute("SELECT k, v FROM meta")}}
ps = ro("promotion_signal_notifications.db")
out["promotion"]["outbox"] = {"by_dest_state": Counter(f"{r['destination']}|{r['event_type']}|{r['state']}" for r in ps.execute(
    "SELECT destination, event_type, state FROM ops_notification_outbox")),
    "attempts_gt1": ps.execute("SELECT COUNT(*) FROM ops_notification_outbox WHERE attempts>1").fetchone()[0],
    "errors": [r[0] for r in ps.execute("SELECT DISTINCT last_error FROM ops_notification_outbox WHERE last_error IS NOT NULL")]}
lat = []
for x in sig:
    r = ps.execute("SELECT sent_at_utc FROM ops_notification_outbox WHERE event_id=?", (x["signal_event_id"],)).fetchone()
    if r and r[0]:
        lat.append((ts(r[0]) - ts(x["event_utc"])).total_seconds())
out["promotion"]["event_to_sent_s"] = {"p50": pct(lat, .5), "p90": pct(lat, .9), "max": max(lat) if lat else None, "n": len(lat)}
po = {r["promotion_id"]: dict(r) for r in p.execute("SELECT * FROM paper_outcomes")}
rows = []
for x in sig:
    oc = po.get(x["promotion_id"], {})
    rows.append({"symbol": x["symbol"], "t": x["decision_utc"][11:19], "score": round(x["score"], 1),
                 "ref": x["reference_price"], **{k: oc.get(k) for k in ("ret_15m_pct", "ret_30m_pct", "ret_1h_pct",
                                                                       "close_ret_pct", "mfe_pct", "mae_pct", "status",
                                                                       "lifecycle_end_state")}})
out["promotion"]["signals"] = rows


def agg(key):
    v = [r[key] for r in rows if r[key] is not None]
    return {"n": len(v), "mean": round(statistics.mean(v), 3) if v else None,
            "median": round(statistics.median(v), 3) if v else None, "pos": sum(x > 0 for x in v)}


out["promotion"]["outcome_agg"] = {k: agg(k) for k in ("ret_15m_pct", "ret_30m_pct", "ret_1h_pct", "close_ret_pct",
                                                        "mfe_pct", "mae_pct")}
out["promotion"]["status"] = Counter(r["status"] for r in rows)
out["promotion"]["lifecycle_end"] = Counter(r["lifecycle_end_state"] for r in rows)

# ---- cross-send checks
v2n = sqlite3.connect(f"file:{REPO / 'v2_release_rc1_notifications.db'}?mode=ro", uri=True)
try:
    out["v2_outbox_today"] = Counter(f"{r[0]}|{r[1]}|{r[2]}" for r in v2n.execute(
        "SELECT destination, event_type, state FROM ops_notification_outbox WHERE created_at_utc >= ?", (W,)))
except sqlite3.Error as exc:
    out["v2_outbox_today"] = f"ERR {exc}"
out["cross_send"] = {
    "lab_outbox_non_research": lab.execute("SELECT COUNT(*) FROM ops_notification_outbox WHERE destination!='RESEARCH'").fetchone()[0],
    "promotion_outbox_non_trade_event": ps.execute("SELECT COUNT(*) FROM ops_notification_outbox WHERE destination!='TRADE_EVENT'").fetchone()[0],
    "buy_sell_in_lab": lab.execute("SELECT COUNT(*) FROM ops_notification_outbox WHERE payload_text LIKE '%BUY%' "
                                   "OR payload_text LIKE '%SELL%'").fetchone()[0],
    "buy_sell_in_promotion": ps.execute("SELECT COUNT(*) FROM ops_notification_outbox WHERE event_type LIKE '%BUY%' "
                                        "OR event_type LIKE '%SELL%'").fetchone()[0]}

# ---- cursors
seq = o.execute("SELECT MAX(seq) FROM candidate_events").fetchone()[0]
cur = {"events_max_seq": seq, "notifier": n.execute("SELECT last_seq FROM cursor").fetchone()[0],
       "promotion": p.execute("SELECT last_seq FROM cursor").fetchone()[0]}
for h in ("intraday", "same_day", "short_term", "long_term"):
    cur[h] = ro(f"evaluator_{h}.db").execute("SELECT last_seq FROM cursor").fetchone()[0]
out["cursors"] = cur

# ---- outcomes (candidates)
oc = ro("outcomes.db")
out["outcomes_status"] = Counter(r[0] for r in oc.execute("SELECT status FROM outcomes WHERE window_id=?", (W,)))
m = ro("market.db")
ing = m.execute("SELECT as_of_utc, cycle_utc, phase, symbols, incomplete_json FROM ingestion_state WHERE window_id=?", (W,)).fetchone()
out["ingestion"] = dict(ing) if ing else None
out["ingestion_cycles"] = dict(m.execute("SELECT COUNT(*) n, SUM(failed_batches) fb, SUM(retried_batches) rb, "
                                         "MAX(duration_s) mx FROM cycles WHERE window_id=?", (W,)).fetchone())
out["totals"] = {"candidates": o.execute("SELECT COUNT(*) FROM candidates WHERE window_id=?", (W,)).fetchone()[0],
                 "events": o.execute("SELECT COUNT(*) FROM candidate_events WHERE window_id=?", (W,)).fetchone()[0],
                 "events_by_type": Counter(r[0] for r in o.execute("SELECT event_type FROM candidate_events WHERE window_id=?", (W,))),
                 "candidates_by_first_phase": Counter(r[0] for r in o.execute(
                     "SELECT first_seen_phase FROM candidates WHERE window_id=?", (W,))),
                 "setup_candidates": o.execute("SELECT COUNT(DISTINCT candidate_id) FROM candidate_events WHERE window_id=? "
                                               "AND classification IN ('BULLISH','BEARISH')", (W,)).fetchone()[0]}
# skip-impact files
led = {}
for f in sorted(EV.glob("skip_*.json")):
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        continue
    led[f.stem] = {k: v for k, v in d.items() if k not in ("detail",)}
out["skip_impact_files"] = led
print(json.dumps(out, indent=1, default=str))
