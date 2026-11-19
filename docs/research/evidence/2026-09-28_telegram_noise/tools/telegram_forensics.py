"""Telegram alert-volume forensics for one trading window (READ-ONLY; every DB opened mode=ro; nothing is sent).

Sources (durable, not Telegram unread badges):
  Signal   results/opportunity/promotion_signal_notifications.db (TRADE_EVENT outbox) + promotion.db
  Lab      results/opportunity/opportunity_research_notifications.db (RESEARCH outbox) + notification.db decisions
  Sentinel v2_release_rc1_notifications.db (OPERATIONS outbox) + results/opportunity/sentinel_replies.jsonl
Legacy senders checked for the day (must be 0): ~/.talonx/dispatch_audit.db, v2_release_rc1.db v2_alert_outbox.

No chat ids, user ids or tokens are read into the output.
usage: python telegram_forensics.py [WINDOW_ID] > out.json"""
from __future__ import annotations

import collections as C
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
R = REPO / "results" / "opportunity"
WID = sys.argv[1] if len(sys.argv) > 1 else "2026-09-28"
sys.path.insert(0, str(REPO))
from talonx_opportunity.phases import trading_window  # noqa: E402


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def pct(xs, q):
    xs = sorted(xs)
    return round(xs[int(q * (len(xs) - 1))], 2) if xs else None


def band(x, edges, labels):
    for e, lab in zip(edges, labels):
        if x < e:
            return lab
    return labels[-1]


SCORE_BANDS = ((65, 70, 75, 80, 85), ("<65", "65-70", "70-75", "75-80", "80-85", "85+"))
PRICE_BANDS = ((1, 5, 20, 100), ("<$1", "$1-5", "$5-20", "$20-100", "$100+"))


def sband(s):
    return band(s or 0, *SCORE_BANDS)


def pband(p):
    return band(p or 0, *PRICE_BANDS)


def per_symbol(syms):
    cnt = C.Counter(syms)
    return {"unique_symbols": len(cnt), "messages_per_symbol_mean": round(len(syms) / len(cnt), 2) if cnt else None,
            "max_messages_one_symbol": max(cnt.values()) if cnt else 0,
            "top20": cnt.most_common(20), "symbols_with_ge_5": sum(v >= 5 for v in cnt.values())}


def outbox_rows(path, day):
    return [dict(r) for r in ro(path).execute(
        "SELECT event_id, destination, event_type, producer, dedup_key, state, attempts, created_at_utc, sent_at_utc, "
        "provenance_json FROM ops_notification_outbox WHERE created_at_utc LIKE ?", (day + "%",))]


def outbox_summary(rows):
    return {"total_rows": len(rows), "by_state": dict(C.Counter(r["state"] for r in rows)),
            "sent": sum(r["state"] == "SENT" for r in rows),
            "retry_sends (attempts>1)": sum((r["attempts"] or 0) > 1 for r in rows),
            "duplicate_dedup_keys": len(rows) - len({r["dedup_key"] for r in rows}),
            "queued (PENDING/RETRY)": sum(r["state"] in ("PENDING", "RETRY") for r in rows),
            "expired": sum(r["state"] == "EXPIRED" for r in rows),
            "failed/held/ambiguous": sum(r["state"] in ("FAILED", "HELD", "AMBIGUOUS") for r in rows)}


