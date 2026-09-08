"""
Task 115 -- Strategy Validation & Promotion Framework, focused tests.

1  immutable version identity          8  promotion manifest
2  fingerprint mutation rules          9  no automatic promotion
3  holdout separation                 10  active/shadow/research isolation
4  validation gate PASS               11  historical transport dry-run
5  validation gate FAIL               12  rejection of active live ledger path
6  cost sensitivity                   13  deterministic rerun
7  concentration evaluation
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from talonx_research.gate import evaluate_gate
from talonx_research.holdout import make_windows, split
from talonx_research.lanes import assert_lane_isolation
from talonx_research.manifest import build_manifest
from talonx_research.replay_engine import (LiveLedgerProtectionError,
                                           assert_research_ledger_path)
from talonx_research.versioning import (LifecycleState, PromotionStatus, StrategyRegistry,
                                        StrategyVersion, seed_known_versions,
                                        v1_fingerprint, v2_fingerprint)


# ---- 1 immutable version identity -----------------------------------------
def test_01_immutable_version_identity(tmp_path):
    reg = StrategyRegistry(tmp_path / "reg.json")
    seed_known_versions(reg)
    sv = reg.get("INSIDER_BUY_CLUSTER_V2@1")
    assert sv is not None and sv.id == "INSIDER_BUY_CLUSTER_V2@1"
    assert sv.lifecycle_state == LifecycleState.ACTIVE.value
    assert sv.is_immutable
    # re-seed is idempotent
    seed_known_versions(reg)
    assert len(reg.all()) == 2


# ---- 2 fingerprint mutation rules ---------------------------------------
def test_02_fingerprint_matches_frozen_and_is_semantic():
    assert v2_fingerprint() == "11107198c5b81237"
    assert v1_fingerprint() == "2ae6216bca70"


def test_02b_cannot_mutate_frozen_version_in_place(tmp_path):
    reg = StrategyRegistry(tmp_path / "reg.json")
    seed_known_versions(reg)
    with pytest.raises(ValueError, match="immutable"):
        reg.register(StrategyVersion(strategy_family="INSIDER_BUY_CLUSTER_V2", version=1,
                                     fingerprint="0000000000000000",
                                     lifecycle_state=LifecycleState.ACTIVE.value))


def test_02c_semantic_change_needs_new_version(tmp_path):
    reg = StrategyRegistry(tmp_path / "reg.json")
    seed_known_versions(reg)
    v2at2 = StrategyVersion(strategy_family="INSIDER_BUY_CLUSTER_V2", version=2,
                            fingerprint="abcdef1234567890",
                            lifecycle_state=LifecycleState.RESEARCH.value)
    reg.register(v2at2)
    assert reg.get("INSIDER_BUY_CLUSTER_V2@2").fingerprint == "abcdef1234567890"
    assert reg.get("INSIDER_BUY_CLUSTER_V2@1").fingerprint == "11107198c5b81237"


# ---- 3 holdout separation --------------------------------------------------
def test_03_holdout_split_is_chronological_and_recorded():
    w = make_windows("2024-09-01", "2026-03-31")
    assert w.validation_start < w.holdout_cutoff < w.validation_end
    df = pd.DataFrame({"entry_session": pd.to_datetime(
        ["2024-10-01", "2025-01-01", "2025-09-01", "2026-01-01"]), "x": [1, 2, 3, 4]})
    disc, hold = split(df, w)
    assert disc["x"].tolist() == [1, 2] and hold["x"].tolist() == [3, 4]
    assert "no parameter was tuned on holdout" in w.to_dict()["note"]


# ---- 4 / 5 validation gate PASS + FAIL ----------------------------------
def _metrics(net, holdout, pf, n, drop1=0.02, drop3=0.015, top_share=0.2, by_year=None):
    return {
        "primary_cost_bps": 20, "n_trades": n,
        "cost_sensitivity": {20: {"mean": net, "profit_factor": pf, "win_rate": 0.62,
                                  "avg_winner": 0.05, "avg_loser": -0.03,
                                  "max_drawdown": {"vs_total_pnl": -0.3}, "p01": -0.2, "n": n}},
        "discovery": {"mean": net}, "holdout": {"mean": holdout},
        "concentration": {"drop_top1_mean_net20": drop1, "drop_top3_mean_net20": drop3,
                          "max_issuer_share_of_positive_sum": top_share, "top_issuer": "X",
                          "by_year_mean_net20": by_year or {"2024": 0.02, "2025": 0.02, "2026": 0.01}},
        "dependence": {"issuer_block_ci_net20": [0.01, 0.03], "week_cluster_ci_net20": [0.015, 0.04]},
        "benchmark": {"mean": 0.02},
    }


def test_04_gate_pass():
    g = evaluate_gate(_metrics(0.022, 0.009, 2.2, 170), episodes_per_year=110)
    assert g.verdict == "VALIDATION_PASS"
    assert g.shadow_eligible is True and not g.hard_fails


def test_05_gate_fail_on_negative_holdout():
    g = evaluate_gate(_metrics(0.02, -0.01, 1.5, 170), episodes_per_year=110)
    assert g.verdict == "VALIDATION_FAIL"
    assert g.shadow_eligible is False
    assert any("holdout_expectancy_positive" in h for h in g.hard_fails)


def test_05b_gate_fail_on_small_sample_and_pf():
    g = evaluate_gate(_metrics(0.02, 0.01, 0.9, 30), episodes_per_year=5)
    assert g.verdict == "VALIDATION_FAIL"
    assert any("meaningful_sample" in h for h in g.hard_fails)
    assert any("profit_factor_gt_1" in h for h in g.hard_fails)


# ---- 6 cost sensitivity ------------------------------------------------
def test_06_cost_sensitivity_grid_present():
    from talonx_research import COST_GRID_BPS
    assert COST_GRID_BPS == (0, 5, 10, 20, 30, 50)


# ---- 7 concentration evaluation ---------------------------------------
def test_07_concentration_finding_on_top_issuer_and_negative_years():
    m = _metrics(0.02, 0.01, 2.0, 170, top_share=0.8,
                 by_year={"2024": -0.01, "2025": -0.02, "2026": 0.03})
    g = evaluate_gate(m, episodes_per_year=110)
    assert g.verdict == "VALIDATION_PASS_WITH_FINDINGS"   # findings, not hard fail
    assert any("issuer_concentration_ok" in f for f in g.findings)
    assert any("time_concentration_ok" in f for f in g.findings)


# ---- 8 promotion manifest --------------------------------------------
def test_08_manifest_shape():
    m = build_manifest(strategy="INSIDER_BUY_CLUSTER_V2", version=1,
                       fingerprint="11107198c5b81237",
                       validation_window={"start": "2024-09-01", "end": "2026-03-31"},
                       discovery_window={}, holdout_window={}, primary_cost_bps=20,
                       verdict="VALIDATION_PASS", shadow_eligible=True,
                       runtime_parity="PASS", gate_checks={}, metrics_summary={})
    assert m["promotion_allowed"] is False
    assert m["version_id"] == "INSIDER_BUY_CLUSTER_V2@1"
    assert "explicit" in m["promotion_note"].lower()


# ---- 9 no automatic promotion ---------------------------------------
def test_09_validation_pass_does_not_promote(tmp_path):
    reg = StrategyRegistry(tmp_path / "reg.json")
    seed_known_versions(reg)
    reg.register(StrategyVersion(strategy_family="X", version=1, fingerprint="deadbeefdeadbeef",
                                 lifecycle_state=LifecycleState.RESEARCH.value))
    reg.transition("X@1", LifecycleState.FROZEN)
    reg.transition("X@1", LifecycleState.VALIDATING)
    reg.transition("X@1", LifecycleState.VALIDATED, reason="VALIDATION_PASS")
    assert reg.get("X@1").lifecycle_state == "VALIDATED"
    assert reg.active().id == "INSIDER_BUY_CLUSTER_V2@1"     # unchanged
    # explicit promotion is required and demotes the incumbent
    reg.promote_to_active("X@1", decided_by="test", note="explicit")
    assert reg.active().id == "X@1"
    assert reg.get("INSIDER_BUY_CLUSTER_V2@1").lifecycle_state == "BASELINE"


# ---- 10 active/shadow/research isolation ---------------------------
def test_10_lane_isolation_assertions():
    ok = assert_lane_isolation(lane="RESEARCH", ledger_path="results/x/replay.db",
                               external_transport="DRY_RUN")
    assert ok["isolated"]
    bad = assert_lane_isolation(lane="SHADOW", ledger_path="C:/workspace/TalonX/v2_lane.db",
                                external_transport="DRY_RUN")
    assert not bad["isolated"]
    bad2 = assert_lane_isolation(lane="RESEARCH", ledger_path="results/x/replay.db",
                                 external_transport="LIVE")
    assert not bad2["isolated"]


# ---- 11 historical transport dry-run ------------------------------
def test_11_replay_payloads_are_dry_run(tmp_path):
    # a tiny chronological replay window; assert zero external sends + dry-run payloads
    from talonx_research.replay_engine import run_chronological_replay
    primary = Path("C:/workspace/TalonX")
    if not (primary / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet").exists():
        pytest.skip("primary worktree data not present")
    res = run_chronological_replay(
        start="2025-01-02", end="2025-02-01",
        ledger_path=tmp_path / "results" / "replay_v2_lane.db",
        bar_dirs=[primary / "results/task95g_broad_cross_sectional/_daily",
                  primary / "results/task107a_form4_feasibility/_prices"],
        form4_parquet=primary / "results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet",
        starting_cash=10_000_000.0)
    assert res.external_sends == 0
    for p in res.alert_payloads:
        assert p["dry_run"] is True and p["transport"] == "NONE"
    assert res.fingerprint == "11107198c5b81237"


# ---- 12 rejection of active live ledger path --------------------
def test_12_replay_refuses_live_ledger():
    for bad in ("C:/workspace/TalonX/v2_lane.db",
                str(Path.home() / ".talonx" / "v2_lane.db"),
                "some/other/dir/v2_lane.db"):
        with pytest.raises(LiveLedgerProtectionError):
            assert_research_ledger_path(bad)
    # a results/ work-area ledger is fine
    assert assert_research_ledger_path("results/task116_v2_production_replay/replay_v2_lane.db")


# ---- 13 deterministic rerun ------------------------------------
def test_13_gate_is_deterministic():
    m = _metrics(0.022, 0.009, 2.2, 170)
    a = evaluate_gate(m, episodes_per_year=110).to_dict()
    b = evaluate_gate(m, episodes_per_year=110).to_dict()
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
