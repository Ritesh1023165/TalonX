"""Task72 -- frozen strategy causality/stop/exit tests."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from research.task72_residual_momentum import contracts as C
from research.task72_residual_momentum.fingerprint import compute_fingerprint
from research.task72_residual_momentum.strategy import evaluate

ET = ZoneInfo("America/New_York")


def _day_bars(symbol, day, open_price, decision_price, end_price, n=180):
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


def _build_dataset(n_days=50, last_day_stop=False, last_day_gap_stop=False):
    """Beta-warmup dataset (SPY flat, AAPL tracks 1.5x SPY) with a
    deliberate final-day big positive residual. When `last_day_stop`,
    post-entry prices on the last day dip enough to trigger the frozen
    2.5% stop; `last_day_gap_stop` makes the stop bar gap straight
    through the stop price at its OPEN."""
    rng = np.random.default_rng(3)
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

        if d < n_days - 1:
            stock_move = 1.5 * spy_move + rng.normal(0, 0.05)
            stock_open = stock_prev_close
            stock_dec = stock_open + stock_move
            stock_end = stock_dec + rng.normal(0, 0.05)
            frames.append(_day_bars("AAPL", day, stock_open, stock_dec, stock_end))
        else:
            stock_open = stock_prev_close
            stock_dec = stock_open + 3.0  # big positive residual -> LONG fires
            if last_day_stop:
                bars = _day_bars("AAPL", day, stock_open, stock_dec, stock_dec, n=180)
                entry_idx = 91  # first bar strictly after 11:00 decision (bar 90)
                entry_price = bars.loc[entry_idx, "open"]
                stop_price = entry_price * (1 - C.STOP_DISTANCE_PCT / 100.0)
                touch_idx = entry_idx + 5
                if last_day_gap_stop:
                    bars.loc[touch_idx, "open"] = stop_price * 0.9
                    bars.loc[touch_idx, "low"] = stop_price * 0.85
                    bars.loc[touch_idx, "close"] = stop_price * 0.9
                    bars.loc[touch_idx, "high"] = stop_price * 0.9
                else:
                    bars.loc[touch_idx, "low"] = stop_price - 0.01
                bars.loc[entry_idx, "low"] = min(bars.loc[entry_idx, "low"], entry_price - 0.01)
                frames.append(bars)
            else:
                stock_end = stock_dec + 2.0
                frames.append(_day_bars("AAPL", day, stock_open, stock_dec, stock_end))
        stock_prev_close = stock_dec if d == n_days - 1 else stock_end
    return pd.concat(frames, ignore_index=True)


def test_no_lookahead_beta_and_signal():
    bars = _build_dataset()
    out = evaluate(bars)
    trades = out[out["data_ready"] == True]  # noqa: E712
    assert not trades.empty
    last_day = sorted(out["trading_day"].dropna().unique())[-1]
    assert (trades[trades["trading_day"] == last_day]["gross_return_pct"].notna()).all()

    bars_alt = bars.copy()
    last_idx = bars_alt[bars_alt["symbol"] == "AAPL"].index[-1]
    bars_alt.loc[last_idx, "close"] *= 5
    out_alt = evaluate(bars_alt)
    early_day = sorted(out["trading_day"].dropna().unique())[15]
    beta_before = out[out["trading_day"] == early_day]["beta"].iloc[0]
    beta_after = out_alt[out_alt["trading_day"] == early_day]["beta"].iloc[0]
    assert beta_before == beta_after or (pd.isna(beta_before) and pd.isna(beta_after))


def test_entry_is_first_bar_strictly_after_decision():
    bars = _build_dataset()
    out = evaluate(bars)
    last_day = sorted(out["trading_day"].dropna().unique())[-1]
    row = out[(out["trading_day"] == last_day) & (out["data_ready"] == True)].iloc[0]
    assert row["entry_timestamp"] > row["decision_timestamp"]


def test_time_exit_when_no_stop_touched():
    bars = _build_dataset(last_day_stop=False)
    out = evaluate(bars)
    last_day = sorted(out["trading_day"].dropna().unique())[-1]
    row = out[(out["trading_day"] == last_day) & (out["data_ready"] == True)].iloc[0]
    assert row["exit_reason"] == "TIME_EXIT"
    assert row["holding_minutes"] <= C.EXIT_HORIZON_MINUTES + 1


def test_stop_fires_when_low_breaches_stop_price():
    bars = _build_dataset(last_day_stop=True, last_day_gap_stop=False)
    out = evaluate(bars)
    last_day = sorted(out["trading_day"].dropna().unique())[-1]
    row = out[(out["trading_day"] == last_day) & (out["data_ready"] == True)].iloc[0]
    assert row["exit_reason"] == "STOP"
    assert row["exit_price"] == row["stop_price"]
    assert row["gross_return_pct"] < 0


def test_gap_through_stop_fills_at_open_not_better():
    bars = _build_dataset(last_day_stop=True, last_day_gap_stop=True)
    out = evaluate(bars)
    last_day = sorted(out["trading_day"].dropna().unique())[-1]
    row = out[(out["trading_day"] == last_day) & (out["data_ready"] == True)].iloc[0]
    assert row["exit_reason"] == "STOP"
    assert row["exit_price"] < row["stop_price"]  # gapped through -> filled at open, worse than stop


def test_one_trade_per_symbol_per_session():
    bars = _build_dataset()
    out = evaluate(bars)
    counts = out.groupby(["symbol", "trading_day"]).size()
    assert (counts == 1).all()


def test_no_overnight_exit_bounded_by_session_close():
    bars = _build_dataset()
    out = evaluate(bars)
    trades = out[out["data_ready"] == True]  # noqa: E712
    for _, row in trades.iterrows():
        et_close = row["entry_timestamp"].tz_convert(ET).normalize() + pd.Timedelta(hours=16)
        assert row["exit_timestamp"].tz_convert(ET) <= et_close


def test_fingerprint_is_deterministic():
    fp1 = compute_fingerprint()
    fp2 = compute_fingerprint()
    assert fp1 == fp2
    assert len(fp1) == 64
