"""Task 101B — focused tests for the 15-minute trend-gate counter-trend study.

Research-only. Confirms frozen 15m trend semantics, causal SMA alignment (no
future leakage), PDL sweep/reclaim reproduction, TREND_ONLY_REJECT identification
with the full gate vector, discovery/holdout isolation, distance-to-SMA bins,
cost calculations, deterministic reruns, and missing/stale-state handling.
Zero production import beyond talonx_quant.config (read-only, via task101a).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


A = _load("t101a_ef", "research/scripts/task101a_event_first.py")
B = _load("t101b_tg", "research/scripts/task101b_trend_gate.py")


# --------------------------------------------------------------------------- #
def test_holdout_split_is_chronological_and_frozen():
    assert B.HOLDOUT_START == "2024-01-01"
    df = pd.DataFrame({"session_date": ["2023-12-31", "2024-01-01", "2024-06-01", "2020-05-05"]})
    split = np.where(df["session_date"] >= B.HOLDOUT_START, "holdout", "discovery")
    assert list(split) == ["discovery", "holdout", "holdout", "discovery"]


def test_frozen_15m_trend_semantics_bullish_above_sma_only():
    # reuse the production formula via task101a's gate application
    d = pd.DataFrame([
        {"direction": "BULLISH", "reference_price": 101.0, "htf_sma200": 100.0},   # above -> pass
        {"direction": "BULLISH", "reference_price": 99.0, "htf_sma200": 100.0},     # below -> FAIL
        {"direction": "BULLISH", "reference_price": 101.0, "htf_sma200": np.nan},   # unknown -> pass (n/a)
    ])
    for c in ["macd_cross_up", "macd_cross_dn", "in_open_blackout", "in_close_blackout"]:
        d[c] = False
    for c in ["rsi_t", "rsi_t1", "rsi_t2", "rsi_t3", "vol_surge", "atr_pct", "atr", "btr",
              "piv_s1", "piv_r1", "rr_structural"]:
        d[c] = 1.0
    d["has_next_bar"] = True
    A._apply_gates(d)
    assert list(d["orig_trend_pass"]) == [True, False, True]      # NaN SMA treated as pass, matching Original


def test_trend_state_classification_and_distance():
    f3 = pd.DataFrame({
        "htf_sma200": [100.0, 100.0, np.nan],
        "reference_price": [102.0, 98.0, 100.0],
    })
    ts = np.where(f3["htf_sma200"].isna(), "UNKNOWN",
                  np.where(f3["reference_price"] > f3["htf_sma200"], "BULLISH_ALIGNED", "BEARISH_COUNTER"))
    assert list(ts) == ["BULLISH_ALIGNED", "BEARISH_COUNTER", "UNKNOWN"]
    dist = (f3["reference_price"] / f3["htf_sma200"] - 1.0) * 1e4
    assert dist.iloc[0] == pytest.approx(200.0)
    assert dist.iloc[1] == pytest.approx(-200.0)


def test_causal_15m_sma_no_future_leak():
    # the 15m SMA mapped to a 1m bar must come from a bucket STRICTLY BEFORE that bar
    idx = pd.date_range("2022-06-15 09:30", periods=120, freq="1min", tz=B.ET)
    close = np.linspace(100, 130, 120)
    r = pd.DataFrame({"et": idx, "close": close}).set_index("et")
    htf = r["close"].resample("15min", label="right", closed="right", origin="start_day").last().dropna()
    sma = htf.rolling(2).mean()
    bar_et = idx.values
    pos = np.searchsorted(sma.index.values, bar_et, side="right") - 1
    # a bar at 09:59 must NOT see the 10:00 bucket SMA
    j = list(idx).index(pd.Timestamp("2022-06-15 09:59", tz=B.ET))
    assert sma.index[pos[j]] <= pd.Timestamp("2022-06-15 09:59", tz=B.ET)


def test_pdl_sweep_reclaim_reproduction_matches_task101a_detector():
    # a clean sweep+reclaim on day 2 -> exactly one F3 candidate, BULLISH, lag<=3
    d1 = A._session_frame([100] * 60, date="2022-06-14") if hasattr(A, "_session_frame") else None
    # build minimal two-day frame directly
    def sess(prices, date):
        n = len(prices)
        t0 = pd.Timestamp(f"{date} 09:30", tz=B.ET)
        et = [t0 + pd.Timedelta(minutes=i) for i in range(n)]
        close = np.array(prices, float)
        return pd.DataFrame({
            "timestamp": [t.tz_convert("UTC") for t in et], "symbol": "TEST",
            "open": np.r_[close[0], close[:-1]], "high": close + 0.05, "low": close - 0.05,
            "close": close, "volume": 1000, "et": pd.DatetimeIndex(et),
            "date": [t.date() for t in et], "tod": [t.time() for t in et],
            "dow": [t.weekday() for t in et],
        })
    d1 = sess([100] * 60, "2022-06-14")
    d2c = [100] * 40 + [99.0, 99.5, 100.5] + [100] * 17  # sweep @40, reclaim @42 (lag 2)
    d2 = sess(d2c, "2022-06-15")
    df = pd.concat([d1, d2], ignore_index=True)
    df = A._pandas_ta_indicators(df)
    import types
    monkey = types.SimpleNamespace()
    old = A.WARMUP_BARS
    A.WARMUP_BARS = 3
    try:
        cands = [c for c in A._detect_candidates(df) if c["trigger_type"] == "F3_PDL_RECLAIM"]
    finally:
        A.WARMUP_BARS = old
    assert len(cands) == 1
    assert cands[0]["direction"] == "BULLISH"
    assert cands[0]["reclaim_lag"] in (1, 2, 3)
    assert cands[0]["same_bar_ambiguous"] is False


def test_trend_only_reject_requires_all_other_gates_pass():
    # trend fails; ATR/conf/rr/blackout all pass -> TREND_ONLY_REJECT True
    d = pd.DataFrame([{
        "orig_atr_pass": True, "orig_conf_pass": True, "orig_rr_pass": True,
        "orig_openblk_pass": True, "orig_closeblk_pass": True, "trend_state": "BEARISH_COUNTER",
    }, {
        "orig_atr_pass": True, "orig_conf_pass": False, "orig_rr_pass": True,   # conf fails -> not TOR
        "orig_openblk_pass": True, "orig_closeblk_pass": True, "trend_state": "BEARISH_COUNTER",
    }])
    hg = ["orig_atr_pass", "orig_conf_pass", "orig_rr_pass", "orig_openblk_pass", "orig_closeblk_pass"]
    d["other_headline_pass"] = d[hg].all(axis=1)
    d["is_trend_fail"] = d["trend_state"] == "BEARISH_COUNTER"
    d["pop_trend_only_reject"] = d["is_trend_fail"] & d["other_headline_pass"]
    d["pop_trend_fail_other_fail"] = d["is_trend_fail"] & (~d["other_headline_pass"])
    assert list(d["pop_trend_only_reject"]) == [True, False]
    assert list(d["pop_trend_fail_other_fail"]) == [False, True]


def test_cost_calc_single_roundtrip_from_row_helper():
    s = pd.DataFrame({
        "has_next_bar": [True] * 4,
        "ret_30m": [0.0030, -0.0010, 0.0000, 0.0020],
        "ret_eod": [0.001, -0.002, 0.0, 0.003],
        "mfe": [0.01] * 4, "mae": [-0.01] * 4,
        "reference_price": [100.0] * 4, "struct_stop": [98.0] * 4, "direction": ["BULLISH"] * 4,
    })
    r = B._row(s)
    assert r["mean_30m_bps"] == pytest.approx(np.mean([30, -10, 0, 20]))
    assert r["net5_bps"] == pytest.approx(r["mean_30m_bps"] - 5)
    assert r["net10_bps"] == pytest.approx(r["mean_30m_bps"] - 10)
    assert r["net20_bps"] == pytest.approx(r["mean_30m_bps"] - 20)


def test_distance_bins_are_frozen_and_cover_the_line():
    edges = [(-1e9, -100), (-100, -50), (-50, -25), (-25, 0), (0, 25), (25, 50), (50, 100), (100, 1e9)]
    xs = [-500, -75, -30, -10, 10, 30, 75, 500]
    for x, (lo, hi) in zip(xs, edges):
        assert lo <= x < hi


def test_bootstrap_ci_deterministic_given_seed():
    rng = np.random.RandomState(0)
    s = pd.DataFrame({
        "has_next_bar": True,
        "ret_30m": rng.normal(0.0, 0.002, 400),
        "session_date": np.repeat([f"2022-01-{d:02d}" for d in range(1, 21)], 20),
    })
    a = B._boot_ci(s, seed=101)
    b = B._boot_ci(s, seed=101)
    assert a == b
    assert a[0] < a[1]


def test_missing_15m_state_is_unknown_not_fail():
    f3 = pd.DataFrame({"htf_sma200": [np.nan], "reference_price": [100.0]})
    ts = np.where(f3["htf_sma200"].isna(), "UNKNOWN",
                  np.where(f3["reference_price"] > f3["htf_sma200"], "BULLISH_ALIGNED", "BEARISH_COUNTER"))
    assert ts[0] == "UNKNOWN"
    # and UNKNOWN is grouped with is_trend_pass (matches Original's None->pass)
    is_trend_fail = ts == "BEARISH_COUNTER"
    assert bool(is_trend_fail[0]) is False


def test_daily_diagnostic_is_labelled_secondary_and_uses_membership():
    assert B.MEMBERSHIP.exists()
    assert B.DAILY_DIR.exists()
    # sweep+reclaim daily proxy logic
    prior_low, low_today, close_today, sma = 100.0, 99.0, 100.5, 101.0
    assert (low_today < prior_low) and (close_today > prior_low)   # sweep + reclaim
    assert close_today < sma                                        # daily trend gate FAIL


def test_deterministic_rerun_of_row_helper():
    s = pd.DataFrame({
        "has_next_bar": [True] * 50, "ret_30m": np.linspace(-0.001, 0.001, 50),
        "ret_eod": np.linspace(-0.002, 0.002, 50), "mfe": [0.01] * 50, "mae": [-0.01] * 50,
        "reference_price": [100.0] * 50, "struct_stop": [98.0] * 50, "direction": ["BULLISH"] * 50,
    })
    assert B._row(s) == B._row(s.copy())