# ------------------------------------------------------------------------------------------------------------- Signal
def signal_section():
    rows = outbox_rows(R / "promotion_signal_notifications.db", WID)
    pr = ro(R / "promotion.db")
    promos = {r["promotion_id"]: dict(r) for r in pr.execute("SELECT * FROM promotions")}
    outc = {r["promotion_id"]: dict(r) for r in pr.execute("SELECT * FROM paper_outcomes")}
    sent = [promos[r["event_id"]] | {"sent_at_utc": r["sent_at_utc"]} for r in rows if r["state"] == "SENT"]
    cls = C.Counter()
    for p in sent:                                        # one outbox row per promotion_id (= candidate identity)
        cls["NEW_PAPER_OPPORTUNITY"] += 1
    by_sym_cands = C.defaultdict(set)
    for p in sent:
        by_sym_cands[p["symbol"]].add(p["candidate_id"])
    multi = {s: sorted(c) for s, c in by_sym_cands.items() if len(c) > 1}
    lat_q = [(ts(p["decision_utc"]) - ts(p["queued_utc"])).total_seconds() / 60 for p in sent]
    lat_ev = [(ts(p["sent_at_utc"]) - ts(p["event_utc"])).total_seconds() / 60 for p in sent if p["sent_at_utc"]]
    lat_data = [(ts(p["sent_at_utc"]) - ts(p["data_as_of_utc"])).total_seconds() / 60 for p in sent if p["sent_at_utc"]]
    # limiter: max sends in any rolling 5 min, and score order among same-tick releases
    dts = sorted(ts(p["decision_utc"]) for p in sent)
    max5 = max((sum(1 for y in dts if x <= y < x + timedelta(minutes=5)) for x in dts), default=0)
    queued_today = [p for p in promos.values() if (p["queued_utc"] or "").startswith(WID)]
    # score-order check: a sent item released while a HIGHER-scored item was waiting in the queue (queued earlier and
    # decided later) is an inversion
    inv = 0
    for p in sent:
        T = ts(p["decision_utc"])
        inv += any(ts(q["queued_utc"]) <= T < ts(q["decision_utc"] or "9999-01-01T00:00:00+00:00")
                   and (q["score"] or 0) > (p["score"] or 0) for q in queued_today if q is not p)
    states = C.Counter((p["state"], p["reason_code"]) for p in queued_today)
    evals = C.Counter((r["decision"], r["reason_code"]) for r in pr.execute(
        "SELECT decision, reason_code FROM evaluations WHERE evaluated_utc LIKE ?", (WID + "%",)))

    def dist(key):
        return dict(sorted(C.Counter(key(p) for p in sent).items()))
    oc = [outc.get(p["promotion_id"]) for p in sent]
    by_band = {}
    for b in SCORE_BANDS[1]:
        grp = [o for p, o in zip(sent, oc) if sband(p["score"]) == b and o]
        r30 = [o["ret_30m_pct"] for o in grp if o["ret_30m_pct"] is not None]
        rc = [o["close_ret_pct"] for o in grp if o["close_ret_pct"] is not None]
        by_band[b] = {"n_sent": sum(sband(p["score"]) == b for p in sent), "n_30m": len(r30),
                      "confirmed_30m": sum(o["status"] == "CONFIRMED" for o in grp),
                      "mean_ret_30m_pct": round(sum(r30) / len(r30), 3) if r30 else None,
                      "n_close": len(rc), "mean_close_ret_pct": round(sum(rc) / len(rc), 3) if rc else None}
    return {"outbox": outbox_summary(rows), "classification": dict(cls),
            "duplicates": {"same_promotion_id_twice": outbox_summary(rows)["duplicate_dedup_keys"],
                           "same_candidate_twice": len(sent) - len({p["candidate_id"] for p in sent}),
                           "symbols_with_multiple_identities": multi},
            "per_symbol": per_symbol([p["symbol"] for p in sent]),
            "candidate_origin_window": dict(C.Counter(p["candidate_id"][:10] for p in sent)),
            "latency_min": {"queued_to_released_p50": pct(lat_q, .5), "queued_to_released_p90": pct(lat_q, .9),
                            "queued_to_released_max": pct(lat_q, 1),
                            "event_to_sent_p50": pct(lat_ev, .5), "event_to_sent_p90": pct(lat_ev, .9),
                            "event_to_sent_max": pct(lat_ev, 1),
                            "data_as_of_to_sent_p50": pct(lat_data, .5), "data_as_of_to_sent_p90": pct(lat_data, .9)},
            "released_after_ge_10min_queue": sum(x >= 10 for x in lat_q),
            "limiter": {"max_sends_any_rolling_5min": max5, "policy": "3 per 5 min",
                        "score_order_inversions": inv},
            "promotions_queued_today_by_state": {f"{a}:{b}": v for (a, b), v in states.most_common()},
            "evaluations_today": {f"{a}:{b}": v for (a, b), v in evals.most_common()},
            "score_distribution": dist(lambda p: sband(p["score"])),
            "price_bands": dist(lambda p: pband(p["reference_price"])),
            "horizons": dist(lambda p: p["horizons_json"]), "data_phase": dist(lambda p: p["data_phase"]),
            "hour_utc": dist(lambda p: p["decision_utc"][11:13]),
            "outcomes_by_score_band (descriptive only, not evidence of edge)": by_band,
            "_sent": sent, "_outcomes": outc, "_queued": queued_today}


