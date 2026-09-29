"""Snapshot field contract check (READ-ONLY) -- what Alpaca ``delayed_sip`` snapshot fields mean vs V1's definitions,
per market phase, from the collector's ``verify`` sample (snapshot fields beside V1's aggregate + reference close).

Checks per phase:
  A  prevDailyBar.t date == V1 reference session, and prevDailyBar.c == V1 prev_close          (daily-bar semantics)
  B  dailyBar.t date (which session the snapshot's "today" bar is)
  C  latestTrade in the SAME minute as V1's last aggregate bar: |latestTrade.p - bar close| / close
     (V1 last price = last valid 1-min SIP bar close; the sweep uses latestTrade.p)
  D  latestTrade.t vs V1 ingestion as-of (the delayed feed's horizon vs V1's data horizon)
The sweep only uses latestTrade.p/t and V1's own prev_close, so A/B are informational; C/D decide the contract.
usage: python -m talonx_shadow.verify_contract [WINDOW_ID]"""
from __future__ import annotations

import collections as C
import json
import sqlite3
import statistics
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from talonx_opportunity.phases import trading_window  # noqa: E402
from talonx_shadow.dtu import shadow_db  # noqa: E402


def main(wid: str) -> dict:
    c = sqlite3.connect(f"file:{shadow_db()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    ref = trading_window(date.fromisoformat(wid)).reference_session.isoformat()
    rows = [dict(r) for r in c.execute("SELECT v.* FROM verify v JOIN sweeps s ON s.id=v.sweep_id WHERE s.window_id=?",
                                       (wid,))]
    out = {"window_id": wid, "reference_session": ref, "phases": {}}
    by = C.defaultdict(list)
    for r in rows:
        by[r["phase"]].append(r)
    for ph, rs in by.items():
        a_date = C.Counter((r["prev_t"] or "")[:10] == ref for r in rs if r["prev_t"])
        a_close = [abs(r["prev_c"] - r["v1_prev_close"]) / r["v1_prev_close"] for r in rs
                   if r["prev_c"] and r["v1_prev_close"] and (r["prev_t"] or "")[:10] == ref]
        b_date = C.Counter((r["daily_t"] or "")[:10] for r in rs if r["daily_t"])
        b_close = [abs(r["daily_c"] - r["v1_prev_close"]) / r["v1_prev_close"] for r in rs
                   if r["daily_c"] and r["v1_prev_close"] and (r["daily_t"] or "")[:10] == ref]
        same_min = [r for r in rs if r["lt_t"] and r["agg_last_t"] and r["lt_t"][:16] == r["agg_last_t"][:16]]
        c_dev = sorted(abs(r["lt_p"] - r["agg_last_c"]) / r["agg_last_c"] * 1e4 for r in same_min if r["agg_last_c"])
        d_lag = [(r["ing_as_of"][:16] >= r["lt_t"][:16]) for r in rs if r["lt_t"] and r["ing_as_of"]]
        out["phases"][ph] = {
            "samples": len(rs),
            "A_prevDailyBar_is_reference_session": dict(a_date),
            "A_prevDailyBar_close_eq_v1_prev_close_share": round(sum(x < 1e-9 for x in a_close) / len(a_close), 4)
            if a_close else None,
            "B_dailyBar_session_dates": dict(b_date),
            "B_dailyBar_close_eq_v1_prev_close_share_when_reference_session": round(
                sum(x < 1e-9 for x in b_close) / len(b_close), 4) if b_close else None,
            "C_same_minute_pairs": len(same_min),
            "C_latestTrade_vs_bar_close_bps_median": round(statistics.median(c_dev), 2) if c_dev else None,
            "C_bps_p95": round(c_dev[int(0.95 * (len(c_dev) - 1))], 2) if c_dev else None,
            "C_share_within_10bps": round(sum(x <= 10 for x in c_dev) / len(c_dev), 4) if c_dev else None,
            "D_latestTrade_not_newer_than_v1_asof_share": round(sum(d_lag) / len(d_lag), 4) if d_lag else None}
    ph = out["phases"]
    ok = bool(ph) and all(v["C_same_minute_pairs"] >= 20 and (v["C_share_within_10bps"] or 0) >= 0.95
                          for v in ph.values())
    out["phases_covered"] = sorted(ph)
    out["SNAPSHOT_FIELD_CONTRACT"] = ("VERIFIED" if ok and {"PREMARKET", "REGULAR", "AFTER_HOURS"} <= set(ph)
                                      else "VERIFIED_FOR_" + "+".join(sorted(ph)) if ok else "NOT_VERIFIED")
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-09-29")
