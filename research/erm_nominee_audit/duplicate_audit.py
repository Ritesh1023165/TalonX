"""ERM nominee -- duplicate-series audit (DEVELOPMENT archive; VOLUMES and dates only, no prices, no returns).

Two population rows with the same entry session are the SAME traded series observed twice iff their raw (as-traded)
VOLUME is identical and > 0 on each of D-1, D and the entry session, and on every session of the 20-session
eligibility window that both have. (Volume is an integer count of shares traded; identical volumes on 20+ sessions
for two different listings is not plausible.)

Output: results/erm_nominee_audit/duplicates.csv, duplicates_summary.json
"""
from __future__ import annotations

import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
ERM = Path(r"C:\workspace\TalonX-erm\results\event_response_map_v1")
OUT = HERE / "results" / "erm_nominee_audit"


def main():
    pop = list(csv.DictReader(open(OUT / "lineage_events.csv", encoding="utf-8")))
    syms = {r["symbol"] for r in pop}
    man = json.loads((ERM / "_archive/alpaca/manifest.json").read_text())
    vol = defaultdict(dict)
    for f in man["files"]:
        if f["purpose"] != "ELIGIBILITY_ONLY":
            continue
        b = json.loads(gzip.decompress((ERM / "_archive/alpaca" / f["file"]).read_bytes())).get("bars") or {}
        for s in syms & set(b):
            for x in b[s]:
                vol[s][x["t"][:10]] = x["v"]
    by_entry = defaultdict(list)
    for r in pop:
        by_entry[r["entry"]].append(r)
    sess = sorted({d for v in vol.values() for d in v})
    pos = {d: i for i, d in enumerate(sess)}
    groups = []
    for ent, rows in sorted(by_entry.items()):
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                if a["symbol"] == b["symbol"]:
                    continue
                va, vb = vol[a["symbol"]], vol[b["symbol"]]
                k = pos.get(a["gap_day"])
                win = sess[max(0, k - 19): k + 1] + [a["prev_session"], ent] if k is not None else []
                common = [d for d in set(win) if d in va and d in vb]
                same = bool(common) and all(va[d] == vb[d] for d in common) and \
                    all(va.get(d, 0) > 0 for d in (a["prev_session"], a["gap_day"], ent))
                if same:
                    groups.append({"entry": ent, "gap_day": a["gap_day"], "a": a["symbol"], "b": b["symbol"],
                                   "cik_a": a["cik"], "cik_b": b["cik"], "method_a": a["id_method"],
                                   "method_b": b["id_method"], "status_a": a["status"], "status_b": b["status"],
                                   "sessions_compared": len(common)})
    with open(OUT / "duplicates.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(groups[0]))
        w.writeheader()
        w.writerows(groups)
    rows_in = {(g["a"], g["entry"]) for g in groups} | {(g["b"], g["entry"]) for g in groups}
    summ = {"identical_series_pairs": len(groups), "rows_involved": len(rows_in),
            "same_cik_pairs": sum(1 for g in groups if g["cik_a"] == g["cik_b"] and g["cik_a"]),
            "different_or_missing_cik_pairs": sum(1 for g in groups if not (g["cik_a"] == g["cik_b"] and g["cik_a"]))}
    (OUT / "duplicates_summary.json").write_text(json.dumps(summ, indent=1))
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
