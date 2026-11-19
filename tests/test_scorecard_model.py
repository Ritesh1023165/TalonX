"""Model, metrics and decision-table tests on synthetic data (no real outcomes are touched)."""
import numpy as np
import pandas as pd
import pytest

from talonx_scorecard import config as C
from talonx_scorecard import metrics as M
from talonx_scorecard import model as MD


def test_newey_west_matches_iid_and_grows_with_autocorrelation():
    rng = np.random.default_rng(0)
    x = rng.normal(size=5000)
    assert abs(M.newey_west_se(x, 4) - x.std() / np.sqrt(len(x))) < 0.1 * x.std() / np.sqrt(len(x))
    ar = np.zeros(5000)
    for i in range(1, 5000):
        ar[i] = 0.8 * ar[i - 1] + rng.normal()
    assert M.newey_west_se(ar, 13) > 1.8 * ar.std() / np.sqrt(len(ar))


def test_ece_zero_for_perfect_calibration_and_large_for_bad():
    rng = np.random.default_rng(1)
    p = rng.uniform(size=200000)
    y = (rng.uniform(size=p.size) < p).astype(float)
    assert M.ece(p, y) < 0.01
    assert M.ece(np.full(1000, 0.9), np.zeros(1000)) > 0.85


@pytest.mark.parametrize("flags,h,expect", [
    ((0, 1, 1, 1, 1), "1M", "FAIL"),
    ((1, 1, 1, 0, 1), "1M", "FAIL_UNSTABLE"),
    ((1, 0, 0, 1, 1), "1M", "FAIL_NO_VALUE"),
    ((1, 1, 1, 1, 1), "1M", "PASS"),
    ((1, 1, 1, 1, 1), "3M", "PROVISIONAL"),
    ((1, 1, 0, 1, 1), "1W", "PASS_ONE_SIDED"),
    ((1, 0, 1, 1, 1), "1D", "PASS_ONE_SIDED"),
    ((1, 1, 1, 1, 0), "1M", "PASS_RANK_ONLY"),
    ((1, 1, 0, 1, 0), "1M", "FAIL_NO_VALUE"),      # the cell the pre-registration leaves undefined
])
def test_decision_table(flags, h, expect):
    g = dict(zip(["G1", "G2", "G3", "G4", "G5"], map(bool, flags)))
    out, note = M.decide(g, h)
    assert out == expect
    if flags == (1, 1, 0, 1, 0):
        assert "UNDEFINED" in note


def test_programme_level_rules():
    ic = {"1D": .02, "1W": .02, "1M": .02, "3M": .02}
    lo = {h: 0.01 for h in ic}
    none = M.programme_outcome({h: "FAIL" for h in ic}, {h: 0.05 for h in ic}, ic)
    assert none["action"] == "CLOSE_SCORECARD_LANE" and not none["leakage_audit_required"]
    only1d = {"1D": "PASS", "1W": "FAIL", "1M": "FAIL", "3M": "FAIL"}
    r = M.programme_outcome(only1d, lo, ic)
    assert r["leakage_audit_required"] and r["action"].startswith("LEAKAGE_AUDIT")
    mid = {"1D": "FAIL", "1W": "PASS", "1M": "FAIL", "3M": "FAIL"}
    assert not M.programme_outcome(mid, lo, ic)["leakage_audit_required"]
    assert M.programme_outcome(mid, {**lo, "1W": 0.05}, ic)["leakage_audit_required"]   # HOLDOUT IC above TRAIN IC


def _synthetic(signal, n_dates=240, n_names=250, seed=3):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=n_dates)
    names = [f"S{i:03d}" for i in range(n_names)]
    raw = {f.id: pd.DataFrame(rng.normal(size=(n_dates, n_names)), index=dates, columns=names) for f in C.FEATURES}
    uni = pd.DataFrame(True, index=dates, columns=names)
    s = raw["F5"].rank(axis=1, pct=True) - 0.5            # F5 is expected-positive; plant the signal there
    excess = signal * s + rng.normal(scale=0.05, size=s.shape)
    return dates, raw, uni, excess


def test_ridge_recovers_planted_feature_and_eq_ic_positive():
    dates, raw, uni, excess = _synthetic(signal=0.05)
    cube = MD.build_cube(raw, uni, dates)
    w = MD.fit_ridge(cube, excess, dates)
    assert w.idxmax() == "F5" and w["F5"] > 5 * w.drop("F5").abs().max()
    iso = MD.fit_calibration(cube, excess, dates, None)
    per, pooled = MD.evaluate(cube, excess, dates, None, iso, "1W")
    g = M.gates(per, pooled, "1W")
    assert g["mean_ic"] > 0.02 and g["G1"] and g["bull_hit"] > g["bear_hit"]


def test_noise_has_no_skill():
    dates, raw, uni, excess = _synthetic(signal=0.0, seed=11)
    cube = MD.build_cube(raw, uni, dates)
    iso = MD.fit_calibration(cube, excess, dates, None)
    per, pooled = MD.evaluate(cube, excess, dates, None, iso, "1W")
    g = M.gates(per, pooled, "1W")
    assert abs(g["mean_ic"]) < 0.01 and not g["G1"]
    assert M.decide(g, "1W")[0] == "FAIL"


def test_calibration_is_monotone():
    dates, raw, uni, excess = _synthetic(signal=0.05, seed=5)
    cube = MD.build_cube(raw, uni, dates)
    iso = MD.fit_calibration(cube, excess, dates, None)
    p = iso.predict(np.linspace(0, 1, 101))
    assert (np.diff(p) >= -1e-12).all() and p[-1] > p[0]
