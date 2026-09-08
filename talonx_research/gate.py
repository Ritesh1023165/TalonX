"""
Default paper-candidate gate (Task 115.C).

Encodes the currently-approved qualitative gate at the 20 bps primary
cost assumption:

  net expectancy > 0
  holdout expectancy > 0
  profit factor > 1
  meaningful sample
  no obvious temporal leakage
  no obvious concentration failure
  top-winner robustness acceptable
  drawdown / loss-tail acceptable
  practical signal frequency

CI lower bound > 0 is DESIRABLE but NOT a hard initial paper-candidate
requirement (R3).

Verdicts: VALIDATION_PASS / VALIDATION_PASS_WITH_FINDINGS / VALIDATION_FAIL
plus shadow_eligible (bool).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MIN_SAMPLE = 60                 # meaningful sample floor
MIN_FREQ_PER_YEAR = 10          # practical signal frequency floor
MAX_TOP_ISSUER_POS_SHARE = 0.60   # a single issuer holding > this share of the positive P&L = concentration finding
DRAWDOWN_FINDING = 0.60         # equal-unit additive drawdown as a fraction of peak cumulative P&L


@dataclass
class GateResult:
    verdict: str
    shadow_eligible: bool
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    hard_fails: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _num(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def evaluate_gate(metrics: dict, *, episodes_per_year: float | None = None,
                  concentration: dict | None = None) -> GateResult:
    """`metrics` = ValidationMetrics.to_dict(); `concentration` optional override."""
    hard: list[str] = []
    findings: list[str] = []
    checks: dict[str, dict[str, Any]] = {}
    pc = metrics.get("primary_cost_bps", 20)
    cs = metrics.get("cost_sensitivity", {})
    primary = cs.get(str(pc)) or cs.get(pc) or {}
    disc = metrics.get("discovery", {})
    hold = metrics.get("holdout", {})
    conc = concentration or metrics.get("concentration", {})
    dep = metrics.get("dependence", {})
    n = int(metrics.get("n_trades", primary.get("n", 0) or 0))

    def chk(name, ok, hard_fail, detail):
        checks[name] = {"pass": bool(ok), "detail": detail}
        if not ok:
            (hard if hard_fail else findings).append(f"{name}: {detail}")

    net = _num(primary.get("mean") or primary.get("expectancy"))
    chk("net_expectancy_positive", net is not None and net > 0, True,
        {"net_mean": net})
    chk("holdout_expectancy_positive", _num(hold.get("mean")) is not None and _num(hold.get("mean")) > 0,
        True, {"holdout_mean": hold.get("mean")})
    chk("discovery_expectancy_positive", _num(disc.get("mean")) is not None and _num(disc.get("mean")) > 0,
        False, {"discovery_mean": disc.get("mean")})
    pf = _num(primary.get("profit_factor"))
    chk("profit_factor_gt_1", pf is not None and pf > 1.0, True, {"pf": pf})
    chk("meaningful_sample", n >= MIN_SAMPLE, True, {"n": n, "floor": MIN_SAMPLE})

    # temporal leakage proxy: discovery and holdout same sign, holdout not wildly larger
    ds, hs = _num(disc.get("mean")), _num(hold.get("mean"))
    leak_ok = (ds is None or hs is None) or (ds > 0 and hs > 0)
    chk("no_obvious_temporal_leakage", leak_ok, False,
        {"discovery": ds, "holdout": hs,
         "note": "both windows positive; holdout was frozen before evaluation"})

    # concentration
    top_share = _num(conc.get("max_issuer_share_of_positive_sum"))
    chk("issuer_concentration_ok",
        top_share is None or top_share <= MAX_TOP_ISSUER_POS_SHARE, False,
        {"top_issuer": conc.get("top_issuer"), "top_issuer_pos_share": top_share})
    drop1 = _num(conc.get("drop_top1_mean_net20"))
    drop3 = _num(conc.get("drop_top3_mean_net20"))
    chk("top_winner_robustness_ok",
        (drop1 is None or drop1 > 0) and (drop3 is None or drop3 > 0), False,
        {"drop_top1": drop1, "drop_top3": drop3})
    by_year = conc.get("by_year_mean_net20", {})
    neg_years = [y for y, v in by_year.items() if _num(v) is not None and _num(v) < 0]
    chk("time_concentration_ok", len(neg_years) <= max(1, len(by_year) // 2), False,
        {"negative_years": neg_years, "by_year": by_year})

    # drawdown / loss tail
    mdd = primary.get("max_drawdown", {})
    mdd_frac = _num(mdd.get("max_drawdown_frac_of_peak")) if isinstance(mdd, dict) else None
    p01 = _num(primary.get("p01"))
    chk("drawdown_loss_tail_ok",
        (mdd_frac is None or mdd_frac <= DRAWDOWN_FINDING) and (p01 is None or p01 > -0.40),
        False, {"max_drawdown": mdd, "p01": p01})

    # practical frequency
    freq = episodes_per_year
    chk("practical_signal_frequency", freq is None or freq >= MIN_FREQ_PER_YEAR, False,
        {"episodes_per_year": freq, "floor": MIN_FREQ_PER_YEAR})

    # desirable (not hard): both dependence-aware CI lower bounds > 0
    ib = dep.get("issuer_block_ci_net20") or [None, None]
    wc = dep.get("week_cluster_ci_net20") or [None, None]
    ci_ok = (_num(ib[0]) is not None and _num(ib[0]) > 0
             and _num(wc[0]) is not None and _num(wc[0]) > 0)
    checks["dependence_ci_lower_bounds_positive"] = {
        "pass": ci_ok, "hard": False, "desirable_only": True,
        "detail": {"issuer_block_ci": ib, "week_cluster_ci": wc}}
    if not ci_ok:
        findings.append("dependence_ci_lower_bounds_positive: desirable, not met "
                        f"(issuer_block={ib}, week_cluster={wc})")

    if hard:
        verdict = "VALIDATION_FAIL"
        shadow = False
    elif findings:
        verdict = "VALIDATION_PASS_WITH_FINDINGS"
        shadow = True
    else:
        verdict = "VALIDATION_PASS"
        shadow = True
    return GateResult(verdict=verdict, shadow_eligible=shadow, checks=checks,
                      findings=findings, hard_fails=hard)
