"""READ-ONLY verification of naturally delivered alerts rendered after the compact-template deployment.

For each SENT RESEARCH_OPPORTUNITY outbox row created after DEPLOY_UTC: re-derive the expected message from the
generation-time records with the deployed renderer AS OF the row's original render instant, and require byte equality;
check template provenance, trace correlation (TRACE_OK), single attempt, unique dedup key and VR still BLOCKED.
Output is sanitised (no chat or Telegram message identifiers). Nothing is sent or written.

usage: python verify_natural.py [ROOT] > natural_verification.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

CODE = Path(__file__).resolve().parents[4]
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else CODE
sys.path.insert(0, str(CODE))
from talonx_opportunity import promotion as P  # noqa: E402
from talonx_opportunity.delivery_trace import make_trace_lookup  # noqa: E402
from talonx_opportunity.phases import trading_window  # noqa: E402

DEPLOY_UTC = "2026-10-09T16:53:33.878022+00:00"
OPP = ROOT / "results" / "opportunity"


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def main() -> dict:
    ob, pc, op = ro(OPP / "promotion_signal_notifications.db"), ro(OPP / "promotion.db"), ro(OPP / "opportunity.db")
    look = make_trace_lookup(OPP / "promotion_signal_notifications.db", OPP / "promotion_delivery_trace.db")
    sched = json.loads((OPP / "control" / "dtu_policy_schedule.json").read_text(encoding="utf-8"))
    rows = ob.execute("SELECT event_id, payload_text, provenance_json, state, attempts, dedup_key, created_at_utc, "
                      "sent_at_utc FROM ops_notification_outbox WHERE event_type='RESEARCH_OPPORTUNITY' AND "
                      "created_at_utc>? ORDER BY created_at_utc, event_id", (DEPLOY_UTC,)).fetchall()
    items, problems = [], []
    for r in rows:
        q = dict(pc.execute("SELECT * FROM promotions WHERE signal_event_id=?", (r["event_id"],)).fetchone())
        ev = op.execute("SELECT features_json, score_json, catalyst, provenance_json, at_utc FROM candidate_events "
                        "WHERE event_id=?", (q["event_id"],)).fetchone()
        ids = [x[0] for x in pc.execute("SELECT signal_event_id FROM promotions WHERE symbol=? AND promotion_id!=? AND "
                                        "state='PROMOTED_SIGNAL' AND signal_event_id IS NOT NULL",
                                        (q["symbol"], q["promotion_id"]))]
        last = ob.execute(f"SELECT MAX(sent_at_utc) FROM ops_notification_outbox WHERE state='SENT' AND sent_at_utc<? "
                          f"AND event_id IN ({','.join('?' * len(ids))})", [r["created_at_utc"], *ids]).fetchone()[0] \
            if ids else None
        uni = None
        for e in sorted(sched["schedule"], key=lambda e: e["effective_from_window"]):
            if e["effective_from_window"] <= q["window_id"]:
                uni = e["policy"]
        ctx = {"event": dict(ev) if ev else None,
               "close_utc": trading_window(date.fromisoformat(q["window_id"])).close_utc,
               "prior_delivery_date": P._ts(last).astimezone(P._ET).date().isoformat() if last else None,
               "universe": uni}
        expected = P.render_review_compact(q, P._ts(r["created_at_utc"]), q["policy_version"], ctx)
        t = look(r["event_id"]) or {}
        it = {"symbol": q["symbol"], "reference": q["promotion_id"], "state": r["state"], "attempts": r["attempts"],
              "template_version": json.loads(r["provenance_json"] or "{}").get("template_version"),
              "render_matches_recorded_evidence": r["payload_text"] == expected,
              "trace_state": t.get("trace_state"), "hidden_retries": t.get("hidden_retries"),
              "data_as_of_utc": q["data_as_of_utc"], "detected_utc": q["event_utc"],
              "written_utc": r["created_at_utc"], "api_ack_utc_audit_only": r["sent_at_utc"],
              "dedup_unique": ob.execute("SELECT COUNT(*) FROM ops_notification_outbox WHERE dedup_key=?",
                                         (r["dedup_key"],)).fetchone()[0] == 1,
              "message": r["payload_text"]}
        for k, ok in (("state", r["state"] == "SENT"), ("attempts", r["attempts"] == 1),
                      ("template", it["template_version"] == P.REVIEW_TEMPLATE_VERSION),
                      ("render", it["render_matches_recorded_evidence"]), ("trace", t.get("trace_state") == "TRACE_OK"),
                      ("dedup", it["dedup_unique"])):
            if not ok:
                problems.append(f"{q['symbol']}:{k}")
        items.append(it)
    from talonx_paperperf import vr_live
    vr = vr_live.entry_control(ROOT / "results" / "vr_paper")["state"]      # the DATA root, not this checkout
    if vr != "BLOCKED":
        problems.append("VR_NOT_BLOCKED")
    return {"deploy_utc": DEPLOY_UTC, "post_deploy_rows": len(items), "vr_entry_control": vr, "problems": problems,
            "verdict": ("NO_NATURAL_DELIVERY_YET" if not items else ("PASS" if not problems else "FAIL")),
            "items": items}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(main(), indent=1, ensure_ascii=False, default=str))
