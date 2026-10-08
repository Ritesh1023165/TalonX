"""One-off, READ-ONLY morning checkpoint (scheduled 2026-10-08 08:30Z = 09:30 BST). Writes local status only:
results/overnight_20261008/morning_checkpoint.json. It never restarts, sends, evaluates research, edits ledgers or reads
blinded forward outcome files (only forward_runs/<day>.json structured status fields)."""
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCHEDULED = datetime(2026, 10, 8, 8, 30, tzinfo=timezone.utc)
OUT = Path(__file__).with_name("morning_checkpoint.json")


def q(db, sql, a=()):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def safe(f):
    try:
        return f()
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)[:200]}


while datetime.now(timezone.utc) < SCHEDULED:
    time.sleep(30)
now = datetime.now(timezone.utc)
o = REPO / "results" / "opportunity"
rep = {"scheduled_utc": SCHEDULED.isoformat(), "actual_utc": now.isoformat(),
       "late_seconds": round((now - SCHEDULED).total_seconds(), 1)}
rep["late_flag"] = rep["late_seconds"] > 600


def fwd():
    d = json.loads((REPO / "results/v2_validation/forward_runs/2026-10-08.json").read_text(encoding="utf-8"))
    return {k: d.get(k) for k in ("run_id", "day", "cutoffs", "scheduled_utc", "started_utc", "ended_utc",
                                  "deadline_utc", "state", "failed_stage", "error_class", "runner_version")} | {
        "artifact": {k: (d.get("artifact") or {}).get(k) for k in ("path", "validated", "problems")},
        "stages": [{k: s.get(k) for k in ("name", "state", "retries", "exit_code", "started_utc", "ended_utc")}
                   for s in d.get("stages", [])]}


rep["v2_forward_2026_10_08"] = safe(fwd)
rep["promotion_control"] = safe(lambda: {k: json.loads((o / "control/promotion_signal_delivery.json").read_text())
                                         .get(k) for k in ("paused", "delivery_mode", "delivery_boundary_utc")})
rep["promotion_component"] = safe(lambda: q(o / "runtime.db", "SELECT pid, state, version, heartbeat_utc, "
                                            "config_fps_json FROM components WHERE name='promotion'"))
rep["components"] = safe(lambda: q(o / "runtime.db", "SELECT name, state, heartbeat_utc FROM components"))
rep["component_errors_since_restore"] = safe(lambda: q(o / "runtime.db", "SELECT event, COUNT(*) FROM component_events "
                                                       "WHERE at_utc > '2026-10-07T22:43' GROUP BY 1"))
rep["outbox"] = safe(lambda: q(o / "promotion_signal_notifications.db",
                               "SELECT event_type, state, COUNT(*) FROM ops_notification_outbox GROUP BY 1,2"))
rep["outbox_after_restore"] = safe(lambda: q(o / "promotion_signal_notifications.db",
                                             "SELECT COUNT(*) FROM ops_notification_outbox WHERE created_at_utc > "
                                             "'2026-10-07T22:42:55+00:00'"))
rep["paused_rows_changed"] = safe(lambda: q(o / "promotion.db", "SELECT COUNT(*) FROM promotions WHERE "
                                            "reason_code='SIGNAL_DELIVERY_PAUSED' AND state!='PROMOTED_SHADOW'"))
rep["promotions_after_restore"] = safe(lambda: q(o / "promotion.db", "SELECT state, reason_code, COUNT(*) FROM promotions "
                                                 "WHERE queued_utc > '2026-10-07T22:42:55+00:00' GROUP BY 1,2"))
vr = REPO / "results" / "vr_paper" / "vr_live.db"
rep["vr_heartbeat"] = safe(lambda: q(vr, "SELECT at_utc, detail_json FROM heartbeat"))
rep["vr_trades_after_pause"] = safe(lambda: q(vr, "SELECT COUNT(*) FROM trades WHERE created_utc > '2026-10-07T11:25:41'"))
rep["vr_open"] = safe(lambda: q(vr, "SELECT paper_mode, COUNT(*) FROM trades WHERE state='OPEN' GROUP BY 1"))
rep["dtu_sweeps_after_endpoint"] = safe(lambda: q(REPO / "results/dtu_shadow/shadow.db", "SELECT COUNT(*), MAX(at_utc) "
                                                  "FROM sweeps WHERE at_utc >= '2026-10-08T00:15'"))
rep["intel_last_poll"] = safe(lambda: (Path.home() / ".talonx/intelligence/poll_history.jsonl").read_text(
    encoding="utf-8").strip().splitlines()[-1][:300])
rep["v2_status"] = safe(lambda: {k: json.loads((REPO / "v2_release_rc1_status.json").read_text()).get(k) for k in
                                 ("heartbeat_utc", "data_state", "execution_scope_count", "open_positions",
                                  "entries_this_tick")})
try:
    import psutil
    names = {"promotion": "component promotion", "vr": "vr_live run", "dtu": "talonx_shadow.dtu run",
             "v2": "talonx_v2.run", "intel": "intelligence.service poll", "dashboard": "dashboard_web.py",
             "forward": "forward_runner"}
    rep["processes"] = {k: sorted(p.info["pid"] for p in psutil.process_iter(["pid", "cmdline"])
                                  if v in " ".join(p.info["cmdline"] or [])) for k, v in names.items()}
except Exception as exc:  # noqa: BLE001
    rep["processes"] = {"error": repr(exc)}
OUT.write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
