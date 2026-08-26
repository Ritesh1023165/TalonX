"""Task74B Family B -- MULTIDAY_CROSS_SECTIONAL_MOMENTUM_OR_REVERSAL.
Isolated research code. See results/task74_alpha_discovery_v2/
research_design_lock_v2.json for the locked mechanism/parameters.

No stop -- fixed-horizon-only discovery (STOP_UNRESOLVED per instruction).
No synthetic daily bars: horizon exits are bounded by each slice's actual
last trading day; if the required forward session does not exist within
the slice, the row is rejected NO_VALID_EXIT, never fabricated.
"""
from __future__ import annotations

import pandas as pd

from research.task71_lib.features import add_session_columns, daily_bars_from_intraday
from research.task74_alpha_discovery_v2.features_multiday import MARKET_SYMBOL, multiday_features

THRESHOLD_BANDS = [
    {"label": "tight", "upper_percentile": 0.90, "lower_percentile": 0.10},
    {"label": "loose", "upper_percentile": 0.80, "lower_percentile": 0.20},
]
HYPOTHESES = ["MOMENTUM", "REVERSAL"]
HORIZONS_TRADING_DAYS = [2, 3, 5]
LEDGER_COLUMNS = [
    "symbol", "decision_day", "hypothesis", "threshold_band", "market_adjusted_return_pct", "cross_sectional_rank_pct",
    "direction", "entry_day", "entry_timestamp", "entry_price",
    "horizon_label", "exit_day", "exit_timestamp", "exit_price", "gross_return_pct",
    "overnight_gap_count", "data_ready", "rejection_reason",
]


def _row(**kwargs) -> dict:
    base = {c: None for c in LEDGER_COLUMNS}
    base.update(kwargs)
    return base


def _direction_for(hypothesis: str, rank: float, upper: float, lower: float) -> str | None:
    if rank >= upper:
        return "LONG" if hypothesis == "MOMENTUM" else "SHORT"
    if rank <= lower:
        return "SHORT" if hypothesis == "MOMENTUM" else "LONG"
    return None


def evaluate(bars_with_market: pd.DataFrame) -> pd.DataFrame:
    df = add_session_columns(bars_with_market)
    reg = df[df["is_regular_session"]]
    full_daily = daily_bars_from_intraday(df).sort_values(["symbol", "trading_day"]).reset_index(drop=True)
    ts_bounds = reg.groupby(["symbol", "trading_day"])["timestamp"].agg(open_timestamp="min", close_timestamp="max").reset_index()
    full_daily = full_daily.merge(ts_bounds, on=["symbol", "trading_day"], how="left")
    full_daily = full_daily[full_daily["symbol"] != MARKET_SYMBOL]

    feat = multiday_features(bars_with_market)
    if feat.empty:
        return pd.DataFrame(columns=LEDGER_COLUMNS)

    per_symbol_series = {sym: g.sort_values("trading_day").reset_index(drop=True) for sym, g in full_daily.groupby("symbol")}

    rows: list[dict] = []
    for _, f in feat.iterrows():
        symbol = f["symbol"]
        series = per_symbol_series.get(symbol)
        if series is None:
            continue
        day_positions = series.index[series["trading_day"] == f["trading_day"]]
        if len(day_positions) == 0:
            continue
        i = int(day_positions[0])
        entry_idx = i + 1

        for band in THRESHOLD_BANDS:
            for hypothesis in HYPOTHESES:
                direction = _direction_for(hypothesis, f["cross_sectional_rank_pct"], band["upper_percentile"], band["lower_percentile"])
                base_kwargs = dict(symbol=symbol, decision_day=f["trading_day"], hypothesis=hypothesis, threshold_band=band["label"],
                                    market_adjusted_return_pct=f["market_adjusted_return_pct"], cross_sectional_rank_pct=f["cross_sectional_rank_pct"])
                if direction is None:
                    rows.append(_row(**base_kwargs, data_ready=False, rejection_reason="THRESHOLD_NOT_MET"))
                    continue
                if entry_idx >= len(series):
                    rows.append(_row(**base_kwargs, direction=direction, data_ready=False, rejection_reason="NO_NEXT_SESSION_FOR_ENTRY"))
                    continue
                entry_row = series.iloc[entry_idx]
                entry_price = float(entry_row["open"])

                for horizon_days in HORIZONS_TRADING_DAYS:
                    exit_idx = entry_idx + horizon_days - 1
                    label = f"{horizon_days}D"
                    if exit_idx >= len(series):
                        rows.append(_row(**base_kwargs, direction=direction, entry_day=entry_row["trading_day"],
                                          entry_timestamp=entry_row["open_timestamp"], entry_price=entry_price,
                                          horizon_label=label, data_ready=False, rejection_reason="NO_VALID_EXIT"))
                        continue
                    exit_row = series.iloc[exit_idx]
                    exit_price = float(exit_row["close"])
                    hold_slice = series.iloc[entry_idx:exit_idx + 1]
                    overnight_gap_count = max(0, len(hold_slice) - 1)
                    raw = (exit_price - entry_price) / entry_price * 100.0
                    signed = raw if direction == "LONG" else -raw
                    rows.append(_row(**base_kwargs, direction=direction, entry_day=entry_row["trading_day"],
                                      entry_timestamp=entry_row["open_timestamp"], entry_price=entry_price,
                                      horizon_label=label, exit_day=exit_row["trading_day"],
                                      exit_timestamp=exit_row["close_timestamp"], exit_price=exit_price,
                                      gross_return_pct=signed, overnight_gap_count=overnight_gap_count,
                                      data_ready=True, rejection_reason=None))
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)
