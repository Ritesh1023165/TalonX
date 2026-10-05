"""ERM nominee -- adjustment-factor lineage (DEVELOPMENT archive only; no returns).

factor(t) = ALL price / RAW price on the same bar (open at entry, close at exit). A factor that differs between entry
and exit means a provider adjustment (split / dividend / spin-off) with ex-date inside (entry, exit]. Only the RATIO of
two price series observed at the SAME timestamp is used; no price is differenced across time.

Model test (multiplicative vs subtractive dividend adjustment): on runs of consecutive sessions without any factor
event, a multiplicative adjustment keeps ALL/RAW constant while RAW-ALL moves with the price; a subtractive one keeps
RAW-ALL constant while ALL/RAW moves.

Output: results/erm_nominee_audit/{adjustment_events.csv, adjustment_summary.json}
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))
from research.common.locked_range_guard import EVENT_RESPONSE_MAP_V1, LockedRangeGuard  # noqa: E402
from research.event_response_map_v1 import data as D  # noqa: E402

ERM = Path(r"C:\workspace\TalonX-erm\results\event_response_map_v1")
OUT = HERE / "results" / "erm_nominee_audit"
REL = 1e-4          # factor change threshold (relative); cent rounding of raw bars >= $5 is <= 0.1 % per price, so
                    # factor noise on one bar is bounded and flagged separately as NOISE_BAND below


def main():
    pop = list(csv.DictReader(open(OUT / "lineage_events.csv", encoding="utf-8")))
    syms = sorted({r["symbol"] for r in pop})
    guard = LockedRangeGuard(EVENT_RESPONSE_MAP_V1)
    a, _ = D.load(ERM / "_archive" / "alpaca", purpose="RETURNS", guard=guard)
    r, _ = D.load(ERM / "_archive" / "alpaca", purpose="ELIGIBILITY_ONLY", guard=guard)
    a, r = a[a["symbol"].isin(syms)], r[r["symbol"].isin(syms)]
    m = a.merge(r, on=["symbol", "date"], suffixes=("_a", "_r"))
    ca = json.loads((ERM / "ca_audit_v2_development.json").read_text())["events"]
    ca_by = {}
    for e in ca:
        ca_by.setdefault(e["symbol"], []).append((e["ex_date"], e["type"]))
    key = {(s, str(d)): (oa, ora, ca_, cr) for s, d, oa, ora, ca_, cr in
           zip(m["symbol"], m["date"], m["open_a"], m["open_r"], m["close_a"], m["close_r"])}
    rows, cls = [], Counter()
    for e in pop:
        if e["status"] in ("BEYOND_DEV_END", "DATA_MISSING_ENTRY"):
            continue
        s, ent, ex = e["symbol"], e["entry"], e["exit"]
        k0, k1 = key.get((s, ent)), key.get((s, ex))
        if not k0 or not k1 or not k0[1] or not k1[3]:
            c = "NO_RAW_PAIR"
            f0 = f1 = None
        else:
            f0, f1 = k0[0] / k0[1], k1[2] / k1[3]
            ch = abs(f1 / f0 - 1)
            acts = [t for x, t in ca_by.get(s, []) if ent < x <= ex]
            if ch <= REL:
                c = "NO_ADJUSTMENT_IN_WINDOW"
            elif acts:
                c = "LISTED_" + "+".join(sorted(set(acts))).upper()
            elif ch <= 2e-3:
                c = "SMALL_UNLISTED_FACTOR_CHANGE_<=0.2pct (dividend or raw cent-rounding noise)"
            else:
                c = "UNLISTED_FACTOR_CHANGE_>0.2pct (dividend/special distribution/other, not in CA metadata)"
        cls[c] += 1
        rows.append({"symbol": s, "entry": ent, "exit": ex, "status": e["status"], "factor_entry": f0,
                     "factor_exit": f1, "class": c})
    # model test on long no-event runs
    mult_stable = sub_stable = tested = 0
    for s, g in m.sort_values(["symbol", "date"]).groupby("symbol"):
        f = (g["close_a"] / g["close_r"]).to_numpy()
        dlt = (g["close_r"] - g["close_a"]).to_numpy()
        px = g["close_r"].to_numpy()
        for i in range(1, len(f)):
            if f[i - 1] > 0.97 or abs(px[i] / px[i - 1] - 1) < 0.02:   # need a material factor and a price move
                continue
            tested += 1
            mult_stable += int(abs(f[i] / f[i - 1] - 1) < 2e-3)
            sub_stable += int(abs(dlt[i] - dlt[i - 1]) < 0.011)
    summ = {"events_checked": len(rows), "classes": dict(cls),
            "model_test": {"pairs_tested (factor<0.97, |raw move|>=2%)": tested,
                           "ratio_stable (multiplicative)": mult_stable, "difference_stable (subtractive)": sub_stable}}
    with open(OUT / "adjustment_events.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (OUT / "adjustment_summary.json").write_text(json.dumps(summ, indent=1, default=int))
    print(json.dumps(summ, indent=1, default=int))


if __name__ == "__main__":
    main()
