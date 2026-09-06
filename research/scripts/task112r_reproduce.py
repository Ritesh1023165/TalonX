"""
task112r_reproduce.py -- Task 112R Gate G2 : frozen Task 107B reproducibility
                         + runtime-episode re-evaluation
==========================================================================
G2a: re-run the frozen Task 107B +10D/20bps primary spec on the FROZEN
     research episode parquet -> must reproduce the analysis.json headline.
G2b: re-run the SAME frozen spec on the RUNTIME detector's episode set
     (talonx_v2.cluster_engine) -> the runtime's own evidence.  If the
     paper-candidate gate still holds, the runtime is validated.

NO parameter research.  NO strategy change.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "results" / "task112r_release_rehearsal"
OUT.mkdir(parents=True, exist_ok=True)


def _load(name, rel):
    s = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


t107b = _load("t107b", "research/scripts/task107b_form4_cluster.py")
t112rp = _load("t112rp", "research/scripts/task112r_parity.py")

PANEL = ROOT / "results/task95g_broad_cross_sectional/_daily"
FROZEN = json.loads((ROOT / "results/task107b_form4_cluster/analysis.json").read_text())


def _eval_p2(ep: pd.DataFrame, label: str) -> dict:
    ep = ep.copy()
    ep["entry_session"] = pd.to_datetime(ep["entry_session"])
    for c in ("n_distinct_owners", "agg_value", "any_officer", "any_director", "any_ten_pct"):
        if c not in ep.columns:
            ep[c] = 0
    rr = t107b.build_returns(ep)
    panel = {f.stem.upper() for f in PANEL.glob("*.csv")}
    p2 = rr[rr["raw_10"].notna() & rr.issuer_sym.isin(panel)].copy()
    res = t107b.evaluate(p2, label)
    h = res["h10"]
    n20 = h["net_20bps"]
    return {
        "label": label, "N": int(len(p2)),
        "net20_mean_pct": round(n20["mean"] * 100, 3),
        "pf": round(n20["profit_factor"], 3),
        "win_rate_pct": round(n20["win_rate"] * 100, 1),
        "discovery_net20_pct": round(h["discovery_net20"].get("mean", float("nan")) * 100, 3),
        "holdout_net20_pct": round(h["holdout_net20"].get("mean", float("nan")) * 100, 3),
        "boot_ci_net20_pct": [round(x * 100, 3) for x in h["boot_ci_net20"]],
        "weekcluster_ci_net20_pct": [round(x * 100, 3) for x in h["weekcluster_ci_net20"]],
        "drop_top1_net20_pct": round(h["concentration"]["drop_top1_mean_net20"] * 100, 3),
        "drop_top3_net20_pct": round(h["concentration"]["drop_top3_mean_net20"] * 100, 3),
        "drop_top_issuer_net20_pct": round(h["concentration"]["drop_top_issuer_mean_net20"] * 100, 3),
        "max_issuer_share_pos": round((h["concentration"]["max_issuer_share_of_positive_sum"] or 0) * 100, 2),
    }


def _gate(m: dict) -> dict:
    return {
        "net20>0": m["net20_mean_pct"] > 0,
        "holdout>0": m["holdout_net20_pct"] > 0,
        "discovery>0": m["discovery_net20_pct"] > 0,
        "PF>1": m["pf"] > 1.0,
        "drop_top1>=0": m["drop_top1_net20_pct"] >= 0,
        "drop_top3>=0": m["drop_top3_net20_pct"] >= 0,
        "drop_top_issuer>0": m["drop_top_issuer_net20_pct"] > 0,
        "N>=300": m["N"] >= 300,
        "bootstrap_ci_lower>0": m["boot_ci_net20_pct"][0] > 0,
    }


def main() -> int:
    P = t112rp.load_P()

    # G2a -- frozen research parquet
    research_ep = pd.read_parquet(ROOT / "results/task107a_form4_feasibility/_build/episodes_w10_mo2.parquet")
    a = _eval_p2(research_ep, "G2a_frozen_research_parquet")

    # G2b -- runtime detector
    runtime_ep = t112rp.runtime_episodes(P)
    b = _eval_p2(runtime_ep, "G2b_runtime_detector")

    frozen = {
        "N": FROZEN["coverage"]["P2_in_panel_n"],
        "net20_mean_pct": round(FROZEN["P2_in_panel"]["h10"]["net_20bps"]["mean"] * 100, 3),
        "pf": round(FROZEN["P2_in_panel"]["h10"]["net_20bps"]["profit_factor"], 3),
        "holdout_net20_pct": round(FROZEN["P2_in_panel"]["h10"]["holdout_net20"]["mean"] * 100, 3),
        "discovery_net20_pct": round(FROZEN["P2_in_panel"]["h10"]["discovery_net20"]["mean"] * 100, 3),
        "boot_ci_net20_pct": [round(x * 100, 3) for x in FROZEN["P2_in_panel"]["h10"]["boot_ci_net20"]],
    }

    report = {
        "frozen_analysis_json": frozen,
        "G2a_reproduce_frozen": a,
        "G2a_matches_frozen": abs(a["net20_mean_pct"] - frozen["net20_mean_pct"]) < 0.05
                              and abs(a["pf"] - frozen["pf"]) < 0.02
                              and a["N"] == frozen["N"],
        "G2b_runtime_detector": b,
        "G2b_gate": _gate(b),
        "G2b_paper_candidate_gate_pass": all(_gate(b).values()),
        "delta_runtime_vs_frozen_net20_pct": round(b["net20_mean_pct"] - frozen["net20_mean_pct"], 3),
    }
    (OUT / "backtest_reproducibility.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
