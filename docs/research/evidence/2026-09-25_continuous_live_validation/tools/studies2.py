"""Consolidated evidence studies v2 (READ-ONLY; corrected: outcome rows are ALREADY direction-adjusted, never flip).

Cohorts A-H, +30m/+1h (only mature values), phase-specific score quality, CAUSAL priority x rate simulation,
FCFS forensics, setup-burst decomposition, stale/fade/flip shadows (with forward requalification tracking),
MATERIAL_UPDATE fatigue, latency decomposition. No production effect.
Caveat: outcomes are measured from each candidate's causal first-sighting reference, not from a simulated send time.
"""
from __future__ import annotations

import json
import math
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
E = REPO / "results" / "continuous_fullday_2026-09-25"
WID = "2026-09-25"
OPEN = datetime(2026, 9, 25, 13, 30, tzinfo=timezone.utc)
SETUP = ("BULLISH", "BEARISH")
ACTIVE = ("WATCH", "BULLISH_SETUP", "BEARISH_SETUP")
P_PHASE = "LAB_NOTIFY_POLICY_V1_PHASE_RESERVED_20260925"
P_EXT = "LAB_NOTIFY_POLICY_V1_REGULAR_EXT_20260925"
EXT_BOUNDARY = "2026-09-25T14:09:49"
OLD_CAP = ("NCPL", "BB", "PMAX", "CIFR")
STATE = E / "studies2_state.json"
TERMINAL = ("CONFIRMED", "FAILED_CONFIRMATION", "INVALIDATED")


def ro(n):
    c = sqlite3.connect(f"file:{R / n}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def s_(xs):
    xs = [x for x in xs if x is not None]
    return {"n": len(xs), "med": round(st.median(xs), 2), "mean": round(st.mean(xs), 2)} if xs else {"n": 0}


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    return None if not xs else round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + .5))], 1)


now = datetime.now(timezone.utc)
o, n, ob, oc, mk = ro("opportunity.db"), ro("notification.db"), ro("opportunity_research_notifications.db"), \
    ro("outcomes.db"), ro("market.db")
cands = {r["candidate_id"]: dict(r) for r in o.execute("select * from candidates where window_id=?", (WID,))}
events = [dict(r) for r in o.execute("select * from candidate_events where window_id=? order by seq", (WID,))]
evid = {e["event_id"]: e for e in events}
by_c = defaultdict(list)
for e in events:
    by_c[e["candidate_id"]].append(e)
decs = {r["event_id"]: dict(r) for r in n.execute("select * from decisions where window_id=?", (WID,))}
obx = {r["event_id"]: dict(r) for r in ob.execute("select * from ops_notification_outbox")}
orows = {r["candidate_id"]: dict(r) for r in oc.execute("select * from outcomes where window_id=?", (WID,))}
latest = {r["symbol"]: dict(r) for r in o.execute("select * from symbol_latest where window_id=?", (WID,))}
state = {}
try:
    state = json.load(open(STATE))
except (OSError, ValueError):
    state = {}
out = {"time_utc": now.isoformat()[:19], "note": "returns are production outcome rows (already direction-adjusted)"}


def outcome_block(cids):
    """Only mature values are aggregated; immature rows are counted, never mixed in."""
    rows = [orows.get(c) for c in cids]
    have = [r for r in rows if r]
    stc = Counter(r["status"] for r in have)
    tot = len(cids) or 1
    return {"n": len(cids), "rows": len(have),
            "ret30": s_([r["ret_30m_pct"] for r in have]), "ret1h": s_([r["ret_1h_pct"] for r in have]),
            "mfe": s_([r["mfe_pct"] for r in have if r["status"] != "OUTCOME_PENDING"]),
            "mae": s_([r["mae_pct"] for r in have if r["status"] != "OUTCOME_PENDING"]),
            "confirmed%": round(100 * stc["CONFIRMED"] / tot), "failed%": round(100 * stc["FAILED_CONFIRMATION"] / tot),
            "invalidated%": round(100 * stc["INVALIDATED"] / tot), "pending%": round(100 * stc["OUTCOME_PENDING"] / tot),
            "no_row_or_na%": round(100 * (len(cids) - len(have) + stc["NOT_APPLICABLE_SAME_DAY"]) / tot)}


