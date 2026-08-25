"""Task71 -- causal feature construction tests (Part: causal feature
construction, VWAP calculation, premarket/session boundaries,
rolling-beta causality, gap calculation, structural-level calculation)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.task71_lib.features import (
    add_session_columns, causal_rolling_beta, daily_bars_from_intraday,
    overnight_gap, prior_day_levels, rolling_realized_vol, session_avwap,
)
from research.task71_lib.holdout_guard import DevelopmentOnlyGuard, HoldoutProtectionError


def _bars(symbol, day, times_et, opens, highs, lows, closes, volumes):
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    rows = []
    for t, o, h, l, c, v in zip(times_et, opens, highs, lows, closes, volumes):
        hour, minute = t
        ts = pd.Timestamp(day, tz=et).replace(hour=hour, minute=minute).tz_convert("UTC")
        rows.append({"timestamp": ts, "symbol": symbol, "open": o, "high": h, "low": l, "close": c, "volume": v})
    return pd.DataFrame(rows)


def test_session_columns_classify_premarket_regular_and_after_hours():
    df = _bars("AAPL", "2025-06-02", [(8, 0), (9, 30), (12, 0), (16, 30)],
               [100, 101, 102, 103], [100, 101, 102, 103], [100, 101, 102, 103], [100, 101, 102, 103], [10, 10, 10, 10])
    out = add_session_columns(df)
    assert out["is_premarket"].tolist() == [True, False, False, False]
    assert out["is_regular_session"].tolist() == [False, True, True, False]


def test_session_avwap_is_causal_and_regular_session_only():
    # Two regular-session bars with different volume weights; premarket bar must not affect avwap.
    df = _bars("AAPL", "2025-06-02", [(8, 0), (9, 30), (9, 31)],
               [90, 100, 200], [90, 100, 200], [90, 100, 200], [90, 100, 200], [1000, 10, 10])
    df = add_session_columns(df)
    out = session_avwap(df)
    assert pd.isna(out["avwap"].iloc[0])  # premarket bar excluded
    assert out["avwap"].iloc[1] == pytest.approx(100.0)  # first regular bar: avwap == its own close
    expected_second = (100 * 10 + 200 * 10) / (10 + 10)
    assert out["avwap"].iloc[2] == pytest.approx(expected_second)
    # Causality: the FIRST regular bar's avwap must not depend on the second bar's price at all.
    df_alt = df.copy()
    df_alt.loc[df_alt.index[2], "close"] = 9999.0
    out_alt = session_avwap(df_alt)
    assert out_alt["avwap"].iloc[1] == out["avwap"].iloc[1]


def test_rolling_realized_vol_uses_only_trailing_bars():
    closes = [100, 101, 99, 102, 98, 103, 97, 104, 96, 105]
    df = _bars("AAPL", "2025-06-02", [(9, 30 + i) for i in range(10)],
               closes, closes, closes, closes, [10] * 10)
    out = rolling_realized_vol(df, window=4)
    # Changing a LATER close must not change an EARLIER bar's realized_vol.
    df_alt = df.copy()
    df_alt.loc[df_alt.index[9], "close"] = 9999.0
    out_alt = rolling_realized_vol(df_alt, window=4)
    assert out["realized_vol"].iloc[4] == pytest.approx(out_alt["realized_vol"].iloc[4])


def test_prior_day_levels_never_leak_same_day_extremes():
    day1 = _bars("AAPL", "2025-06-02", [(9, 30), (10, 0)], [100, 100], [105, 90], [95, 80], [100, 85], [10, 10])
    day2 = _bars("AAPL", "2025-06-03", [(9, 30)], [86], [86], [86], [86], [10])
    df = pd.concat([day1, day2], ignore_index=True)
    df = add_session_columns(df)
    out = prior_day_levels(df)
    day2_row = out[out["trading_day"] == pd.Timestamp("2025-06-03").date()].iloc[0]
    assert day2_row["prior_day_high"] == pytest.approx(105.0)
    assert day2_row["prior_day_low"] == pytest.approx(80.0)
    # day 1's own rows must have NaN prior_day_high (no history before it)
    day1_rows = out[out["trading_day"] == pd.Timestamp("2025-06-02").date()]
    assert day1_rows["prior_day_high"].isna().all()


def test_overnight_gap_uses_prior_close_and_todays_open_only():
    daily = pd.DataFrame({
        "symbol": ["AAPL", "AAPL", "AAPL"],
        "trading_day": [pd.Timestamp("2025-06-02").date(), pd.Timestamp("2025-06-03").date(), pd.Timestamp("2025-06-04").date()],
        "open": [100.0, 102.0, 97.0], "close": [100.0, 100.0, 97.0], "high": [101, 103, 98], "low": [99, 101, 96],
    })
    out = overnight_gap(daily)
    assert pd.isna(out["gap_pct"].iloc[0])
    assert out["gap_pct"].iloc[1] == pytest.approx(2.0)  # (102-100)/100*100
    assert out["gap_pct"].iloc[2] == pytest.approx(-3.0)  # (97-100)/100*100 vs day1's close=100


def test_causal_rolling_beta_only_uses_strictly_prior_days():
    days = pd.date_range("2025-01-02", periods=30, freq="B")
    rng = np.random.default_rng(0)
    market_ret = rng.normal(0, 0.01, size=30)
    market_close = 100 * np.cumprod(1 + market_ret)
    market_daily = pd.DataFrame({"trading_day": [d.date() for d in days], "close": market_close})
    stock_ret = 1.5 * market_ret + rng.normal(0, 0.001, size=30)
    stock_close = 50 * np.cumprod(1 + stock_ret)
    stock_daily = pd.DataFrame({"symbol": ["AAPL"] * 30, "trading_day": [d.date() for d in days], "close": stock_close})

    out = causal_rolling_beta(stock_daily, market_daily, window=20)
    # Recover something close to the true beta=1.5 once enough trailing history exists.
    late_beta = out["beta"].iloc[-1]
    assert late_beta == pytest.approx(1.5, abs=0.3)

    # Causality: perturbing the LAST day's stock return must not change an EARLIER day's beta.
    stock_daily_alt = stock_daily.copy()
    stock_daily_alt.loc[stock_daily_alt.index[-1], "close"] *= 5
    out_alt = causal_rolling_beta(stock_daily_alt, market_daily, window=20)
    assert out["beta"].iloc[25] == pytest.approx(out_alt["beta"].iloc[25])


def test_daily_bars_from_intraday_uses_regular_session_only():
    df = _bars("AAPL", "2025-06-02", [(8, 0), (9, 30), (12, 0), (15, 59)],
               [50, 100, 101, 102], [50, 105, 106, 107], [50, 95, 96, 97], [50, 100, 101, 102], [999, 10, 10, 10])
    df = add_session_columns(df)
    daily = daily_bars_from_intraday(df)
    assert len(daily) == 1
    assert daily.iloc[0]["open"] == pytest.approx(100.0)  # NOT the premarket 50
    assert daily.iloc[0]["close"] == pytest.approx(102.0)


def test_holdout_guard_blocks_any_2024_date_range():
    guard = DevelopmentOnlyGuard()
    with pytest.raises(HoldoutProtectionError):
        guard.check("2024-02-01", "2024-03-15")
    with pytest.raises(HoldoutProtectionError):
        guard.check("2023-12-01", "2024-01-15")  # straddles into 2024
    guard.check("2025-02-03", "2025-03-14")  # must not raise
    assert guard.checks_performed == 1
