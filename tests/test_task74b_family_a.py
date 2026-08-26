"""Task74B Family A -- catalyst feature construction + direction/causality tests."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

from research.task74_alpha_discovery_v2.family_a_catalyst import evaluate
from research.task74_alpha_discovery_v2.features_catalyst import catalyst_features

ET = ZoneInfo("America/New_York")


def _flat_day(symbol, day, price, volume_per_min=100, n=390):
    base = pd.Timestamp(day, tz=ET).replace(hour=9, minute=30)
    rows = []
    for i in range(n + 1):
        ts = (base + pd.Timedelta(minutes=i)).tz_convert("UTC")
        rows.append({"timestamp": ts, "symbol": symbol, "open": price, "high": price + 0.01,
                      "low": price - 0.01, "close": price, "volume": volume_per_min})
    return pd.DataFrame(rows)


def _gap_day(symbol, day, open_price, decision_price, end_price, volume_per_min=100, n=390):
    """Ramps 09:30->10:00 (bar 30) from open_price to decision_price, then to end_price by close."""
    base = pd.Timestamp(day, tz=ET).replace(hour=9, minute=30)
    rows = []
    for i in range(n + 1):
        if i <= 30:
            p = open_price + (decision_price - open_price) * (i / 30)
        else:
            p = decision_price + (end_price - decision_price) * ((i - 30) / (n - 30))
        ts = (base + pd.Timedelta(minutes=i)).tz_convert("UTC")
        rows.append({"timestamp": ts, "symbol": symbol, "open": p, "high": p + 0.01,
                      "low": p - 0.01, "close": p, "volume": volume_per_min})
    return pd.DataFrame(rows)


def _dataset(gap_up=True, high_rvol=True):
    frames = []
    prev_close = 100.0
    for d in range(9):
        day = (pd.Timestamp("2025-06-02") + pd.Timedelta(days=d)).date()
        if day.weekday() >= 5:
            continue
        frames.append(_flat_day("AAPL", day, prev_close, volume_per_min=100))
        prev_close = 100.0
    big_day = (pd.Timestamp("2025-06-02") + pd.Timedelta(days=9)).date()
    gap_open = prev_close * (1.04 if gap_up else 0.96)  # 4% gap
    decision_price = gap_open * (1.005 if gap_up else 0.995)
    end_price = decision_price * (1.02 if gap_up else 0.98)
    vol = 500 if high_rvol else 100
    frames.append(_gap_day("AAPL", big_day, gap_open, decision_price, end_price, volume_per_min=vol))
    return pd.concat(frames, ignore_index=True), big_day


def test_gap_and_rvol_computed_causally():
    bars, big_day = _dataset(gap_up=True, high_rvol=True)
    feat = catalyst_features(bars, decision_hour=10, decision_minute=0)
    row = feat[feat["trading_day"] == big_day]
    assert not row.empty
    row = row.iloc[0]
    assert row["gap_pct"] > 3.5  # ~4% gap
    assert row["rvol"] > 3.0  # 500 vs trailing avg 100 -> 5x


def test_continuation_hypothesis_long_on_gap_up():
    bars, big_day = _dataset(gap_up=True, high_rvol=True)
    out = evaluate(bars)
    rows = out[(out["trading_day"] == big_day) & (out["hypothesis"] == "CONTINUATION")
               & (out["threshold_band"] == "tight") & (out["data_ready"] == True)]  # noqa: E712
    assert not rows.empty
    assert (rows["direction"] == "LONG").all()


def test_reversal_hypothesis_short_on_gap_up():
    bars, big_day = _dataset(gap_up=True, high_rvol=True)
    out = evaluate(bars)
    rows = out[(out["trading_day"] == big_day) & (out["hypothesis"] == "REVERSAL")
               & (out["threshold_band"] == "tight") & (out["data_ready"] == True)]  # noqa: E712
    assert not rows.empty
    assert (rows["direction"] == "SHORT").all()


def test_low_rvol_day_rejected_by_threshold():
    bars, big_day = _dataset(gap_up=True, high_rvol=False)
    out = evaluate(bars)
    rows = out[out["trading_day"] == big_day]
    assert (rows["data_ready"] == False).all()  # noqa: E712
    assert (rows["rejection_reason"] == "THRESHOLD_NOT_MET").all()


def test_entry_strictly_after_decision():
    bars, big_day = _dataset(gap_up=True, high_rvol=True)
    out = evaluate(bars)
    trades = out[out["data_ready"] == True]  # noqa: E712
    assert not trades.empty
    assert (trades["entry_timestamp"] > trades["decision_timestamp"]).all()