def ev_scores(eids):
    sc = [evid[x]["score"] for x in eids if x in evid and evid[x]["score"] is not None]
    cl = Counter(evid[x]["classification"] for x in eids if x in evid)
    return {"score_p50": pct(sc, .5), "score_p90": pct(sc, .9), "BULLISH": cl["BULLISH"], "BEARISH": cl["BEARISH"]}


# ---------- cohorts (immutable membership = decision rows as recorded)
reg_setup = [d for d in decs.values() if d["phase"] == "REGULAR" and d["classification"] in SETUP
             and d["event_type"] in ("NEW", "UPGRADE") and (d["counted_new"] or d["decision"].startswith("BUDGET"))]
A = [d for d in reg_setup if d["policy_version"] == P_PHASE and d["decision"] == "SELECTED"]
B_ids = [h["event_id"] for h in json.load(open(E / "pre_override_held_regular.json"))]
B = [decs[x] for x in B_ids if x in decs]
C = [d for d in reg_setup if d["policy_version"] == P_EXT and d["decision"] == "SELECTED"]
D = [d for d in reg_setup if d["policy_version"] == P_EXT and d["decision"].startswith("BUDGET")]
Eo = [d for d in decs.values() if d["symbol"] in OLD_CAP and d["event_type"] == "UPGRADE" and d["decision"].startswith("BUDGET")]
inv = [e for e in events if e["event_type"] == "INVALIDATED"]
F_ = sorted({e["candidate_id"] for e in inv if "stale" in (e["reason"] or "")})
G_ = sorted({e["candidate_id"] for e in inv if "faded" in (e["reason"] or "")})
H_ = sorted({e["candidate_id"] for e in inv if "flipped" in (e["reason"] or "")})
cid = lambda ds: sorted({d["candidate_id"] for d in ds})  # noqa: E731
coh = {"A_INITIAL_REGULAR_SENT": A, "B_PRE_EXTENSION_REGULAR_HELD": B, "C_POST_EXTENSION_REGULAR_SENT": C,
       "D_POST_EXTENSION_REGULAR_HELD": D, "E_OLD_PREMARKET_CAP_HELD": Eo}
out["cohorts"] = {k: {**ev_scores([d["event_id"] for d in v]), **outcome_block(cid(v))} for k, v in coh.items()}
out["cohorts"].update({"F_STALE_CLOSED(original identity)": outcome_block(F_),
                       "G_FADE_CLOSED(original identity)": outcome_block(G_),
                       "H_DIRECTION_FLIP(original identity)": outcome_block(H_)})
sent_all = sorted({d["candidate_id"] for d in decs.values() if d["decision"] == "SELECTED"})
held_all = sorted({d["candidate_id"] for d in decs.values() if d["decision"].startswith("BUDGET")} - set(sent_all))
out["sent_vs_held_all"] = {"ALL_SENT": outcome_block(sent_all), "ALL_HELD": outcome_block(held_all)}


# comparable maturity: only candidates with a +1h value (and separately +30m)
def fair(a, b, key):
    ca = [c for c in cid(a) if (orows.get(c) or {}).get(key) is not None]
    cb = [c for c in cid(b) if (orows.get(c) or {}).get(key) is not None]
    return {"a": s_([orows[c][key] for c in ca]), "b": s_([orows[c][key] for c in cb])}


out["fair"] = {f"{x}_vs_{y}": {"ret30": fair(coh[x], coh[y], "ret_30m_pct"), "ret1h": fair(coh[x], coh[y], "ret_1h_pct")}
               for x, y in (("A_INITIAL_REGULAR_SENT", "B_PRE_EXTENSION_REGULAR_HELD"),
                            ("A_INITIAL_REGULAR_SENT", "C_POST_EXTENSION_REGULAR_SENT"),
                            ("C_POST_EXTENSION_REGULAR_SENT", "D_POST_EXTENSION_REGULAR_HELD"))}

