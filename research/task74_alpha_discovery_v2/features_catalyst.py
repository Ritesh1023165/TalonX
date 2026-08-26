"""Task74B Family A -- causal feature construction: overnight gap
magnitude + relative activity (RVOL) trigger. Reuses
research/task71_lib/features.py's session/daily-bar primitives.
"""
from __future__ import annotations

import pandas as pd

from research.task71_lib.features import add_session_columns, daily_bars_from_intraday

TRAILING_DAYS_DEFAULT = 10


def catalyst_features(bars: pd.DataFrame, decision_hour: int, decision_minute: int, trailing_days: int = TRAILING_DAYS_DEFAULT) -> pd.DataFrame:
    """One row per (symbol, trading_day): gap_pct (causal -- prior day's
    completed close vs. today's open), rvol (today's 09:30->decision
    cumulative volume vs. a CAUSAL trailing-`trailing_days`-day average of
    the SAME time-of-day window, prior days only, today excluded)."""
    df = add_session_columns(bars)
    reg = df[df["is_regular_session"]]
    daily = daily_bars_from_intraday(df).sort_values(["symbol", "trading_day"]).reset_index(drop=True)
    daily["prior_close"] = daily.groupby("symbol")["close"].shift(1)
    daily["gap_pct"] = (daily["open"] - daily["prior_close"]) / daily["prior_close"] * 100.0

    partial_vol_rows = []
    decision_ts_lookup = {}
    for (symbol, day), day_bars in reg.groupby(["symbol", "trading_day"]):
        day_bars = day_bars.sort_values("timestamp")
        et_day_start = pd.Timestamp(day, tz=day_bars["et_time"].dt.tz)
        open_cutoff = (et_day_start + pd.Timedelta(hours=9, minutes=30)).tz_convert("UTC")
        decision_cutoff = (et_day_start + pd.Timedelta(hours=decision_hour, minutes=decision_minute)).tz_convert("UTC")
        window = day_bars[(day_bars["timestamp"] >= open_cutoff) & (day_bars["timestamp"] <= decision_cutoff)]
        if window.empty:
            continue
        partial_vol_rows.append({"symbol": symbol, "trading_day": day, "partial_volume": float(window["volume"].sum())})
        decision_ts_lookup[(symbol, day)] = window.iloc[-1]["timestamp"]

    pv = pd.DataFrame(partial_vol_rows).sort_values(["symbol", "trading_day"]).reset_index(drop=True)
    pv["trailing_avg_partial_volume"] = pv.groupby("symbol")["partial_volume"].transform(
        lambda s: s.shift(1).rolling(trailing_days, min_periods=max(3, trailing_days // 2)).mean()
    )
    pv["rvol"] = pv["partial_volume"] / pv["trailing_avg_partial_volume"]

    merged = daily.merge(pv, on=["symbol", "trading_day"], how="inner")
    merged = merged.dropna(subset=["gap_pct", "rvol"])
    merged["decision_timestamp"] = merged.apply(lambda r: decision_ts_lookup.get((r["symbol"], r["trading_day"])), axis=1)
    merged = merged.dropna(subset=["decision_timestamp"])
    return merged[["symbol", "trading_day", "gap_pct", "rvol", "decision_timestamp"]].reset_index(drop=True)
