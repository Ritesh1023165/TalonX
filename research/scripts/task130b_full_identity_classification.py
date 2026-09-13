"""
TASK 130B Part 3 -- classify ALL ambiguous symbol-to-issuer-CIK
mappings across the 626-name Discovery Universe v1 population, using
identity evidence only, never trade profitability.

Reuses `reconcile_identities` (unmodified import from
task130a_identity_and_stats.py) for the base date-range/overlap
evidence across every ambiguous symbol in the population -- that
function already iterates the full 626-name universe, not just traded
symbols. This script then OVERLAYS the true, accession-level
evidence chain (Part 2, `task130b_accession_identity.py`'s own output)
for the 8 symbols that were actually traded, replacing the 60-day-
grace-based "which CIK did the trade use" inference with the exact
constituent-record evidence.

Explicit three-tier final classification, reported for ALL 35 (not
just the 8 traded):
  - VERIFIED_CONSISTENT: TRADED, and the exact accession-level
    evidence chain confirms every constituent record of the winning
    episode shares one issuer CIK.
  - VERIFIED_ERROR_REQUIRING_CORRECTION: TRADED, and the accession
    chain instead shows the winning episode's constituent records
    span more than one issuer CIK (a real cross-issuer cluster merge).
  - UNRESOLVED: overlapping CIK date ranges for the symbol (genuinely
    ambiguous identity, regardless of whether it was ever traded), OR
    a traded symbol whose accession chain could not produce an exact
    eligible-entry-session match.
  - NOT_TRADED_DATE_RANGE_CONSISTENT: never traded in this population,
    non-overlapping CIK date ranges (no accession-level chain was
    built, since no episode from this symbol was ever admitted into
    an entered trade -- explicitly NOT claimed accession-verified).

Never claims all 35 are "resolved" merely because the 8 traded cases
are verified -- NOT_TRADED_DATE_RANGE_CONSISTENT is reported as its
own, distinct, lower-confidence tier.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RELEASE_ROOT = Path("C:/workspace/TalonX")
sys.path.insert(0, str(RELEASE_ROOT))
RESEARCH_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RESEARCH_ROOT / "research" / "scripts"))

OUT = RESEARCH_ROOT / "results" / "task130b_identity_evidence"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    from task130a_identity_and_stats import reconcile_identities

    # base date-range evidence across the FULL 626-name population --
    # the closed_trades used here only affect the "symbol_has_entered_
    # trades" / 60-day-grace fields, which this script overrides below
    # for the 8 traded symbols using the true accession chain instead.
    closed = json.loads((RESEARCH_ROOT / "results/task130b_durable_replay/closed_trades.json").read_text())
    identity = reconcile_identities(closed)

    chains = json.loads((OUT / "accession_evidence_chains.json").read_text())
    accession_classification = json.loads((OUT / "classification_summary.json").read_text())

    final_cases = []
    n_verified_consistent = 0
    n_verified_error = 0
    n_unresolved = 0
    n_not_traded_date_range_consistent = 0

    for case in identity["cases"]:
        sym = case["symbol"]
        c = dict(case)
        if sym in accession_classification:
            # TRADED, accession-level evidence chain available (Part 2)
            acc_result = accession_classification[sym]
            c["evidence_tier"] = "ACCESSION_LEVEL_EXACT_CONSTITUENT_RECORDS"
            c["accession_chain"] = chains.get(sym)
            if acc_result == "VERIFIED_CONSISTENT":
                c["final_classification"] = "VERIFIED_CONSISTENT"
                n_verified_consistent += 1
            elif acc_result == "VERIFIED_ERROR_REQUIRING_CORRECTION":
                c["final_classification"] = "VERIFIED_ERROR_REQUIRING_CORRECTION"
                n_verified_error += 1
            else:  # UNRESOLVED_NO_EXACT_EPISODE_MATCH
                c["final_classification"] = "UNRESOLVED"
                n_unresolved += 1
        elif case["classification"] == "MAPPING_DEFECT_OR_UNRESOLVED_OVERLAPPING_DATES":
            c["evidence_tier"] = "DATE_RANGE_OVERLAP_EVIDENCE_ONLY"
            c["final_classification"] = "UNRESOLVED"
            n_unresolved += 1
        else:
            c["evidence_tier"] = "DATE_RANGE_EVIDENCE_ONLY_NOT_TRADED_NOT_ACCESSION_VERIFIED"
            c["final_classification"] = "NOT_TRADED_DATE_RANGE_CONSISTENT"
            n_not_traded_date_range_consistent += 1
        final_cases.append(c)

    result = {
        "n_ambiguous_symbols_total": identity["n_ambiguous_symbols_total"],
        "n_traded_ambiguous_symbols": len(accession_classification),
        "final_classification_counts": {
            "VERIFIED_CONSISTENT": n_verified_consistent,
            "VERIFIED_ERROR_REQUIRING_CORRECTION": n_verified_error,
            "UNRESOLVED": n_unresolved,
            "NOT_TRADED_DATE_RANGE_CONSISTENT": n_not_traded_date_range_consistent,
        },
        "note": (
            "VERIFIED_CONSISTENT/VERIFIED_ERROR_REQUIRING_CORRECTION/UNRESOLVED status for "
            "the 8 traded symbols is based on the exact accession-level constituent-record "
            "evidence chain (Part 2), not trade profitability. The remaining "
            f"{n_not_traded_date_range_consistent} ambiguous symbols were never traded in this "
            "population and are reported as NOT_TRADED_DATE_RANGE_CONSISTENT -- visible, not "
            "silently discarded, and explicitly NOT claimed to be accession-level verified. "
            f"{n_unresolved} case(s) are UNRESOLVED (overlapping CIK date ranges and/or no exact "
            "eligible-entry-session match) -- kept visible in the population; exclusion is "
            "diagnostic only, never applied by default."
        ),
        "cases": final_cases,
    }
    (OUT / "full_identity_classification.json").write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