# ---------- phase-specific score quality: setup-surfacing event's own phase & score
def band(s):
    return "90+" if s >= 90 else "80_90" if s >= 80 else "70_80" if s >= 70 else "60_70" if s >= 60 else "lt60"


pq = defaultdict(set)
seen = set()
for e in events:
    if e["event_type"] not in ("NEW", "UPGRADE") or e["candidate_id"] in seen and e["classification"] not in SETUP:
        continue
    if e["classification"] in SETUP:
        dph = "REGULAR" if (e["data_as_of_utc"] and ts(e["data_as_of_utc"]) > OPEN) else "PREMARKET"
        pq[f"{dph}_SETUP_{band(e['score'] or 0)}"].add(e["candidate_id"])
        seen.add(e["candidate_id"])
    elif e["event_type"] == "NEW" and e["classification"] == "WATCH":
        pq["WATCH_50+" if (e["score"] or 0) >= 50 else "WATCH_lt50"].add(e["candidate_id"])
for k in list(pq):
    if k.startswith("WATCH"):
        pq[k] -= seen                                         # watch that later became a setup counts as setup
out["phase_score_quality"] = {k: {**outcome_block(sorted(v)),
                                  "stale%": round(100 * sum(any("stale" in (x["reason"] or "") for x in by_c[c]) for c in v) / max(1, len(v)))}
                              for k, v in sorted(pq.items())}

# ---------- causal priority x rate simulation (REGULAR new-setup surfacings only; WATCH excluded)
def feats(eid):
    e = evid[eid]
    f = json.loads(e["features_json"] or "{}")
    cat = (e["catalyst"] or "").lower()
    return {"eid": eid, "cid": e["candidate_id"], "sym": e["symbol"], "t": ts(e["at_utc"]), "score": e["score"] or 0,
            "new": e["event_type"] == "NEW", "dollars": f.get("pm_dollars") or 0, "act": f.get("activity_adv_fraction") or 0,
            "cat": 2 if any(k in cat for k in ("8-k", "earnings", "424b", "offering", "6-k", "s-1", "13d")) else 1 if "filing" in cat else 0}


pool_all = sorted((feats(d["event_id"]) for d in reg_setup), key=lambda x: (x["t"], -x["score"]))
closed_at = {}
for e in events:
    if e["event_type"] in ("INVALIDATED", "EXPIRED") and e["candidate_id"] not in closed_at:
        closed_at[e["candidate_id"]] = ts(e["at_utc"])
POL = {"FCFS": lambda p, t: (-(t - p["t"]).total_seconds(), p["score"]),          # oldest first, then production order
       "SCORE": lambda p, t: p["score"],
       "CLASS_SCORE": lambda p, t: (1 if p["new"] else 0, p["score"]),
       "COMPOSITE": lambda p, t: p["score"] + 3 * math.log10(p["dollars"] / 1e6 + 1) + 10 * min(p["act"], 1) + 4 * p["cat"]
       - 0.5 * (t - p["t"]).total_seconds() / 60}
RATES = {"3_per_5m": (3, 5), "5_per_5m": (5, 5), "10_per_15m": (10, 15)}
slots = sorted({p["t"] for p in pool_all})
sim = {}
for pn, key in POL.items():
    for rn, (k, win) in RATES.items():
        sent, sent_t, queue = [], [], []
        for t in slots:
            queue += [p for p in pool_all if p["t"] == t]
            queue = [p for p in queue if (t - p["t"]) <= timedelta(minutes=30)
                     and not (closed_at.get(p["cid"]) and closed_at[p["cid"]] <= t)]   # causal expiry/invalidation
            budget = k - sum(1 for x in sent_t if t - x < timedelta(minutes=win))
            for p in sorted(queue, key=lambda p: key(p, t), reverse=True)[:max(0, budget)]:
                sent.append(p)
                sent_t.append(t)
                queue.remove(p)
        chosen = {p["cid"] for p in sent}
        held = [p for p in pool_all if p["cid"] not in chosen]
        sim[f"{pn}@{rn}"] = {"selected": len(sent), "held": len(held),
                             "score_p50": pct([p["score"] for p in sent], .5), "score_p90": pct([p["score"] for p in sent], .9),
                             "ret30": s_([(orows.get(p["cid"]) or {}).get("ret_30m_pct") for p in sent]),
                             "ret1h": s_([(orows.get(p["cid"]) or {}).get("ret_1h_pct") for p in sent]),
                             "mfe": s_([(orows.get(p["cid"]) or {}).get("mfe_pct") for p in sent]),
                             "mae": s_([(orows.get(p["cid"]) or {}).get("mae_pct") for p in sent]),
                             "confirmed%": round(100 * sum((orows.get(p["cid"]) or {}).get("status") == "CONFIRMED" for p in sent) / max(1, len(sent))),
                             "invalidated%": round(100 * sum((orows.get(p["cid"]) or {}).get("status") == "INVALIDATED" for p in sent) / max(1, len(sent))),
                             "high_score_85+_missed": sum(1 for p in held if p["score"] >= 85)}
