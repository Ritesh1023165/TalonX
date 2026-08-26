"""Task72 -- pre-registered classification logic tests."""
from __future__ import annotations

from research.task72_residual_momentum.classify import classify


def _base_metrics(**overrides) -> dict:
    m = {
        "number_of_trades": 170, "symbol_coverage": 35, "session_coverage": 24,
        "gross_expectancy_pct": 0.30, "net_expectancy_10bps_pct": 0.20, "net_expectancy_15bps_pct": 0.15,
        "profit_factor_10bps": 1.5, "top1_symbol_contribution": 0.1, "top1_day_contribution": 0.1,
        "top3_winners_removed_expectancy_10bps_pct": 0.05,
        "segment_signs": {"EARLY": True, "MID": True, "LATE": True},
        "symbol_cluster_ci": [0.05, 0.4], "day_cluster_ci": [0.02, 0.4],
        "stop_rate": 0.1, "strategy_fingerprint_match": True,
    }
    m.update(overrides)
    return m


def test_clean_positive_case_passes():
    result = classify(_base_metrics())
    assert result["classification"] == "VALIDATION_PASS"


def test_zero_stop_rate_is_not_a_pathology():
    result = classify(_base_metrics(stop_rate=0.0))
    assert result["criteria"]["12_stop_behavior_reasonable"] is True


def test_zero_trades_is_inconclusive():
    result = classify({"number_of_trades": 0, "insufficient_n": True})
    assert result["classification"] == "VALIDATION_INCONCLUSIVE"


def test_costs_erasing_edge_fails():
    result = classify(_base_metrics(net_expectancy_10bps_pct=0.001, net_expectancy_15bps_pct=-0.02))
    assert result["classification"] in ("VALIDATION_FAIL", "VALIDATION_INCONCLUSIVE")
    assert result["criteria"]["15_costs_do_not_erase_edge"] is False


def test_thin_sample_is_inconclusive_not_fail():
    result = classify(_base_metrics(session_coverage=10, symbol_coverage=8))
    assert result["classification"] == "VALIDATION_INCONCLUSIVE"
