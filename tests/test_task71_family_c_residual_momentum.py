"""Task71 Family C (residual momentum) -- causal-beta and direction tests."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from research.task71_lib.family_c_residual_momentum import evaluate

ET = ZoneInfo("America/New_York")


def _day_bars(symbol, day, open_price, decision_price, end_price, n=180):
    """Prices ramp from open_price to decision_price by 11:00 (bar 90),
    then to end_price by session end."""
    base = pd.Timestamp(day, tz=ET).replace(hour=9, minute=30)
    rows = []
    for i in range(n):
        if i <= 90:
            p = open_price + (decision_price - open_price) * (i / 90)
        else:
            p = decision_price + (end_price - decision_price) * ((i - 90) / (n - 90))
        ts = (base + pd.Timedelta(minutes=i)).tz_convert("UTC")
        rows.append({"timestamp": ts, "symbol": symbol, "open": p, "high": p + 0.05, "low": p - 0.05, "close": p, "volume": 100})
    return pd.DataFrame(rows)


def _build_dataset(n_days=50):
    rng = np.random.default_rng(1)
    frames = []
    stock_prev_close, spy_prev_close = 100.0, 500.0
    for d in range(n_days):
        day = (pd.Timestamp("2025-06-02") + pd.Timedelta(days=d)).date()
        if day.weekday() >= 5:
            continue
        spy_move = rng.normal(0, 0.3)
        spy_open = spy_prev_close
        spy_dec = spy_open + spy_move
        spy_end = spy_dec + rng.normal(0, 0.2)
        frames.append(_day_bars("SPY", day, spy_open, spy_dec, spy_end))
        spy_prev_close = spy_end

        if d < n_days - 1:  # last day gets the deliberate large residual
            stock_move = 1.5 * spy_move + rng.normal(0, 0.05)
            stock_open = stock_prev_close
            stock_dec = stock_open + stock_move
            stock_end = stock_dec + rng.normal(0, 0.05)
        else:
            # Deliberate: stock moves up hard while SPY is flat -> big positive residual.
            stock_open = stock_prev_close
            stock_dec = stock_open + 3.0
            stock_end = stock_dec + 2.0
        frames.append(_day_bars("AAPL", day, stock_open, stock_dec, stock_end))
        stock_prev_close = stock_end
    return pd.concat(frames, ignore_index=True)


def test_beta_uses_only_trailing_days_and_residual_signal_direction():
    bars = _build_dataset()
    out = evaluate(bars)
    trades = out[out["data_ready"] == True]  # noqa: E712
    assert not trades.empty
    # The last day's deliberate large positive residual should produce a LONG signal.
    last_day = sorted(out["trading_day"].dropna().unique())[-1]
    last_day_trades = trades[trades["trading_day"] == last_day]
    assert not last_day_trades.empty
    assert (last_day_trades["direction"] == "LONG").all()

    # Causality: mutating a LATER day's stock price must not change an EARLIER day's beta.
    bars_alt = bars.copy()
    last_aapl_idx = bars_alt[(bars_alt["symbol"] == "AAPL")].index[-1]
    bars_alt.loc[last_aapl_idx, "close"] *= 3
    bars_alt.loc[last_aapl_idx, "open"] *= 3
    out_alt = evaluate(bars_alt)
    early_day = sorted(out["trading_day"].dropna().unique())[15]
    beta_before = out[out["trading_day"] == early_day]["beta"].iloc[0]
    beta_after = out_alt[out_alt["trading_day"] == early_day]["beta"].iloc[0]
    assert beta_before == beta_after or (pd.isna(beta_before) and pd.isna(beta_after))
