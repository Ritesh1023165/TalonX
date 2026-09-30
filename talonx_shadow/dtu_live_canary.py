"""DTU live canary checkpoint (READ-ONLY). MEASURED workload after activation vs the same clock interval of the
previous full-universe session, SEC observability, shadow-referenced coverage, Signals by DTU state at decision.
usage: python -m talonx_shadow.dtu_live_canary WINDOW_ID ACTIVATION_UTC [BASELINE_WINDOW_ID]"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
LIVE = REPO / "results" / "opportunity"


def ro(p):
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def shift(t: str, days: int) -> str:
    return (datetime.fromisoformat(t) - timedelta(days=days)).isoformat()


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def pct(a, b):
    return round(100 * (1 - a / b), 1) if a is not None and b else None


def main(wid: str, act: str, base_wid: str | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    m, o = ro(LIVE / "market.db"), ro(LIVE / "opportunity.db")
    base_wid = base_wid or "2026-09-29"
    days = (datetime.fromisoformat(wid) - datetime.fromisoformat(base_wid)).days
    b0, b1 = shift(act, days), shift(now, days)          # the same clock interval on the baseline session
    cyc = lambda w, a, b: [dict(r) for r in m.execute(  # noqa: E731
        "SELECT * FROM cycles WHERE window_id=? AND at_utc>=? AND at_utc<? AND as_of_utc IS NOT NULL", (w, a, b))]
    post, base = cyc(wid, act, now), cyc(base_wid, b0, b1)
    scans = lambda w, a, b: [dict(r) for r in o.execute(  # noqa: E731
        "SELECT decision_utc, phase, duration_s, funnel_json FROM scans WHERE window_id=? AND state='SCANNED' AND "
        "decision_utc>=? AND decision_utc<?", (w, a, b))]
    sp, sb = scans(wid, act, now), scans(base_wid, b0, b1)
    fs = lambda rows, k: [(json.loads(r["funnel_json"] or "{}").get("sec_cache") or {}).get(k) for r in rows]  # noqa
    elig = lambda rows: [json.loads(r["funnel_json"] or "{}").get("ELIGIBLE") for r in rows]  # noqa: E731
    act_rows = [dict(r) for r in m.execute("SELECT cycle_utc, n_active, counts_json, fallback_reason FROM dtu_active "
                                           "WHERE window_id=? AND cycle_utc>=?", (wid, act))]
    counts = json.loads(act_rows[-1]["counts_json"]) if act_rows else {}
    sweeps = [dict(r) for r in m.execute("SELECT * FROM dtu_sweeps WHERE window_id=? AND at_utc>=?", (wid, act))]
    bars_post = sum(r["bars"] or 0 for r in post) / max(1, len(post))
    bars_base = sum(r["bars"] or 0 for r in base) / max(1, len(base))
    out = {"TIME_UTC": now, "window": wid, "activation_utc": act, "baseline": f"{base_wid} {b0[11:16]}-{b1[11:16]}Z",
           "DTU_COUNTS_NOW": counts, "EFFECTIVE_ACTIVE_MEDIAN": med([r["n_active"] for r in act_rows]),
           "EFFECTIVE_ACTIVE_PEAK": max((r["n_active"] for r in act_rows), default=None),
           "fallback_cycles": sum(1 for r in act_rows if r["fallback_reason"]),
           "FULL_BASELINE_SYMBOLS": med([r["fetched_symbols"] for r in base]) or 5650,
           "ACTIVE_SYMBOLS_FETCHED_MEDIAN": med([r["fetched_symbols"] for r in post]),
           "BAR_ROWS_PER_CYCLE": {"post": round(bars_post, 1), "baseline": round(bars_base, 1),
                                  "reduction_pct (activity differs by day)": pct(bars_post, bars_base)},
           "SYMBOL_FETCH_REDUCTION_PCT": pct(med([r["fetched_symbols"] for r in post]),
                                             med([r["fetched_symbols"] for r in base]) or 5650),
           "INGESTION_CYCLE_S": {"post_median": med([r["duration_s"] for r in post]),
                                 "baseline_median": med([r["duration_s"] for r in base])},
           "DISCOVERY": {"post_scans": len(sp), "baseline_scans": len(sb),
                         "evaluated_median": {"post": med(elig(sp)), "baseline": med(elig(sb))},
                         "scan_s_median": {"post": med([r["duration_s"] for r in sp]),
                                           "baseline": med([r["duration_s"] for r in sb])},
                         "sec_lookups_per_scan": {"post": med(fs(sp, "lookups")), "baseline": med(fs(sb, "lookups"))},
                         "SEC_LOOKUP_REDUCTION_PCT": pct(med(fs(sp, "lookups")), med(fs(sb, "lookups")))},
           "SEC": {"max_served_age_raw": max([x for x in fs(sp, "max_served_age_raw") if x is not None], default=None),
                   "p99_max": max([x for x in fs(sp, "served_age_p99_raw") if x is not None], default=None),
                   "count_ge_600": sum(x or 0 for x in fs(sp, "count_age_ge_600")),
                   "stale_fallbacks": sum(x or 0 for x in fs(sp, "stale_fallback_count")),
                   "request_rate_max": max([x for x in fs(sp, "sec_request_rate_per_s") if x is not None], default=None)},
           "EVENT_SWEEP": {"sweeps": len(sweeps), "requests_median": med([s["requests"] for s in sweeps]),
                           "duration_p50": med([s["duration_s"] for s in sweeps]),
                           "duration_p95": sorted(s["duration_s"] for s in sweeps)[int(.95 * (len(sweeps) - 1))]
                           if sweeps else None, "symbols_median": med([s["symbols"] for s in sweeps]),
                           "gap_promotions": sum(s["gap_promotions"] or 0 for s in sweeps),
                           "sec8k_promotions": sum(s["sec8k_promotions"] or 0 for s in sweeps),
                           "errors": sum(1 for s in sweeps if s["errors"])}}
    from talonx_shadow import dtu_canary_compare as CC
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        cmp_ = CC.main(wid)
    out["COVERAGE_VS_SHADOW"] = {k: cmp_.get(k) for k in ("core_identical", "gapper_coverage_ge3pct", "gapper_missed",
                                                           "gap_promotions", "UNEXPLAINED_DIFFERENCES")}
    ev = [dict(r) for r in o.execute("SELECT symbol, event_type, to_state, at_utc FROM candidate_events WHERE window_id=? "
                                     "AND at_utc>=?", (wid, act))]
    out["EVENTS_POST"] = {"total": len(ev), "setups": sum(1 for e in ev if e["event_type"] in ("NEW", "UPGRADE") and
                                                         e["to_state"] in ("BULLISH_SETUP", "BEARISH_SETUP"))}
    p = ro(LIVE / "promotion.db")
    sigs = [dict(r) for r in p.execute("SELECT promotion_id, symbol, score, event_utc FROM promotions WHERE window_id=? "
                                       "AND state='PROMOTED_SIGNAL' AND event_utc>=?", (wid, act))]
    from talonx_paperperf.signal_forensics import production_dtu_state
    st = production_dtu_state(wid, sigs)
    by = {}
    for s in sigs:
        k = st.get(s["promotion_id"], "UNKNOWN").split(":")[0]
        by[k] = by.get(k, 0) + 1
    out["SIGNALS_POST"] = {"total": len(sigs), "by_dtu_state_at_decision": by,
                           "80_plus": sum(1 for s in sigs if (s["score"] or 0) >= 80),
                           "unexplained": [s["symbol"] for s in sigs if st.get(s["promotion_id"]) ==
                                           "PROTECTED_OR_UNEXPLAINED"]}
    print(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    main(*sys.argv[1:4])
