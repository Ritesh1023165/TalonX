"""Task75A Part 3 -- canonical market-session calendar, anchored to SPY's
own observed regular-session trading days. See
results/task75_cross_sectional_extreme_winner_short_reversion/
calendar_session_contract.json for the full policy and impact audit.
"""
from __future__ import annotations

import pandas as pd

from research.task71_lib.features import add_session_columns, daily_bars_from_intraday

MARKET_SYMBOL = "SPY"


def build_daily_table(bars: pd.DataFrame) -> pd.DataFrame:
    """One row per (symbol, trading_day): open/close + first/last bar
    timestamps, regular session only."""
    df = add_session_columns(bars)
    reg = df[df["is_regular_session"]]
    daily = daily_bars_from_intraday(df).sort_values(["symbol", "trading_day"]).reset_index(drop=True)
    ts_bounds = reg.groupby(["symbol", "trading_day"])["timestamp"].agg(open_timestamp="min", close_timestamp="max").reset_index()
    return daily.merge(ts_bounds, on=["symbol", "trading_day"], how="left")


def canonical_calendar(daily: pd.DataFrame) -> list:
    """The ordered list of SPY's own regular-session trading days --
    the ONLY calendar Day0/Day1/exit positions are ever indexed against."""
    spy = daily[daily["symbol"] == MARKET_SYMBOL].sort_values("trading_day")
    return spy["trading_day"].tolist()


def per_symbol_day_lookup(daily: pd.DataFrame) -> dict:
    """{symbol: {trading_day: row_dict}} for O(1) required-session checks."""
    out: dict = {}
    for symbol, group in daily.groupby("symbol"):
        out[symbol] = {row["trading_day"]: row for _, row in group.iterrows()}
    return out
