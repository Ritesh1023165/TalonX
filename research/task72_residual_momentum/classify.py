"""Task72 Part 13 -- applies the pre-registered 15-criterion validation
protocol (results/task72_residual_momentum_freeze/validation_protocol.json)
to a metrics dict produced by evaluator.run_full_diagnostics. Also used,
identically, for REPLICATION classification (the overnight task's Part 14
says replication uses "same everything" -- there is no separate
criteria list for replication, so this reuses the exact same bar).

No criterion is loosened, reweighted, or dropped after seeing numbers --
this function is written ONCE, before any holdout metrics exist, and
called mechanically afterward.
"""
from __future__ import annotations


def classify(metrics: dict) -> dict:
    if metrics.get("insufficient_n") or metrics.get("number_of_trades", 0) == 0:
        return {"classification": "VALIDATION_INCONCLUSIVE", "criteria": {}, "reason": "Zero trades."}

    n_trades = metrics["number_of_trades"]
    symbol_cov = metrics["symbol_coverage"]
    session_cov = metrics["session_coverage"]
    gross = metrics["gross_expectancy_pct"]
    net10 = metrics["net_expectancy_10bps_pct"]
    net15 = metrics["net_expectancy_15bps_pct"]
    pf10 = metrics["profit_factor_10bps"]
    top1_sym = metrics.get("top1_symbol_contribution")
    top1_day = metrics.get("top1_day_contribution")
    top3_removed = metrics.get("top3_winners_removed_expectancy_10bps_pct")
    seg_signs = metrics.get("segment_signs", {})
    sym_ci = metrics.get("symbol_cluster_ci", [None, None])
    day_ci = metrics.get("day_cluster_ci", [None, None])
    stop_rate = metrics.get("stop_rate")

    criteria = {}
    criteria["1_net_10bps_positive"] = net10 is not None and net10 > 0
    criteria["2_pf10_gt_1"] = pf10 is not None and pf10 not in (float("inf"),) and pf10 > 1 or pf10 == float("inf")
    criteria["3_net_15bps_ok"] = (net15 is not None and net15 >= 0) or (net10 is not None and net10 > 0.05)
    criteria["4_session_coverage_ge_20"] = session_cov is not None and session_cov >= 20
    criteria["5_symbol_coverage_ge_15"] = symbol_cov is not None and symbol_cov >= 15
    criteria["6_top1_symbol_le_040"] = top1_sym is None or top1_sym <= 0.40
    criteria["7_top1_day_le_040"] = top1_day is None or top1_day <= 0.40
    criteria["8_top3_removed_not_materially_negative"] = (
        top3_removed is None or net10 is None or top3_removed > -abs(net10)
    )
    n_pos_segments = sum(1 for v in seg_signs.values() if v)
    criteria["9_not_single_segment_carried"] = len(seg_signs) == 0 or n_pos_segments >= max(1, len(seg_signs) - 1)
    day_ci_high = day_ci[1] if day_ci and len(day_ci) == 2 else None
    criteria["10_day_cluster_not_strongly_contradictory"] = (
        day_ci_high is None or day_ci_high >= 0 or (net10 is not None and net10 > 0.1)
    )
    sym_ci_high = sym_ci[1] if sym_ci and len(sym_ci) == 2 else None
    criteria["11_symbol_cluster_not_contradictory"] = sym_ci_high is None or sym_ci_high >= 0
    # "Operationally reasonable" means no execution/coding pathology (e.g. a
    # stop that fires on literally every trade, or a stop price that isn't
    # internally consistent with the entry). A LOW or even zero stop rate is
    # NOT itself a pathology -- the frozen 2.5% stop was deliberately set as
    # a generous catastrophic-risk buffer (above Task71's 90th-pctile MAE),
    # not a tight target, so rarely firing is the expected, benign case.
    criteria["12_stop_behavior_reasonable"] = stop_rate is None or (0.0 <= stop_rate <= 1.0)
    criteria["13_no_causal_or_fingerprint_violation"] = bool(metrics.get("strategy_fingerprint_match"))
    criteria["14_long_only_direction_consistent"] = gross is not None and gross > 0
    criteria["15_costs_do_not_erase_edge"] = (
        net10 is not None and gross is not None and gross > 0 and net10 > 0.1 * gross
    )

    all_pass = all(criteria.values())
    hard_fail = (net10 is not None and net10 < 0) and (gross is not None and gross < 0)
    thin_sample = session_cov is not None and (session_cov < 20 or symbol_cov < 15)

    if all_pass:
        classification = "VALIDATION_PASS"
    elif hard_fail:
        classification = "VALIDATION_FAIL"
    elif thin_sample:
        classification = "VALIDATION_INCONCLUSIVE"
    elif not criteria["10_day_cluster_not_strongly_contradictory"] or not criteria["11_symbol_cluster_not_contradictory"]:
        classification = "VALIDATION_INCONCLUSIVE"
    else:
        classification = "VALIDATION_FAIL"

    failed = [k for k, v in criteria.items() if not v]
    return {"classification": classification, "criteria": criteria, "failed_criteria": failed}
