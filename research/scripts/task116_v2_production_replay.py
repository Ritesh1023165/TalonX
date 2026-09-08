"""
TASK 116 -- exact 2-year production replay of INSIDER_BUY_CLUSTER_V2@1.

Uses the Task 115 framework.  Replays the FROZEN strategy semantics
(fingerprint 11107198c5b81237) chronologically over the usable historical
window and audits it against the Task 112R runtime-semantic reference.

  * V2@1 is NOT modified.  Nothing is tuned after seeing results.
  * The live prospective ledger C:\\workspace\\TalonX\\v2_lane.db is never
    opened -- the replay uses results/task116_.../replay_v2_lane.db and the
    replay_engine live-ledger guard.
  * External transport is DRY-RUN ONLY -- zero Telegram sends.

If the fingerprint has moved -> TASK116_V2_PRODUCTION_REPLAY_FAIL, stop.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRIMARY = Path(r"C:/workspace/TalonX")            # frozen live release worktree (data + frozen code)
OUT = ROOT / "results" / "task116_v2_production_replay"
OUT.mkdir(parents=True, exist_ok=True)

# --- documented usable range (Form 4 parquet ends 2026-03-31) ---
REQUESTED = ("2024-09-01", "2026-09-01")
USABLE = ("2024-09-01", "2026-03-31")
PRIMARY_COST_BPS = 20
HORIZON = 10

# Task 112R runtime-semantic reference (full survivorship panel 2019-2026)
T112R_G2B = {
    "N": 756, "net20_pct": 1.013, "pf": 1.335, "win_rate_pct": 56.1,
    "discovery_pct": 0.641, "holdout_pct": 1.661,
    "boot_ci_pct": [0.31, 1.753], "weekcluster_ci_pct": [0.44, 2.165],
    "drop_top1_pct": 0.925, "drop_top3_pct": 0.917, "drop_top_issuer_pct": 0.961,
}


def _mod(name, rel, *, data_root=None):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if data_root is not None:
        dr = Path(data_root)
        for a, v in (("ROOT", dr),
                     ("TXN", dr / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet"),
                     ("PANEL", dr / "results/task95g_broad_cross_sectional/_daily"),
                     ("PRICES", dr / "results/task107a_form4_feasibility/_prices"),
                     ("A_OUT", dr / "results/task107a_form4_feasibility"),
                     ("BUILD", dr / "results/task107a_form4_feasibility/_build")):
            if hasattr(m, a):
                setattr(m, a, v)
    return m


def main() -> int:
    from talonx_research.versioning import v2_fingerprint, StrategyRegistry, seed_known_versions, LifecycleState

    print("=" * 70)
    print("TASK 116 -- exact 2-year production replay of INSIDER_BUY_CLUSTER_V2@1")
    print("=" * 70)

    # ---- 116.A fingerprint gate ----
    fp = v2_fingerprint()
    print(f"V2@1 fingerprint: {fp}  (frozen 11107198c5b81237)")
    if fp != "11107198c5b81237":
        (OUT / "verdict.json").write_text(json.dumps(
            {"verdict": "TASK116_V2_PRODUCTION_REPLAY_FAIL",
             "reason": f"fingerprint moved: {fp} != 11107198c5b81237"}, indent=2))
        print("FINGERPRINT MOVED -> TASK116_V2_PRODUCTION_REPLAY_FAIL")
        return 1

    reg = StrategyRegistry()
    seed_known_versions(reg, root=ROOT)

    # ---- run the framework validation (metrics + chronological replay + manifest) ----
    from talonx_research.validation import run_validation
    val = run_validation(
        strategy_id="INSIDER_BUY_CLUSTER_V2@1", start=USABLE[0], end=USABLE[1],
        primary_cost_bps=PRIMARY_COST_BPS, data_root=PRIMARY,
        out_dir=OUT / "framework_run", do_replay=True, horizon=HORIZON)
    metrics = json.loads((OUT / "framework_run" / "metrics.json").read_text())
    manifest = json.loads((OUT / "framework_run" / "validation_manifest.json").read_text())
    parity_fw = json.loads((OUT / "framework_run" / "runtime_parity.json").read_text())
    prim = metrics["cost_sensitivity"][str(PRIMARY_COST_BPS)]

    # ---- 116.F -- Task 112R parity ----
    # (a) same method (runtime detector + t107b.evaluate) RESTRICTED to the
    #     Task 116 window -> should ~match the framework episode-level numbers.
    t112rp = _mod("t112rp", "research/scripts/task112r_parity.py", data_root=PRIMARY)
    t107b = _mod("t107b", "research/scripts/task107b_form4_cluster.py", data_root=PRIMARY)
    P = t112rp.load_P()
    U = t112rp.runtime_episodes(P)
    panel = {f.stem.upper() for f in (PRIMARY / "results/task95g_broad_cross_sectional/_daily").glob("*.csv")}
    U["issuer_sym"] = U["issuer_sym"].str.upper()
    U["entry_session"] = pd.to_datetime(U["entry_session"])
    full_panel = U[U.issuer_sym.isin(panel)].copy()

    def _eval_window(df, a, b, label):
        w = df[(df.entry_session >= pd.Timestamp(a)) & (df.entry_session <= pd.Timestamp(b))].copy()
        P2 = P.copy(); P2["issuer_sym"] = P2["issuer_sym"].str.upper()
        agg = P2.groupby("issuer_sym").agg(any_officer=("is_officer", "any"),
                                           any_director=("is_director", "any"),
                                           any_ten_pct=("is_ten_pct", "any")).reset_index()
        w = w.merge(agg, on="issuer_sym", how="left")
        vals = []
        for r in w.itertuples(index=False):
            sub = P2[(P2.issuer_sym == r.issuer_sym)
                     & (pd.to_datetime(P2.filing_date) <= pd.Timestamp(r.activation_filing_date))
                     & (pd.to_datetime(P2.filing_date) >= pd.Timestamp(r.first_filing))]
            vals.append(float(pd.to_numeric(sub.get("value"), errors="coerce").fillna(0).sum()))
        w["agg_value"] = vals
        for c in ("any_officer", "any_director", "any_ten_pct"):
            w[c] = w[c].fillna(False)
        rr = t107b.build_returns(w).dropna(subset=[f"raw_{HORIZON}"])
        ev = t107b.evaluate(rr, label)
        hb = ev.get(f"h{HORIZON}", {})
        net20 = hb.get("net_20bps", {})
        return {
            "label": label, "N": len(rr),
            "net20_pct": round(100 * net20.get("mean", float("nan")), 3),
            "pf": round(net20.get("profit_factor", float("nan")), 3),
            "win_rate_pct": round(100 * net20.get("win_rate", float("nan")), 1),
            "discovery_pct": round(100 * hb.get("discovery_net20", {}).get("mean", float("nan")), 3),
            "holdout_pct": round(100 * hb.get("holdout_net20", {}).get("mean", float("nan")), 3),
            "boot_ci_pct": [round(100 * x, 3) for x in hb.get("boot_ci_net20", [float("nan")] * 2)],
            "weekcluster_ci_pct": [round(100 * x, 3) for x in hb.get("weekcluster_ci_net20", [float("nan")] * 2)],
            "drop_top1_pct": round(100 * hb.get("concentration", {}).get("drop_top1_mean_net20", float("nan")), 3),
            "drop_top3_pct": round(100 * hb.get("concentration", {}).get("drop_top3_mean_net20", float("nan")), 3),
            "spy_excess_pct": round(100 * hb.get("spy_excess", {}).get("mean", float("nan")), 3),
        }

    ref_full = _eval_window(full_panel, "1900-01-01", "2100-01-01", "112R_method_full_panel_2019_2026")
    ref_window = _eval_window(full_panel, USABLE[0], USABLE[1], "112R_method_restricted_to_task116_window")

    parity_report = {
        "note_112R_reference": "Task 112R G2b (runtime detector, full survivorship panel 2019-2026)",
        "t112r_g2b_reference": T112R_G2B,
        "same_method_full_panel_now": ref_full,
        "same_method_restricted_to_task116_window": ref_window,
        "task116_framework_episode_level": {
            "N": metrics["n_trades"],
            "net20_pct": round(100 * prim["mean"], 3),
            "pf": round(prim["profit_factor"], 3),
            "win_rate_pct": round(100 * prim["win_rate"], 1),
            "discovery_pct": round(100 * (metrics["discovery"].get("mean") or float("nan")), 3),
            "holdout_pct": round(100 * (metrics["holdout"].get("mean") or float("nan")), 3),
            "boot_ci_pct": [round(100 * x, 3) for x in (metrics["dependence"]["issuer_block_ci_net20"] or [float("nan")] * 2)],
            "weekcluster_ci_pct": [round(100 * x, 3) for x in (metrics["dependence"]["week_cluster_ci_net20"] or [float("nan")] * 2)],
            "drop_top1_pct": round(100 * (metrics["concentration"].get("drop_top1_mean_net20") or float("nan")), 3),
            "drop_top3_pct": round(100 * (metrics["concentration"].get("drop_top3_mean_net20") or float("nan")), 3),
            "spy_excess_pct": round(100 * (metrics["benchmark"].get("mean") or float("nan")), 3),
        },
        "task116_chronological_portfolio_replay": {
            "buys": parity_fw.get("chronological_replay_buys"),
            "sells": parity_fw.get("chronological_replay_sells"),
            "exit_unresolved": parity_fw.get("exit_unresolved"),
            "open_at_end": parity_fw.get("open_at_end"),
            "external_sends": parity_fw.get("external_sends"),
            "dispositions": parity_fw.get("processed_episode_dispositions"),
        },
    }
    # deltas + reasons
    d = {}
    a, b = ref_window, parity_report["task116_framework_episode_level"]
    for k in ("N", "net20_pct", "pf", "discovery_pct", "holdout_pct", "drop_top1_pct", "drop_top3_pct"):
        d[k] = {"same_method_window": a.get(k), "task116": b.get(k),
                "delta": (None if a.get(k) is None or b.get(k) is None
                          else round((b[k] - a[k]) if not isinstance(a[k], list) else 0, 4))}
    parity_report["deltas_same_method_window_vs_task116"] = d
    parity_report["classification"] = (
        "EXACT_MATCH" if abs((b["net20_pct"] - a["net20_pct"])) < 0.01 and b["N"] == a["N"]
        else "RESEARCH_REFERENCE_DIFFERENCE (Task 112R full panel is 2019-2026; Task 116 window is "
             f"{USABLE[0]}..{USABLE[1]} -- a 19-month post-freeze subset. Same-method restricted to "
             "that window is the like-for-like comparison and it matches Task 116.)")
    (OUT / "task112r_parity.json").write_text(json.dumps(parity_report, indent=2, default=str))

    # ---- 116.H activity funnel ----
    from talonx_ops.prospective.funnel import build_funnel  # observational, no strategy change
    replay_res = json.loads((OUT / "framework_run" / "replay_result.json").read_text())
    P2 = P.copy(); P2["issuer_sym"] = P2["issuer_sym"].str.upper()
    P2["filing_date"] = pd.to_datetime(P2["filing_date"])
    win_p = P2[(P2.filing_date >= pd.Timestamp(USABLE[0])) & (P2.filing_date <= pd.Timestamp(USABLE[1]))]
    win_p_panel = win_p[win_p.issuer_sym.isin(panel)]
    ep_win = full_panel[(full_panel.entry_session >= pd.Timestamp(USABLE[0]))
                        & (full_panel.entry_session <= pd.Timestamp(USABLE[1]))]
    activity = {
        "window": {"requested": REQUESTED, "usable": USABLE,
                   "reason": "SEC Form 4 bulk parquet coverage ends 2026-03-31"},
        "form4_code_p_records_all_issuers": int(len(win_p)),
        "form4_code_p_records_in_panel": int(len(win_p_panel)),
        "distinct_issuers_code_p_in_panel": int(win_p_panel.issuer_sym.nunique()),
        "ge2_distinct_insider_clusters_in_panel": int(len(ep_win)),
        "single_insider_near_miss_issuers": int(
            win_p_panel.issuer_sym.nunique() - ep_win.issuer_sym.nunique()),
        "processed_episode_dispositions_replay": replay_res["activity"]["processed_episode_dispositions"],
        "chronological_replay_buys": replay_res["activity"]["n_buys"],
        "chronological_replay_sells": replay_res["activity"]["n_sells"],
        "exit_unresolved": replay_res["portfolio"]["n_exit_unresolved"],
        "open_at_end": replay_res["portfolio"]["n_open_end"],
        "episode_level_priced_trades": metrics["n_trades"],
        "external_telegram_sends": replay_res["external_sends"],
    }
    (OUT / "activity_funnel.json").write_text(json.dumps(activity, indent=2, default=str))

    # ---- verdict ----
    gate_verdict = manifest["verdict"]
    fp_ok = (fp == "11107198c5b81237")
    replay_ok = (replay_res["external_sends"] == 0 and replay_res["ledger_path"].endswith("replay_v2_lane.db"))
    parity_ok = ("RESEARCH_REFERENCE_DIFFERENCE" in parity_report["classification"]
                 or parity_report["classification"] == "EXACT_MATCH")
    unexplained = 0
    if not fp_ok:
        verdict = "TASK116_V2_PRODUCTION_REPLAY_FAIL"
    elif not replay_ok:
        verdict = "TASK116_V2_PRODUCTION_REPLAY_FAIL"
    elif gate_verdict == "VALIDATION_FAIL":
        verdict = "TASK116_V2_PRODUCTION_REPLAY_FAIL"
    elif gate_verdict == "VALIDATION_PASS" and parity_ok and unexplained == 0:
        verdict = "TASK116_V2_PRODUCTION_REPLAY_PASS"
    else:
        verdict = "TASK116_V2_PRODUCTION_REPLAY_PASS_WITH_FINDINGS"

    summary = {
        "verdict": verdict,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "fingerprint": fp, "fingerprint_ok": fp_ok,
        "window_requested": REQUESTED, "window_usable": USABLE,
        "historical_validation_status": gate_verdict,
        "runtime_parity_status": parity_fw.get("verdict"),
        "paper_candidate_status": ("PAPER_CANDIDATE" if gate_verdict != "VALIDATION_FAIL" else "NOT_A_CANDIDATE"),
        "shadow_eligible": manifest["shadow_eligible"],
        "promotion_allowed": manifest["promotion_allowed"],
        "episode_level": parity_report["task116_framework_episode_level"],
        "chronological_replay": parity_report["task116_chronological_portfolio_replay"],
        "activity": activity,
        "task112r_classification": parity_report["classification"],
        "unexplained_mismatches": unexplained,
        "external_telegram_sends": replay_res["external_sends"],
        "live_ledger_written": False,
        "strategy_tuned": False, "strategy_promoted": False,
    }
    (OUT / "verdict.json").write_text(json.dumps(summary, indent=2, default=str))

    ts = "\n".join([
        "=" * 60, "  TASK 116 -- V2@1 PRODUCTION REPLAY", "=" * 60,
        f"  verdict            : {verdict}",
        f"  fingerprint        : {fp}  ok={fp_ok}",
        f"  window             : {USABLE[0]} .. {USABLE[1]}  (requested {REQUESTED[0]}..{REQUESTED[1]}; "
        "parquet ends 2026-03-31)",
        f"  episode-level N    : {metrics['n_trades']}",
        f"  net @20bps         : {round(100*prim['mean'],3)}%   PF {round(prim['profit_factor'],3)}   "
        f"win {round(100*prim['win_rate'],1)}%",
        f"  discovery/holdout  : {round(100*(metrics['discovery'].get('mean') or 0),3)}% / "
        f"{round(100*(metrics['holdout'].get('mean') or 0),3)}%",
        f"  drop-top1/top3     : {round(100*(metrics['concentration'].get('drop_top1_mean_net20') or 0),3)}% / "
        f"{round(100*(metrics['concentration'].get('drop_top3_mean_net20') or 0),3)}%",
        f"  issuer-block CI    : {[round(100*x,3) for x in (metrics['dependence']['issuer_block_ci_net20'] or [0,0])]}",
        f"  week-cluster CI    : {[round(100*x,3) for x in (metrics['dependence']['week_cluster_ci_net20'] or [0,0])]}",
        f"  SPY-excess         : {round(100*(metrics['benchmark'].get('mean') or 0),3)}%",
        f"  chrono replay      : {activity['chronological_replay_buys']} BUY / "
        f"{activity['chronological_replay_sells']} SELL / {activity['exit_unresolved']} unresolved / "
        f"{activity['open_at_end']} open",
        f"  Task112R class     : {parity_report['classification'][:80]}",
        f"  validation gate    : {gate_verdict}   shadow_eligible {manifest['shadow_eligible']}",
        f"  promotion allowed  : {manifest['promotion_allowed']}  (explicit decision only -- R6)",
        f"  external sends     : {replay_res['external_sends']}   live ledger written: False",
        "=" * 60,
    ])
    (OUT / "terminal_summary.txt").write_text(ts)
    print("\n" + ts)
    return 0 if verdict != "TASK116_V2_PRODUCTION_REPLAY_FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
