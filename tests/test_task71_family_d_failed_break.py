"""Task71 Family D (failed structural break) -- causality and reclaim tests."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

from research.task71_lib.family_d_failed_break import evaluate

ET = ZoneInfo("America/New_York")


def _bars(symbol, day, prices, start_hm=(9, 30)):
    base = pd.Timestamp(day, tz=ET).replace(hour=start_hm[0], minute=start_hm[1])
    rows = []
    for i, p in enumerate(prices):
        ts = (base + pd.Timedelta(minutes=i)).tz_convert("UTC")
        rows.append({"timestamp": ts, "symbol": symbol, "open": p, "high": p + 0.05, "low": p - 0.05, "close": p, "volume": 100})
    return pd.DataFrame(rows)


def test_failed_break_above_prior_high_produces_short_signal():
    day1 = _bars("AAPL", "2025-06-02", [100.0] * 100)  # prior_day_high = 100.05
    # Day 2: penetrates above (high > 100.05), then reclaims back below within window, then drifts down.
    prices = [100.0, 100.0, 101.0, 100.0] + [99.0 - 0.01 * i for i in range(120)]
    day2 = _bars("AAPL", "2025-06-03", prices)
    bars = pd.concat([day1, day2], ignore_index=True)
    out = evaluate(bars)
    day2_trades = out[(out["trading_day"] == pd.Timestamp("2025-06-03").date()) & (out["data_ready"] == True)]  # noqa: E712
    assert not day2_trades.empty
    assert (day2_trades["side"] == "HIGH").any()
    assert (day2_trades[day2_trades["side"] == "HIGH"]["direction"] == "SHORT").all()


def test_no_reclaim_within_window_is_rejected_not_fabricated():
    day1 = _bars("AAPL", "2025-06-02", [100.0] * 100)
    # Day 2: penetrates above and NEVER reclaims (stays elevated for the whole window+session).
    prices = [101.0] * 200
    day2 = _bars("AAPL", "2025-06-03", prices)
    bars = pd.concat([day1, day2], ignore_index=True)
    out = evaluate(bars)
    day2_rows = out[out["trading_day"] == pd.Timestamp("2025-06-03").date()]
    assert (day2_rows["data_ready"] == False).all()  # noqa: E712
    assert (day2_rows["rejection_reason"] == "NO_FAILED_BREAK_EVENT").all()


def test_prior_day_level_is_causal_not_same_day():
    # First trading day in the dataset has no prior day -> must reject as DATA_NOT_READY, never fabricate a level.
    day1 = _bars("AAPL", "2025-06-02", [100.0, 105.0, 99.0] + [100.0] * 50)
    out = evaluate(day1)
    assert (out["rejection_reason"] == "DATA_NOT_READY").all()
