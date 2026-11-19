"""READ-ONLY preview of capping Opportunity Engine new-opportunity admission at the top-N qualifying names by the SAME
live ADV20 the DTU_V2 floor already uses (2026-10-08 overnight task). No config change, no deployment, no returns.

Source: market.db (mode=ro) tables dtu_snapshots / dtu_snapshot / universe / dtu_active / cycles / dtu_sweeps.
Under DTU_V2_LIVE_FLOOR, rows in state ACTIVE_CORE or EVENT_ELIGIBLE are exactly the names passing both live floors
(close >= $5, ADV20 >= $20M, all 20 sessions valid, plus the V1 structural/floor rules); ``core_rank`` is their rank by
live ADV20 descending with ties broken by symbol ascending (universe_tiers.classify_members). Cap N = core_rank <= N.
usage: python universe_cap_preview.py OUT_DIR WINDOW [WINDOW ...]
"""
import csv
import json
import sqlite3
import statistics
import sys
from pathlib import Path

REPO = next(p for p in Path(__file__).resolve().parents if (p / "talonx_opportunity").is_dir())
CAPS = (500, 600, 700)


def q(c, sql, a=()):
    return c.execute(sql, a).fetchall()


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * (len(xs) - 1)))] if xs else None


def main(out: Path, windows: list[str]) -> dict:
    c = sqlite3.connect(f"file:{REPO / 'results/opportunity/market.db'}?mode=ro", uri=True)
    res = {"source": "results/opportunity/market.db (mode=ro)", "windows": {}}
    members = {}
    for w in windows:
        snap = q(c, "SELECT snapshot_version, reference_session, created_utc, core_size, counts_json, policy_fp "
                    "FROM dtu_snapshots WHERE window_id=?", (w,))
        if not snap:
            res["windows"][w] = {"status": "NO_SNAPSHOT"}
            continue
        sv, ref, created, core, counts, fp = snap[0]
        rows = q(c, "SELECT symbol, state, core_rank, price, adv20, cik FROM dtu_snapshot WHERE window_id=? AND "
                    "state IN ('ACTIVE_CORE','EVENT_ELIGIBLE') ORDER BY core_rank", (w,))
        ranks = [r[2] for r in rows]
        assert ranks == list(range(1, len(rows) + 1)), "core_rank must be dense 1..n"
        exch = {m["symbol"]: m.get("exchange") for m in json.loads(q(c, "SELECT members_json FROM universe WHERE "
                                                                       "window_id=?", (w,))[0][0])}
        wr = {"snapshot_version": sv, "reference_session": ref, "snapshot_created_utc": created, "policy_fp": fp,
              "snapshot_counts": json.loads(counts), "current_core_size": core,
              "qualifying_both_floors": len(rows), "current_admissible": len(rows), "caps": {}}
        ties = sum(1 for a, b in zip(rows, rows[1:]) if a[4] == b[4])
        wr["exact_adv20_ties_adjacent"] = ties
        for n in CAPS + (core,):
            sel = rows[:n]
            if not sel:
                continue
            adv = [r[4] for r in sel]
            px = [r[3] for r in sel]
            ex = {}
            for r in sel:
                ex[exch.get(r[0]) or "UNKNOWN"] = ex.get(exch.get(r[0]) or "UNKNOWN", 0) + 1
            wr["caps"][str(n)] = {
                "selected": len(sel), "filled": len(sel) == n,
                "adv20_cutoff_usd": round(sel[-1][4]), "adv20_next_excluded_usd": round(rows[n][4]) if len(rows) > n else None,
                "cutoff_symbol": sel[-1][0],
                "adv20_usd": {"min": round(min(adv)), "p25": round(pct(adv, .25)), "median": round(statistics.median(adv)),
                              "p75": round(pct(adv, .75)), "max": round(max(adv))},
                "close_usd": {"min": round(min(px), 2), "p25": round(pct(px, .25), 2), "median": round(statistics.median(px), 2),
                              "p75": round(pct(px, .75), 2), "max": round(max(px), 2)},
                "price_buckets": {"5-10": sum(5 <= p < 10 for p in px), "10-20": sum(10 <= p < 20 for p in px),
                                  "20-50": sum(20 <= p < 50 for p in px), "50-200": sum(50 <= p < 200 for p in px),
                                  ">=200": sum(p >= 200 for p in px)},
                "exchange": ex, "sector": "UNKNOWN (no sector/SIC metadata stored for the OE universe)",
                "removed_vs_current_admissible": len(rows) - len(sel)}
        members[w] = [r[0] for r in rows]
        # workload: actual REGULAR ingestion cycles + DTU sweep cost for this window
        cyc = q(c, "SELECT fetched_symbols, batches, duration_s FROM cycles WHERE window_id=? AND phase='REGULAR'", (w,))
        if cyc:
            wr["observed_regular_cycles"] = {"n": len(cyc), "fetched_symbols_median": statistics.median(x[0] for x in cyc),
                                             "batches_median": statistics.median(x[1] for x in cyc),
                                             "duration_s_median": round(statistics.median(x[2] for x in cyc if x[2]), 2)}
        sw = q(c, "SELECT requests, duration_s FROM dtu_sweeps WHERE window_id=?", (w,))
        if sw:
            wr["dtu_event_sweep"] = {"n": len(sw), "requests_median": statistics.median(x[0] for x in sw)}
        act = q(c, "SELECT counts_json FROM dtu_active WHERE window_id=? ORDER BY cycle_utc", (w,))
        if act:
            cs = [json.loads(a[0]) for a in act]
            wr["effective_active"] = {"median": statistics.median(x.get("effective_active", 0) for x in cs),
                                      "max": max(x.get("effective_active", 0) for x in cs),
                                      "operator_added_median": statistics.median(x.get("OPERATOR_ADDED", 0) for x in cs),
                                      "event_promoted_median": statistics.median(x.get("EVENT_PROMOTED", 0) for x in cs)}
        res["windows"][w] = wr
    # turnover across consecutive available operational snapshots (membership only)
    ws = [w for w in windows if w in members]
    res["turnover"] = {}
    for a, b in zip(ws, ws[1:]):
        t = {}
        for n in CAPS:
            A, B = set(members[a][:n]), set(members[b][:n])
            t[str(n)] = {"entered": len(B - A), "left": len(A - B), "kept": len(A & B)}
        res["turnover"][f"{a}->{b}"] = t
    last = ws[-1] if ws else None
    if last:
        rank = {s: i + 1 for i, s in enumerate(members[last])}
        with (out / f"membership_{last}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["symbol", "adv20_rank", "in_top500", "in_top600", "in_top700"])
            for s in members[last]:
                w.writerow([s, rank[s], rank[s] <= 500, rank[s] <= 600, rank[s] <= 700])
    (out / "preview.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    print(json.dumps(main(out, sys.argv[2:]), indent=1)[:6000])
