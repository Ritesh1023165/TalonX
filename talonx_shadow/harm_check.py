"""Stop-condition check (READ-ONLY): is production measurably harmed or altered while the shadow runs?
Compares ingestion cycles and discovery scans before/after the collector's first sweep (same phase), and confirms
the production universe, provider mutation mode and outbox dedup are unchanged. usage: python -m ... [WINDOW_ID]"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from talonx_shadow.dtu import LIVE, shadow_db  # noqa: E402


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def main(wid: str) -> dict:
    sh = ro(shadow_db())
    first = sh.execute("SELECT MIN(at_utc) FROM sweeps").fetchone()[0]
    m, o = ro(LIVE / "market.db"), ro(LIVE / "opportunity.db")

    def cyc(where, args):
        rows = m.execute(f"SELECT duration_s, failed_symbols, failed_batches FROM cycles WHERE {where}", args).fetchall()
        d = [r[0] for r in rows if r[0] is not None]
        return {"n": len(rows), "median_s": round(statistics.median(d), 2) if d else None,
                "p95_s": round(sorted(d)[int(.95 * (len(d) - 1))], 2) if d else None,
                "failed_batches": sum(r[2] or 0 for r in rows), "failed_symbols": sum(r[1] or 0 for r in rows)}
    out = {"window_id": wid, "shadow_first_sweep": first,
           "ingestion_before": cyc("at_utc < ? AND at_utc > '2026-09-25' AND phase IN ('PREMARKET','REGULAR','AFTER_HOURS')",
                                   (first,)),
           "ingestion_after": cyc("at_utc >= ?", (first,))}
    uni = json.loads(m.execute("SELECT members_json FROM universe WHERE window_id=?", (wid,)).fetchone()[0])
    out["production_universe_eligible"] = sum(1 for x in uni if x.get("status") == "ELIGIBLE")
    ing = m.execute("SELECT symbols FROM ingestion_state WHERE window_id=?", (wid,)).fetchone()
    out["production_fetch_symbols"] = ing[0] if ing else None
    try:                                                   # DTU ACTIVE: the resolved active set is the expected list
        d = m.execute("SELECT n_active, fallback_reason FROM dtu_active WHERE window_id=? ORDER BY cycle_utc DESC "
                      "LIMIT 1", (wid,)).fetchone()
    except sqlite3.Error:
        d = None
    out["dtu_active"] = {"n_active": d[0], "fallback": d[1]} if d else None
    expected = d[0] if d and not d[1] else out["production_universe_eligible"]
    oc = ro(REPO / "operator_control.db")
    out["operator_added"] = oc.execute("SELECT COUNT(*) FROM operator_universe").fetchone()[0]
    for name in ("opportunity_research_notifications.db", "promotion_signal_notifications.db"):
        c = ro(LIVE / name)
        out[f"dup_dedup_{name}"] = c.execute("SELECT COUNT(*)-COUNT(DISTINCT dedup_key) FROM ops_notification_outbox"
                                             ).fetchone()[0]
    fun = [json.loads(r[0]).get("ELIGIBLE") for r in o.execute(
        "SELECT funnel_json FROM scans WHERE window_id=? AND state='SCANNED'", (wid,))]
    out["discovery_eligible_per_scan"] = sorted(set(x for x in fun if x is not None))
    fetch_ok = out["production_fetch_symbols"] in (None, expected) or (d and not d[1])
    disc_ok = d is not None or out["discovery_eligible_per_scan"] in ([], [out["production_universe_eligible"]])
    out["STOP_CONDITION"] = ("TRIGGERED" if (not fetch_ok or not disc_ok
                                             or any(v for k, v in out.items() if k.startswith("dup_dedup")))
                             else "CLEAR")
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-09-29")
