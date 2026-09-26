"""P0 package 1 LIVE acceptance (read-only). Evaluates every discovery scan after the SEC DATA_FIX boundary and the
notifier reserve state for one window.

usage: python live_acceptance.py <window_id YYYY-MM-DD> [--warmup N]   -> JSON on stdout

SEC steady-state criteria (after the first N data-bearing scans, default 2):
  heavy-scan p90 < 120 s | 0 skipped 300 s slots | cache-hit wait p99 < 2 s | max served age < 600 s |
  SEC request rate < 5/s | no provider-incomplete | cursor lag 0.  (category G: run the full-day missed-mover audit.)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(r"C:\workspace\TalonX")
R = REPO / "results" / "opportunity"


def ro(name):
    c = sqlite3.connect(f"file:{R / name}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))] if xs else None


def main(wid, warmup=2):
    o, rt, n = ro("opportunity.db"), ro("runtime.db"), ro("notification.db")
    b = rt.execute("SELECT deployment_id, at_utc, classification, decided_by, config_fps_json FROM deployment_events "
                   "WHERE component='discovery' AND config_fps_json LIKE '%SEC_CATALYST_CACHE%' ORDER BY at_utc DESC "
                   "LIMIT 1").fetchone()
    since = b["at_utc"] if b else "9999"
    scans = [dict(r) for r in o.execute("SELECT decision_utc, data_as_of_utc, phase, state, duration_s, funnel_json "
                                        "FROM scans WHERE window_id=? AND decision_utc>=? ORDER BY decision_utc",
                                        (wid, since))]
    data = [s for s in scans if s["state"] == "SCANNED"]
    rows = []
    for s in data:
        f = json.loads(s["funnel_json"] or "{}")
        sc = f.get("sec_cache") or {}
        st = datetime.fromisoformat(s["decision_utc"])
        rows.append({"start": s["decision_utc"][11:19], "end": (st + timedelta(seconds=s["duration_s"] or 0)).strftime("%H:%M:%S"),
                     "duration_s": s["duration_s"], "phase": s["phase"], "data_as_of": (s["data_as_of_utc"] or "")[11:16],
                     "scored": f.get("SCORED"), "provider_incomplete": f.get("PROVIDER_INCOMPLETE"), **{
                         k: sc.get(k) for k in ("mode", "lookups", "cache_hits", "cache_misses", "sync_fallbacks",
                                                "hit_wait_p99_s", "hit_wait_max_s", "max_served_age_s", "sec_requests",
                                                "sec_request_rate_per_s", "refresher_requests_during_scan",
                                                "refresher_yields")}})
    steady = rows[warmup:]
    starts = {datetime.fromisoformat(s["decision_utc"]).replace(second=0, microsecond=0) for s in scans}
    skipped = []
    five = [s for s in scans if s["phase"] in ("REGULAR", "AFTER_HOURS")]
    if five:
        t = datetime.fromisoformat(five[0]["decision_utc"]).replace(second=0, microsecond=0)
        t = t.replace(minute=t.minute - t.minute % 5)
        end = datetime.fromisoformat(five[-1]["decision_utc"])
        while t <= end:
            if t not in starts:
                skipped.append(t.strftime("%H:%M"))
            t += timedelta(minutes=5)
    dur = [r["duration_s"] for r in steady if r["duration_s"] is not None]
    waits = [r["hit_wait_p99_s"] for r in steady if r["hit_wait_p99_s"] is not None]
    ages = [r["max_served_age_s"] for r in steady if r["max_served_age_s"] is not None]
    rates = [r["sec_request_rate_per_s"] for r in steady if r["sec_request_rate_per_s"] is not None]
    crit = {"heavy_scan_p90_lt_120s": (pct(dur, .9) is not None and pct(dur, .9) < 120),
            "no_skipped_slots": not skipped,
            "cache_hit_wait_p99_lt_2s": bool(waits) and max(waits) < 2,
            "max_served_age_lt_600s": bool(ages) and max(ages) < 600,
            "sec_rate_lt_5_per_s": bool(rates) and max(rates) < 5,
            "no_provider_incomplete": all(not r["provider_incomplete"] for r in rows)}
    seq = o.execute("SELECT MAX(seq) FROM candidate_events").fetchone()[0]
    lag = {"notifier": seq - n.execute("SELECT last_seq FROM cursor").fetchone()[0]}
    try:
        from talonx_opportunity.notifier import NOTIFY_POLICY_OVERRIDES, Notifier  # noqa: F401
        det = json.loads(rt.execute("SELECT detail_json FROM components WHERE name='notifier'").fetchone()[0] or "{}")
        reserve = det.get("after_hours_reserve")
    except Exception as exc:  # noqa: BLE001
        reserve = f"ERR {exc}"
    out = {"window": wid, "sec_boundary": dict(b) if b else None, "warmup": rows[:warmup], "steady_n": len(steady),
           "steady_duration": {"p50": pct(dur, .5), "p90": pct(dur, .9), "max": max(dur) if dur else None},
           "max_hit_wait_p99_s": max(waits) if waits else None, "max_served_age_s": max(ages) if ages else None,
           "max_sec_rate": max(rates) if rates else None,
           "sync_fallbacks_steady": sum(r["sync_fallbacks"] or 0 for r in steady),
           "skipped_slots": skipped, "criteria": crit, "cursor_lag": lag, "after_hours_reserve": reserve,
           "VERDICT": "ACCEPTED" if steady and all(crit.values()) else "NOT_ACCEPTED" if steady else "NO_LIVE_SCANS_YET",
           "scans": rows}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0], int(a[a.index("--warmup") + 1]) if "--warmup" in a else 2)