# ---------------------------------------------------------------------------------------------------------------- Lab
def lab_section():
    rows = outbox_rows(R / "opportunity_research_notifications.db", WID)
    n = ro(R / "notification.db")
    dec = {r["outbox_event_id"]: dict(r) for r in n.execute(
        "SELECT * FROM decisions WHERE outbox_event_id IS NOT NULL")}
    sent = [dec[r["event_id"]] for r in rows if r["state"] == "SENT" and r["event_id"] in dec]
    kinds = C.Counter()
    for d in sent:
        t, c = d["event_type"], d["classification"]
        k = ("WATCH" if (t, c) == ("NEW", "WATCH") else f"NEW_{c}" if t == "NEW" else
             f"UPGRADE_TO_{c}" if t == "UPGRADE" else f"MATERIAL_UPDATE_{c}" if t == "MATERIAL_UPDATE"
             else t)
        kinds[k] += 1
    return {"outbox": outbox_summary(rows), "sent_by_kind": dict(kinds.most_common()),
            "sent_by_phase": dict(C.Counter(d["phase"] for d in sent)),
            "per_symbol": per_symbol([d["symbol"] for d in sent]),
            "per_candidate_max": max(C.Counter(d["candidate_id"] for d in sent).values(), default=0),
            "decisions_today_all": dict(C.Counter(r[0] for r in n.execute(
                "SELECT decision FROM decisions WHERE window_id=?", (WID,))))}


def sentinel_section():
    rows = outbox_rows(REPO / "v2_release_rc1_notifications.db", WID)
    replies = 0
    p = R / "sentinel_replies.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                replies += str(json.loads(line).get("at_utc", "")).startswith(WID)
            except ValueError:
                pass
    return {"operations_outbox": outbox_summary(rows), "operations_by_type": dict(C.Counter(r["event_type"] for r in rows)),
            "command_replies": replies,
            "total_sent": sum(r["state"] == "SENT" for r in rows) + replies}


def legacy_section():
    out = {}
    try:
        c = ro(Path(os.path.expanduser("~/.talonx/dispatch_audit.db")))
        out["legacy_last_telegram_push_today"] = c.execute(
            "SELECT COUNT(*) FROM last_telegram_push WHERE pushed_at LIKE ?", (WID + "%",)).fetchone()[0]
    except sqlite3.Error as e:
        out["legacy_last_telegram_push_today"] = f"unreadable: {e}"
    try:
        c = ro(REPO / "v2_release_rc1.db")
        out["v2_trade_event_outbox_today"] = c.execute(
            "SELECT COUNT(*) FROM v2_alert_outbox WHERE created_at_utc LIKE ?", (WID + "%",)).fetchone()[0]
    except sqlite3.Error as e:
        out["v2_trade_event_outbox_today"] = f"unreadable: {e}"
    return out


# ------------------------------------------------------------------ future Signal volume policies (READ-ONLY estimates)
def simulate(queued, policy, gone_at):
    """Replay the promotion queue (score-desc, rate limit, 30-min expiry) under ``policy``. ``gone_at[pid]`` = when the
    real run found the candidate no longer valid (REJECTED_WHILE_QUEUED) -- used as that item's validity end."""
    rate_max, rate_s = policy.get("rate", (3, 300))
    items = sorted((p for p in queued if policy["keep"](p)), key=lambda p: p["queued_utc"])
    if not items:
        return []
    t, end = ts(items[0]["queued_utc"]), ts(items[-1]["queued_utc"]) + timedelta(minutes=31)
    q, i, sent, times, seen_sym = [], 0, [], [], set()
    while t <= end:
        while i < len(items) and ts(items[i]["queued_utc"]) <= t:
            q.append(items[i])
            i += 1
        q = [p for p in q if (t - ts(p["queued_utc"])).total_seconds() <= 1800
             and (gone_at.get(p["promotion_id"]) is None or t < gone_at[p["promotion_id"]])]
        q.sort(key=lambda p: (-(p["score"] or 0), p["queued_utc"]))
        used = sum(1 for x in times if (t - x).total_seconds() < rate_s)
        for p in list(q):
            if used >= rate_max:
                break
            if policy.get("one_per_symbol") and p["symbol"] in seen_sym:
                q.remove(p)
                continue
            sent.append(p)
            times.append(t)
            seen_sym.add(p["symbol"])
            q.remove(p)
            used += 1
        t += timedelta(seconds=30)
    return sent