out["causal_sim"] = {"pool": len(pool_all), "scan_slots": len(slots), "results": sim,
                     "production": {"sent": len(A) + len(C), "held": len(B) + len(D)}}

# ---------- FCFS forensics (production)
prod_sent = [feats(d["event_id"]) | {"at": d["decided_utc"]} for d in A + C]
prod_held = [feats(d["event_id"]) | {"at": d["decided_utc"]} for d in B + D]
pairs = []
for h in prod_held:
    w = [s for s in prod_sent if s["score"] < h["score"] and s["at"] <= h["at"]]
    if w:
        s0 = min(w, key=lambda s: s["score"])
        ro_ = lambda c, k: (orows.get(c) or {}).get(k)  # noqa: E731
        pairs.append({"sent": s0["sym"], "sent_score": round(s0["score"], 1), "sent_at": s0["at"][11:19],
                      "held": h["sym"], "held_score": round(h["score"], 1), "held_at": h["at"][11:19],
                      "gap": round(h["score"] - s0["score"], 1),
                      "dt_min": round((ts(h["at"]) - ts(s0["at"])).total_seconds() / 60, 1),
                      "sent_30/1h/mfe/mae": [ro_(s0["cid"], k) for k in ("ret_30m_pct", "ret_1h_pct", "mfe_pct", "mae_pct")],
                      "held_30/1h/mfe/mae": [ro_(h["cid"], k) for k in ("ret_30m_pct", "ret_1h_pct", "mfe_pct", "mae_pct")]})
out["fcfs"] = {"WEAKER_SENT_BEFORE_STRONGER_HELD_COUNT": len(pairs),
               "top": sorted(pairs, key=lambda x: -x["gap"])[:10]}

# ---------- setup-burst decomposition (WATCH -> SETUP upgrades on REGULAR data)
COMP = ("gap", "activity", "liquidity", "catalyst", "structure", "data_confidence")
drivers, samples = Counter(), []
ups = [e for e in events if e["event_type"] == "UPGRADE" and e["classification"] in SETUP
       and e["data_as_of_utc"] and ts(e["data_as_of_utc"]) > OPEN]
for e in ups:
    prev = [x for x in by_c[e["candidate_id"]] if x["seq"] < e["seq"] and x["score_json"]]
    if not prev:
        continue
    p = prev[-1]
    a, b = json.loads(p["score_json"] or "{}"), json.loads(e["score_json"] or "{}")
    fa, fb = json.loads(p["features_json"] or "{}"), json.loads(e["features_json"] or "{}")
    d = {k: round((b.get(k) or 0) - (a.get(k) or 0), 1) for k in COMP}
    tot = sum(v for v in d.values() if v > 0) or 1
    big = [k for k, v in d.items() if v > 0 and v / tot >= 0.3]
    grp = ("MULTI_FACTOR" if len(big) > 1 else {"activity": "ACTIVITY_DRIVEN", "liquidity": "VOLUME_DRIVEN",
                                                  "gap": "MOVE_DRIVEN", "catalyst": "CATALYST_DRIVEN"}.get(big[0] if big else "", "OTHER"))
    gate = (fa.get("pm_dollars") or 0) < 500_000 <= (fb.get("pm_dollars") or 0)
    drivers[grp] += 1
    drivers["crossed_500k_dollar_gate"] += gate
    drivers["crossed_score_60"] += (p["score"] or 0) < 60 <= (e["score"] or 0)
    samples.append({"sym": e["symbol"], "cls": e["classification"], "score": f"{round(p['score'] or 0)}->{round(e['score'] or 0)}",
                    "delta": d, "dollars": f"{round((fa.get('pm_dollars') or 0) / 1e3)}k->{round((fb.get('pm_dollars') or 0) / 1e3)}k",
                    "act": f"{round(fa.get('activity_adv_fraction') or 0, 3)}->{round(fb.get('activity_adv_fraction') or 0, 3)}",
                    "gap": f"{round(fa.get('gap_pct') or 0, 1)}->{round(fb.get('gap_pct') or 0, 1)}", "driver": grp, "dollar_gate": gate})
