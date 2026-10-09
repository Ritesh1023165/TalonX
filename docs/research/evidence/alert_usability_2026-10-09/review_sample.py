"""Alert-usability review 2026-10-09 -- READ-ONLY, sanitised sample of naturally delivered RESEARCH_OPPORTUNITY alerts.

Reads (read-only URIs): the promotion Signal outbox, promotion.db ``promotions`` (NOT ``paper_outcomes``), the
opportunity.db ``candidate_events`` row that triggered each promotion (generation-time evidence only -- never the
mutable ``candidates.last_*`` columns), the delivery-trace store (timestamps only), the DTU policy schedule and the
window's universe report. No subsequent price, return or outcome is read. Output carries no chat id, Telegram message
id, token or credential; internal event ids are reduced to a short hash.

Selection: outbox rows with event_type RESEARCH_OPPORTUNITY and state SENT whose sent_at_utc <= CUTOFF and whose
promotion belongs to a window governed by DTU_V3_TOP600 (effective 2026-10-09), ordered by sent_at_utc DESC then
event_id; the first N (<= 20). Repeats: for sampled symbols only, earlier SENT review alerts are counted.

usage: python docs/research/evidence/alert_usability_2026-10-09/review_sample.py [ROOT] > sample.json
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

CUTOFF = "2026-10-09T16:15:00+00:00"
N = 20
POLICY, POLICY_FROM = "DTU_V3_TOP600", "2026-10-09"


def ro(p: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def secs(a, b):
    return round((ts(b) - ts(a)).total_seconds(), 1) if a and b else None


def main(root: Path) -> dict:
    opp = root / "results" / "opportunity"
    sched = json.loads((opp / "control" / "dtu_policy_schedule.json").read_text(encoding="utf-8"))
    eff = [s for s in sched["schedule"] if s["policy"] == POLICY]
    assert eff and eff[0]["effective_from_window"] == POLICY_FROM, "600-stock policy identity changed"
    ob, pc, op = ro(opp / "promotion_signal_notifications.db"), ro(opp / "promotion.db"), ro(opp / "opportunity.db")
    tr_path = opp / "promotion_delivery_trace.db"
    tr = ro(tr_path) if tr_path.exists() else None
    rows = ob.execute(
        "SELECT o.event_id, o.payload_text, o.created_at_utc, o.sent_at_utc, o.attempts FROM ops_notification_outbox o "
        "WHERE o.event_type='RESEARCH_OPPORTUNITY' AND o.state='SENT' AND o.sent_at_utc<=? "
        "ORDER BY o.sent_at_utc DESC, o.event_id", (CUTOFF,)).fetchall()
    uni = {}
    items = []
    for r in rows:
        p = pc.execute("SELECT symbol, family, window_id, score, reference_price, data_as_of_utc, event_utc, queued_utc, "
                       "decision_utc, horizons_json, processing_phase, data_phase, policy_version, event_id, candidate_id "
                       "FROM promotions WHERE signal_event_id=?", (r["event_id"],)).fetchone()
        if p is None or p["window_id"] < POLICY_FROM:
            continue                                   # not generated under the active 600-stock policy
        w = p["window_id"]
        if w not in uni:
            f = opp / "universe_reports" / w / f"universe_{w}.json"
            uni[w] = {u["symbol"]: u for u in json.loads(f.read_text(encoding="utf-8"))["rows"]} if f.exists() else {}
        e = op.execute("SELECT event_type, from_state, to_state, at_utc, data_as_of_utc, score, gap_pct, last_price, "
                       "reason, features_json, score_json, catalyst, provenance_json FROM candidate_events "
                       "WHERE event_id=?", (p["event_id"],)).fetchone()
        feat = json.loads(e["features_json"] or "{}") if e else {}
        sc = json.loads(e["score_json"] or "{}") if e else {}
        prov = json.loads(e["provenance_json"] or "{}") if e else {}
        resp = None
        if tr is not None:
            h = hashlib.sha256(r["payload_text"].encode("utf-8")).hexdigest()
            t = tr.execute("SELECT send_start_utc, response_utc, network_retries, rate_limit_retries, trace_state "
                           "FROM traces WHERE payload_sha256=? ORDER BY send_start_utc", (h,)).fetchall()
            resp = [dict(x) for x in t] or None
        prior = pc.execute("SELECT COUNT(*), MAX(window_id) FROM promotions WHERE symbol=? AND reason_code="
                           "'RESEARCH_REVIEW_ALERT' AND state='PROMOTED_SIGNAL' AND decision_utc<?",
                           (p["symbol"], p["decision_utc"])).fetchone()
        prior_same_window = pc.execute("SELECT COUNT(*) FROM promotions WHERE symbol=? AND window_id=? AND "
                                       "reason_code='RESEARCH_REVIEW_ALERT' AND state='PROMOTED_SIGNAL' AND "
                                       "decision_utc<?", (p["symbol"], w, p["decision_utc"])).fetchone()[0]
        u = uni[w].get(p["symbol"], {})
        items.append({
            "ref": hashlib.sha256(r["event_id"].encode()).hexdigest()[:10],
            "symbol": p["symbol"], "family": p["family"], "window_id": w,
            "universe_state": u.get("state"), "universe_reason": u.get("reason"),
            "rendered_message": r["payload_text"],
            "trigger": {"event_type": e["event_type"] if e else None, "from_state": e["from_state"] if e else None,
                        "to_state": e["to_state"] if e else None, "reason": e["reason"] if e else None,
                        "gap_pct_vs_prev_close": e["gap_pct"] if e else None, "prev_close": feat.get("prev_close"),
                        "prev_high": feat.get("prev_high"), "range_position": feat.get("range_position"),
                        "range_distance_pct": feat.get("range_distance_pct"), "trend5_pct": feat.get("trend5_pct"),
                        "atr20_pct": feat.get("atr20_pct"),
                        "window_to_date_volume_sh": feat.get("pm_volume"),
                        "window_to_date_dollars": feat.get("pm_dollars"),
                        "window_to_date_valid_1min_bars": feat.get("pm_bars"),
                        "volume_fraction_of_adv20": feat.get("activity_adv_fraction")},
            "score": {"total": p["score"], "parts": {k: sc.get(k) for k in ("gap", "activity", "liquidity", "catalyst",
                                                                           "structure", "data_confidence")},
                      "why_as_generated": sc.get("why")},
            "catalyst_as_generated": e["catalyst"] if e else None,
            "price": {"reference_price": p["reference_price"], "last_bar_start_utc": feat.get("last_bar_utc"),
                      "data_as_of_utc": p["data_as_of_utc"], "feed": prov.get("feed"),
                      "provider_delay_min": prov.get("delay_minutes")},
            "timing_utc": {"data_as_of": p["data_as_of_utc"], "ingestion_cycle": prov.get("ingestion_cycle_utc"),
                           "candidate_event": p["event_utc"], "promotion_queued": p["queued_utc"],
                           "outbox_created": r["created_at_utc"], "api_acknowledged_sent_at": r["sent_at_utc"],
                           "trace": resp},
            "delays_s": {"data_to_event": secs(p["data_as_of_utc"], p["event_utc"]),
                         "event_to_queued": secs(p["event_utc"], p["queued_utc"]),
                         "queued_to_ack": secs(p["queued_utc"], r["sent_at_utc"]),
                         "data_to_ack": secs(p["data_as_of_utc"], r["sent_at_utc"])},
            "horizons": json.loads(p["horizons_json"] or "[]"), "processing_phase": p["processing_phase"],
            "data_phase": p["data_phase"], "policy_version": p["policy_version"],
            "repeat": {"earlier_review_alerts_for_symbol": prior[0], "latest_earlier_window": prior[1],
                       "earlier_in_same_window": prior_same_window},
            "outbox_attempts": r["attempts"]})
        if len(items) >= N:
            break
    syms = {i["symbol"] for i in items}
    first, last = (items[-1]["timing_utc"]["api_acknowledged_sent_at"], items[0]["timing_utc"]["api_acknowledged_sent_at"]) \
        if items else (None, None)
    return {"cutoff_utc": CUTOFF, "selection": "SENT RESEARCH_OPPORTUNITY, sent_at<=cutoff, window>=2026-10-09 "
            "(DTU_V3_TOP600), ORDER BY sent_at DESC, event_id; first 20", "universe_policy": POLICY,
            "universe_policy_effective_from_window": POLICY_FROM, "alerts": len(items), "distinct_symbols": len(syms),
            "windows": sorted({i["window_id"] for i in items}), "sent_range_utc": [first, last],
            "partial_session": True, "items": items}


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[4]
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(main(root), indent=1, ensure_ascii=False, default=str))
