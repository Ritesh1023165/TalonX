"""AFTER_HOURS reserve LIVE confirmation for 2026-09-28 (read-only).
PURPOSE: prove the data-phase reserve fix on live traffic. OUTPUT: JSON on stdout.
Case A: processed AFTER_HOURS + data REGULAR  -> must not be counted_new against the AH reserve.
Case B: processed AFTER_HOURS + data AFTER_HOURS eligible setup -> may consume the AH reserve (<= 3)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
R = REPO / "results" / "opportunity"
WID = "2026-09-28"


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


n, o, lab = ro(R / "notification.db"), ro(R / "opportunity.db"), ro(R / "opportunity_research_notifications.db")
dec = [dict(r) for r in n.execute("SELECT * FROM decisions WHERE window_id=? AND phase='AFTER_HOURS' ORDER BY seq", (WID,))]
ev = {r["event_id"]: dict(r) for r in o.execute(
    "SELECT event_id, data_as_of_utc, at_utc, score, gap_pct, symbol FROM candidate_events WHERE window_id=? "
    "AND at_utc >= '2026-09-28T20:00'", (WID,))}
for d in dec:
    d.update({k: ev.get(d["event_id"], {}).get(k) for k in ("data_as_of_utc", "at_utc", "score", "gap_pct")})
setups = ("BULLISH", "BEARISH")
reg_after = [d for d in dec if d.get("data_phase") == "REGULAR"]
true_ah = [d for d in dec if d.get("data_phase") == "AFTER_HOURS"]


def brief(d):
    return None if d is None else {k: d.get(k) for k in ("symbol", "event_type", "classification", "decision", "reason",
                                                         "counted_new", "data_phase", "data_as_of_utc", "decided_utc",
                                                         "score", "outbox_event_id", "delivery_state")}


first_reg_setup = next((d for d in reg_after if d["classification"] in setups), None)
first_ah_cand = next((d for d in true_ah), None)
first_ah_setup = next((d for d in true_ah if d["classification"] in setups), None)
first_ah_send = next((d for d in true_ah if d["decision"] == "SELECTED" and d["counted_new"]), None)
sent_state = None
if first_ah_send and first_ah_send.get("outbox_event_id"):
    r = lab.execute("SELECT state, sent_at_utc, destination FROM ops_notification_outbox WHERE event_id=?",
                    (first_ah_send["outbox_event_id"],)).fetchone()
    sent_state = dict(r) if r else None
rt = ro(R / "runtime.db")
det = json.loads(rt.execute("SELECT detail_json FROM components WHERE name='notifier'").fetchone()[0] or "{}")
out = {"window": WID, "ah_decisions": len(dec), "missing_data_phase": sum(d.get("data_phase") is None for d in dec),
       "case_A_regular_data_after_close": {"n": len(reg_after),
                                            "counted_new": sum(d["counted_new"] or 0 for d in reg_after),
                                            "decisions": {k: sum(1 for d in reg_after if d["decision"] == k)
                                                          for k in sorted({d["decision"] for d in reg_after})}},
       "case_B_true_ah": {"n": len(true_ah), "counted_new": sum(d["counted_new"] or 0 for d in true_ah),
                          "setups": sum(d["classification"] in setups for d in true_ah),
                          "decisions": {k: sum(1 for d in true_ah if d["decision"] == k)
                                        for k in sorted({d["decision"] for d in true_ah})}},
       "first_regular_data_setup_after_20": brief(first_reg_setup), "first_true_ah_candidate": brief(first_ah_cand),
       "first_true_ah_setup": brief(first_ah_setup), "first_true_ah_send": brief(first_ah_send),
       "first_true_ah_send_outbox": sent_state, "notifier_after_hours_reserve": det.get("after_hours_reserve"),
       "duplicate_outbox_events": lab.execute("SELECT COUNT(*) - COUNT(DISTINCT dedup_key) FROM ops_notification_outbox")
       .fetchone()[0]}
A, B = out["case_A_regular_data_after_close"], out["case_B_true_ah"]
res = out["notifier_after_hours_reserve"] or {}
out["VERDICT"] = ("ACCEPTED" if A["counted_new"] == 0 and out["missing_data_phase"] == 0 and B["counted_new"] <= 3
                  and res.get("AH_RESERVED_USED_BY_TRUE_AH", 0) == B["counted_new"] and B["setups"] > 0
                  and out["duplicate_outbox_events"] == 0
                  else "NO_TRUE_AH_SETUP_YET" if B["setups"] == 0 and A["counted_new"] == 0 else "NOT_ACCEPTED")
print(json.dumps(out, indent=1, default=str))
