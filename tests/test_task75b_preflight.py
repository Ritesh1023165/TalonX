"""Task75B PREFLIGHT: frozen fingerprints, two-layer holdout guard state machine, range intersection, live-path write
refusal, bootstrap determinism/grouping, and the no-synthetic-bar / manifest / attribution helpers."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.task75_v1.fingerprint import compute_contract_only_fingerprint, compute_fingerprint
from research.task75b_preflight import holdout as H

FULL = "08930fb2bbbd1f8acbf2071be2e7bf6b2ead784a94e38837d05f4e8937eebff3"
CONTRACT = "677adccd7e653e30c96122f0149356523f3a2fb3cb82a3d4967c3a1a06aa6f06"


def test_full_fingerprint_exact():
    assert compute_fingerprint() == FULL


def test_contract_only_fingerprint_exact():
    assert compute_contract_only_fingerprint() == CONTRACT
    rec = json.loads((Path(__file__).resolve().parents[1] / "results" /
                      "task75_cross_sectional_extreme_winner_short_reversion" / "candidate_fingerprint.json").read_text())
    assert rec["contract_only_fingerprint_sha256"] == CONTRACT and rec["full_fingerprint_sha256"] == FULL


def test_contract_still_records_raw_provenance():
    from research.task75_v1 import contracts as C
    assert C.DATA_ADJUSTMENT.startswith("raw")          # the frozen discovery provenance is never edited


def g(tmp_path, state="PREFLIGHT"):
    return H.HoldoutGuard(state, tmp_path / "state.json")


@pytest.mark.parametrize("layer", ["DOWNLOAD", "LOAD"])
def test_preflight_blocks_both_windows_allows_development(tmp_path, layer):
    gd = g(tmp_path)
    gd.check_range("2025-02-03", "2025-03-14", layer=layer)
    gd.check_range("2026-05-15", "2026-08-14", layer=layer)
    with pytest.raises(H.HoldoutViolation):
        gd.check_range("2024-06-01", "2024-06-05", layer=layer)
    with pytest.raises(H.HoldoutViolation):
        gd.check_range("2024-12-01", "2024-12-31", layer=layer)


@pytest.mark.parametrize("s,e", [("2024-05-01", "2024-06-01"),      # touches start boundary
                                 ("2024-09-02", "2024-09-30"),      # touches end boundary
                                 ("2024-08-01", "2024-10-01"),      # partial overlap
                                 ("2024-01-01", "2024-12-31"),      # full overlap
                                 ("2024-07-01", "2024-07-02")])     # fully inside
def test_intersection_boundaries(s, e):
    assert H.intersects(s, e, H.VALIDATION)


def test_non_intersecting_edges():
    assert not H.intersects("2024-05-01", "2024-05-31", H.VALIDATION)
    assert not H.intersects("2024-09-03", "2024-10-20", H.VALIDATION)
    assert not H.intersects("2024-09-03", "2024-10-20", H.REPLICATION)


def test_ready_opens_validation_only(tmp_path):
    gd = g(tmp_path)
    gd.transition("TASK75B_READY", authorized_by="test", reason="t")
    gd.check_range("2024-06-01", "2024-09-02", layer="DOWNLOAD")
    with pytest.raises(H.HoldoutViolation):
        gd.check_range("2024-10-21", "2024-12-20", layer="DOWNLOAD")


@pytest.mark.parametrize("final", ["VALIDATION_FAIL", "VALIDATION_INCONCLUSIVE"])
def test_fail_or_inconclusive_locks_replication_permanently(tmp_path, final):
    gd = g(tmp_path)
    for s in ("TASK75B_READY", "VALIDATION_RUNNING", final):
        gd.transition(s, authorized_by="test", reason="t")
    with pytest.raises(H.HoldoutViolation):
        gd.check_range("2024-11-01", "2024-11-05", layer="LOAD")
    with pytest.raises(H.HoldoutViolation):
        gd.transition("REPLICATION_UNLOCKED", authorized_by="test", reason="t")


def test_pass_makes_replication_eligible_but_still_locked_until_explicit_unlock(tmp_path):
    gd = g(tmp_path)
    for s in ("TASK75B_READY", "VALIDATION_RUNNING", "VALIDATION_PASS"):
        gd.transition(s, authorized_by="test", reason="t")
    assert gd.replication_locked()
    gd.transition("REPLICATION_UNLOCKED", authorized_by="operator", reason="explicit")
    gd.check_range("2024-11-01", "2024-11-05", layer="LOAD")


def test_no_skipping_states(tmp_path):
    with pytest.raises(H.HoldoutViolation):
        g(tmp_path).transition("VALIDATION_PASS", authorized_by="x", reason="skip")


def test_loader_guard_rejects_frames_with_protected_timestamps(tmp_path):
    df = pd.DataFrame({"timestamp": pd.to_datetime(["2025-02-03 14:30", "2024-06-03 14:30"], utc=True)})
    with pytest.raises(H.HoldoutViolation):
        g(tmp_path).check_frame(df)
    g(tmp_path).check_frame(df.iloc[:1])


def test_state_is_durable(tmp_path):
    gd = g(tmp_path)
    gd.transition("TASK75B_READY", authorized_by="t", reason="t")
    assert H.HoldoutGuard.load(tmp_path / "state.json").state == "TASK75B_READY"


def test_unknown_state_fails_closed(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"state": "READY", "audit": []}))
    with pytest.raises(H.HoldoutViolation):
        H.HoldoutGuard.load(p)


def test_live_runtime_paths_cannot_be_written():
    with pytest.raises(H.HoldoutViolation):
        H.assert_research_path(Path("C:/workspace/TalonX/results/opportunity/market.db"))
    H.assert_research_path(Path(__file__).resolve().parents[1] / "results" / "task75b_preflight" / "x.json")


def test_bootstrap_deterministic_seed_and_grouping():
    from research.task67a_lib.research_stats import DEFAULT_SEED, bootstrap_ci_clustered
    assert DEFAULT_SEED == 670067
    rng = np.random.default_rng(1)
    v = rng.normal(0.5, 3, 400)
    sym = np.repeat([f"S{i}" for i in range(20)], 20)
    a = bootstrap_ci_clustered(v, sym, n_resamples=10_000, ci_level=0.95, seed=DEFAULT_SEED)
    b = bootstrap_ci_clustered(v, sym, n_resamples=10_000, ci_level=0.95, seed=DEFAULT_SEED)
    assert (a.ci_low, a.ci_high) == (b.ci_low, b.ci_high)
    day = np.tile([f"D{i}" for i in range(40)], 10)
    c = bootstrap_ci_clustered(v, day, n_resamples=10_000, ci_level=0.95, seed=DEFAULT_SEED)
    assert (c.ci_low, c.ci_high) != (a.ci_low, a.ci_high)      # grouping matters: symbol vs entry_day


# ------------------------------------------------------------------ survival / attribution / manifest helpers
from research.task75b_preflight import survival as S  # noqa: E402


def _st(net10=0.3, gross=0.4, cs=(0.01, 0.05), cd=(0.01, 0.02), bij=True):
    return {"net_10bps_pct": net10, "gross_mean_pct": gross, "decision_to_entry_day_bijective": bij,
            "original_2000": {"symbol": [cs[0], 1], "day": [cd[0], 1]},
            "spec_10000": {"symbol": [cs[1], 1], "entry_day": [cd[1], 1]}}


def test_survival_requires_both_bootstrap_calls_and_no_discretion():
    assert S.survival_gates(_st(), 0)["pass"]
    assert not S.survival_gates(_st(cd=(0.034, 0.0)), 0)["pass"]          # 10k day CI at exactly 0 fails
    assert not S.survival_gates(_st(cd=(-0.001, 0.03)), 0)["pass"]        # original call slightly negative fails
    assert not S.survival_gates(_st(net10=0.1499), 0)["pass"]
    assert not S.survival_gates(_st(), 1)["pass"]                          # unexplained blocks


def test_classification_order():
    ok = {"pass": True}
    assert S.classify(ok, fingerprints_ok=True, raw_parity_ok=False, semantics_ok=True, dataset_ok=True, unexplained=0,
                      holdout_untouched=True) == "TASK75B_BLOCKED_ENVIRONMENT_DRIFT"
    assert S.classify(ok, fingerprints_ok=True, raw_parity_ok=True, semantics_ok=True, dataset_ok=True, unexplained=2,
                      holdout_untouched=True) == "TASK75B_BLOCKED_DATA_INTEGRITY"
    assert S.classify({"pass": False}, fingerprints_ok=True, raw_parity_ok=True, semantics_ok=True, dataset_ok=True,
                      unexplained=0, holdout_untouched=True) == "TASK75_RETIRED_AFTER_CORPORATE_ACTION_CORRECTION"
    assert S.classify(ok, fingerprints_ok=True, raw_parity_ok=True, semantics_ok=True, dataset_ok=True, unexplained=0,
                      holdout_untouched=True) == "TASK75B_READY"


def _led(rows):
    cols = ["symbol", "decision_day", "cross_sectional_rank_pct", "data_ready", "entry_price", "exit_price",
            "gross_return_pct", "exit_day"]
    return pd.DataFrame(rows, columns=cols)


def test_trade_diff_attribution_categories():
    cal = {"x": ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05", "2026-06-08", "2026-06-09"]}
    raw = _led([["KLAC", "2026-06-04", .9, True, 2000, 250, 87.5, "2026-06-09"],     # spans a split
                ["AAA", "2026-06-04", .9, True, 100, 99, 1.0, "2026-06-09"],         # uniform factor only
                ["BBB", "2026-06-04", .85, True, 50, 50, 0.0, "2026-06-09"],         # drops out (rank propagation)
                ["CCC", "2026-06-04", .5, False, None, None, None, None]])
    alled = _led([["KLAC", "2026-06-04", .9, True, 200, 250, -25.0, "2026-06-09"],
                  ["AAA", "2026-06-04", .9, True, 99.0, 98.01, 1.0, "2026-06-09"],
                  ["BBB", "2026-06-04", .75, False, None, None, None, None],
                  ["CCC", "2026-06-04", .5, False, None, None, None, None]])
    ca = [{"symbol": "KLAC", "ex_or_effective_date": "2026-06-03"}]   # inside the 06-01..06-04 lookback span
    d = S.attribute_diff(raw, alled, ca, cal).set_index("symbol")["category"].to_dict()
    assert d == {"KLAC": "DIRECT_CORPORATE_ACTION", "AAA": "OTHER_EXPLAINED", "BBB": "RANK_BOUNDARY_PROPAGATION"}


def test_unexplained_when_nothing_accounts_for_a_change():
    cal = {"x": ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]}
    raw = _led([["AAA", "2026-06-04", .9, True, 100, 99, 1.0, "2026-06-04"]])
    alled = _led([["AAA", "2026-06-04", .9, True, 100, 90, 10.0, "2026-06-04"]])
    d = S.attribute_diff(raw, alled, [], cal)
    assert list(d["category"]) == ["UNEXPLAINED"]


def test_manifest_hash_is_order_and_path_independent(tmp_path):
    a = tmp_path / "a.csv"
    a.write_bytes(b"x,y\n1,2\n")
    h = S.file_sha256(a)
    assert S.aggregate_hash({"A.csv": h, "B.csv": "0"}) == S.aggregate_hash({"B.csv": "0", "A.csv": h})
    assert S.aggregate_hash({"A.csv": h}) != S.aggregate_hash({"A.csv": "0"})


def test_declaration_binds_all_adjustment_identically_for_spy():
    p = Path(__file__).resolve().parents[1] / "results" / "task75b_preflight" / "dataset_basis_declaration.json"
    d = json.loads(p.read_text())
    b = d["dataset_basis"]
    assert (b["provider"], b["feed"], b["timeframe"], b["adjustment"]) == ("alpaca", "sip", "1Min", "all")
    assert "IDENTICAL" in b["symbols"] and "SPY" in b["symbols"]
    assert d["strategy_semantics_changed"] == "NO" and d["fingerprint_changed"] == "NO"


# ------------------------------------------------------------------ Task75 closure (A1/A2)
def test_ca_audit_v2_selects_by_ex_date_not_process_date():
    from research.task75b_preflight.ca_audit_v2 import select_by_ex_date
    rows = {"cash_dividends": [
        {"symbol": "GOOGL", "ex_date": "2025-03-10", "process_date": "2025-03-17", "rate": 0.2},   # ex in window
        {"symbol": "TXN", "ex_date": "2025-01-31", "process_date": "2025-02-11", "rate": 1.36}]}  # ex before window
    got = select_by_ex_date(rows, "2025-02-03", "2025-03-14")
    assert [(e["symbol"], e["ex_or_effective_date"]) for e in got] == [("GOOGL", "2025-03-10")]


def test_ca_audit_v2_query_ranges_never_touch_reserved_windows(tmp_path):
    import json as _j
    from datetime import date as _d, timedelta as _t
    from research.task75b_preflight.ca_audit_v2 import LOOKBACK_PAD_DAYS, PROCESS_TRAIL_DAYS
    man = _j.loads((Path(__file__).resolve().parents[1] / "results" / "task74_alpha_discovery_v2" /
                    "development_data_manifest.json").read_text())
    gd = H.HoldoutGuard("PREFLIGHT", tmp_path / "s.json")
    for s in man["slices"].values():
        lo = (_d.fromisoformat(s["start"]) - _t(days=LOOKBACK_PAD_DAYS)).isoformat()
        hi = (_d.fromisoformat(s["end"]) + _t(days=PROCESS_TRAIL_DAYS)).isoformat()
        gd.check_range(lo, hi, layer="DOWNLOAD")                     # raises if any widened range hits 2024 windows


def test_cent_rounding_relabel_is_bounded():
    from research.task75b_preflight.attribution_v2 import relabel, rounding_bound
    raw = pd.DataFrame([{"symbol": "AAA", "decision_day": "2025-03-05", "entry_price": 170.53, "exit_price": 165.88,
                         "market_adjusted_return_pct": 1.0},
                        {"symbol": "BBB", "decision_day": "2025-03-05", "entry_price": 100.0, "exit_price": 99.0,
                         "market_adjusted_return_pct": 1.0}])
    f = 0.9941
    allp = pd.DataFrame([{"symbol": "AAA", "decision_day": "2025-03-05", "entry_price": round(170.53 * f, 2),
                          "exit_price": round(165.88 * f, 2), "market_adjusted_return_pct": 1.0},
                         {"symbol": "BBB", "decision_day": "2025-03-05", "entry_price": 99.0, "exit_price": 90.0,
                          "market_adjusted_return_pct": 1.0}])
    diff = pd.DataFrame([{"symbol": "AAA", "decision_day": "2025-03-05", "change": "PRICE_OR_PNL_CHANGED",
                          "category": "UNEXPLAINED"},
                         {"symbol": "BBB", "decision_day": "2025-03-05", "change": "PRICE_OR_PNL_CHANGED",
                          "category": "UNEXPLAINED"}])
    out = relabel(diff, raw, allp).set_index("symbol")["category"].to_dict()
    assert out == {"AAA": "OTHER_EXPLAINED_CENT_ROUNDING", "BBB": "UNEXPLAINED"}   # real changes stay unexplained
    assert rounding_bound(100, 100) == pytest.approx(1e-4, abs=1e-8)


def test_survival_thresholds_unchanged_by_closure():
    assert S.NET_10BPS_MIN_PCT == 0.15 and S.SEED == 670067 and S.RETURN_TOL_PCT == 1e-6 and S.FACTOR_TOL == 1e-5


def test_guard_state_left_in_preflight_with_both_windows_locked():
    g2 = H.HoldoutGuard.load()
    assert g2.state == "PREFLIGHT" and g2.validation_locked() and g2.replication_locked()
