"""Task71 Family B -- OVERNIGHT_GAP_CONTINUATION (not "PEAD" -- see
results/task71_structural_discovery/event_data_audit.json). Isolated
research code."""
from __future__ import annotations

import pandas as pd

from research.task67a_lib.research_stats import forward_return_horizons
from research.task71_lib.features import (
    add_session_columns, daily_bars_from_intraday, overnight_gap,
)

GAP_THRESHOLD_BANDS_PCT = (1.0, 2.0)
INTRADAY_HORIZONS_MINUTES = (120, 180)
MULTIDAY_HORIZON_LABELS = ("NEXT_DAY_CLOSE", "3_DAY_CLOSE")
LEDGER_COLUMNS = [
    "symbol", "trading_day", "gap_threshold_band", "gap_pct", "direction",
    "decision_timestamp", "entry_timestamp", "entry_price",
    "horizon_label", "horizon_family", "exit_timestamp", "exit_price", "gross_return_pct",
    "data_ready", "rejection_reason",
]


def _row(**kwargs) -> dict:
    base = {c: None for c in LEDGER_COLUMNS}
    base.update(kwargs)
    return base


def evaluate(bars: pd.DataFrame) -> pd.DataFrame:
    df = add_session_columns(bars)
    daily = daily_bars_from_intraday(df)
    daily = overnight_gap(daily)
    daily_sorted = daily.sort_values(["symbol", "trading_day"]).reset_index(drop=True)

    rows: list[dict] = []
    for symbol, sym_daily in daily_sorted.groupby("symbol"):
        sym_daily = sym_daily.reset_index(drop=True)
        sym_bars = df[(df["symbol"] == symbol) & df["is_regular_session"]].sort_values("timestamp")
        for i, day_row in sym_daily.iterrows():
            day = day_row["trading_day"]
            gap_pct = day_row["gap_pct"]
            day_bars = sym_bars[sym_bars["trading_day"] == day]
            if pd.isna(gap_pct) or day_bars.empty:
                for band in GAP_THRESHOLD_BANDS_PCT:
                    rows.append(_row(symbol=symbol, trading_day=day, gap_threshold_band=band, gap_pct=gap_pct, data_ready=False, rejection_reason="DATA_NOT_READY"))
                continue
            open_bar = day_bars.iloc[0]
            decision_ts = open_bar["timestamp"]
            after = day_bars[day_bars["timestamp"] > decision_ts]
            if after.empty:
                for band in GAP_THRESHOLD_BANDS_PCT:
                    rows.append(_row(symbol=symbol, trading_day=day, gap_threshold_band=band, gap_pct=gap_pct, decision_timestamp=decision_ts, data_ready=False, rejection_reason="NO_NEXT_BAR_FOR_ENTRY"))
                continue
            entry_bar = after.iloc[0]
            entry_ts, entry_price = entry_bar["timestamp"], float(entry_bar["open"])
            et_day_start = pd.Timestamp(day, tz=day_bars["et_time"].dt.tz)
            session_close_utc = (et_day_start + pd.Timedelta(hours=16)).tz_convert("UTC")

            for band in GAP_THRESHOLD_BANDS_PCT:
                if gap_pct >= band:
                    direction = "LONG"
                elif gap_pct <= -band:
                    direction = "SHORT"
                else:
                    rows.append(_row(symbol=symbol, trading_day=day, gap_threshold_band=band, gap_pct=gap_pct, decision_timestamp=decision_ts, data_ready=False, rejection_reason="GAP_BELOW_THRESHOLD"))
                    continue

                intraday = forward_return_horizons(
                    day_bars, entry_timestamp=entry_ts, entry_price=entry_price,
                    horizons_minutes=list(INTRADAY_HORIZONS_MINUTES) + [None], session_close_timestamp=session_close_utc,
                )
                for h in intraday:
                    label = "EOD" if h["horizon_label"] == "TO_SESSION_CLOSE" else h["horizon_label"]
                    if h["bars_observed"] == 0:
                        rows.append(_row(symbol=symbol, trading_day=day, gap_threshold_band=band, gap_pct=gap_pct, direction=direction,
                                          decision_timestamp=decision_ts, entry_timestamp=entry_ts, entry_price=entry_price,
                                          horizon_label=label, horizon_family="INTRADAY_SHORT", data_ready=False, rejection_reason="NO_VALID_EXIT"))
                        continue
                    raw = h["forward_close_return_pct"]
                    signed = raw if direction == "LONG" else -raw
                    rows.append(_row(symbol=symbol, trading_day=day, gap_threshold_band=band, gap_pct=gap_pct, direction=direction,
                                      decision_timestamp=decision_ts, entry_timestamp=entry_ts, entry_price=entry_price,
                                      horizon_label=label, horizon_family="INTRADAY_SHORT", exit_timestamp=h["bounded_end"],
                                      gross_return_pct=signed, data_ready=True, rejection_reason=None))

                for n_ahead, label in ((1, "NEXT_DAY_CLOSE"), (3, "3_DAY_CLOSE")):
                    target_idx = i + n_ahead
                    if target_idx >= len(sym_daily):
                        rows.append(_row(symbol=symbol, trading_day=day, gap_threshold_band=band, gap_pct=gap_pct, direction=direction,
                                          decision_timestamp=decision_ts, entry_timestamp=entry_ts, entry_price=entry_price,
                                          horizon_label=label, horizon_family="MULTI_DAY", data_ready=False, rejection_reason="NO_VALID_EXIT"))
                        continue
                    exit_close = float(sym_daily.iloc[target_idx]["close"])
                    exit_day = sym_daily.iloc[target_idx]["trading_day"]
                    raw = (exit_close - entry_price) / entry_price * 100.0
                    signed = raw if direction == "LONG" else -raw
                    rows.append(_row(symbol=symbol, trading_day=day, gap_threshold_band=band, gap_pct=gap_pct, direction=direction,
                                      decision_timestamp=decision_ts, entry_timestamp=entry_ts, entry_price=entry_price,
                                      horizon_label=label, horizon_family="MULTI_DAY", exit_timestamp=exit_day, exit_price=exit_close,
                                      gross_return_pct=signed, data_ready=True, rejection_reason=None))
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)
