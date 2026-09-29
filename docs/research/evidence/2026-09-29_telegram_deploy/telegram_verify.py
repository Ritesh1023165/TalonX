"""One-shot, read-only verification of the 2026-09-29 06:42Z Telegram deploy (notifier ROUTING_FIX, promotion UI_ONLY).
PURPOSE: prove the new Lab routing/format is live on real traffic, no replay, no duplicates. OUTPUT: JSON on stdout."""
import json, sqlite3
R = "results/opportunity/"
DEPLOY = "2026-09-29T06:42:33"
def ro(p):
    c = sqlite3.connect(f"file:{R+p}?mode=ro", uri=True, timeout=10); c.row_factory = sqlite3.Row; return c
n, lab, sg = ro("notification.db"), ro("opportunity_research_notifications.db"), ro("promotion_signal_notifications.db")
new_lab = [dict(r) for r in lab.execute("SELECT event_id,event_type,state,created_at_utc,substr(payload_text,1,40) head "
                                        "FROM ops_notification_outbox WHERE created_at_utc > ?", (DEPLOY,))]
new_sig = [dict(r) for r in sg.execute("SELECT event_id,state,created_at_utc,substr(payload_text,1,30) head "
                                       "FROM ops_notification_outbox WHERE created_at_utc > ?", (DEPLOY,))]
dec = [dict(r) for r in n.execute("SELECT decision, lab_route, route_reason, COUNT(*) n FROM decisions "
                                  "WHERE decided_utc > ? GROUP BY 1,2,3", (DEPLOY,))]
out = {"lab_new_rows": len(new_lab), "lab_new_by_type": {}, "lab_all_new_format": all(r["head"].startswith("🧪 TALONX LAB") for r in new_lab),
       "lab_states": {}, "signal_new_rows": len(new_sig),
       "signal_all_new_format": all(r["head"].startswith("🚨 TALONX SIGNAL") for r in new_sig),
       "lab_dup_dedup": lab.execute("SELECT COUNT(*)-COUNT(DISTINCT dedup_key) FROM ops_notification_outbox").fetchone()[0],
       "signal_dup_dedup": sg.execute("SELECT COUNT(*)-COUNT(DISTINCT dedup_key) FROM ops_notification_outbox").fetchone()[0],
       "pre_deploy_rows_created_after_deploy": sum(1 for r in new_lab if r["event_id"] <= "" ),
       "decisions_since_deploy": dec,
       "unrouted_legacy_rows_since_deploy": n.execute("SELECT COUNT(*) FROM decisions WHERE decided_utc > ? AND decision='SELECTED' AND lab_route IS NULL", (DEPLOY,)).fetchone()[0],
       "digests": [dict(r) for r in n.execute("SELECT digest_id,n_events,delivery_state,substr(payload_text,1,60) head FROM digests")],
       "immediate_and_digested": n.execute("SELECT COUNT(*) FROM decisions WHERE lab_route='IMMEDIATE' AND digest_id IS NOT NULL").fetchone()[0],
       "cursor_lag": ro("opportunity.db").execute("SELECT MAX(seq) FROM candidate_events").fetchone()[0] - n.execute("SELECT last_seq FROM cursor WHERE name='events'").fetchone()[0]}
for r in new_lab:
    out["lab_new_by_type"][r["event_type"]] = out["lab_new_by_type"].get(r["event_type"], 0) + 1
    out["lab_states"][r["state"]] = out["lab_states"].get(r["state"], 0) + 1
out["VERDICT"] = "PASS" if (out["lab_new_rows"] and out["lab_all_new_format"] and out["signal_all_new_format"]
                            and out["lab_dup_dedup"] == 0 and out["signal_dup_dedup"] == 0
                            and out["unrouted_legacy_rows_since_deploy"] == 0 and out["immediate_and_digested"] == 0) \
    else ("NO_LAB_TRAFFIC_YET" if not out["lab_new_rows"] else "FAIL")
print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
