"""Monday 2026-09-28 general health watcher (read-only).
PURPOSE: surface the first anomaly of the live session.
STOP: exits on the first NEW anomaly, or at --until (default 2026-09-29T00:15Z).
OUTPUT: stdout (task output) + appends every anomaly to results/monday_2026-09-28/watch_events.jsonl.
OWNER: Monday acceptance session (one instance only; re-armed by the operator after each exit).
Anomalies: component not UP/BUSY (60 s grace), poller verdict != EXPECTED_DISTINCT_POLLERS, notifier cursor lag > 300
for >= 2 checks, scan >= 240 s, skipped 300 s slot, new TICK_ERROR/CRASH, outbox FAILED/AMBIGUOUS, V2 status stale."""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
sys.path.insert(0, str(REPO))
R = REPO / "results" / "opportunity"
OUT = REPO / "results" / "monday_2026-09-28" / "watch_events.jsonl"
STATE = REPO / "results" / "monday_2026-09-28" / "watch_state.json"


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def check(prev: dict) -> tuple[list[str], dict]:
    from talonx_ops.opportunity_read import read_opportunity_status
    from talonx_ops.prospective.telegram_owner import logical_poller_report
    now = datetime.now(timezone.utc)
    an, st = [], {}
    s = read_opportunity_status()
    bad = [f"{c['component']}={c['health']}" for c in s["components"] if c["health"] not in ("UP", "BUSY_LONG_SCAN")]
    st["bad"] = bad
    if bad and prev.get("bad") == bad:
        an.append("COMPONENT_NOT_UP " + ",".join(bad))
    pr = logical_poller_report()
    if not pr.healthy:
        an.append(f"POLLER {pr.verdict} {pr.roles}")
    o, n = ro(R / "opportunity.db"), ro(R / "notification.db")
    lag = o.execute("SELECT MAX(seq) FROM candidate_events").fetchone()[0] - n.execute("SELECT last_seq FROM cursor").fetchone()[0]
    st["lag"] = lag
    if lag > 300 and prev.get("lag", 0) > 300:
        an.append(f"NOTIFIER_LAG {lag}")
    scans = o.execute("SELECT decision_utc, duration_s, phase, state FROM scans WHERE window_id='2026-09-28' "
                      "ORDER BY decision_utc").fetchall()
    seen = set(prev.get("seen_scans", []))
    for sc in scans:
        if sc["decision_utc"] in seen:
            continue
        if (sc["duration_s"] or 0) >= 240:
            an.append(f"SCAN_GE_240 {sc['decision_utc'][11:19]} {sc['duration_s']}s {sc['phase']}")
    st["seen_scans"] = [sc["decision_utc"] for sc in scans]
    # skipped 300 s slots (REGULAR/AFTER_HOURS only)
    starts = {datetime.fromisoformat(sc["decision_utc"]).replace(second=0, microsecond=0) for sc in scans}
    five = [sc for sc in scans if sc["phase"] in ("REGULAR", "AFTER_HOURS")]
    skipped = []
    if five:
        t = datetime.fromisoformat(five[0]["decision_utc"]).replace(second=0, microsecond=0)
        t = t.replace(minute=t.minute - t.minute % 5)
        end = datetime.fromisoformat(five[-1]["decision_utc"])
        while t <= end:
            if t not in starts:
                skipped.append(t.strftime("%H:%M"))
            t += timedelta(minutes=5)
    new_skips = [x for x in skipped if x not in prev.get("skipped", [])]
    if new_skips:
        an.append("SKIPPED_SLOT " + ",".join(new_skips))
    st["skipped"] = skipped
    rt = ro(R / "runtime.db")
    last_id = prev.get("err_id", rt.execute("SELECT COALESCE(MAX(id),0) FROM component_events").fetchone()[0])
    errs = rt.execute("SELECT id, component, event, detail_json FROM component_events WHERE id > ? AND event IN "
                      "('TICK_ERROR','CRASH','FORCE_KILLED','SUPERVISOR_RESTART')", (last_id,)).fetchall()
    for e in errs:
        an.append(f"{e['event']} {e['component']} {str(e['detail_json'])[:120]}")
    st["err_id"] = max([last_id] + [e["id"] for e in errs])
    for name, p in (("lab", R / "opportunity_research_notifications.db"), ("signal", R / "promotion_signal_notifications.db"),
                    ("v2", REPO / "v2_release_rc1_notifications.db")):
        k = ro(p).execute("SELECT COUNT(*) FROM ops_notification_outbox WHERE state IN ('FAILED','AMBIGUOUS') AND "
                          "created_at_utc >= '2026-09-28'").fetchone()[0]
        if k > prev.get(f"fail_{name}", 0):
            an.append(f"OUTBOX_FAILED {name} {k}")
        st[f"fail_{name}"] = k
    v2 = json.loads((REPO / "v2_release_rc1_status.json").read_text())
    age = (now - datetime.fromisoformat(v2["heartbeat_utc"])).total_seconds()
    if age > 180:
        an.append(f"V2_STALE {age:.0f}s")
    return an, st


def main(until: str):
    end = datetime.fromisoformat(until)
    prev = json.loads(STATE.read_text()) if STATE.exists() else {}
    while datetime.now(timezone.utc) < end:
        try:
            an, st = check(prev)
        except Exception as exc:  # noqa: BLE001
            print(f"WATCH_READ_ERROR {type(exc).__name__}: {exc}", flush=True)
            time.sleep(60)
            continue
        STATE.write_text(json.dumps(st))
        if an:
            rec = {"at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "anomalies": an}
            with OUT.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            print("ANOMALY " + json.dumps(rec), flush=True)
            return
        prev = st
        time.sleep(60)
    print("WATCH_UNTIL_REACHED", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[a.index("--until") + 1] if "--until" in a else "2026-09-29T00:15:00+00:00")
