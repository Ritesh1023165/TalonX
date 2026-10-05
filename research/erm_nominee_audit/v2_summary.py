"""Summarise / reconcile the V2 manifest (metadata only). Output: results/erm_nominee_audit/v2/summary.json"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

import os

HERE = Path(__file__).resolve().parents[2]
AUD = Path(os.environ.get("ERM_AUDIT_INPUTS", HERE / "results" / "erm_nominee_audit"))
OUT = Path(os.environ.get("ERM_V2_OUT", AUD / "v2_1"))


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    m = pd.read_csv(OUT / "manifest.csv", dtype=str).fillna("")
    a = m[m["pop"] == "A"]
    v1 = pd.read_csv(AUD / "reconciled_events.csv", dtype=str).fillna("")
    v1["v1_status"] = v1.apply(lambda r: r.status_after if r.alive_after == "True" else
                               ("BEYOND_WINDOW" if r.status == "BEYOND_DEV_END" else "EXCLUDED"), axis=1)
    gd = pd.read_csv(AUD / "lineage_events.csv", dtype=str).fillna("")[["symbol", "entry", "bench_used_gateD"]]
    a = a.merge(v1[["symbol", "entry", "v1_status", "first_rule"]], on=["symbol", "entry"], how="left") \
         .merge(gd, on=["symbol", "entry"], how="left")
    kept = m[m.v2_status.isin(["VALID", "DATA_MISSING_EXIT"])]
    kv = m[m.v2_status == "VALID"]
    av = a[a.frozen_status == "VALID"]
    akv = a[a.v2_status == "VALID"]
    s = {
        "population_rows": m["pop"].value_counts().to_dict(),
        "v2_status_by_population": pd.crosstab(m["pop"], m.v2_status).to_dict(orient="index"),
        "proposed_primary_sample": {"valid": int(len(kv)),
                                    "missing_exit": int((m.v2_status == "DATA_MISSING_EXIT").sum()),
                                    "missing_entry": int((m.v2_status == "DATA_MISSING_ENTRY").sum()),
                                    "beyond_window": int((m.v2_status == "BEYOND_WINDOW").sum()),
                                    "excluded": int((m.v2_status == "EXCLUDED").sum()),
                                    "valid_symbols": int(kv.symbol.nunique()), "valid_entry_dates": int(kv.entry.nunique()),
                                    "valid_by_gap_year": kv.gap_day.str[:4].value_counts().sort_index().to_dict(),
                                    "valid_by_population": kv["pop"].value_counts().to_dict()},
        "first_reason_original_valid": av.first_reason.replace("", "KEPT_" ).value_counts().to_dict(),
        "first_reason_all_rows": m.first_reason.replace("", "NONE").value_counts().to_dict(),
        "flag_hits_all_rows_overlapping": pd.Series([f for x in m["flags"] for f in x.split("|") if f]).value_counts().to_dict(),
        "identity_classes_all": m.identity.value_counts().to_dict(),
        "identity_reasons_unresolved": m.loc[m.identity == "UNRESOLVED_IDENTITY", "identity_reason"].value_counts().to_dict(),
        "identity_original_valid": av.identity.value_counts().to_dict(),
        "mapping_class_original_valid": av.mapping_class.value_counts().to_dict(),
        "mapping_class_kept_valid": kv.mapping_class.value_counts().to_dict(),
        "instrument_kept_valid": kv.instrument.value_counts().to_dict(),
        "instrument_original_valid": av.instrument.value_counts().to_dict(),
        "sic_source_original_valid": av.sic_source.value_counts().to_dict(),
        "sp_evidence_unnamed_original_valid": av.loc[av.named != "True", "sp_evidence"].value_counts().to_dict(),
        "duplicates": {"rows_in_verified_groups": int((m.dup_group.str.startswith("G")).sum()),
                       "rows_unresolved": int((m.dup_group == "UNRESOLVED").sum()),
                       "groups": int(m.loc[m.dup_group.str.startswith("G"), "dup_group"].nunique())},
        "remapped_kept_valid": int((kv.mapping_class == "VERIFIED_DIFFERENT_SECURITY").sum()),
        "benchmark_changes_vs_gateD_kept_valid_A": int((akv.benchmark_v2 != akv.bench_used_gateD).sum()),
        "benchmark_kept_valid": kv.benchmark_v2.value_counts().to_dict(),
        "additions_from_B_or_C_valid": int(kv["pop"].isin(["B", "C"]).sum()),
        "additions_detail": kv.loc[kv["pop"].isin(["B", "C"]), ["pop", "symbol", "gap_day"]].to_dict(orient="records"),
        "transition_v1_to_v2_A": pd.crosstab(a.v1_status, a.v2_status).to_dict(orient="index"),
        "sensitivity_kept_valid": kv.sens_no_detected_stock_adj_or_etf_cash_div.value_counts().to_dict(),
        "sensitivity_legs_kept_valid": {"stock": kv.sens_stock_leg.value_counts().to_dict(),
                                        "etf_cash_dividend": kv.sens_etf_cash_dividend_leg.value_counts().to_dict()},
        "hashes": {p.name: sha(p) for p in sorted(OUT.glob("*.csv"))},
    }
    (OUT / "summary.json").write_text(json.dumps(s, indent=1, default=str))
    print(json.dumps({k: v for k, v in s.items() if k not in ("additions_detail",)}, indent=1, default=str))


if __name__ == "__main__":
    main()
