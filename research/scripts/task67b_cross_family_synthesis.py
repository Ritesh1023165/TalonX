"""
research/scripts/task67b_cross_family_synthesis.py
------------------------------------------------------
Task 67B final step: cross-family synthesis across the 6 completed
Stage 1 phenomenon-discovery families. Reads each family's already-
computed, already-committed results/task67a_phenomenon_discovery/
family_0N_*/{summary.json,events.csv} -- computes NOTHING new about any
individual family's statistics (those are final, per-family, already
reviewed) -- only compares them: event overlap (research_stats.
cross_family_overlap), a gross-effect comparison table, frequency,
concentration, and a ranking, writing
results/task67a_phenomenon_discovery/{cross_family_summary.json,.md}.

For each family, one definition is picked as that family's REPRESENTATIVE
for the overlap matrix and gross-effect comparison (not a re-judgment of
which definition is "best" -- families 1/2/4/5 have 3 definitions with
materially the same verdict, so the representative is simply a fixed,
documented choice; family 3 and 6 differ meaningfully across definitions
and the strongest one is used):
  F1 multi_hour_trend        -> trend60_slope_consistent
  F2 structural_pullback     -> pullback_toward_vwap_holds
  F3 range_expansion         -> compression90_expansion10_2.5x  (the one WEAK_SIGNAL def, not the two NOT_OBSERVED)
  F4 relative_strength       -> rs_trailing_60m  (beta-adjusted basis)
  F5 compression_expansion   -> relative_narrow_range_15v90  (largest n, most stable)
  F6 opening_later           -> opening_return_magnitude  (marginally strongest per Family 6's own report)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


def _df_to_md_table(df: pd.DataFrame) -> str:
    """Minimal markdown-table renderer (avoids an optional `tabulate`
    dependency this environment doesn't have installed)."""
    if df.empty:
        return "(empty)"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(v) for v in row.tolist()) + " |")
    return "\n".join(lines)

from research.task67a_lib.research_stats import cross_family_overlap

ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = ROOT / "results" / "task67a_phenomenon_discovery"

REPRESENTATIVE = {
    "family_01_multi_hour_trend": "trend60_slope_consistent",
    "family_02_structural_pullback": "pullback_toward_vwap_holds",
    "family_03_range_expansion": "compression90_expansion10_2.5x",
    "family_04_relative_strength": "rs_trailing_60m",
    "family_05_compression_expansion": "relative_narrow_range_15v90",
    "family_06_opening_later": "opening_return_magnitude",
}

FAMILY_LABELS = {
    "family_01_multi_hour_trend": "F1 Multi-Hour Trend",
    "family_02_structural_pullback": "F2 Structural Pullback",
    "family_03_range_expansion": "F3 Range Expansion",
    "family_04_relative_strength": "F4 Relative Strength",
    "family_05_compression_expansion": "F5 Compression->Expansion",
    "family_06_opening_later": "F6 Opening->Later",
}


def load_family_summary(fam: str) -> dict:
    with open(RESULTS_DIR / fam / "summary.json", encoding="utf-8") as f:
        return json.load(f)


def load_representative_events(fam: str) -> pd.DataFrame:
    df = pd.read_csv(RESULTS_DIR / fam / "events.csv")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    rep = REPRESENTATIVE[fam]
    return df[df["definition"] == rep].copy()


def get_horizon_excess(summary: dict, defn: str, horizon: str) -> dict:
    """Handles Family 4's differently-shaped beta_adjusted structure vs.
    the standard per_horizon shape used by Families 1/2/3/5/6."""
    dd = summary["definitions"][defn]
    if "beta_adjusted" in dd:
        hh = dd["beta_adjusted"]["per_horizon"].get(horizon, {})
        spy = hh.get("spy_adjusted", {}) or {}
        return {
            "excess_mean_pct": spy.get("point_estimate"),
            "ci_low": spy.get("ci_low"),
            "ci_high": spy.get("ci_high"),
            "n": hh.get("n"),
        }
    hh = dd.get("per_horizon", {}).get(horizon, {})
    boot = hh.get("excess_bootstrap_clustered") or {}
    return {
        "excess_mean_pct": hh.get("excess_mean_pct"),
        "ci_low": boot.get("ci_low"),
        "ci_high": boot.get("ci_high"),
        "n": hh.get("n_matched_pairs"),
    }


def get_verdict(summary: dict, defn: str) -> str:
    return summary["definitions"][defn]["verdict"]


def get_econ(summary: dict, defn: str) -> str:
    dd = summary["definitions"][defn]
    if "beta_adjusted" in dd:
        return dd["beta_adjusted"]["economic_classification_beta_adjusted"]
    return dd.get("economic_classification")


def get_effect_surface_instability(summary: dict, defn: str) -> bool:
    dd = summary["definitions"][defn]
    return bool(dd.get("effect_surface_instability", False))


def get_concentration(summary: dict, defn: str) -> dict:
    return summary["definitions"][defn].get("concentration", {})


