"""ERM nominee -- metadata-only event-set reconciliation of the proposed correction rules (no prices, no returns).

Rules are applied in a FIXED order; each original row gets the FIRST rule that changes it (attribution), and every
rule's full hit count is also reported (overlaps). Inputs: pit_events.csv, pit_additions.csv, sic_pit.csv (if present).

  C1 TRADED_BAR      a bar with raw volume 0 is absent: D-1 or D placeholder -> no gap event; any placeholder among
                     the 20 eligibility sessions -> not eligible; entry placeholder -> DATA_MISSING_ENTRY (dropped);
                     exit placeholder -> DATA_MISSING_EXIT (kept as a flagged row, excluded from metrics, counts in G4)
  C2 SERIES_DEDUP    identical series on the same entry session -> one row; keep the row whose ticker has dated
                     Form 3/4/5 evidence <= D for its issuer; tie -> lexicographically smaller symbol
  C3 ISSUER_PIT      VERIFIED_DIFFERENT_SECURITY rows re-mapped to the dated (<= D) Form 3/4/5 issuer; no issuer ->
                     named rows kept with SPY benchmark (frozen 'unknown SIC -> SPY'), unnamed rows cannot satisfy R1a
  C4 R1A_PIT         unnamed rows not S&P-exempt (C5) need a 10-K/10-K/A/10-Q/10-Q/A of the issuer filed <= D
                     (availability only, NO recency); unresolvable history -> excluded, counted METADATA_INSUFFICIENT
  C5 SP_PIT          S&P exemption iff the ticker was a point-in-time S&P 500 member on some date <= D
  C6 SIC_PIT         SIC = header SIC of the issuer's latest company filing dated <= D; SIC 6770 on D -> masked
                     (removed); also drives the sector ETF (benchmark change, not a set change)
  ADD                rows a corrected rule admits that the frozen rule excluded (frozen-R1a-removed symbols)
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[2] / "results" / "erm_nominee_audit"


def b(x):
    return x.astype(str) == "True"


def main():
    e = pd.read_csv(OUT / "pit_events.csv", dtype=str).fillna("")
    for c in ("vol0_prev", "vol0_gap", "vol0_entry", "vol0_exit", "named", "f345_link_by_D", "r1a_avail",
              "r1a_recent365", "r1a_hist_trunc", "sp_ever_by_D_", "sp_frozen", "sp_on_D_"):
        e[c] = b(e[c])
    e["vol0_in_elig20"] = e["vol0_in_elig20"].astype(int)
    sic_path = OUT / "sic_pit.csv"
    sic = pd.read_csv(sic_path, dtype=str).fillna("") if sic_path.exists() else None
    if sic is not None:
        e = e.merge(sic[["symbol", "entry", "sic_pit", "sic_pit_source", "bench_pit"]], on=["symbol", "entry"], how="left")
    rule, hits = [""] * len(e), {k: 0 for k in ("C1_NO_GAP", "C1_NOT_ELIGIBLE", "C1_MISSING_ENTRY", "C1_EXIT_TO_MISSING",
                                                 "C2_DUPLICATE_DROPPED", "C3_REMAPPED", "C3_NO_ISSUER_UNNAMED",
                                                 "C4_R1A_NOT_AVAILABLE", "C4_METADATA_INSUFFICIENT",
                                                 "C5_SP_EXEMPTION_LOST", "C6_SIC6770_MASKED")}
    alive = pd.Series(True, index=e.index)
    new_status = e["status"].copy()
    for i, r in e.iterrows():
        if r.status in ("BEYOND_DEV_END",):
            continue
        tag = ""
        if r.vol0_prev or r.vol0_gap:
            hits["C1_NO_GAP"] += 1; tag = tag or "C1_NO_GAP"
        elif r.vol0_in_elig20 > 0:
            hits["C1_NOT_ELIGIBLE"] += 1; tag = tag or "C1_NOT_ELIGIBLE"
        elif r.vol0_entry:
            hits["C1_MISSING_ENTRY"] += 1; tag = tag or "C1_MISSING_ENTRY"
        if tag:
            alive[i] = False
        elif r.vol0_exit and r.status == "VALID":
            hits["C1_EXIT_TO_MISSING"] += 1; new_status[i] = "DATA_MISSING_EXIT"; tag = "C1_EXIT_TO_MISSING"
        rule[i] = tag
    # C2 dedup among rows still alive
    keyed = e[alive & (e.duplicate_of != "")]
    drop = set()
    for i, r in keyed.iterrows():
        j = e.index[(e.symbol == r.duplicate_of) & (e.entry == r.entry)]
        if len(j) == 0 or not alive[j[0]]:
            continue
        o = e.loc[j[0]]
        keep_self = (r.f345_link_by_D and not o.f345_link_by_D) or \
            (r.f345_link_by_D == o.f345_link_by_D and r.symbol < o.symbol)
        drop.add(j[0] if keep_self else i)
    for i in drop:
        hits["C2_DUPLICATE_DROPPED"] += 1
        alive[i] = False
        rule[i] = rule[i] or "C2_DUPLICATE_DROPPED"
    for i, r in e.iterrows():
        if not alive[i] or r.status == "BEYOND_DEV_END":
            continue
        if r.mapping == "VERIFIED_DIFFERENT_SECURITY":
            if r.issuer_pit:
                hits["C3_REMAPPED"] += 1
                rule[i] = rule[i] or "C3_REMAPPED"
            elif not r.named:
                hits["C3_NO_ISSUER_UNNAMED"] += 1; alive[i] = False; rule[i] = rule[i] or "C3_NO_ISSUER_UNNAMED"
                continue
        exempt = r.sp_ever_by_D_
        if not r.named and r.sp_frozen and not exempt:
            hits["C5_SP_EXEMPTION_LOST"] += 1
        if not r.named and not exempt:
            if not r.r1a_avail:
                k = "C4_METADATA_INSUFFICIENT" if r.r1a_hist_trunc else "C4_R1A_NOT_AVAILABLE"
                hits[k] += 1; alive[i] = False; rule[i] = rule[i] or k
                continue
        if sic is not None and r.get("sic_pit") == "6770":
            hits["C6_SIC6770_MASKED"] += 1; alive[i] = False; rule[i] = rule[i] or "C6_SIC6770_MASKED"
    e["first_rule"], e["alive_after"], e["status_after"] = rule, alive, new_status
    e.loc[~alive & (e.status != "BEYOND_DEV_END"), "status_after"] = "REMOVED"
    # recency variant (for comparison only): unnamed, non-exempt rows alive that would fail a 365-day recency test
    rec_only = int((alive & ~e.named & ~e.sp_ever_by_D_ & e.r1a_avail & ~e.r1a_recent365).sum())
    # additions (traded-bar rule, availability-only R1a or S&P-PIT, no placeholder at D-1/D)
    ad = pd.read_csv(OUT / "pit_additions.csv", dtype=str).fillna("")
    for c in ("r1a_avail", "r1a_recent365", "sp_ever_by_D", "vol0_prev_or_gap"):
        ad[c] = b(ad[c])
    at = ad[(ad.bar_rule == "traded_bar_rule") & ~ad.vol0_prev_or_gap]
    added = at[at.r1a_avail | at.sp_ever_by_D]
    added_recent = at[at.r1a_recent365 | at.sp_ever_by_D]
    e.to_csv(OUT / "reconciled_events.csv", index=False)
    added.to_csv(OUT / "reconciled_additions.csv", index=False)
    v0 = e[e.status == "VALID"]
    summ = {
        "original": {"valid": int((e.status == "VALID").sum()), "missing_exit": int((e.status == "DATA_MISSING_EXIT").sum()),
                     "missing_entry": int((e.status == "DATA_MISSING_ENTRY").sum()),
                     "beyond_dev_end": int((e.status == "BEYOND_DEV_END").sum())},
        "rule_hits_full_overlapping": hits,
        "first_rule_attribution_original_valid": v0.first_rule.replace("", "UNCHANGED").value_counts().to_dict(),
        "first_rule_attribution_original_missing_exit": e[e.status == "DATA_MISSING_EXIT"].first_rule.replace("", "UNCHANGED").value_counts().to_dict(),
        "after": {"valid": int(((e.status_after == "VALID") & e.alive_after).sum()),
                  "missing_exit": int(((e.status_after == "DATA_MISSING_EXIT") & e.alive_after).sum()),
                  "additions_valid_or_unknown_exit": len(added)},
        "additions_by_reason": {"r1a_available_only": int((added.r1a_avail & ~added.sp_ever_by_D).sum()),
                                "sp_exempt": int(added.sp_ever_by_D.sum())},
        "additions_symbols": sorted(added.symbol.unique().tolist()),
        "recency365_variant": {"extra_removals_among_kept": rec_only, "additions": len(added_recent)},
        "sic_pit_applied": sic is not None,
        "benchmark_changes_valid_after": (int(((e.bench_pit != e.bench_used_gateD) & e.alive_after & (e.status_after == "VALID")).sum())
                                          if sic is not None else None),
    }
    (OUT / "reconcile_summary.json").write_text(json.dumps(summ, indent=1, default=int))
    print(json.dumps(summ, indent=1, default=int))


if __name__ == "__main__":
    main()