out["burst"] = {"BURST_TOTAL_UPGRADES": len(samples), **dict(drivers),
                "mean_component_delta": {k: round(st.mean([s["delta"][k] for s in samples]), 1) for k in COMP} if samples else {},
                "sample": sorted(samples, key=lambda s: -float(s["score"].split("->")[1]))[:8]
                + [s for s in samples if s["cls"] == "BEARISH"][:3]}

# ---------- lifecycle shadows (forward requalification tracking persisted in studies2_state.json)
req = state.setdefault("requal", {})
def shadow(cids, kind):
    rows = []
    for c in cids:
        cd = cands[c]
        lt = latest.get(cd["symbol"]) or {}
        clos = next((x for x in by_c[c] if x["event_type"] == "INVALIDATED"), None)
        same_dir = ("GAP_UP" if (lt.get("gap_pct") or 0) > 0 else "GAP_DOWN") == cd["family"]
        worthy = lt.get("cls") in ACTIVE
        reg_data = lt.get("decision_utc") and ts(lt["decision_utc"]) >= OPEN + timedelta(minutes=20)
        opp = cands.get(f"{WID}:{cd['symbol']}:{'GAP_DOWN' if cd['family'] == 'GAP_UP' else 'GAP_UP'}")
        key = f"{kind}:{c}"
        if worthy and same_dir and cd["state"] not in ACTIVE and key not in req:
            req[key] = {"first_seen_requal_utc": now.isoformat()[:19], "cls": lt.get("cls"), "score": lt.get("score"),
                        "data": "REGULAR" if reg_data else "PREMARKET"}
        r = orows.get(c) or {}
        rows.append({"symbol": cd["symbol"], "identity": c, "closed_at": clos and clos["at_utc"][11:16], "reason": clos and clos["reason"],
                     "now_cls": lt.get("cls"), "now_score": lt.get("score"), "now_dir_same": same_dir,
                     "evidence": "REGULAR" if reg_data else "PREMARKET", "blocked_same_dir_worthy": worthy and same_dir and cd["state"] not in ACTIVE,
                     "opposite_identity": opp and opp["state"], "requal": req.get(key),
                     "orig_outcome": [r.get(k) for k in ("status", "ret_30m_pct", "ret_1h_pct", "mfe_pct", "mae_pct")]})
    blk = [r for r in rows if r["blocked_same_dir_worthy"]]
    return {"total": len(rows), "resumed_now_regular_evidence": sum(r["evidence"] == "REGULAR" for r in rows),
            "would_requalify": len(blk), "watch": sum(r["now_cls"] == "WATCH" for r in blk),
            "bullish": sum(r["now_cls"] == "BULLISH_SETUP" for r in blk), "bearish": sum(r["now_cls"] == "BEARISH_SETUP" for r in blk),
            "no_longer_qualifies": sum(1 for r in rows if not r["blocked_same_dir_worthy"]),
            "opposite_identity_created": sum(bool(r["opposite_identity"]) for r in rows),
            "blocked_detail": blk[:15]}


out["stale_shadow"] = shadow(F_, "STALE")
out["fade_shadow"] = shadow(G_, "FADE")
out["flip_shadow"] = shadow(H_, "FLIP")