def signal_policies(sig):
    queued = sig["_queued"]
    outc = sig["_outcomes"]
    gone = {p["promotion_id"]: ts(p["decision_utc"]) for p in queued if p["state"] == "REJECTED_WHILE_QUEUED"}
    liq = {}
    o = ro(R / "opportunity.db")
    for p in queued:
        r = o.execute("SELECT liquidity_json FROM candidates WHERE candidate_id=?", (p["candidate_id"],)).fetchone()
        liq[p["candidate_id"]] = json.loads(r[0] or "{}") if r else {}
    pm = lambda p: (liq.get(p["candidate_id"]) or {}).get("pm_dollars") or 0  # noqa: E731
    elig80 = {p["promotion_id"] for p in queued if (p["score"] or 0) >= 80}
    pol = {
        "P0_CURRENT_3_PER_5MIN (simulated)": {"keep": lambda p: True},
        "P1_SCORE_GE_70": {"keep": lambda p: (p["score"] or 0) >= 70},
        "P2_SCORE_GE_75": {"keep": lambda p: (p["score"] or 0) >= 75},
        "P3_TOP1_PER_5MIN": {"keep": lambda p: True, "rate": (1, 300)},
        "P4_TOP2_PER_15MIN": {"keep": lambda p: True, "rate": (2, 900)},
        "P5_TRADABILITY_PRICE_GE_5_AND_SESSION_DOLLARS_GE_5M":
            {"keep": lambda p: (p["reference_price"] or 0) >= 5 and pm(p) >= 5e6},
        "P6_ONE_PER_SYMBOL_PER_DAY": {"keep": lambda p: True, "one_per_symbol": True},
        "P7_SCORE_GE_70_AND_TRADABILITY": {"keep": lambda p: (p["score"] or 0) >= 70 and (p["reference_price"] or 0) >= 5
                                           and pm(p) >= 5e6},
    }
    out = {"_note": "estimates: queue replayed at 30 s ticks with the real run's invalidation times; outcome metrics "
                    "exist only for items the REAL run promoted (coverage reported); descriptive, n small, no edge claim",
           "eligible_queued_today": len(queued), "eligible_ge_80": len(elig80)}
    for name, p in pol.items():
        s = simulate(queued, p, gone)
        ids = {x["promotion_id"] for x in s}
        oc = [outc[i] for i in ids if i in outc]
        r30 = [x["ret_30m_pct"] for x in oc if x["ret_30m_pct"] is not None]
        rc = [x["close_ret_pct"] for x in oc if x["close_ret_pct"] is not None]
        out[name] = {"SIGNALS_SENT": len(s), "UNIQUE_SYMBOLS": len({x["symbol"] for x in s}),
                     "HIGH_SCORE_CAPTURE": f"{len(ids & elig80)}/{len(elig80)}",
                     "MISSED_80_PLUS": len(elig80 - ids),
                     "OUTCOME_COVERAGE": f"{len(oc)}/{len(s)}",
                     "CONFIRMED_30M_RATE": round(sum(x["status"] == "CONFIRMED" for x in oc) / len(r30), 3) if r30 else None,
                     "MEAN_RET_30M_PCT": round(sum(r30) / len(r30), 3) if r30 else None,
                     "MEAN_CLOSE_RET_PCT": round(sum(rc) / len(rc), 3) if rc else None}
    return out


def main():
    sig = signal_section()
    lab = lab_section()
    out = {"window_id": WID, "generated_utc": datetime.now().astimezone().isoformat(),
           "SIGNAL": {k: v for k, v in sig.items() if not k.startswith("_")}, "LAB": lab,
           "SENTINEL": sentinel_section(), "LEGACY_AND_V2": legacy_section(),
           "FUTURE_SIGNAL_POLICIES_READ_ONLY": signal_policies(sig)}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
