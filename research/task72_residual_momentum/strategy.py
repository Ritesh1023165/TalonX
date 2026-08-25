"""Task72 Part 5/6 -- frozen IDIOSYNCRATIC_RESIDUAL_MOMENTUM_LONG_V1
signal + entry + stop + exit simulation. Reuses Task71's already-tested
causal feature primitives (research/task71_lib/features.py) unmodified;
adds ONLY the stop/time-exit bar-walk that Family C's Task71 evaluator
did not need (Task71 used fixed-horizon-only exits).

Causality invariants (see tests/test_task72_strategy.py):
  - beta uses only trading sessions strictly before the decision day
  - the 09:30->11:00 signal uses only bars at-or-before the decision cutoff
  - entry is the first bar strictly after the decision cutoff
  - the stop is evaluated starting from the bar strictly after entry
  - the exit horizon is bounded by session close (no overnight)
  - no synthetic/interpolated bars anywhere
"""
from __future__ import annotations

import pandas as pd

from research.task71_lib.features import (
    add_session_columns, causal_rolling_beta, daily_bars_from_intraday,
)
from research.task72_residual_momentum import contracts as C

LEDGER_COLUMNS = [
    "symbol", "trading_day", "beta",
    "stock_return_to_decision_pct", "market_return_to_decision_pct", "residual_pct",
    "decision_timestamp", "entry_timestamp", "entry_price",
    "stop_price", "exit_timestamp", "exit_price", "exit_reason",
    "gross_return_pct", "holding_minutes",
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
    contracts.MARKET_BENCHMARK_SYMBOL ('SPY') rows, RTH+premarket 1m bars,
    columns [timestamp(UTC tz-aware), symbol, open, high, low, close,
    volume]. Returns one row per (symbol, trading_day) -- LONG_ONLY, so at
    most one trade per symbol per session, matching contracts.py's frozen
    rule."""
    df = add_session_columns(bars_with_market)
    reg = df[df["is_regular_session"]]
    daily_all = daily_bars_from_intraday(df)
    market_daily = daily_all[daily_all["symbol"] == C.MARKET_BENCHMARK_SYMBOL].drop(columns=["symbol"]).reset_index(drop=True)
    market_bars = reg[reg["symbol"] == C.MARKET_BENCHMARK_SYMBOL].sort_values("timestamp")

    stock_daily = daily_all[daily_all["symbol"] != C.MARKET_BENCHMARK_SYMBOL]
    beta_table = causal_rolling_beta(stock_daily, market_daily, window=C.BETA_LOOKBACK_TRADING_DAYS)
    beta_lookup = beta_table.set_index(["symbol", "trading_day"])["beta"]

    rows: list[dict] = []
    for symbol, sym_bars in reg[reg["symbol"] != C.MARKET_BENCHMARK_SYMBOL].groupby("symbol"):
        for day, day_bars in sym_bars.groupby("trading_day"):
            day_bars = day_bars.sort_values("timestamp")
            beta = beta_lookup.get((symbol, day), None)
            et_day_start = pd.Timestamp(day, tz=day_bars["et_time"].dt.tz)
            open_cutoff = (et_day_start + pd.Timedelta(hours=9, minutes=30)).tz_convert("UTC")
            decision_cutoff = (et_day_start + pd.Timedelta(
                hours=C.DECISION_TIME_ET_HOUR, minutes=C.DECISION_TIME_ET_MINUTE)).tz_convert("UTC")
            session_close_utc = (et_day_start + pd.Timedelta(hours=16)).tz_convert("UTC")

            if beta is None or pd.isna(beta):
                rows.append(_row(symbol=symbol, trading_day=day, beta=beta,
                                  data_ready=False, rejection_reason="DATA_NOT_READY"))
                continue

            stock_open = _price_at_or_before(day_bars, open_cutoff)
            stock_dec = _price_at_or_before(day_bars, decision_cutoff)
            mkt_day_bars = market_bars[market_bars["trading_day"] == day]
            mkt_open = _price_at_or_before(mkt_day_bars, open_cutoff)
            mkt_dec = _price_at_or_before(mkt_day_bars, decision_cutoff)
            if None in (stock_open, stock_dec, mkt_open, mkt_dec) or stock_open == 0 or mkt_open == 0:
                rows.append(_row(symbol=symbol, trading_day=day, beta=beta,
                                  data_ready=False, rejection_reason="DATA_NOT_READY"))
                continue

            stock_ret = (stock_dec - stock_open) / stock_open * 100.0
            mkt_ret = (mkt_dec - mkt_open) / mkt_open * 100.0
            residual = stock_ret - beta * mkt_ret
            decision_ts = day_bars[day_bars["timestamp"] <= decision_cutoff].iloc[-1]["timestamp"]

            if residual < C.RESIDUAL_THRESHOLD_PCT:
                rows.append(_row(symbol=symbol, trading_day=day, beta=beta,
                                  stock_return_to_decision_pct=stock_ret,
                                  market_return_to_decision_pct=mkt_ret, residual_pct=residual,
                                  decision_timestamp=decision_ts,
                                  data_ready=False, rejection_reason="RESIDUAL_BELOW_THRESHOLD"))
                continue

            after = day_bars[day_bars["timestamp"] > decision_ts]
            if after.empty:
                rows.append(_row(symbol=symbol, trading_day=day, beta=beta,
                                  stock_return_to_decision_pct=stock_ret,
                                  market_return_to_decision_pct=mkt_ret, residual_pct=residual,
                                  decision_timestamp=decision_ts,
                                  data_ready=False, rejection_reason="NO_NEXT_BAR_FOR_ENTRY"))
                continue
            entry_bar = after.iloc[0]
            entry_ts, entry_price = entry_bar["timestamp"], float(entry_bar["open"])
            stop_price = entry_price * (1.0 - C.STOP_DISTANCE_PCT / 100.0)
            horizon_end = min(entry_ts + pd.Timedelta(minutes=C.EXIT_HORIZON_MINUTES), session_close_utc)

            window = day_bars[(day_bars["timestamp"] >= entry_ts) & (day_bars["timestamp"] < horizon_end)]
            if window.empty:
                rows.append(_row(symbol=symbol, trading_day=day, beta=beta,
                                  stock_return_to_decision_pct=stock_ret,
                                  market_return_to_decision_pct=mkt_ret, residual_pct=residual,
                                  decision_timestamp=decision_ts, entry_timestamp=entry_ts,
                                  entry_price=entry_price, stop_price=stop_price,
                                  data_ready=False, rejection_reason="NO_VALID_EXIT"))
                continue

            # Stop is checked starting from the bar STRICTLY AFTER entry
            # ("first subsequent 1m bar" per the frozen contract).
            post_entry = window[window["timestamp"] > entry_ts]
            stop_hits = post_entry[post_entry["low"] <= stop_price]
            if not stop_hits.empty:
                stop_bar = stop_hits.iloc[0]
                fill_price = float(stop_bar["open"]) if float(stop_bar["open"]) <= stop_price else stop_price
                exit_ts, exit_price, exit_reason = stop_bar["timestamp"], fill_price, "STOP"
            else:
                last_bar = window.iloc[-1]
                exit_ts, exit_price, exit_reason = last_bar["timestamp"], float(last_bar["close"]), "TIME_EXIT"

            gross = (exit_price - entry_price) / entry_price * 100.0
            holding_minutes = (exit_ts - entry_ts).total_seconds() / 60.0
            rows.append(_row(symbol=symbol, trading_day=day, beta=beta,
                              stock_return_to_decision_pct=stock_ret,
                              market_return_to_decision_pct=mkt_ret, residual_pct=residual,
                              decision_timestamp=decision_ts, entry_timestamp=entry_ts, entry_price=entry_price,
                              stop_price=stop_price, exit_timestamp=exit_ts, exit_price=exit_price,
                              exit_reason=exit_reason, gross_return_pct=gross, holding_minutes=holding_minutes,
                              data_ready=True, rejection_reason=None))
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)
