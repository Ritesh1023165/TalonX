"""Task71 -- causal feature construction shared by families A-D. Every
function here only uses information available strictly at or before the
bar/day being computed for -- no function looks forward. Input is always
a talonx_backtest.data-normalized DataFrame (columns: timestamp [UTC
tz-aware], symbol, open, high, low, close, volume).
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ET = ZoneInfo("America/New_York")
REGULAR_OPEN = pd.Timedelta(hours=9, minutes=30)
REGULAR_CLOSE = pd.Timedelta(hours=16, minutes=0)
PREMARKET_START = pd.Timedelta(hours=4, minutes=0)


def add_session_columns(bars: pd.DataFrame) -> pd.DataFrame:
    """Adds: et_time (tz-aware ET timestamp), trading_day (ET calendar
    date), minutes_since_midnight_et, is_regular_session, is_premarket.
    Pure/causal -- derived only from each bar's own timestamp."""
    df = bars.copy()
    et = df["timestamp"].dt.tz_convert(ET)
    df["et_time"] = et
    df["trading_day"] = et.dt.date
    tod = et - et.dt.normalize()
    df["minutes_since_midnight_et"] = tod.dt.total_seconds() / 60.0
    df["is_regular_session"] = (tod >= REGULAR_OPEN) & (tod < REGULAR_CLOSE)
    df["is_premarket"] = (tod >= PREMARKET_START) & (tod < REGULAR_OPEN)
    return df


def session_avwap(bars: pd.DataFrame) -> pd.DataFrame:
    """Adds `avwap` -- causal session-anchored VWAP, regular session only:
    cumsum(close*volume)/cumsum(volume) within each (symbol, trading_day),
    in chronological order. Rows outside the regular session get NaN.
    Requires add_session_columns to have been run already."""
    df = bars.copy()
    df = df.sort_values(["symbol", "timestamp"])
    reg = df[df["is_regular_session"]].copy()
    reg["_pv"] = reg["close"] * reg["volume"]
    grouped = reg.groupby(["symbol", "trading_day"], sort=False)
    reg["avwap"] = grouped["_pv"].cumsum() / grouped["volume"].cumsum()
    df["avwap"] = np.nan
    df.loc[reg.index, "avwap"] = reg["avwap"]
    return df


def rolling_realized_vol(bars: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Adds `realized_vol` -- rolling std of 1-bar pct returns over the
    trailing `window` bars, per symbol, in chronological order. Causal:
    at bar i this only uses bars [i-window+1, i]."""
    df = bars.copy()
    df = df.sort_values(["symbol", "timestamp"])
    min_periods = min(window, max(2, window // 2))
    ret = df.groupby("symbol")["close"].pct_change()
    df["realized_vol"] = ret.groupby(df["symbol"]).transform(lambda s: s.rolling(window, min_periods=min_periods).std())
    return df


def prior_day_levels(bars: pd.DataFrame) -> pd.DataFrame:
    """Adds `prior_day_high`, `prior_day_low`, `prior_day_close` -- the
    PREVIOUS trading day's regular-session high/low/close, broadcast onto
    every bar of the current trading day. Causal: only uses data from a
    strictly earlier trading_day."""
    df = bars.copy()
    reg = df[df["is_regular_session"]]
    daily = reg.groupby(["symbol", "trading_day"]).agg(
        day_high=("high", "max"), day_low=("low", "min"), day_close=("close", "last"),
    ).reset_index()
    daily = daily.sort_values(["symbol", "trading_day"])
    daily["prior_day_high"] = daily.groupby("symbol")["day_high"].shift(1)
    daily["prior_day_low"] = daily.groupby("symbol")["day_low"].shift(1)
    daily["prior_day_close"] = daily.groupby("symbol")["day_close"].shift(1)
    out = df.merge(
        daily[["symbol", "trading_day", "prior_day_high", "prior_day_low", "prior_day_close"]],
        on=["symbol", "trading_day"], how="left",
    )
    return out


def daily_bars_from_intraday(bars: pd.DataFrame) -> pd.DataFrame:
    """Collapses regular-session intraday bars into one row per
    (symbol, trading_day): open (first regular bar's open), close (last
    regular bar's close). Used for daily-return beta estimation and gap
    calculation."""
    reg = bars[bars["is_regular_session"]].sort_values(["symbol", "trading_day", "timestamp"])
    daily = reg.groupby(["symbol", "trading_day"]).agg(
        open=("open", "first"), close=("close", "last"), high=("high", "max"), low=("low", "min"),
    ).reset_index()
    return daily.sort_values(["symbol", "trading_day"]).reset_index(drop=True)


def causal_rolling_beta(stock_daily: pd.DataFrame, market_daily: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Per symbol, per trading_day: OLS beta of stock daily close-to-close
    returns vs market (e.g. SPY) daily returns, estimated over the
    TRAILING `window` days STRICTLY BEFORE the current trading_day (never
    including it). Returns one row per (symbol, trading_day) with `beta`
    (NaN until `window` prior days of history exist).
    """
    market_daily = market_daily.sort_values("trading_day").reset_index(drop=True)
    market_daily["market_return"] = market_daily["close"].pct_change()
    market_ret = market_daily.set_index("trading_day")["market_return"]

    out_rows = []
    for symbol, group in stock_daily.groupby("symbol"):
        group = group.sort_values("trading_day").reset_index(drop=True)
        group["stock_return"] = group["close"].pct_change()
        merged = group.merge(market_ret.rename("market_return"), left_on="trading_day", right_index=True, how="left")
        stock_r = merged["stock_return"].to_numpy()
        mkt_r = merged["market_return"].to_numpy()
        betas = np.full(len(merged), np.nan)
        for i in range(len(merged)):
            lo = i - window
            if lo < 0:
                continue
            x = mkt_r[lo:i]
            y = stock_r[lo:i]
            mask = ~(np.isnan(x) | np.isnan(y))
            if mask.sum() < max(5, window // 2):
                continue
            xm, ym = x[mask], y[mask]
            var_x = np.var(xm)
            if var_x == 0 or np.isnan(var_x):
                continue
            cov_xy = np.mean((xm - xm.mean()) * (ym - ym.mean()))
            betas[i] = cov_xy / var_x
        merged["beta"] = betas
        out_rows.append(merged[["symbol", "trading_day", "beta"]])
    return pd.concat(out_rows, ignore_index=True)


def overnight_gap(daily: pd.DataFrame) -> pd.DataFrame:
    """Adds `gap_pct` = (today's regular open - prior trading day's
    regular close) / prior close, per symbol. Causal by construction
    (only uses yesterday's close and today's own open, both already
    known at today's open)."""
    daily = daily.sort_values(["symbol", "trading_day"]).reset_index(drop=True)
    daily["prior_close"] = daily.groupby("symbol")["close"].shift(1)
    daily["gap_pct"] = (daily["open"] - daily["prior_close"]) / daily["prior_close"] * 100.0
    return daily
