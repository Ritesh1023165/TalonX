"""ERM nominee -- deterministic identity / lineage classification over lineage_events.csv + duplicates.csv.
Pure metadata (no prices). Output: results/erm_nominee_audit/{classified_events.csv, classification_summary.json}

MAPPING classes (precedence top-down; first match wins):
  VERIFIED_DIFFERENT_SECURITY  dated evidence shows the series used for the event is NOT the assigned issuer's
                               security on D:  (a) the latest Form 3/4/5 ticker observation <= D names another issuer
                               CIK;  (b) the ticker had been renamed away from the assigned entity on/before D;  or
                               (c) the series is identical to another row's series whose issuer has dated (<= D)
                               Form 3/4/5 ticker evidence while this row's assigned issuer has none.
  UNRESOLVED                   no issuer CIK (UNMAPPED / FORM345_AMBIGUOUS), or identical to another row with a
                               different CIK and neither side has dated evidence.
  FUTURE_ASSISTED_MAPPING      issuer assigned, no contrary evidence, but NO dated evidence <= D links this ticker to
                               the issuer (link rests on the 2026 SEC ticker file, later renames, later Form 3/4/5,
                               or the provider's as-of-today relabelling of predecessor history).
  VERIFIED_CONTINUITY          a Form 3/4/5 filed on/before D by the assigned issuer reports this ticker, and none of
                               the above applies.
BAR-LINEAGE flags (independent of mapping):
  PLACEHOLDER_AT_KEY      zero-volume (non-traded) bar at D-1 (gap reference), D, entry or exit
  PLACEHOLDER_IN_ELIG     >= 1 zero-volume row among the 20 sessions ending D (eligibility window)
DUPLICATE flag: the row's series is identical (volumes) to another row on the same entry session.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[2] / "results" / "erm_nominee_audit"
B = ["vol0_prev", "vol0_gap", "vol0_entry", "vol0_exit", "f345_link_by_D", "f345_conflict_by_D",
     "f345_link_only_after_D", "named", "sp_on_D", "sp_ever_by_D", "r1a_qual_2019_by_D", "r1a_qual_pre2019_by_entry",
     "r1a_history_truncated", "interval_covers_D_entry_exit"]


def main():
    d = pd.read_csv(OUT / "lineage_events.csv", dtype=str).fillna("")
    for c in B:
        d[c] = d[c] == "True"
    d["vol0_in_elig20"] = d["vol0_in_elig20"].astype(int)
    g = pd.read_csv(OUT / "duplicates.csv", dtype=str).fillna("")
    link = {(r.symbol, r.entry): r.f345_link_by_D for r in d.itertuples()}
    cik = {(r.symbol, r.entry): r.cik for r in d.itertuples()}
    dup_of, cross_wrong, cross_unres = {}, set(), set()
    for r in g.itertuples():
        ka, kb = (r.a, r.entry), (r.b, r.entry)
        dup_of[ka], dup_of[kb] = r.b, r.a
        if cik[ka] != cik[kb] or not cik[ka]:
            la, lb = link[ka], link[kb]
            if la and not lb:
                cross_wrong.add(kb)
            elif lb and not la:
                cross_wrong.add(ka)
            else:
                cross_unres |= {ka, kb}

    def mapping(r):
        k = (r.symbol, r.entry)
        if r.cik and (r.f345_conflict_by_D or r.renamed_out_before_D != "[]" or k in cross_wrong):
            return "VERIFIED_DIFFERENT_SECURITY"
        if not r.cik or k in cross_unres:
            return "UNRESOLVED"
        return "VERIFIED_CONTINUITY" if r.f345_link_by_D else "FUTURE_ASSISTED_MAPPING"

    d["mapping"] = [mapping(r) for r in d.itertuples()]
    d["placeholder_at_key"] = d.vol0_prev | d.vol0_gap | d.vol0_entry | d.vol0_exit
    d["placeholder_in_elig"] = d.vol0_in_elig20 > 0
    d["duplicate_of"] = [dup_of.get((r.symbol, r.entry), "") for r in d.itertuples()]
    d.to_csv(OUT / "classified_events.csv", index=False)
    v = d[d.status == "VALID"]
    summ = {
        "population_rows": len(d), "valid_rows": len(v),
        "mapping_all": d.mapping.value_counts().to_dict(),
        "mapping_valid": v.mapping.value_counts().to_dict(),
        "mapping_symbols": d.groupby("mapping").symbol.nunique().to_dict(),
        "different_security_reason_valid": {
            "f345_conflict": int((v.mapping.eq("VERIFIED_DIFFERENT_SECURITY") & v.f345_conflict_by_D).sum()),
            "renamed_away_before_D": int((v.mapping.eq("VERIFIED_DIFFERENT_SECURITY") & (v.renamed_out_before_D != "[]")).sum()),
            "identical_to_better_evidenced_row": int(sum((r.symbol, r.entry) in cross_wrong for r in v.itertuples()))},
        "placeholder_at_key_valid": int(v.placeholder_at_key.sum()),
        "placeholder_in_elig_valid": int(v.placeholder_in_elig.sum()),
        "placeholder_any_valid": int((v.placeholder_at_key | v.placeholder_in_elig).sum()),
        "duplicate_rows_valid": int((v.duplicate_of != "").sum()),
        "crosstab_valid_mapping_x_placeholder_any": pd.crosstab(
            v.mapping, v.placeholder_at_key | v.placeholder_in_elig).to_dict(),
        "crosstab_valid_mapping_x_duplicate": pd.crosstab(v.mapping, v.duplicate_of != "").to_dict(),
    }
    (OUT / "classification_summary.json").write_text(json.dumps(summ, indent=1, default=str))
    print(json.dumps(summ, indent=1, default=str))


if __name__ == "__main__":
    main()
