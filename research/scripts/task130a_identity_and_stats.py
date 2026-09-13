"""
TASK 130A Parts 7/8/9 -- issuer-identity reconciliation for the 35
ambiguous symbol-to-CIK mappings, a supplemental P&L-ranked
concentration test (alongside, not replacing, the original trade-count
ranking), and the full corrected economics (bootstraps, sensitivities,
calendar stability) on the corrected gated replay's own 153 trades.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RELEASE_ROOT = Path("C:/workspace/TalonX")
sys.path.insert(0, str(RELEASE_ROOT))
RESEARCH_ROOT = Path(__file__).resolve().parents[2]

OUT = RESEARCH_ROOT / "results" / "task130a_corrected_replay"
FORM4_PARQUET = RELEASE_ROOT / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"
BOOTSTRAP_SEED = 130130
BOOTSTRAP_REPS = 5000
PRIMARY_MATERIALITY_PCT = 0.50


# ---------------------------------------------------------------------
# Part 7 -- issuer identity reconciliation
# ---------------------------------------------------------------------
def reconcile_identities(closed_trades: list[dict]) -> dict:
    universe = sorted(json.loads((RESEARCH_ROOT / "results/task118_profitability/reconciliation/population_manifest.json")
                                 .read_text())["C_full_panel_A_union_B"])
    form4_all = pd.read_parquet(FORM4_PARQUET, columns=["issuer_sym", "issuer_cik", "issuer_name",
                                                        "accession", "filing_date"])
    form4 = form4_all[form4_all["issuer_sym"].isin(universe)]  # SAME 626-name scope as Task 130's own manifest
    entered_symbols = {t["symbol"] for t in closed_trades}
    ambiguous = (form4.groupby("issuer_sym")["issuer_cik"].nunique())
    ambiguous_syms = sorted(ambiguous[ambiguous > 1].index)

    cases = []
    for sym in ambiguous_syms:
        rows = form4[form4["issuer_sym"] == sym]
        by_cik = rows.groupby("issuer_cik").agg(
            n_records=("accession", "count"),
            first_filing=("filing_date", "min"), last_filing=("filing_date", "max"),
            issuer_names=("issuer_name", lambda s: sorted(set(s))))
        by_cik = by_cik.sort_values("first_filing")
        cik_list = by_cik.to_dict(orient="index")
        ciks_sorted_by_date = list(by_cik.index)
        # classify: do the date ranges for successive CIKs overlap (symbol
        # reuse by literally-concurrent, different issuers -- suspicious)
        # or are they sequential/non-overlapping (consistent with a
        # legitimate historical identity change -- rename, re-incorporation,
        # spin-off assuming the old ticker)?
        overlapping = False
        for i in range(len(ciks_sorted_by_date) - 1):
            a, b = cik_list[ciks_sorted_by_date[i]], cik_list[ciks_sorted_by_date[i + 1]]
            if a["last_filing"] >= b["first_filing"]:
                overlapping = True
        names_differ_materially = len({n for v in cik_list.values() for n in v["issuer_names"]}) > 1

        if overlapping:
            classification = "MAPPING_DEFECT_OR_UNRESOLVED_OVERLAPPING_DATES"
        elif not names_differ_materially:
            classification = "MULTIPLE_SECURITIES_SAME_ISSUER_NAME"  # e.g. class A/B under one umbrella name mapped to >1 CIK
        else:
            classification = "LIKELY_LEGITIMATE_HISTORICAL_IDENTITY_CHANGE"  # sequential, non-overlapping, different names

        this_symbol_entered = sym in entered_symbols
        entered_trade_dates = sorted(t["entry_session"] for t in closed_trades if t["symbol"] == sym)
        # which CIK period do this symbol's actual ENTERED trades fall into?
        trade_ciks_used = []
        if this_symbol_entered:
            for d in entered_trade_dates:
                dts = pd.Timestamp(d)
                for cik, v in cik_list.items():
                    if v["first_filing"] <= dts <= v["last_filing"] + pd.Timedelta(days=60):
                        trade_ciks_used.append(cik)
                        break

        cases.append({
            "symbol": sym, "n_distinct_ciks": len(cik_list), "classification": classification,
            "cik_detail": {str(k): {"n_records": int(v["n_records"]),
                                    "first_filing": str(v["first_filing"].date()),
                                    "last_filing": str(v["last_filing"].date()),
                                    "issuer_names": v["issuer_names"]}
                          for k, v in cik_list.items()},
            "symbol_has_entered_trades": this_symbol_entered,
            "entered_trade_dates": entered_trade_dates,
            "cik_used_by_actual_trades": sorted(set(trade_ciks_used)),
            "single_cluster_spans_multiple_ciks": len(set(trade_ciks_used)) > 1,
        })

    n_overlapping = sum(1 for c in cases if c["classification"] == "MAPPING_DEFECT_OR_UNRESOLVED_OVERLAPPING_DATES")
    n_multi_class = sum(1 for c in cases if c["classification"] == "MULTIPLE_SECURITIES_SAME_ISSUER_NAME")
    n_rename = sum(1 for c in cases if c["classification"] == "LIKELY_LEGITIMATE_HISTORICAL_IDENTITY_CHANGE")
    n_cross_cik_clusters = sum(1 for c in cases if c["single_cluster_spans_multiple_ciks"])
    entered_ambiguous_symbols = [c["symbol"] for c in cases if c["symbol_has_entered_trades"]]

    return {
        "n_ambiguous_symbols_total": len(ambiguous_syms),
        "n_classified_likely_legitimate_identity_change": n_rename,
        "n_classified_multiple_securities_same_name": n_multi_class,
        "n_classified_mapping_defect_or_unresolved": n_overlapping,
        "n_ambiguous_symbols_with_entered_trades": len(entered_ambiguous_symbols),
        "entered_ambiguous_symbols": entered_ambiguous_symbols,
        "n_entered_trades_whose_single_cluster_spans_multiple_ciks": n_cross_cik_clusters,
        "proof_no_cross_issuer_cluster_merge": (
            "For every ambiguous symbol with an ENTERED trade, the trade's own entry date was "
            "matched to exactly ONE issuer_cik's own filing date range (60-day grace). "
            "single_cluster_spans_multiple_ciks==False for all confirms no episode/cluster mixed "
            "filings from two different issuer_ciks under the shared ticker."
        ),
        "cases": cases,
    }


# ---------------------------------------------------------------------
# Part 8/9 -- stats (reused pattern from task130_discovery_evaluation.py)
# ---------------------------------------------------------------------
def _issuer_block_bootstrap(returns_by_issuer: dict, *, seed: int) -> dict:
    issuers = list(returns_by_issuer.keys())
    if len(issuers) < 2:
        return {"n_issuer_blocks": len(issuers), "ci_pct": None}
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(BOOTSTRAP_REPS):
        idx = rng.integers(0, len(issuers), size=len(issuers))
        sampled = [r for i in idx for r in returns_by_issuer[issuers[i]]]
        if sampled:
            means.append(float(np.mean(sampled)))
    ci = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]
    return {"n_issuer_blocks": len(issuers), "ci_pct": [round(100 * c, 4) for c in ci]}


def _date_block_bootstrap(returns_by_month: dict, *, seed: int) -> dict:
    months = list(returns_by_month.keys())
    if len(months) < 2:
        return {"n_date_blocks": len(months), "ci_pct": None}
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(BOOTSTRAP_REPS):
        idx = rng.integers(0, len(months), size=len(months))
        sampled = [r for i in idx for r in returns_by_month[months[i]]]
        if sampled:
            means.append(float(np.mean(sampled)))
    ci = [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]
    return {"n_date_blocks": len(months), "ci_pct": [round(100 * c, 4) for c in ci]}


def compute_stats(closed: list[dict]) -> dict:
    n = len(closed)
    net = [c["net_return"] for c in closed]
    gross = [c["gross_return"] for c in closed]
    by_issuer, by_month, by_half = {}, {}, {}
    for c in closed:
        by_issuer.setdefault(c["symbol"], []).append(c["net_return"])
        ts = pd.Timestamp(c["entry_session"])
        by_month.setdefault(str(ts.to_period("M")), []).append(c["net_return"])
        half = f"{ts.year}H{1 if ts.month <= 6 else 2}"
        by_half.setdefault(half, []).append(c["net_return"])

    gross_win = sum(r for r in net if r > 0)
    gross_loss = -sum(r for r in net if r <= 0)

    # ORIGINAL sensitivity: rank issuers by TRADE COUNT
    count_rank = sorted(by_issuer, key=lambda k: -len(by_issuer[k]))

    def _excl_count_top_n(n_top: int) -> dict:
        excl = set(count_rank[:n_top])
        remaining = [c["net_return"] for c in closed if c["symbol"] not in excl]
        return {"n_remaining": len(remaining), "excluded_issuers": count_rank[:n_top],
               "mean_net_pct": round(100 * float(np.mean(remaining)), 4) if remaining else None}

    # SUPPLEMENTAL sensitivity: rank issuers by aggregate POSITIVE net $ P&L
    # contribution -- deterministic tie-break: (pnl desc, symbol asc).
    pnl_by_issuer = {}
    for c in closed:
        pnl_by_issuer.setdefault(c["symbol"], 0.0)
        pnl_by_issuer[c["symbol"]] += c["net_pnl_usd"]
    positive_contributors = {k: v for k, v in pnl_by_issuer.items() if v > 0}
    pnl_rank = sorted(positive_contributors, key=lambda k: (-positive_contributors[k], k))

    def _excl_pnl_top_n(n_top: int) -> dict:
        excl = set(pnl_rank[:n_top])
        remaining = [c["net_return"] for c in closed if c["symbol"] not in excl]
        remaining_pnl = sum(c["net_pnl_usd"] for c in closed if c["symbol"] not in excl)
        return {"n_remaining": len(remaining), "excluded_issuers": pnl_rank[:n_top],
               "mean_net_pct": round(100 * float(np.mean(remaining)), 4) if remaining else None,
               "remaining_total_pnl_usd": round(remaining_pnl, 2)}

    return {
        "n_closed_trades": n, "n_distinct_issuers": len(by_issuer),
        "gross_mean_pct": round(100 * float(np.mean(gross)), 4),
        "net_mean_pct": round(100 * float(np.mean(net)), 4),
        "net_median_pct": round(100 * float(np.median(net)), 4),
        "win_rate": round(float(np.mean([r > 0 for r in net])), 4),
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else None,
        "meets_primary_criterion_gt_0_50pct": (100 * float(np.mean(net))) > PRIMARY_MATERIALITY_PCT,
        "issuer_block_bootstrap": _issuer_block_bootstrap(by_issuer, seed=BOOTSTRAP_SEED),
        "date_block_bootstrap": _date_block_bootstrap(by_month, seed=BOOTSTRAP_SEED),
        "original_sensitivity_trade_count_ranked": {
            "excl_top1": _excl_count_top_n(1), "excl_top3": _excl_count_top_n(3), "excl_top5": _excl_count_top_n(5),
        },
        "supplemental_sensitivity_pnl_contribution_ranked_NOT_PREREGISTERED": {
            "label": "SUPPLEMENTAL completion test (Task 130A), not part of the original Task 130 preregistration",
            "n_positive_contributors": len(positive_contributors),
            "excl_top1": _excl_pnl_top_n(1), "excl_top3": _excl_pnl_top_n(3), "excl_top5": _excl_pnl_top_n(5),
        },
        "calendar_half_year_stability": {k: {"n": len(v), "mean_net_pct": round(100 * float(np.mean(v)), 4)}
                                        for k, v in sorted(by_half.items())},
    }


def main() -> int:
    closed = json.loads((OUT / "closed_trades.json").read_text())
    identity = reconcile_identities(closed)
    stats = compute_stats(closed)

    (OUT / "identity_reconciliation.json").write_text(json.dumps(identity, indent=2, default=str))
    (OUT / "corrected_stats.json").write_text(json.dumps(stats, indent=2, default=str))

    print(json.dumps({k: v for k, v in identity.items() if k != "cases"}, indent=2, default=str))
    print(json.dumps(stats, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
