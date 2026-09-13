"""
TASK 130 Part 2 -- builds the versioned, machine-readable Discovery
Universe v1 manifest. Reuses Task 118D's already-matched-runtime
population (results/task118_profitability/reconciliation/population_manifest.json)
verbatim for the symbol lists -- does NOT reconstruct membership from
scratch, does NOT invent a market-cap threshold, does NOT substitute
"all US equities"/Russell 3000/S&P 1500.

Adds, from the actual Form 4 research parquet and daily-bar directories
(existing data only, no new download): issuer CIK mapping (with
ambiguity detection -- a symbol resolving to >1 distinct CIK is flagged,
not silently resolved), filing coverage (any Form 4 code-P record at
all), price coverage (daily bar directory presence), and an explicit
inclusion/exclusion reason per symbol.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

RELEASE_ROOT = Path("C:/workspace/TalonX")
sys.path.insert(0, str(RELEASE_ROOT))
RESEARCH_ROOT = Path(__file__).resolve().parents[2]

OUT = RESEARCH_ROOT / "results" / "task130_option_a_discovery"
OUT.mkdir(parents=True, exist_ok=True)

POP_MANIFEST = RESEARCH_ROOT / "results/task118_profitability/reconciliation/population_manifest.json"
FORM4_PARQUET = RELEASE_ROOT / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"
DAILY_DIR_1 = RELEASE_ROOT / "results/task95g_broad_cross_sectional/_daily"
DAILY_DIR_2 = RELEASE_ROOT / "results/task107a_form4_feasibility/_prices"

UNIVERSE_VERSION = "discovery_universe_v1"


def main() -> int:
    pop = json.loads(POP_MANIFEST.read_text())
    A_names = set(pop["A_the_39"])
    C_names = sorted(pop["C_full_panel_A_union_B"])

    form4 = pd.read_parquet(FORM4_PARQUET, columns=["issuer_sym", "issuer_cik", "issuer_name", "filing_date"])
    form4_c = form4[form4["issuer_sym"].isin(C_names)]

    price1 = {f.stem.upper() for f in DAILY_DIR_1.glob("*.csv")}
    price2 = {f.stem.upper() for f in DAILY_DIR_2.glob("*.csv")}

    entries = []
    n_ambiguous = 0
    n_no_filing_coverage = 0
    n_no_price_coverage = 0
    for sym in C_names:
        rows = form4_c[form4_c["issuer_sym"] == sym]
        cik_counts = Counter(rows["issuer_cik"])
        n_records = len(rows)
        ambiguous = len(cik_counts) > 1
        primary_cik = cik_counts.most_common(1)[0][0] if cik_counts else None
        issuer_name = (rows[rows["issuer_cik"] == primary_cik]["issuer_name"].iloc[0]
                      if n_records else None)
        first_filing = str(rows["filing_date"].min().date()) if n_records else None
        last_filing = str(rows["filing_date"].max().date()) if n_records else None
        has_price = sym in price1 or sym in price2
        price_source = ("task95g_broad_cross_sectional/_daily" if sym in price1 else
                        "task107a_form4_feasibility/_prices" if sym in price2 else None)

        if ambiguous:
            n_ambiguous += 1
        if n_records == 0:
            n_no_filing_coverage += 1
        if not has_price:
            n_no_price_coverage += 1

        reason = []
        if n_records == 0:
            reason.append("NO_FORM4_RECORDS_IN_RESEARCH_PARQUET")
        if not has_price:
            reason.append("NO_DAILY_PRICE_COVERAGE")
        if ambiguous:
            reason.append(f"AMBIGUOUS_CIK_MAPPING_{len(cik_counts)}_DISTINCT_CIKS")
        inclusion_reason = ("INCLUDED_task118d_matched_runtime_population_C" if sym not in reason
                            else "INCLUDED_BUT_LIMITED")

        entries.append({
            "symbol": sym, "primary_issuer_cik": str(int(primary_cik)) if primary_cik is not None else None,
            "issuer_name": issuer_name,
            "in_tier1_sec_resolved_39": sym in A_names,
            "n_form4_open_market_records": int(n_records),
            "distinct_ciks_seen": len(cik_counts),
            "cik_mapping_ambiguous": ambiguous,
            "first_filing_date": first_filing, "last_filing_date": last_filing,
            "has_daily_price_coverage": has_price, "price_source": price_source,
            "membership_eligibility_source": "task118d_matched_runtime_population_C "
                                             "(task116_620_panel UNION tier1_39_sec_resolved), "
                                             "re-run under post-task117 runtime",
            "exclusion_reasons": reason,
            "confidence": "HIGH" if (n_records > 0 and has_price and not ambiguous) else
                         ("MEDIUM" if (n_records > 0 or has_price) else "LOW"),
        })

    summary = {
        "universe_version": UNIVERSE_VERSION,
        "source": "results/task118_profitability/reconciliation/population_manifest.json "
                 "(Task 118D, matched post-Task-117 runtime, NOT Task 116's raw 620-name figure)",
        "n_total_symbols": len(C_names),
        "n_tier1_sec_resolved_subset": len(A_names),
        "n_broad_discovery_only": len(C_names) - len(A_names),
        "n_symbols_with_cik_mapping_ambiguity": n_ambiguous,
        "n_symbols_with_zero_form4_coverage": n_no_filing_coverage,
        "n_symbols_with_zero_price_coverage": n_no_price_coverage,
        "known_mapping_ambiguity_note": (
            f"{n_ambiguous} symbols resolve to more than one distinct issuer_cik in the "
            "research parquet (e.g. ticker reuse after a name change/spin-off/share-class "
            "filing quirk) -- the primary_issuer_cik field here is the MOST-FREQUENT CIK "
            "for that symbol in the data, not a verified single true mapping; flagged, not "
            "silently resolved."
        ),
        "zero_filing_coverage_note": (
            f"{n_no_filing_coverage} symbols (including SHOP, one of Tier 1's own 39 "
            "SEC-resolved names) have ZERO Form 4 open-market code-P records in the research "
            "parquet used by this replay -- these symbols cannot produce any episode/trade "
            "in this evaluation regardless of liquidity or contract, purely a data-coverage "
            "gap, not a filtering decision. Not silently dropped from the manifest."
        ),
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    (OUT / "universe_manifest_discovery_v1.json").write_text(
        json.dumps({"summary": summary, "entries": entries}, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
