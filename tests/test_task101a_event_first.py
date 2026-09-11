"""Task 101A — focused tests for the event-first structural candidate research module.

Research-only. Confirms causal trigger detection, no look-ahead, full gate-vector
evaluation, RSI-memory variants, forward-horizon causality, MFE/MAE, cost
adjustment, bearish sign semantics, session/dedup/ambiguity handling, and
deterministic rerun. Also asserts the frozen production thresholds the module
reads. Zero production import beyond talonx_quant.config (read-only).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "task101a_ef", REPO / "research" / "scripts" / "task101a_event_first.py"
)
ef = importlib.util.module_from_spec(_spec)
sys.modules["task101a_ef"] = ef
_spec.loader.exec_module(ef)

ET = "America/New_York"


@pytest.fixture(autouse=True)
def _small_warmup(monkeypatch):
    """Synthetic fixtures are short; drop the 60-bar production warm-up so the
    trigger bars are not sliced away. Detection logic is identical."""
    monkeypatch.setattr(ef, "WARMUP_BARS", 3)
    yield


def _session_frame(prices, *, date="2022-06-15", start="09:30", vol=1000, sym="TEST",
                   highs=None, lows=None):
    """Build a 1-minute RTH frame from a close-price list."""
    n = len(prices)
    t0 = pd.Timestamp(f"{date} {start}", tz=ET)
    idx = [t0 + pd.Timedelta(minutes=i) for i in range(n)]
    close = np.array(prices, float)
    high = close + 0.05 if highs is None else np.array(highs, float)
    low = close - 0.05 if lows is None else np.array(lows, float)
    opn = np.concatenate([[close[0]], close[:-1]])
    df = pd.DataFrame({
        "timestamp": [t.tz_convert("UTC") for t in idx],
        "symbol": sym, "open": opn, "high": high, "low": low, "close": close,
        "volume": vol,
    })
    df["et"] = pd.DatetimeIndex(idx)
    df["date"] = df["et"].dt.date
    df["tod"] = df["et"].dt.time
    df["dow"] = df["et"].dt.weekday
    return df


# --------------------------------------------------------------------------- #
# frozen thresholds
# --------------------------------------------------------------------------- #
def test_reads_frozen_production_thresholds():
    assert ef.ORIG == {"min_atr_pct": 0.25, "confluence_min": 2, "min_rr": 1.5}
    assert ef.EXP == {"min_atr_pct": 0.10, "confluence_min": 1, "min_rr": 1.0}
    assert ef.RSI_OS == 30.0 and ef.RSI_OB == 70.0
    assert ef.ATR_PERIOD == 14 and ef.RSI_PERIOD == 14
    assert (ef.MACD_FAST, ef.MACD_SLOW, ef.MACD_SIGNAL) == (12, 26, 9)
    assert ef.VOL_AVG == 20 and ef.VOL_SURGE == 2.0
    assert ef.HTF_SMA == 200


# --------------------------------------------------------------------------- #
# AVWAP causality + dedup
# --------------------------------------------------------------------------- #
def test_session_avwap_is_causal_cumulative():
    g = _session_frame([10, 10, 10], vol=100)
    aw = ef._session_avwap(g)
    # first bar avwap == its own typical price
    assert aw[0] == pytest.approx((10.05 + 9.95 + 10) / 3)
    assert np.all(np.isfinite(aw))


def test_f1_avwap_reclaim_requires_completed_bar_cross():
    # price sits below AVWAP for a while, then a completed close crosses above
    prices = [100] * 40 + [99.0, 99.0, 99.0, 101.0] + [101.0] * 20
    highs = [p + 0.05 for p in prices]
    lows = [p - 0.05 for p in prices]
    df = _session_frame(prices, highs=highs, lows=lows, vol=1000)
    df["symbol"] = "TEST"
    df = ef._pandas_ta_indicators(df)
    cands = ef._detect_candidates(df)
    f1 = [c for c in cands if c["trigger_type"] == "F1_AVWAP_RECLAIM"]
    assert len(f1) >= 1
    c = f1[0]
    # trigger bar is a COMPLETED bar; reference is the NEXT bar's open (causal)
    assert c["trigger_close"] > c["avwap_at_t"]
    assert c["direction"] == "BULLISH"
    ti = c["trigger_bar_idx"]
    assert c["reference_price"] == pytest.approx(float(df["open"].iloc[ti + 1]))


def test_f1_dedup_one_per_reclaim_episode():
    # cross up, stay up (no decisive re-loss) -> exactly one F1 despite many bars above
    prices = [100] * 40 + [99] * 3 + [101] * 40
    df = _session_frame(prices, highs=[p + 0.05 for p in prices], lows=[p - 0.05 for p in prices])
    df["symbol"] = "TEST"
    df = ef._pandas_ta_indicators(df)
    cands = [c for c in ef._detect_candidates(df) if c["trigger_type"] == "F1_AVWAP_RECLAIM"]
    assert len(cands) == 1


# --------------------------------------------------------------------------- #
# opening range timing / no breakout before the range is complete
# --------------------------------------------------------------------------- #
def test_f2_opening_range_established_from_first_15_bars_only():
    # OR high is set by bars 0..14; a spike inside the OR window must NOT be a breakout
    prices = [10, 10, 10, 10, 10, 20, 10, 10, 10, 10, 10, 10, 10, 10, 10] + [11] * 40
    highs = [p + 0.05 for p in prices]
    df = _session_frame(prices, highs=highs, lows=[p - 0.05 for p in prices])
    df["symbol"] = "TEST"
    df = ef._pandas_ta_indicators(df)
    cands = [c for c in ef._detect_candidates(df) if c["trigger_type"] == "F2_OR_BREAKOUT"]
    # OR high = 20.05 (the in-window spike). Post-09:45 price of 11 never exceeds it -> no breakout.
    assert cands == []


def test_f2_breakout_only_after_15m_and_causal():
    prices = [10] * 15 + [10.0] * 5 + [10.5, 10.8, 11.5] + [11.5] * 20  # OR high ~10.05
    df = _session_frame(prices, highs=[p + 0.05 for p in prices], lows=[p - 0.05 for p in prices])
    df["symbol"] = "TEST"
    df = ef._pandas_ta_indicators(df)
    cands = [c for c in ef._detect_candidates(df) if c["trigger_type"] == "F2_OR_BREAKOUT"]
    assert len(cands) == 1
    assert cands[0]["trigger_bar_idx"] >= ef.OR_BARS
    assert cands[0]["direction"] == "BULLISH"


def test_f2_breakdown_is_bearish_and_informational():
    prices = [10] * 15 + [10] * 3 + [9.5, 9.0, 8.5] + [8.5] * 20
    df = _session_frame(prices, highs=[p + 0.05 for p in prices], lows=[p - 0.05 for p in prices])
    df["symbol"] = "TEST"
    df = ef._pandas_ta_indicators(df)
    cands = [c for c in ef._detect_candidates(df) if c["trigger_type"] == "F2_OR_BREAKDOWN"]
    assert len(cands) == 1
    assert cands[0]["direction"] == "BEARISH"
    assert cands[0].get("informational") is True


# --------------------------------------------------------------------------- #
# PDL sweep/reclaim window + same-bar ambiguity
# --------------------------------------------------------------------------- #
def _two_day_frame(day1_prices, day2_prices):
    d1 = _session_frame(day1_prices, date="2022-06-14")
    d2 = _session_frame(day2_prices, date="2022-06-15")
    df = pd.concat([d1, d2], ignore_index=True)
    df["symbol"] = "TEST"
    return ef._pandas_ta_indicators(df)


def test_f3_reclaim_within_three_bars():
    d1 = [100] * 60                    # prior day low ~ 99.95
    d2 = [100] * 40 + [99.0, 99.5, 99.7, 100.5] + [100] * 15  # sweep then reclaim on bar +3
    df = _two_day_frame(d1, d2)
    cands = [c for c in ef._detect_candidates(df) if c["trigger_type"] == "F3_PDL_RECLAIM"]
    assert len(cands) == 1
    assert cands[0]["reclaim_lag"] == 3
    assert cands[0]["same_bar_ambiguous"] is False
    assert cands[0]["direction"] == "BULLISH"


def test_f3_no_reclaim_after_three_bars():
    d1 = [100] * 60
    d2 = [100] * 40 + [99.0] * 20  # sweeps prior-day low and NEVER reclaims before EOD
    df = _two_day_frame(d1, d2)
    cands = [c for c in ef._detect_candidates(df) if c["trigger_type"] == "F3_PDL_RECLAIM"]
    assert cands == []


def test_f3_same_bar_sweep_and_reclaim_flagged_ambiguous():
    d1 = [100] * 60
    # bar dips its low below PDL and closes back above it on the SAME bar
    d2c = [100] * 40 + [100.2] + [100] * 19
    lows = [p - 0.05 for p in d2c]
    lows[40] = 99.0  # same-bar sweep
    d1f = _session_frame(d1, date="2022-06-14")
    d2f = _session_frame(d2c, date="2022-06-15", lows=lows)
    df = pd.concat([d1f, d2f], ignore_index=True)
    df["symbol"] = "TEST"
    df = ef._pandas_ta_indicators(df)
    cands = [c for c in ef._detect_candidates(df) if c["trigger_type"] == "F3_PDL_RECLAIM"]
    assert len(cands) == 1
    assert cands[0]["same_bar_ambiguous"] is True
    assert cands[0]["reclaim_lag"] == 0


def test_f3_skipped_on_corp_action_gap():
    d1 = [400] * 60
    d2 = [100] * 60          # ~75% overnight gap -> CORP_ACTION_SUSPECT
    df = _two_day_frame(d1, d2)
    cands = [c for c in ef._detect_candidates(df) if c["trigger_type"] == "F3_PDL_RECLAIM"]
    assert cands == []


# --------------------------------------------------------------------------- #
# gate vector: every gate evaluated even after the first failure
# --------------------------------------------------------------------------- #
def test_full_gate_vector_evaluated_after_first_failure():
    df = pd.DataFrame([{
        "direction": "BULLISH", "macd_cross_up": True, "macd_cross_dn": False,
        "rsi_t": 25.0, "rsi_t1": 26.0, "rsi_t2": 27.0, "rsi_t3": 28.0,
        "vol_surge": 3.0, "atr_pct": 0.05,               # ATR fails
        "reference_price": 100.0, "struct_stop": 98.0, "piv_s1": 98.0, "piv_r1": 104.0,
        "atr": 0.5, "btr": 0.6, "htf_sma200": 90.0, "in_open_blackout": False,
        "in_close_blackout": False, "rr_structural": 3.0, "has_next_bar": True,
    }])
    ef._apply_gates(df)
    row = df.iloc[0]
    assert row["orig_atr_pass"] == False          # first failure
    # ...but confluence / rr / trend / blackout are STILL computed:
    assert row["conf_score"] == 3                  # macd + rsi<30 + vol>2
    assert row["orig_conf_pass"] == True
    assert row["orig_rr_pass"] == True
    assert row["orig_trend_pass"] == True
    assert row["orig_openblk_pass"] == True
    assert row["first_rejection"] == "ATR"
    assert "ATR" in row["rejection_vector"]
    assert row["orig_would_pass"] == False
    assert row["exp_atr_pass"] == False and row["exp_conf_pass"] == True


def test_confluence_formula_matches_spec():
    # bullish, macd cross up, rsi 25 (<30), vol surge 1.0 (<2) -> 2
    assert ef._confluence("BULLISH", True, False, 25.0, 1.0) == 2
    # bullish, no macd cross, rsi 50, vol 3.0 -> 1
    assert ef._confluence("BULLISH", False, False, 50.0, 3.0) == 1
    # bearish overbought counts only for bearish
    assert ef._confluence("BEARISH", False, False, 80.0, 1.0) == 1
    assert ef._confluence("BULLISH", False, False, 80.0, 1.0) == 0


def test_rr_undefined_when_no_structural_target():
    # r1 below price -> production reward=None -> rr undefined -> gate fails
    rr, stop, tgt = ef._rr_structural("BULLISH", 100.0, 1.0, 98.0, 99.0)
    assert np.isnan(rr)
    rr2, _, _ = ef._rr_structural("BULLISH", 100.0, 1.0, 98.0, 106.0)
    assert rr2 == pytest.approx((106 - 100) / (100 - 98))


# --------------------------------------------------------------------------- #
# RSI memory variants
# --------------------------------------------------------------------------- #
def test_rsi_memory_variants_only_relax_the_rsi_leg():
    df = pd.DataFrame([{
        "direction": "BULLISH", "macd_cross_up": False, "macd_cross_dn": False,
        "rsi_t": 45.0, "rsi_t1": 28.0, "rsi_t2": 55.0, "rsi_t3": 60.0,
        "vol_surge": 1.0, "atr_pct": 0.5, "reference_price": 100.0, "struct_stop": 98.0,
        "piv_s1": 98.0, "piv_r1": 104.0, "atr": 1.0, "btr": 1.2, "htf_sma200": 90.0,
        "in_open_blackout": False, "in_close_blackout": False, "rr_structural": 3.0,
        "has_next_bar": True,
    }])
    ef._apply_gates(df)
    r = df.iloc[0]
    assert r["conf_score_mem0"] == 0     # rsi_t 45 not <30, no macd, no vol
    assert r["conf_score_mem1"] == 1     # rsi_t1 28 < 30 within 1-bar memory
    assert r["conf_score_mem2"] == 1
    assert r["conf_score_mem3"] == 1


# --------------------------------------------------------------------------- #
# forward attribution causality + sign + cost
# --------------------------------------------------------------------------- #
def test_forward_horizons_are_causal_and_signed():
    prices = [100] * 40 + [99, 99, 101] + [102, 98, 105] + [110] * 40  # reclaim then a dip then up
    df = _session_frame(prices, highs=[p + 0.05 for p in prices], lows=[p - 0.05 for p in prices])
    df["symbol"] = "TEST"
    df = ef._pandas_ta_indicators(df)
    cands = ef._detect_candidates(df)
    ef._attribute_forward(df, cands)
    c = [x for x in cands if x["trigger_type"] == "F1_AVWAP_RECLAIM"][0]
    ref = c["reference_price"]
    ti = c["trigger_bar_idx"]
    # +15m return = close 15 bars after ref-bar open, relative to ref, BULLISH sign = +
    exp = df["close"].iloc[ti + 1 + 14] / ref - 1.0
    assert c["ret_15m"] == pytest.approx(exp)
    assert c["ret_eod"] == pytest.approx(df["close"].iloc[-1] / ref - 1.0)
    assert c["mfe"] >= c["mae"]          # favourable excursion >= adverse excursion, always
    assert c["mae"] < 0                  # the post-entry dip to 98 is below the reference
    assert c["ret_eod"] > 0              # BULLISH, price ends higher -> positive directional return


def test_bearish_sign_semantics_price_decline_is_positive_directional():
    prices = [10] * 15 + [10] * 3 + [9.5, 9.0, 8.0] + [7.0] * 30
    df = _session_frame(prices, highs=[p + 0.05 for p in prices], lows=[p - 0.05 for p in prices])
    df["symbol"] = "TEST"
    df = ef._pandas_ta_indicators(df)
    cands = ef._detect_candidates(df)
    ef._attribute_forward(df, cands)
    c = [x for x in cands if x["trigger_type"] == "F2_OR_BREAKDOWN"][0]
    # price falls after the breakdown -> "directional return" (decline) is POSITIVE for bearish
    assert c["ret_eod"] > 0
    assert "R_eod" not in c or pd.isna(c.get("R_eod", np.nan))  # no executed-short R for informational


def test_cost_adjustment_is_a_single_roundtrip_subtraction():
    s = pd.DataFrame({"has_next_bar": [True] * 3, "ret_30m": [0.0020, -0.0010, 0.0005],
                      "reference_price": [100.0] * 3, "struct_stop": [98.0] * 3,
                      "direction": ["BULLISH"] * 3, "ret_eod": [0.001, -0.001, 0.0],
                      "mfe": [0.01] * 3, "mae": [-0.01] * 3})
    row = ef._fmt_row(s)
    assert row["gross_bps"] == pytest.approx(np.mean([20, -10, 5]))
    assert row["net10_bps"] == pytest.approx(row["gross_bps"] - 10)
    assert row["net20_bps"] == pytest.approx(row["gross_bps"] - 20)


# --------------------------------------------------------------------------- #
# session boundaries / missing data / determinism
# --------------------------------------------------------------------------- #
def test_load_symbol_keeps_regular_session_only():
    # synthetic file with extended-hours rows must be dropped
    t = pd.date_range("2022-06-15 08:00", "2022-06-15 18:00", freq="1min", tz=ET)
    df = pd.DataFrame({"timestamp": t.tz_convert("UTC"), "symbol": "ZZ",
                       "open": 100.0, "high": 100.1, "low": 99.9, "close": 100.0, "volume": 500})
    p = REPO / "results" / "task101a_event_first" / "_test_ZZ.csv"
    df.to_csv(p, index=False)
    try:
        out = ef._load_symbol(str(p))
    finally:
        p.unlink(missing_ok=True)
    assert out is None or ((out["tod"] >= dt.time(9, 30)) & (out["tod"] < dt.time(16, 0))).all()


def test_deterministic_rerun():
    prices = [100] * 40 + [99, 99, 101] + [101] * 60
    df = _session_frame(prices, highs=[p + 0.05 for p in prices], lows=[p - 0.05 for p in prices])
    df["symbol"] = "TEST"
    df = ef._pandas_ta_indicators(df)
    a = ef._detect_candidates(df.copy())
    b = ef._detect_candidates(df.copy())
    assert [x["candidate_id"] for x in a] == [x["candidate_id"] for x in b]