def main() -> None:
    fams = list(REPRESENTATIVE.keys())
    summaries = {f: load_family_summary(f) for f in fams}
    events = {f: load_representative_events(f) for f in fams}

    # --- Event overlap matrix (all 15 pairs) ---
    overlap_rows = []
    for i, fa in enumerate(fams):
        for fb in fams[i + 1:]:
            res = cross_family_overlap(
                events[fa], events[fb],
                symbol_col="symbol", time_col="timestamp",
                day_col="trading_day", time_tolerance_minutes=5.0,
            )
            overlap_rows.append({
                "family_a": FAMILY_LABELS[fa], "family_b": FAMILY_LABELS[fb],
                "n_events_a": res["n_events_a"], "n_events_b": res["n_events_b"],
                "a_covered_by_b_time_frac": res["a_covered_by_b_same_symbol_time"]["fraction"],
                "b_covered_by_a_time_frac": res["b_covered_by_a_same_symbol_time"]["fraction"],
                "a_covered_by_b_day_frac": res["a_covered_by_b_same_symbol_day"]["fraction"],
                "b_covered_by_a_day_frac": res["b_covered_by_a_same_symbol_day"]["fraction"],
            })
    overlap_df = pd.DataFrame(overlap_rows)
    overlap_df.to_csv(RESULTS_DIR / "event_overlap_matrix.csv", index=False)

    # --- Gross forward effect comparison ---
    comparison_rows = []
    for f in fams:
        defn = REPRESENTATIVE[f]
        summary = summaries[f]
        dd = summary["definitions"][defn]
        row = {
            "family": FAMILY_LABELS[f],
            "representative_definition": defn,
            "verdict": get_verdict(summary, defn),
            "economic_classification": get_econ(summary, defn),
            "n_dedup_events": dd.get("n_dedup_events"),
            "n_symbols": dd.get("n_symbols"),
            "n_days": dd.get("n_days"),
            "effect_surface_instability": get_effect_surface_instability(summary, defn),
        }
        for h in ["15m", "30m", "60m", "120m"]:
            hx = get_horizon_excess(summary, defn, h)
            row[f"excess_{h}"] = hx["excess_mean_pct"]
            row[f"ci_low_{h}"] = hx["ci_low"]
            row[f"ci_high_{h}"] = hx["ci_high"]
        conc = get_concentration(summary, defn)
        row["top1_symbol_share"] = conc.get("top1_symbol_share")
        row["top3_symbol_share"] = conc.get("top3_symbol_share")
        row["best_day_share"] = conc.get("best_day_share")
        n_trading_days_total = summary["data"]["n_trading_days"]
        row["events_per_week"] = (
            round(row["n_dedup_events"] / (n_trading_days_total / 5.0), 1)
            if row["n_dedup_events"] else 0.0
        )
        comparison_rows.append(row)
    comparison_df = pd.DataFrame(comparison_rows)
    comparison_df.to_csv(RESULTS_DIR / "family_comparison.csv", index=False)

    # --- Redundancy flags ---
    # Same-symbol-DAY overlap is deliberately NOT used for this flag: with
    # only 63 DEVELOPMENT trading days and several families firing
    # thousands of events spread across nearly every symbol, "did family A
    # and family B ever both fire on this symbol on this day" is close to
    # saturated (frequently >=0.99 in one direction) for purely
    # combinatorial reasons -- it says almost nothing about whether the two
    # families are detecting the SAME episodes. The tight same-symbol-TIME
    # overlap (5-minute tolerance) is the meaningful redundancy signal:
    # it asks whether the families are firing on essentially the same
    # moment, not merely the same calendar day.
    redundant_pairs = overlap_df[
        (overlap_df["a_covered_by_b_time_frac"] > 0.4) | (overlap_df["b_covered_by_a_time_frac"] > 0.4)
    ][["family_a", "family_b", "a_covered_by_b_time_frac", "b_covered_by_a_time_frac"]]

    # --- Ranking ---
    verdict_rank = {"PHENOMENON_PRESENT": 3, "WEAK_SIGNAL": 2, "PHENOMENON_NOT_OBSERVED": 1, "INSUFFICIENT_DATA": 0}
    econ_rank = {"STRONG_EFFECT": 3, "POTENTIALLY_TRADEABLE": 2, "ECONOMICALLY_TOO_SMALL": 1, "INSUFFICIENT_DATA": 0, None: 0}
    ranking_rows = []
    for row in comparison_rows:
        breadth_score = (row["n_symbols"] / 35.0 + row["n_days"] / max(comparison_df["n_days"])) / 2.0
        stability_score = 0.0 if row["effect_surface_instability"] else 1.0
        conc_score = 1.0 - (row["top1_symbol_share"] or 0.0)
        ranking_rows.append({
            "family": row["family"],
            "verdict_score": verdict_rank[row["verdict"]],
            "econ_score": econ_rank.get(row["economic_classification"], 0),
            "breadth_score": round(breadth_score, 3),
            "stability_score": stability_score,
            "events_per_week": row["events_per_week"],
            "concentration_score": round(conc_score, 3),
            "composite": round(
                verdict_rank[row["verdict"]] * 3
                + econ_rank.get(row["economic_classification"], 0) * 2
                + breadth_score * 2
                + stability_score * 2
                + conc_score * 1,
                3,
            ),
        })
    ranking_df = pd.DataFrame(ranking_rows).sort_values("composite", ascending=False).reset_index(drop=True)
    ranking_df.to_csv(RESULTS_DIR / "effect_surface_summary.csv", index=False)

    phenomenon_ranking = {
        "method": "composite = 3*verdict_tier + 2*econ_tier + 2*breadth_score + 2*stability_score(1 if stable else 0) + 1*concentration_score(1-top1_share). Documented, fixed BEFORE inspecting whether it changes the ordering; not tuned to produce a preferred result.",
        "ranking": ranking_df.to_dict(orient="records"),
    }
    with open(RESULTS_DIR / "phenomenon_ranking.json", "w", encoding="utf-8") as f:
        json.dump(phenomenon_ranking, f, indent=2, default=str)

    # --- cross_family_summary.json ---
    cross_summary = {
        "task": "67B cross-family synthesis",
        "representative_definitions": REPRESENTATIVE,
        "event_overlap_matrix": overlap_df.to_dict(orient="records"),
        "redundant_pairs_same_symbol_time_over_40pct": redundant_pairs.to_dict(orient="records"),
        "redundancy_methodology_note": "Flag is based on same-symbol-TIME overlap (5-minute tolerance), not same-symbol-day: with 63 DEVELOPMENT trading days and several families firing thousands of events, same-symbol-day overlap is close to saturated for purely combinatorial reasons (frequently >=0.99 in one direction) and is not a meaningful redundancy signal on this dataset. See event_overlap_matrix for both.",
        "family_comparison": comparison_df.to_dict(orient="records"),
        "ranking": phenomenon_ranking["ranking"],
    }
    with open(RESULTS_DIR / "cross_family_summary.json", "w", encoding="utf-8") as f:
        json.dump(cross_summary, f, indent=2, default=str)

    # --- cross_family_summary.md ---
    md = ["# Task 67B - Cross-Family Synthesis\n"]
    md.append("## Family comparison (representative definition per family)\n")
    md.append("| Family | Verdict | Econ | n_dedup | symbols | days | evt/wk | unstable? | top1 sym share | excess 60m [CI] |")
    md.append("|---|---|---|---|---|---|---|---|---|---|")
    for row in comparison_rows:
        e60 = row.get("excess_60m")
        lo, hi = row.get("ci_low_60m"), row.get("ci_high_60m")
        e60s = f"{round(e60,4)} [{round(lo,4) if lo is not None else 'n/a'}, {round(hi,4) if hi is not None else 'n/a'}]" if e60 is not None else "n/a"
        md.append(
            f"| {row['family']} | {row['verdict']} | {row['economic_classification']} | "
            f"{row['n_dedup_events']} | {row['n_symbols']} | {row['n_days']} | {row['events_per_week']} | "
            f"{row['effect_surface_instability']} | {round(row['top1_symbol_share'] or 0, 3)} | {e60s} |"
        )
    md.append("\n## Ranking (composite score, method documented in phenomenon_ranking.json)\n")
    md.append("| Rank | Family | Verdict tier | Econ tier | Breadth | Stability | Concentration | Composite |")
    md.append("|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(ranking_df.itertuples(), 1):
        md.append(f"| {i} | {r.family} | {r.verdict_score} | {r.econ_score} | {r.breadth_score} | {r.stability_score} | {r.concentration_score} | {r.composite} |")
    md.append("\n## Redundant family pairs (>40% same-symbol-TIME overlap, 5-min tolerance)\n")
    md.append(
        "Same-symbol-DAY overlap is NOT used for this flag -- with only 63 DEVELOPMENT trading days "
        "and several families firing thousands of events across nearly every symbol, day-level overlap "
        "is close to saturated (frequently >=0.99 in one direction) for purely combinatorial reasons and "
        "says little about whether two families detect the same episodes. Same-symbol-TIME overlap (is "
        "family A firing within 5 minutes of family B, not just on the same calendar day) is the "
        "meaningful signal.\n"
    )
    if len(redundant_pairs):
        md.append(_df_to_md_table(redundant_pairs))
    else:
        md.append("None found at the 40% same-symbol-time threshold -- the 6 families are largely detecting materially different episodes, not re-labeling the same underlying moves.")
    md.append("\n## Event overlap matrix (full, 5-minute same-symbol-time tolerance)\n")
    md.append(_df_to_md_table(overlap_df.round(3)))
    (RESULTS_DIR / "cross_family_summary.md").write_text("\n".join(md), encoding="utf-8")

    print("[cross_family_synthesis] wrote outputs to", RESULTS_DIR)
    print(ranking_df[["family", "composite"]].to_string(index=False))


if __name__ == "__main__":
    main()
