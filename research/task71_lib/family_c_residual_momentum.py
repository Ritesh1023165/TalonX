"""Task71 Family C -- IDIOSYNCRATIC_RESIDUAL_MOMENTUM. Isolated research
code. Beta is estimated causally (trailing daily window strictly before
the decision day) -- see research/task71_lib/features.causal_rolling_beta.
"""
from __future__ import annotations

import pandas as pd

from research.task67a_lib.research_stats import forward_return_horizons
from research.task71_lib.features import (
    add_session_columns, causal_rolling_beta, daily_bars_from_intraday,
)

DECISION_TIME_ET = pd.Timedelta(hours=11, minutes=0)
BETA_WINDOW_DAYS = 20
THRESHOLD_BANDS_PCT = (0.75, 1.5)
HORIZONS_MINUTES = (60, 120, 180)
MARKET_SYMBOL = "SPY"
LEDGER_COLUMNS = [
    "symbol", "trading_day", "threshold_band", "beta", "stock_return_to_decision_pct",
    "market_return_to_decision_pct", "residual_pct", "direction",
    "decision_timestamp", "entry_timestamp", "entry_price",
    "horizon_label", "exit_timestamp", "gross_return_pct",
    "data_ready", "rejection_reason",
]


def _row(**kwargs) -> dict:
    base = {c: None for c in LEDGER_COLUMNS}
    base.update(kwargs)
    return base


def _price_at_or_before(day_bars: pd.DataFrame, cutoff_utc) -> float | None:
    window = day_bars[day_bars["timestamp"] <= cutoff_utc]
    if window.empty:
        return None
    return float(window.iloc[-1]["close"])


def evaluate(bars_with_market: pd.DataFrame) -> pd.DataFrame:
    """`bars_with_market` must include both the stock universe AND
    MARKET_SYMBOL ('SPY') rows."""
    df = add_session_columns(bars_with_market)
    reg = df[df["is_regular_session"]]
    daily_all = daily_bars_from_intraday(df)
    market_daily = daily_all[daily_all["symbol"] == MARKET_SYMBOL].drop(columns=["symbol"]).reset_index(drop=True)
    market_bars = reg[reg["symbol"] == MARKET_SYMBOL].sort_values("timestamp")

    stock_daily = daily_all[daily_all["symbol"] != MARKET_SYMBOL]
    beta_table = causal_rolling_beta(stock_daily, market_daily, window=BETA_WINDOW_DAYS)
    beta_lookup = beta_table.set_index(["symbol", "trading_day"])["beta"]

    rows: list[dict] = []
    for symbol, sym_bars in reg[reg["symbol"] != MARKET_SYMBOL].groupby("symbol"):
        for day, day_bars in sym_bars.groupby("trading_day"):
            day_bars = day_bars.sort_values("timestamp")
            beta = beta_lookup.get((symbol, day), None)
            et_day_start = pd.Timestamp(day, tz=day_bars["et_time"].dt.tz)
            open_cutoff = (et_day_start + pd.Timedelta(hours=9, minutes=30)).tz_convert("UTC")
            decision_cutoff = (et_day_start + DECISION_TIME_ET).tz_convert("UTC")

            if beta is None or pd.isna(beta):
                for band in THRESHOLD_BANDS_PCT:
                    rows.append(_row(symbol=symbol, trading_day=day, threshold_band=band, beta=beta, data_ready=False, rejection_reason="DATA_NOT_READY"))
                continue

            stock_open = _price_at_or_before(day_bars, open_cutoff)
            stock_dec = _price_at_or_before(day_bars, decision_cutoff)
            mkt_day_bars = market_bars[market_bars["trading_day"] == day]
            mkt_open = _price_at_or_before(mkt_day_bars, open_cutoff)
            mkt_dec = _price_at_or_before(mkt_day_bars, decision_cutoff)
            if None in (stock_open, stock_dec, mkt_open, mkt_dec) or stock_open == 0 or mkt_open == 0:
                for band in THRESHOLD_BANDS_PCT:
                    rows.append(_row(symbol=symbol, trading_day=day, threshold_band=band, beta=beta, data_ready=False, rejection_reason="DATA_NOT_READY"))
                continue

            stock_ret = (stock_dec - stock_open) / stock_open * 100.0
            mkt_ret = (mkt_dec - mkt_open) / mkt_open * 100.0
            residual = stock_ret - beta * mkt_ret
            decision_ts = day_bars[day_bars["timestamp"] <= decision_cutoff].iloc[-1]["timestamp"]
            after = day_bars[day_bars["timestamp"] > decision_ts]
            if after.empty:
                for band in THRESHOLD_BANDS_PCT:
                    rows.append(_row(symbol=symbol, trading_day=day, threshold_band=band, beta=beta, stock_return_to_decision_pct=stock_ret,
                                      market_return_to_decision_pct=mkt_ret, residual_pct=residual, decision_timestamp=decision_ts,
                                      data_ready=False, rejection_reason="NO_NEXT_BAR_FOR_ENTRY"))
                continue
            entry_bar = after.iloc[0]
            entry_ts, entry_price = entry_bar["timestamp"], float(entry_bar["open"])
            session_close_utc = (et_day_start + pd.Timedelta(hours=16)).tz_convert("UTC")

            for band in THRESHOLD_BANDS_PCT:
                if residual >= band:
                    direction = "LONG"
                elif residual <= -band:
                    direction = "SHORT"
                else:
                    rows.append(_row(symbol=symbol, trading_day=day, threshold_band=band, beta=beta, stock_return_to_decision_pct=stock_ret,
                                      market_return_to_decision_pct=mkt_ret, residual_pct=residual, decision_timestamp=decision_ts,
                                      data_ready=False, rejection_reason="RESIDUAL_BELOW_THRESHOLD"))
                    continue
                horizon_results = forward_return_horizons(
                    day_bars, entry_timestamp=entry_ts, entry_price=entry_price,
                    horizons_minutes=list(HORIZONS_MINUTES) + [None], session_close_timestamp=session_close_utc,
                )
                for h in horizon_results:
                    label = "EOD" if h["horizon_label"] == "TO_SESSION_CLOSE" else h["horizon_label"]
                    if h["bars_observed"] == 0:
                        rows.append(_row(symbol=symbol, trading_day=day, threshold_band=band, beta=beta, stock_return_to_decision_pct=stock_ret,
                                          market_return_to_decision_pct=mkt_ret, residual_pct=residual, direction=direction,
                                          decision_timestamp=decision_ts, entry_timestamp=entry_ts, entry_price=entry_price,
                                          horizon_label=label, data_ready=False, rejection_reason="NO_VALID_EXIT"))
                        continue
                    raw = h["forward_close_return_pct"]
                    signed = raw if direction == "LONG" else -raw
                    rows.append(_row(symbol=symbol, trading_day=day, threshold_band=band, beta=beta, stock_return_to_decision_pct=stock_ret,
                                      market_return_to_decision_pct=mkt_ret, residual_pct=residual, direction=direction,
                                      decision_timestamp=decision_ts, entry_timestamp=entry_ts, entry_price=entry_price,
                                      horizon_label=label, exit_timestamp=h["bounded_end"], gross_return_pct=signed,
                                      data_ready=True, rejection_reason=None))
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)
