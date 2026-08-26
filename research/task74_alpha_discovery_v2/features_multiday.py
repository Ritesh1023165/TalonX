"""Task74B Family B -- causal feature construction: market-adjusted
multi-day cross-sectional displacement + rank. Reuses
research/task71_lib/features.py's session/daily-bar primitives.
"""
from __future__ import annotations

import pandas as pd

from research.task71_lib.features import add_session_columns, daily_bars_from_intraday

MARKET_SYMBOL = "SPY"
LOOKBACK_DAYS_DEFAULT = 3


def multiday_features(bars_with_market: pd.DataFrame, lookback_days: int = LOOKBACK_DAYS_DEFAULT) -> pd.DataFrame:
    """One row per (symbol, trading_day) [Day0, a completed session]:
    market_adjusted_return_pct = stock's trailing `lookback_days`-day
    cumulative return minus SPY's over the SAME window (causal -- both
    windows end at and include Day0's own completed close), and
    cross_sectional_rank_pct = that day's percentile rank among all
    universe symbols with a valid value that day. Also carries each
    day's regular-session open/close AND the actual first/last bar
    timestamps (needed for entry/exit simulation)."""
    df = add_session_columns(bars_with_market)
    reg = df[df["is_regular_session"]]
    daily = daily_bars_from_intraday(df).sort_values(["symbol", "trading_day"]).reset_index(drop=True)
    ts_bounds = reg.groupby(["symbol", "trading_day"])["timestamp"].agg(open_timestamp="min", close_timestamp="max").reset_index()
    daily = daily.merge(ts_bounds, on=["symbol", "trading_day"], how="left")

    market_daily = daily[daily["symbol"] == MARKET_SYMBOL].sort_values("trading_day").reset_index(drop=True)
    market_daily["market_ret_pct"] = market_daily["close"].pct_change(periods=lookback_days) * 100.0
    market_ret = market_daily.set_index("trading_day")["market_ret_pct"]

    stock_daily = daily[daily["symbol"] != MARKET_SYMBOL].copy()
    stock_daily["stock_ret_pct"] = stock_daily.groupby("symbol")["close"].pct_change(periods=lookback_days) * 100.0
    stock_daily["market_ret_pct"] = stock_daily["trading_day"].map(market_ret)
    stock_daily = stock_daily.dropna(subset=["stock_ret_pct", "market_ret_pct"])
    stock_daily["market_adjusted_return_pct"] = stock_daily["stock_ret_pct"] - stock_daily["market_ret_pct"]
    stock_daily["cross_sectional_rank_pct"] = stock_daily.groupby("trading_day")["market_adjusted_return_pct"].rank(pct=True)
    return stock_daily.reset_index(drop=True)
