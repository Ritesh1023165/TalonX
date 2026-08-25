"""Task71 Family D -- FAILED_STRUCTURAL_BREAK. Isolated research code.
Named honestly (not "liquidity trap" -- no order-book data exists here)."""
from __future__ import annotations

import pandas as pd

from research.task67a_lib.research_stats import forward_return_horizons
from research.task71_lib.features import add_session_columns, prior_day_levels

RECLAIM_WINDOW_MINUTES_BANDS = (15, 30)
HORIZONS_MINUTES = (30, 60, 120)
LEDGER_COLUMNS = [
    "symbol", "trading_day", "reclaim_window_band", "side", "direction",
    "penetration_depth_pct", "time_beyond_level_minutes",
    "penetration_timestamp", "reclaim_timestamp", "decision_timestamp",
    "entry_timestamp", "entry_price", "horizon_label", "exit_timestamp",
    "gross_return_pct", "data_ready", "rejection_reason",
]


def _row(**kwargs) -> dict:
    base = {c: None for c in LEDGER_COLUMNS}
    base.update(kwargs)
    return base


def _find_failed_break(day_bars: pd.DataFrame, side: str, level: float, window_minutes: int):
    """side='HIGH': looks for a bar whose `high` penetrates above `level`,
    then a later bar (within window_minutes) whose `close` reclaims back
    below `level`. side='LOW' is the mirror. Returns
    (penetration_row, reclaim_row, depth_pct, minutes_beyond) or None."""
    if side == "HIGH":
        pen_mask = day_bars["high"] > level
    else:
        pen_mask = day_bars["low"] < level
    if not pen_mask.any():
        return None
    pen_idx = day_bars.index[pen_mask][0]
    pen_row = day_bars.loc[pen_idx]
    pen_ts = pen_row["timestamp"]
    window_end = pen_ts + pd.Timedelta(minutes=window_minutes)
    after = day_bars[(day_bars["timestamp"] > pen_ts) & (day_bars["timestamp"] <= window_end)]
    if side == "HIGH":
        reclaim_mask = after["close"] < level
        depth_pct = (pen_row["high"] - level) / level * 100.0
    else:
        reclaim_mask = after["close"] > level
        depth_pct = (level - pen_row["low"]) / level * 100.0
    if not reclaim_mask.any():
        return None
    reclaim_idx = after.index[reclaim_mask][0]
    reclaim_row = after.loc[reclaim_idx]
    minutes_beyond = (reclaim_row["timestamp"] - pen_ts).total_seconds() / 60.0
    return pen_row, reclaim_row, depth_pct, minutes_beyond


def evaluate(bars: pd.DataFrame) -> pd.DataFrame:
    df = add_session_columns(bars)
    df = prior_day_levels(df)
    reg = df[df["is_regular_session"]].sort_values(["symbol", "timestamp"])

    rows: list[dict] = []
    for (symbol, day), day_bars in reg.groupby(["symbol", "trading_day"], sort=True):
        day_bars = day_bars.sort_values("timestamp")
        prior_high = day_bars["prior_day_high"].iloc[0]
        prior_low = day_bars["prior_day_low"].iloc[0]
        et_day_start = pd.Timestamp(day, tz=day_bars["et_time"].dt.tz)
        session_close_utc = (et_day_start + pd.Timedelta(hours=16)).tz_convert("UTC")

        for band in RECLAIM_WINDOW_MINUTES_BANDS:
            if pd.isna(prior_high) or pd.isna(prior_low):
                rows.append(_row(symbol=symbol, trading_day=day, reclaim_window_band=band, data_ready=False, rejection_reason="DATA_NOT_READY"))
                continue
            found_any = False
            for side, level, direction in (("HIGH", prior_high, "SHORT"), ("LOW", prior_low, "LONG")):
                result = _find_failed_break(day_bars, side, level, band)
                if result is None:
                    continue
                pen_row, reclaim_row, depth_pct, minutes_beyond = result
                decision_ts = reclaim_row["timestamp"]
                after = day_bars[day_bars["timestamp"] > decision_ts]
                if after.empty:
                    rows.append(_row(symbol=symbol, trading_day=day, reclaim_window_band=band, side=side, direction=direction,
                                      penetration_depth_pct=depth_pct, time_beyond_level_minutes=minutes_beyond,
                                      penetration_timestamp=pen_row["timestamp"], reclaim_timestamp=decision_ts,
                                      decision_timestamp=decision_ts, data_ready=False, rejection_reason="NO_NEXT_BAR_FOR_ENTRY"))
                    found_any = True
                    continue
                entry_bar = after.iloc[0]
                entry_ts, entry_price = entry_bar["timestamp"], float(entry_bar["open"])
                horizon_results = forward_return_horizons(
                    day_bars, entry_timestamp=entry_ts, entry_price=entry_price,
                    horizons_minutes=list(HORIZONS_MINUTES), session_close_timestamp=session_close_utc,
                )
                for h in horizon_results:
                    if h["bars_observed"] == 0:
                        rows.append(_row(symbol=symbol, trading_day=day, reclaim_window_band=band, side=side, direction=direction,
                                          penetration_depth_pct=depth_pct, time_beyond_level_minutes=minutes_beyond,
                                          penetration_timestamp=pen_row["timestamp"], reclaim_timestamp=decision_ts,
                                          decision_timestamp=decision_ts, entry_timestamp=entry_ts, entry_price=entry_price,
                                          horizon_label=h["horizon_label"], data_ready=False, rejection_reason="NO_VALID_EXIT"))
                        found_any = True
                        continue
                    raw = h["forward_close_return_pct"]
                    signed = raw if direction == "LONG" else -raw
                    rows.append(_row(symbol=symbol, trading_day=day, reclaim_window_band=band, side=side, direction=direction,
                                      penetration_depth_pct=depth_pct, time_beyond_level_minutes=minutes_beyond,
                                      penetration_timestamp=pen_row["timestamp"], reclaim_timestamp=decision_ts,
                                      decision_timestamp=decision_ts, entry_timestamp=entry_ts, entry_price=entry_price,
                                      horizon_label=h["horizon_label"], exit_timestamp=h["bounded_end"], gross_return_pct=signed,
                                      data_ready=True, rejection_reason=None))
                    found_any = True
            if not found_any:
                rows.append(_row(symbol=symbol, trading_day=day, reclaim_window_band=band, data_ready=False, rejection_reason="NO_FAILED_BREAK_EVENT"))
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)
