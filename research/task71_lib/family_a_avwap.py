"""Task71 Family A -- AVWAP_FLOW_STATE. Isolated research code."""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.task67a_lib.research_stats import forward_return_horizons
from research.task71_lib.features import add_session_columns, rolling_realized_vol, session_avwap

DECISION_TIME_ET = pd.Timedelta(hours=11, minutes=0)
THRESHOLD_BANDS = (1.0, 2.0)
HORIZONS_MINUTES = (30, 60, 120)
LEDGER_COLUMNS = [
    "symbol", "trading_day", "threshold_band", "extension_side", "bet", "direction",
    "normalized_distance", "decision_timestamp", "entry_timestamp", "entry_price",
    "horizon_label", "exit_timestamp", "exit_price", "gross_return_pct",
    "data_ready", "rejection_reason",
]


def _row(**kwargs) -> dict:
    base = {c: None for c in LEDGER_COLUMNS}
    base.update(kwargs)
    return base


def prepare(bars: pd.DataFrame) -> pd.DataFrame:
    df = add_session_columns(bars)
    df = rolling_realized_vol(df, window=20)
    df = session_avwap(df)
    return df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def evaluate(bars: pd.DataFrame) -> pd.DataFrame:
    """One row per (symbol, trading_day, threshold_band, bet, horizon)."""
    df = prepare(bars)
    reg = df[df["is_regular_session"]]
    rows: list[dict] = []

    for (symbol, day), group in reg.groupby(["symbol", "trading_day"], sort=True):
        group = group.sort_values("timestamp")
        et_day_start = pd.Timestamp(day, tz=group["et_time"].dt.tz)
        decision_cutoff = et_day_start + DECISION_TIME_ET
        before = group[group["et_time"] <= decision_cutoff]
        if before.empty:
            for band in THRESHOLD_BANDS:
                rows.append(_row(symbol=symbol, trading_day=day, threshold_band=band, data_ready=False, rejection_reason="DATA_NOT_READY"))
            continue
        decision_bar = before.iloc[-1]
        decision_ts = decision_bar["timestamp"]
        avwap, vol, price = decision_bar["avwap"], decision_bar["realized_vol"], decision_bar["close"]
        if pd.isna(avwap) or pd.isna(vol) or vol == 0:
            for band in THRESHOLD_BANDS:
                rows.append(_row(symbol=symbol, trading_day=day, threshold_band=band, decision_timestamp=decision_ts, data_ready=False, rejection_reason="DATA_NOT_READY"))
            continue
        normalized_distance = ((price - avwap) / price) / vol

        after = group[group["timestamp"] > decision_ts]
        if after.empty:
            for band in THRESHOLD_BANDS:
                rows.append(_row(symbol=symbol, trading_day=day, threshold_band=band, decision_timestamp=decision_ts, normalized_distance=normalized_distance, data_ready=False, rejection_reason="NO_NEXT_BAR_FOR_ENTRY"))
            continue
        entry_bar = after.iloc[0]
        entry_ts, entry_price = entry_bar["timestamp"], float(entry_bar["open"])
        session_close_ts = et_day_start + pd.Timedelta(hours=16)
        session_close_utc = session_close_ts.tz_convert("UTC") if session_close_ts.tzinfo else session_close_ts

        for band in THRESHOLD_BANDS:
            side = None
            if normalized_distance >= band:
                side = "ABOVE"
            elif normalized_distance <= -band:
                side = "BELOW"
            if side is None:
                rows.append(_row(symbol=symbol, trading_day=day, threshold_band=band, decision_timestamp=decision_ts, normalized_distance=normalized_distance, data_ready=False, rejection_reason="AVWAP_DISTANCE_BELOW_THRESHOLD"))
                continue
            bets = [("CONTINUATION", "LONG" if side == "ABOVE" else "SHORT"), ("REVERSION", "SHORT" if side == "ABOVE" else "LONG")]
            horizon_results = forward_return_horizons(
                group, entry_timestamp=entry_ts, entry_price=entry_price,
                horizons_minutes=list(HORIZONS_MINUTES), session_close_timestamp=session_close_utc,
            )
            for bet, direction in bets:
                for h in horizon_results:
                    if h["bars_observed"] == 0:
                        rows.append(_row(symbol=symbol, trading_day=day, threshold_band=band, extension_side=side, bet=bet, direction=direction,
                                          normalized_distance=normalized_distance, decision_timestamp=decision_ts, entry_timestamp=entry_ts, entry_price=entry_price,
                                          horizon_label=h["horizon_label"], data_ready=False, rejection_reason="NO_VALID_EXIT"))
                        continue
                    raw_ret = h["forward_close_return_pct"]
                    signed_ret = raw_ret if direction == "LONG" else -raw_ret
                    rows.append(_row(symbol=symbol, trading_day=day, threshold_band=band, extension_side=side, bet=bet, direction=direction,
                                      normalized_distance=normalized_distance, decision_timestamp=decision_ts, entry_timestamp=entry_ts, entry_price=entry_price,
                                      horizon_label=h["horizon_label"], exit_timestamp=h["bounded_end"], gross_return_pct=signed_ret,
                                      data_ready=True, rejection_reason=None))
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)
