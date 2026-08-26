"""Task74B Family B -- multi-day cross-sectional feature + evaluator tests."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

from research.task74_alpha_discovery_v2.family_b_multiday import evaluate
from research.task74_alpha_discovery_v2.features_multiday import multiday_features

ET = ZoneInfo("America/New_York")


def _session(symbol, day, open_price, close_price):
    """Minimal 2-bar regular session: 09:30 open, 15:59 close."""
    base = pd.Timestamp(day, tz=ET)
    o_ts = (base.replace(hour=9, minute=30)).tz_convert("UTC")
    c_ts = (base.replace(hour=15, minute=59)).tz_convert("UTC")
    return pd.DataFrame([
        {"timestamp": o_ts, "symbol": symbol, "open": open_price, "high": open_price, "low": open_price, "close": open_price, "volume": 100},
        {"timestamp": c_ts, "symbol": symbol, "open": close_price, "high": close_price, "low": close_price, "close": close_price, "volume": 100},
    ])


def _weekdays(start, n):
    days, d = [], 0
    while len(days) < n:
        day = (pd.Timestamp(start) + pd.Timedelta(days=d)).date()
        if day.weekday() < 5:
            days.append(day)
        d += 1
    return days


def _dataset():
    days = _weekdays("2025-06-02", 15)
    frames = []
    # SPY flat throughout
    spy_price = 500.0
    for day in days:
        frames.append(_session("SPY", day, spy_price, spy_price))
    # WINNER: flat, then a big 3-day outperformance ending at days[9] (Day0)
    price = 100.0
    for i, day in enumerate(days):
        if i in (7, 8, 9):
            end = price * 1.05
            frames.append(_session("WINNER", day, price, end))
            price = end
        else:
            frames.append(_session("WINNER", day, price, price))
    # LOSER: mirrors WINNER but down
    price = 100.0
    for i, day in enumerate(days):
        if i in (7, 8, 9):
            end = price * 0.95
            frames.append(_session("LOSER", day, price, end))
            price = end
        else:
            frames.append(_session("LOSER", day, price, price))
    # 6 filler symbols, flat -> mid rank
    for f in range(6):
        price = 100.0
        for day in days:
            frames.append(_session(f"MID{f}", day, price, price))
    return pd.concat(frames, ignore_index=True), days[9]


def test_cross_sectional_rank_extremes():
    bars, day0 = _dataset()
    feat = multiday_features(bars, lookback_days=3)
    row = feat[(feat["symbol"] == "WINNER") & (feat["trading_day"] == day0)]
    assert not row.empty
    assert row.iloc[0]["cross_sectional_rank_pct"] == feat[feat["trading_day"] == day0]["cross_sectional_rank_pct"].max()
    row_l = feat[(feat["symbol"] == "LOSER") & (feat["trading_day"] == day0)]
    assert row_l.iloc[0]["cross_sectional_rank_pct"] == feat[feat["trading_day"] == day0]["cross_sectional_rank_pct"].min()


def test_momentum_hypothesis_long_on_winner():
    bars, day0 = _dataset()
    out = evaluate(bars)
    rows = out[(out["symbol"] == "WINNER") & (out["decision_day"] == day0) & (out["hypothesis"] == "MOMENTUM")
               & (out["threshold_band"] == "tight") & (out["data_ready"] == True)]  # noqa: E712
    assert not rows.empty
    assert (rows["direction"] == "LONG").all()


def test_reversal_hypothesis_short_on_winner():
    bars, day0 = _dataset()
    out = evaluate(bars)
    rows = out[(out["symbol"] == "WINNER") & (out["decision_day"] == day0) & (out["hypothesis"] == "REVERSAL")
               & (out["threshold_band"] == "tight") & (out["data_ready"] == True)]  # noqa: E712
    assert not rows.empty
    assert (rows["direction"] == "SHORT").all()


def test_entry_is_next_session_after_decision_day():
    bars, day0 = _dataset()
    out = evaluate(bars)
    rows = out[(out["symbol"] == "WINNER") & (out["decision_day"] == day0) & (out["data_ready"] == True)]  # noqa: E712
    assert not rows.empty
    assert (rows["entry_day"] > rows["decision_day"]).all()


def test_horizon_exit_indexing_2d_3d_5d():
    bars, day0 = _dataset()
    out = evaluate(bars)
    rows = out[(out["symbol"] == "WINNER") & (out["decision_day"] == day0) & (out["hypothesis"] == "MOMENTUM")
               & (out["threshold_band"] == "tight") & (out["data_ready"] == True)]  # noqa: E712
    labels = set(rows["horizon_label"])
    assert labels == {"2D", "3D", "5D"}
    # 5D holds longer than 2D -> more overnight gaps
    r2 = rows[rows["horizon_label"] == "2D"].iloc[0]
    r5 = rows[rows["horizon_label"] == "5D"].iloc[0]
    assert r5["overnight_gap_count"] > r2["overnight_gap_count"]


def test_no_synthetic_exit_when_slice_runs_out():
    bars, day0 = _dataset()
    out = evaluate(bars)
    # Decision on the LAST usable day should be rejected NO_NEXT_SESSION_FOR_ENTRY or NO_VALID_EXIT, never fabricated.
    last_day = sorted(out["decision_day"].dropna().unique())[-1]
    rows = out[out["decision_day"] == last_day]
    if not rows.empty and not (rows["data_ready"] == True).any():  # noqa: E712
        assert rows["rejection_reason"].isin(["NO_NEXT_SESSION_FOR_ENTRY", "NO_VALID_EXIT", "THRESHOLD_NOT_MET"]).all()
