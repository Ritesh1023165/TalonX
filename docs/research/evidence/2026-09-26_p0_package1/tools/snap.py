"""Read-only before/after snapshot for P0 package 1 deployment boundaries. usage: python snap.py > file.json"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
R = REPO / "results" / "opportunity"


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


o, n, p, rt, m = (ro(R / f) for f in ("opportunity.db", "notification.db", "promotion.db", "runtime.db", "market.db"))
lab, ps = ro(R / "opportunity_research_notifications.db"), ro(R / "promotion_signal_notifications.db")
out = {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
out["components"] = {r["name"]: {"pid": r["pid"], "state": r["state"], "version": r["version"],
                                 "config_fps": json.loads(r["config_fps_json"] or "{}"), "commit": r["commit_sha"],
                                 "heartbeat": r["heartbeat_utc"]}
                     for r in rt.execute("SELECT * FROM components")}
cur = {"events_max_seq": o.execute("SELECT MAX(seq) FROM candidate_events").fetchone()[0],
       "notifier": n.execute("SELECT last_seq FROM cursor").fetchone()[0],
       "promotion": p.execute("SELECT last_seq FROM cursor").fetchone()[0]}
for h in ("intraday", "same_day", "short_term", "long_term"):
    cur[h] = ro(R / f"evaluator_{h}.db").execute("SELECT last_seq FROM cursor").fetchone()[0]
out["cursors"] = cur
out["counts"] = {
    "candidates": o.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
    "candidate_ids_distinct": o.execute("SELECT COUNT(DISTINCT candidate_id) FROM candidates").fetchone()[0],
    "events": o.execute("SELECT COUNT(*) FROM candidate_events").fetchone()[0],
    "event_ids_distinct": o.execute("SELECT COUNT(DISTINCT event_id) FROM candidate_events").fetchone()[0],
    "scans": o.execute("SELECT COUNT(*) FROM scans").fetchone()[0],
    "decisions": dict(Counter(r[0] for r in n.execute("SELECT decision FROM decisions"))),
    "decisions_total": n.execute("SELECT COUNT(*) FROM decisions").fetchone()[0],
    "surfaced": n.execute("SELECT COUNT(*) FROM surfaced").fetchone()[0],
    "lab_outbox": dict(Counter(f"{r[0]}|{r[1]}" for r in lab.execute("SELECT destination, state FROM ops_notification_outbox"))),
    "promotions": dict(Counter(r[0] for r in p.execute("SELECT state FROM promotions"))),
    "promotion_outbox": dict(Counter(f"{r[0]}|{r[1]}" for r in ps.execute("SELECT destination, state FROM ops_notification_outbox"))),
    "open_queue": p.execute("SELECT COUNT(*) FROM promotions WHERE state='QUEUED'").fetchone()[0]}
out["decisions_columns"] = [r[1] for r in n.execute("PRAGMA table_info(decisions)")]
ing = m.execute("SELECT window_id, as_of_utc, cycle_utc, phase FROM ingestion_state ORDER BY cycle_utc DESC LIMIT 1").fetchone()
out["ingestion"] = dict(ing) if ing else None
out["last_scan"] = dict(o.execute("SELECT decision_utc, phase, state FROM scans ORDER BY decision_utc DESC LIMIT 1").fetchone())
out["deployments_last5"] = [dict(r) for r in rt.execute(
    "SELECT deployment_id, component, classification, decided_by, declared, old_version, new_version FROM "
    "deployment_events ORDER BY at_utc DESC LIMIT 5")]
s = json.loads((REPO / "v2_release_rc1_status.json").read_text())
out["v2"] = {k: s.get(k) for k in ("heartbeat_utc", "tick", "data_state", "campaign_id", "strategy_version",
                                   "execution_mode")}
out["v2"]["provider_fp"] = (s.get("price_provider_contract") or {}).get("contract_fingerprint")
v = ro(REPO / "v2_release_rc1.db")
out["v2"]["tables"] = {t: v.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                       for t in ("positions", "trades", "pending_entry_intents")}
out["v2"]["db_sha"] = sha(REPO / "v2_release_rc1.db")
print(json.dumps(out, indent=1, default=str))
