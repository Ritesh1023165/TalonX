"""Read-only full-stack snapshot for the 2026-09-26 weekend shutdown (pre and post). usage: python shutdown_snap.py"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
sys.path.insert(0, str(REPO))
R = REPO / "results" / "opportunity"
NOW = datetime.now(timezone.utc)


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def age(ts):
    try:
        return round((NOW - datetime.fromisoformat(ts)).total_seconds(), 1)
    except Exception:  # noqa: BLE001
        return None


git = lambda *a: subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True).stdout.strip()  # noqa: E731
out = {"time_utc": NOW.isoformat(timespec="seconds"), "branch": git("branch", "--show-current"),
       "head": git("rev-parse", "--short", "HEAD"), "main": git("rev-parse", "--short", "origin/main"),
       "tracked_changes": [x for x in git("status", "--porcelain", "--untracked-files=no").splitlines() if x]}

rt = ro(R / "runtime.db")
out["components"] = {r["name"]: {"pid": r["pid"], "state": r["state"], "hb_age_s": age(r["heartbeat_utc"]),
                                 "version": r["version"], "config_fps": json.loads(r["config_fps_json"] or "{}"),
                                 "deployment": (json.loads(r["detail_json"] or "{}").get("deployment_id"))}
                     for r in rt.execute("SELECT * FROM components")}
out["pending_declarations"] = [dict(r) for r in rt.execute(
    "SELECT id, component, classification, expected_version FROM change_declarations WHERE consumed_by IS NULL")]

o, n, p = ro(R / "opportunity.db"), ro(R / "notification.db"), ro(R / "promotion.db")
seq = o.execute("SELECT MAX(seq) FROM candidate_events").fetchone()[0]
cur = {"notifier": n.execute("SELECT last_seq FROM cursor").fetchone()[0],
       "promotion": p.execute("SELECT last_seq FROM cursor").fetchone()[0]}
for h in ("intraday", "same_day", "short_term", "long_term"):
    cur[h] = ro(R / f"evaluator_{h}.db").execute("SELECT last_seq FROM cursor").fetchone()[0]
out["engine"] = {"max_event_seq": seq, "cursors": cur, "lag": {k: seq - v for k, v in cur.items()},
                 "candidates": o.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
                 "events": o.execute("SELECT COUNT(*) FROM candidate_events").fetchone()[0],
                 "outcome_rows": ro(R / "outcomes.db").execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]}
out["promotion"] = {"mode": out["components"].get("promotion", {}).get("config_fps", {}).get("mode"),
                    "states": dict(Counter(r[0] for r in p.execute("SELECT state FROM promotions"))),
                    "queued": p.execute("SELECT COUNT(*) FROM promotions WHERE state='QUEUED'").fetchone()[0],
                    "distinct_candidates": p.execute("SELECT COUNT(DISTINCT candidate_id) FROM promotions").fetchone()[0]}


def outbox(path, label):
    try:
        c = ro(path)
        return dict(Counter(f"{r[0]}|{r[1]}" for r in c.execute("SELECT destination, state FROM ops_notification_outbox")))
    except Exception as exc:  # noqa: BLE001
        return f"ERR {type(exc).__name__}"


out["outboxes"] = {"lab": outbox(R / "opportunity_research_notifications.db", "lab"),
                   "promotion_signal": outbox(R / "promotion_signal_notifications.db", "sig"),
                   "v2_release_ops": outbox(REPO / "v2_release_rc1_notifications.db", "v2"),
                   "shared_notifications": outbox(REPO / "notifications.db", "shared")}
PENDING = ("PENDING", "RETRY", "AMBIGUOUS", "FAILED")
out["pending_or_failed"] = {k: {s: v for s, v in (d.items() if isinstance(d, dict) else []) if s.split("|")[1] in PENDING}
                            for k, d in out["outboxes"].items()}

st = R / "sentinel_state.json"
det = json.loads(rt.execute("SELECT detail_json FROM components WHERE name='sentinel'").fetchone()[0] or "{}")
out["sentinel"] = {"enabled": det.get("enabled"), "mode": det.get("mutation_mode"), "handled": det.get("handled"),
                   "saved_offset": json.loads(st.read_text())["next_offset"] if st.exists() else None,
                   "ledger_lines": sum(1 for _ in (R / "sentinel_replies.jsonl").open(encoding="utf-8")) if (R / "sentinel_replies.jsonl").exists() else 0}
op = REPO / "operator_control.db"
if op.exists():
    c = ro(op)
    out["operator_control"] = {"exclusions": [dict(r) for r in c.execute("SELECT symbol, status, activation FROM symbol_exclusions")],
                               "universe": [dict(r) for r in c.execute("SELECT * FROM operator_universe")],
                               "audit_rows": c.execute("SELECT COUNT(*) FROM operator_audit").fetchone()[0]}
m = ro(R / "market.db")
ing = m.execute("SELECT window_id, symbols, cycle_utc FROM ingestion_state ORDER BY cycle_utc DESC LIMIT 1").fetchone()
out["provider"] = {"fetch_universe": dict(ing) if ing else None,
                   "sec_refresh_fp": out["components"].get("discovery", {}).get("config_fps", {}).get("SEC_CATALYST_CACHE")}

v = ro(REPO / "v2_release_rc1.db")
camp = dict(v.execute("SELECT campaign_id, strategy_version, config_fingerprint, execution_mode FROM campaign").fetchone())
s = json.loads((REPO / "v2_release_rc1_status.json").read_text())
out["v2"] = {**camp, "provider_fp": (s.get("price_provider_contract") or {}).get("contract_fingerprint"),
             "cash": v.execute("SELECT cash FROM portfolio WHERE id=1").fetchone()[0],
             "positions": v.execute("SELECT COUNT(*) FROM positions").fetchone()[0],
             "trades": v.execute("SELECT COUNT(*) FROM trades").fetchone()[0],
             "intents": v.execute("SELECT COUNT(*) FROM pending_entry_intents").fetchone()[0],
             "alert_outbox_rows": v.execute("SELECT COUNT(*) FROM v2_alert_outbox").fetchone()[0],
             "db_sha": hashlib.sha256((REPO / "v2_release_rc1.db").read_bytes()).hexdigest()[:16],
             "status_hb_age_s": age(s["heartbeat_utc"]), "status_tick": s.get("tick"),
             "eod_09_25_closed": (REPO / "results" / "prospective_2026-09-25" / "eod.json").exists()}

dbs = sorted(R.glob("*.db")) + [REPO / f for f in ("v2_release_rc1.db", "v2_release_rc1_notifications.db",
                                                   "notifications.db", "operator_control.db")]
dbs += [Path.home() / ".talonx" / f for f in ("eod_reconciliation.db", "ingestion_ledger.db", "paper_trading.db")]
out["db_integrity"] = {}
for d in dbs:
    if d.exists():
        try:
            out["db_integrity"][d.name] = ro(d).execute("PRAGMA quick_check").fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            out["db_integrity"][d.name] = f"ERR {type(exc).__name__}"

try:
    import psutil
    procs = []
    for pr in psutil.process_iter(["pid", "ppid", "name", "cmdline"]):
        cl = " ".join(pr.info.get("cmdline") or [])
        if pr.info.get("name", "").lower().startswith("python") and any(
                k in cl for k in ("talonx", "run_talonx", "dashboard_web")):
            procs.append({"pid": pr.info["pid"], "ppid": pr.info["ppid"], "cmd": cl[-90:]})
    out["processes"] = procs
    out["process_count"] = len(procs)
    from talonx_ops.prospective.telegram_owner import logical_poller_report
    pr_ = logical_poller_report().to_dict()
    out["pollers"] = {k: pr_[k] for k in ("verdict", "roles", "healthy")}
except Exception as exc:  # noqa: BLE001
    out["processes_error"] = repr(exc)
print(json.dumps(out, indent=1, default=str))
