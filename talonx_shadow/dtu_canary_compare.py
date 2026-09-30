"""DTU live-canary comparison (READ-ONLY): PRODUCTION DTU active set vs SHADOW expected active set, per window.

Once DTU is ACTIVE, production no longer evaluates inactive symbols, so the full-universe reference comes from the
shadow collector's universe-wide delayed_sip sweep (it keeps running unchanged):
  * CORE        production dtu_snapshot ACTIVE_CORE vs shadow snapshot is_shadow_core (must be identical)
  * PROMOTIONS  production GAP promotions vs shadow GAP_TRIGGER promotions (first times, per symbol)
  * COVERAGE    every V1-eligible >= 3 % gapper the shadow saw (the pre-condition of ANY setup): was the symbol in
                production's active set by the next production scan?  -> SAME_SCAN / ONE_SCAN_LATE / MISSED
  * EVENTS      production setups / Signals / movers: symbol active (production) at the decision time
usage: python -m talonx_shadow.dtu_canary_compare WINDOW_ID"""
from __future__ import annotations

import bisect
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / "results" / "opportunity"


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def active_timeline(m, wid):
    """[(cycle_utc, set)] from production dtu_active (symbols stored when the set changes)."""
    out, cur = [], None
    for r in m.execute("SELECT cycle_utc, symbols_json, fallback_reason FROM dtu_active WHERE window_id=? ORDER BY "
                       "cycle_utc", (wid,)):
        if r["symbols_json"] is not None:
            cur = set(json.loads(r["symbols_json"]))
        if cur is not None:
            out.append((r["cycle_utc"], cur, r["fallback_reason"]))
    return out


def active_at(tl, t):
    i = bisect.bisect_right([x[0] for x in tl], t) - 1
    return tl[i][1] if i >= 0 else set()


def main(wid: str) -> dict:
    m, o, sh = ro(LIVE / "market.db"), ro(LIVE / "opportunity.db"), ro(REPO / "results" / "dtu_shadow" / "shadow.db")
    tl = active_timeline(m, wid)
    if not tl:
        return {"window_id": wid, "status": "NO_PRODUCTION_DTU_DATA"}
    pcore = {r[0] for r in m.execute("SELECT symbol FROM dtu_snapshot WHERE window_id=? AND state='ACTIVE_CORE'", (wid,))}
    score = {r[0] for r in sh.execute("SELECT symbol FROM snapshot WHERE window_id=? AND is_shadow_core=1", (wid,))}
    pg = {r[0]: r[1] for r in m.execute("SELECT symbol, started_utc FROM dtu_promotions WHERE window_id=? AND "
                                        "reason='GAP_TRIGGER'", (wid,))}
    sg = {r[0]: r[1] for r in sh.execute("SELECT symbol, first_at_utc FROM promotions WHERE window_id=? AND "
                                         "reason='GAP_TRIGGER'", (wid,))}
    scans = [r[0] for r in o.execute("SELECT decision_utc FROM scans WHERE window_id=? AND state='SCANNED' ORDER BY "
                                      "decision_utc", (wid,))]
    v1 = {r[0] for r in sh.execute("SELECT symbol FROM snapshot WHERE window_id=? AND v1_floor_eligible=1", (wid,))}
    cov = {"SAME_SCAN": 0, "ONE_SCAN_LATE": 0, "MISSED": 0}
    missed = []
    for s, t in sh.execute("SELECT symbol, at_utc FROM first_cross WHERE window_id=? AND threshold=3.0", (wid,)):
        if s not in v1 or t < tl[0][0]:
            continue
        i = bisect.bisect_left(scans, t)
        nxt = scans[i] if i < len(scans) else None
        if nxt and s in active_at(tl, nxt):
            cov["SAME_SCAN"] += 1
        elif i + 1 < len(scans) and s in active_at(tl, scans[i + 1]):
            cov["ONE_SCAN_LATE"] += 1
        else:
            cov["MISSED"] += 1
            missed.append((s, t))
    ev = {}
    for name, q in (("setups", "SELECT symbol, at_utc FROM candidate_events WHERE window_id=? AND event_type IN "
                               "('NEW','UPGRADE') AND to_state IN ('BULLISH_SETUP','BEARISH_SETUP')"),):
        rows = o.execute(q, (wid,)).fetchall()
        ev[name] = {"total": len(rows), "active_at_decision": sum(1 for s, t in rows if s in active_at(tl, t))}
    out = {"window_id": wid, "production_cycles": len(tl), "fallback_cycles": sum(1 for x in tl if x[2]),
           "core_identical": pcore == score, "core_diff": sorted(pcore ^ score)[:20],
           "gap_promotions": {"production": len(pg), "shadow": len(sg), "only_production": sorted(set(pg) - set(sg))[:20],
                              "only_shadow": sorted(set(sg) - set(pg))[:20]},
           "gapper_coverage_ge3pct": cov, "gapper_missed": missed[:30], "events": ev,
           "effective_active_median": sorted(len(x[1]) for x in tl)[len(tl) // 2],
           "effective_active_peak": max(len(x[1]) for x in tl)}
    out["UNEXPLAINED_DIFFERENCES"] = (not out["core_identical"]) or bool(missed)
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main(sys.argv[1])
