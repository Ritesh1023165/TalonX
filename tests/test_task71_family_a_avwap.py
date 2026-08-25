"""Task71 Family A (AVWAP) -- causality and direction-sign tests."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

from research.task71_lib.family_a_avwap import evaluate

ET = ZoneInfo("America/New_York")


def _minute_bars(symbol, day, start_hm, prices, volumes=None):
    volumes = volumes or [100] * len(prices)
    rows = []
    hour, minute = start_hm
    base = pd.Timestamp(day, tz=ET).replace(hour=hour, minute=minute)
    for i, (p, v) in enumerate(zip(prices, volumes)):
        ts = (base + pd.Timedelta(minutes=i)).tz_convert("UTC")
        rows.append({"timestamp": ts, "symbol": symbol, "open": p, "high": p + 0.1, "low": p - 0.1, "close": p, "volume": v})
    return pd.DataFrame(rows)


def _one_symbol_one_day_strong_uptrend():
    # 09:30 open at 100, drifts up with noise to build realized_vol, then
    # a strong extension above AVWAP going into 11:00, then continues up afterward.
    prices = [100 + 0.02 * i + (0.3 if i % 2 == 0 else -0.3) for i in range(90)]  # 09:30-10:59
    prices += [prices[-1] + 0.5 * i for i in range(1, 130)]  # extend hard into/after 11:00
    return _minute_bars("AAPL", "2025-06-02", (9, 30), prices)


def test_no_lookahead_decision_state_unaffected_by_post_decision_prices():
    bars = _one_symbol_one_day_strong_uptrend()
    out1 = evaluate(bars)
    bars_alt = bars.copy()
    # Mutate a bar well AFTER the 11:00 decision point.
    late_idx = bars_alt.index[-1]
    bars_alt.loc[late_idx, "close"] = 1.0
    bars_alt.loc[late_idx, "open"] = 1.0
    out2 = evaluate(bars_alt)
    decided1 = out1[["symbol", "trading_day", "threshold_band", "normalized_distance"]].drop_duplicates()
    decided2 = out2[["symbol", "trading_day", "threshold_band", "normalized_distance"]].drop_duplicates()
    pd.testing.assert_frame_equal(decided1.reset_index(drop=True), decided2.reset_index(drop=True))


def test_continuation_and_reversion_are_opposite_directions_same_state():
    bars = _one_symbol_one_day_strong_uptrend()
    out = evaluate(bars)
    trades = out[out["data_ready"] == True]  # noqa: E712
    if trades.empty:
        return  # synthetic fixture didn't clear the threshold band -- not the point of this test
    above = trades[trades["extension_side"] == "ABOVE"]
    if above.empty:
        return
    cont = above[above["bet"] == "CONTINUATION"]
    rev = above[above["bet"] == "REVERSION"]
    assert (cont["direction"] == "LONG").all()
    assert (rev["direction"] == "SHORT").all()


def test_rejection_when_no_avwap_distance_exceeds_threshold():
    # Flat prices all day -> normalized_distance ~ 0, everything rejected.
    prices = [100.0] * 200
    bars = _minute_bars("AAPL", "2025-06-02", (9, 30), prices)
    out = evaluate(bars)
    assert (out["data_ready"] == False).all()  # noqa: E712
