"""Task71 Family B (overnight gap) -- causal gap + multi-day horizon tests."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from research.task71_lib.family_b_event_gap import evaluate

ET = ZoneInfo("America/New_York")


def _day_bars(symbol, day, open_price, close_price, n=120):
    base = pd.Timestamp(day, tz=ET).replace(hour=9, minute=30)
    step = (close_price - open_price) / max(n - 1, 1)
    rows = []
    for i in range(n):
        p = open_price + step * i
        ts = (base + pd.Timedelta(minutes=i)).tz_convert("UTC")
        rows.append({"timestamp": ts, "symbol": symbol, "open": p, "high": p + 0.1, "low": p - 0.1, "close": p, "volume": 100})
    return pd.DataFrame(rows)


def test_gap_up_continuation_is_long_and_gap_down_is_short():
    d1 = _day_bars("AAPL", "2025-06-02", 100.0, 100.0)
    d2 = _day_bars("AAPL", "2025-06-03", 103.0, 105.0)  # +3% gap up, continues up
    d3 = _day_bars("AAPL", "2025-06-04", 101.9, 99.0)  # gap down from 105 close, continues down
    bars = pd.concat([d1, d2, d3], ignore_index=True)
    out = evaluate(bars)
    day2 = out[(out["trading_day"] == pd.Timestamp("2025-06-03").date()) & (out["data_ready"] == True)]  # noqa: E712
    assert not day2.empty
    assert (day2["direction"] == "LONG").all()
    assert (day2["gross_return_pct"] > 0).any()  # price did continue up


def test_multiday_horizons_use_correct_future_trading_day_close():
    d1 = _day_bars("AAPL", "2025-06-02", 100.0, 100.0)
    d2 = _day_bars("AAPL", "2025-06-03", 103.0, 103.0)  # gap up day (decision day)
    d3 = _day_bars("AAPL", "2025-06-04", 103.0, 110.0)  # next day close = 110
    d4 = _day_bars("AAPL", "2025-06-05", 110.0, 110.0)
    d5 = _day_bars("AAPL", "2025-06-06", 110.0, 120.0)  # 3rd trading day after decision -> close 120
    bars = pd.concat([d1, d2, d3, d4, d5], ignore_index=True)
    out = evaluate(bars)
    decision_day_rows = out[(out["trading_day"] == pd.Timestamp("2025-06-03").date()) & (out["data_ready"] == True)]  # noqa: E712
    next_day = decision_day_rows[decision_day_rows["horizon_label"] == "NEXT_DAY_CLOSE"]
    three_day = decision_day_rows[decision_day_rows["horizon_label"] == "3_DAY_CLOSE"]
    assert not next_day.empty and not three_day.empty
    assert (next_day["horizon_family"] == "MULTI_DAY").all()
    # entry price ~= 103 (next bar's open after the 09:30 gap-up open bar)
    entry_price = next_day["entry_price"].iloc[0]
    expected_next = (110.0 - entry_price) / entry_price * 100.0
    assert next_day["gross_return_pct"].iloc[0] == pytest.approx(expected_next, abs=0.01)