# ---------- MATERIAL_UPDATE fatigue (all sent today)
sent_ev = [(evid.get(d["event_id"]), obx.get(d["outbox_event_id"] or "")) for d in decs.values()]
sent_ev = [(e, x) for e, x in sent_ev if e and x and x["state"] == "SENT"]
mu = Counter()
for e, _ in sent_ev:
    if e["event_type"] != "MATERIAL_UPDATE":
        continue
    prev = [p for p in by_c[e["candidate_id"]] if p["seq"] < e["seq"]]
    p = prev[-1] if prev else {}
    if e["classification"] != p.get("classification") or (e["catalyst"] or "") != (p.get("catalyst") or ""):
        mu["HIGH"] += 1
    elif abs((e["score"] or 0) - (p.get("score") or 0)) < 5 and abs((e["gap_pct"] or 0) - (p.get("gap_pct") or 0)) < 5:
        mu["LOW"] += 1
    else:
        mu["MEDIUM"] += 1
tot_mu = sum(mu.values())
hours = Counter(x["sent_at_utc"][11:13] for _, x in sent_ev)
q15 = Counter(x["sent_at_utc"][11:14] + str(int(x["sent_at_utc"][14:16]) // 15 * 15).zfill(2) for _, x in sent_ev)
out["fatigue"] = {"sent_total": len(sent_ev), "by_type": dict(Counter(e["event_type"] for e, _ in sent_ev)),
                  "MU_total": tot_mu, **{f"MU_{k}": v for k, v in mu.items()},
                  "MU_low%": round(100 * mu["LOW"] / max(1, tot_mu)), "POTENTIAL_MESSAGES_SAVED(low-only)": mu["LOW"],
                  "per_candidate_top10": Counter(e["symbol"] for e, _ in sent_ev).most_common(10),
                  "per_hour": sorted(hours.items()), "per_15m_max": max(q15.values(), default=0),
                  "per_15m_last4": sorted(q15.items())[-4:]}

# ---------- latency decomposition (REGULAR setup surfacings that were SENT)
cyc = [(ts(r["at_utc"]), ts(r["as_of_utc"])) for r in mk.execute(
    "select at_utc, as_of_utc from cycles where window_id=? and as_of_utc is not null order by id", (WID,))]
scan_dur = {r["decision_utc"][:19]: r["duration_s"] for r in o.execute("select decision_utc, duration_s from scans where window_id=?", (WID,))}
parts = defaultdict(list)
for d in A + C:
    e = evid[d["event_id"]]
    x = obx.get(d["outbox_event_id"] or "")
    if not x or not x.get("sent_at_utc"):
        continue
    asof, slot = ts(e["data_as_of_utc"]), ts(e["at_utc"])
    visible = asof + timedelta(minutes=15)
    ing = next((t for t, a in cyc if a >= asof), None)
    dur = scan_dur.get(e["at_utc"][:19]) or 0
    if not ing:
        continue
    parts["provider_s"].append(900)
    parts["ingest_s"].append((ing - visible).total_seconds())
    parts["slot_wait_s"].append((slot - ing).total_seconds())
    parts["scan_compute_s"].append(dur)
    parts["notifier_decide_s"].append((ts(d["decided_utc"]) - slot).total_seconds() - dur)
    parts["send_s"].append((ts(x["sent_at_utc"]) - ts(d["decided_utc"])).total_seconds())
    for k in (2, 1):
        g = datetime.fromtimestamp(math.ceil(ing.timestamp() / (60 * k)) * 60 * k, tz=timezone.utc)
        parts[f"saved_{k}min_s"].append(max(0.0, (slot - g).total_seconds()))
out["latency"] = {k: {"n": len(v), "p50": pct(v, .5), "p90": pct(v, .9), "max": round(max(v), 1) if v else None}
                  for k, v in parts.items()}
out["latency"]["saved_buckets_1min"] = dict(Counter("0-60" if v <= 60 else "60-120" if v <= 120 else "120-180" if v <= 180
                                                    else "180-240" if v <= 240 else ">240" for v in parts["saved_1min_s"]))
out["latency"]["note"] = "same-data shadow: earliest k-min slot after the scan's own data was ingested (no rescoring)"
json.dump(state, open(STATE, "w"), indent=1)
print(json.dumps(out, indent=1, default=str))
