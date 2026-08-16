"""
tests/test_quant_indicators.py
------------------------------------
Tests talonx_quant.indicators.compute_indicators against a real
RollingBarBuffer + pandas_ta call (no mocking of the indicator math
itself) -- the ATR/bar_true_range fields added for the analyst-review
risk/reward and movement-confirmation filters are new enough (and
mechanical enough to get subtly wrong) to warrant exercising the real
pandas_ta accessor rather than only testing strategy.py's pure functions
against a hand-built IndicatorSnapshot.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_quant.buffer import RollingBarBuffer
from talonx_quant.config import QuantConfig


def _seed_buffer(
    bar_count: int, *, last_high: float | None = None, last_low: float | None = None,
    last_close: float | None = None, start: datetime | None = None,
) -> RollingBarBuffer:
    """
    Seeds a buffer with `bar_count` bars of mild, deterministic price
    movement (so RSI/MACD/ATR all have real, non-degenerate history), then
    optionally overrides the LAST bar's high/low/close -- lets a test
    control the final bar's true range precisely while keeping everything
    upstream realistic. `start` defaults to a fixed pre-market timestamp
    (all bars in the default 120-bar window stay within pre-market, so
    every existing test below is unaffected by buffer.py's session
    tagging); pass a different `start` to make a test's window cross a
    session boundary.
    """
    buf = RollingBarBuffer(max_bars_per_symbol=bar_count + 5)
    start = start if start is not None else datetime(2026, 8, 1, 9, 30, tzinfo=timezone.utc)
    price = 100.0
    for i in range(bar_count):
        price += 0.1 if i % 2 == 0 else -0.05  # mild deterministic drift
        high, low, close = price + 0.5, price - 0.5, price
        if i == bar_count - 1:
            high = last_high if last_high is not None else high
            low = last_low if last_low is not None else low
            close = last_close if last_close is not None else close
        buf.add_bar(
            symbol="AAPL", timestamp=start + timedelta(minutes=i),
            open_=price, high=high, low=low, close=close, volume=1000.0 + i,
        )
    return buf


@pytest.fixture
def config() -> QuantConfig:
    return QuantConfig()


def test_compute_indicators_returns_none_below_min_bars(config):
    from talonx_quant.indicators import compute_indicators

    buf = _seed_buffer(config.min_bars_required - 1)
    df = buf.get_dataframe("AAPL")

    assert compute_indicators(df, config) is None


def test_compute_indicators_returns_atr_once_warmed_up(config):
    from talonx_quant.indicators import compute_indicators

    buf = _seed_buffer(config.min_bars_required)
    df = buf.get_dataframe("AAPL")

    snapshot = compute_indicators(df, config)

    assert snapshot is not None
    assert snapshot.atr is not None
    assert snapshot.atr > 0


def test_bar_true_range_matches_manual_formula(config):
    from talonx_quant.indicators import compute_indicators

    # Force the final bar's high/low far from the prior close so the
    # true-range formula's max() picks a specific, hand-checkable branch.
    buf = _seed_buffer(config.min_bars_required, last_high=150.0, last_low=140.0, last_close=145.0)
    df = buf.get_dataframe("AAPL")
    prev_close = float(df.iloc[-2]["close"])

    snapshot = compute_indicators(df, config)

    expected = max(150.0 - 140.0, abs(150.0 - prev_close), abs(140.0 - prev_close))
    assert snapshot.bar_true_range == pytest.approx(expected)


def test_bar_true_range_none_prev_close_is_used_correctly_for_gap_up(config):
    from talonx_quant.indicators import compute_indicators

    # A gap-up bar: high/low are both ABOVE the prior close, so the
    # |high - prev_close| branch should dominate over high-low.
    buf = _seed_buffer(config.min_bars_required, last_high=200.0, last_low=199.0, last_close=199.5)
    df = buf.get_dataframe("AAPL")
    prev_close = float(df.iloc[-2]["close"])

    snapshot = compute_indicators(df, config)

    assert snapshot.bar_true_range == pytest.approx(abs(200.0 - prev_close))


def test_indicator_snapshot_fields_are_all_present(config):
    from talonx_quant.indicators import compute_indicators

    buf = _seed_buffer(config.min_bars_required)
    df = buf.get_dataframe("AAPL")

    snapshot = compute_indicators(df, config)

    # Regression guard: every field IndicatorSnapshot declares must be
    # populated (not silently dropped) once there's enough warmed-up
    # history -- both the pre-existing indicators and the new ATR ones.
    assert snapshot.rsi is not None
    assert snapshot.macd is not None
    assert snapshot.sma_fast is not None
    assert snapshot.sma_slow is not None
    assert snapshot.volume_surge_ratio is not None
    assert snapshot.atr is not None
    assert snapshot.bar_true_range is not None


# --- Continuous ATR across the session boundary (2026-08-16 quant audit, P1) --
#
# ATR/bar_true_range used to reset at the regular-session open the same
# way the volume baseline below still does -- a 2026-08-16 quant audit
# flagged this as a P1 flaw: the 09:30-09:45 opening range typically runs
# 3-5x wider than midday trading, so restricting ATR's window to just the
# first few post-open bars produced a wildly unstable, artificially
# inflated baseline exactly when the ATR-move gate and structural R:R's
# risk distance most need a stable read. Volatility doesn't reset at a
# session boundary the way liquidity does, so ATR is now computed from
# the FULL buffer, continuous across the boundary -- only the volume
# baseline (a genuinely different, session-scoped concept: thin
# pre-market PARTICIPATION, not true price range) still resets.

def test_atr_uses_the_full_buffer_when_every_bar_is_the_same_session(config):
    """Regression guard: the default _seed_buffer window (all pre-market)
    must produce a real atr/bar_true_range -- sanity baseline before the
    session-crossing test below."""
    from talonx_quant.indicators import compute_indicators, _same_session_tail

    buf = _seed_buffer(config.min_bars_required)
    df = buf.get_dataframe("AAPL")
    assert len(_same_session_tail(df)) == len(df)  # sanity: no boundary crossed

    snapshot = compute_indicators(df, config)
    assert snapshot.atr is not None
    assert snapshot.bar_true_range is not None


def test_atr_is_continuous_across_the_regular_session_open(config):
    """A buffer whose first few bars are pre-market and the rest regular
    (crossing 09:30 ET) must still compute a real ATR/bar_true_range from
    the FULL buffer -- not reset/None right at the boundary the way the
    volume baseline (test_volume_baseline_resets_at_the_regular_session_open)
    deliberately does."""
    from talonx_quant.indicators import compute_indicators

    # 13:25 UTC = 09:25 ET -- 5 minutes of pre-market, then the 6th bar
    # (13:30 UTC = 09:30 ET) crosses into regular session.
    start = datetime(2026, 8, 3, 13, 25, tzinfo=timezone.utc)
    buf = _seed_buffer(config.min_bars_required, start=start)
    df = buf.get_dataframe("AAPL")

    assert df["session"].iloc[0] == "pre_market"
    assert df["session"].iloc[-1] == "regular"

    snapshot = compute_indicators(df, config)

    assert snapshot.atr is not None
    assert snapshot.bar_true_range is not None


def test_atr_is_continuous_even_when_the_regular_session_tail_is_very_short(config):
    """Only 3 bars have crossed into the regular session so far (far
    short of atr_period+1) -- ATR must still be populated from the FULL
    120-bar buffer rather than going None, since it's no longer
    restricted to the (here, very thin) same-session tail."""
    from talonx_quant.indicators import compute_indicators

    buf = _seed_buffer(config.min_bars_required)
    df = buf.get_dataframe("AAPL")
    session_col = df.columns.get_loc("session")
    df.iloc[-3:, session_col] = "regular"
    assert (df["session"].iloc[-3:] == "regular").all()
    assert df["session"].iloc[-4] != "regular"

    snapshot = compute_indicators(df, config)  # must not raise

    assert snapshot.atr is not None
    assert snapshot.bar_true_range is not None


def test_atr_and_bar_true_range_are_continuous_when_the_latest_bar_is_the_sessions_first(config):
    """The buffer's LAST bar is exactly the regular session's FIRST bar
    (09:30 ET), every bar before it pre-market -- ATR/bar_true_range must
    still be populated (reading the previous, pre-market bar's close as
    the "previous close" for this bar's true range), not go None the way
    a session-restricted baseline would right at this exact boundary."""
    from talonx_quant.indicators import compute_indicators

    # 119 minutes before 13:30 UTC (09:30 ET) puts bar 119 (the last of
    # 120) exactly on the regular-session open; bars 0-118 are pre-market.
    start = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc) - timedelta(minutes=config.min_bars_required - 1)
    buf = _seed_buffer(config.min_bars_required, start=start)
    df = buf.get_dataframe("AAPL")
    assert df["session"].iloc[-1] == "regular"
    assert df["session"].iloc[-2] == "pre_market"

    snapshot = compute_indicators(df, config)

    assert snapshot.atr is not None
    assert snapshot.bar_true_range is not None


# --- Dual Volume Baselines (pre-market vs. regular session) --------------

def test_volume_baseline_uses_the_full_buffer_when_every_bar_is_the_same_session(config):
    """Regression guard, mirroring the ATR equivalent above: the default
    _seed_buffer window (all pre-market) must produce a real
    volume_avg/volume_surge_ratio -- the session-aware restriction must
    be a no-op when there's no session boundary in the window."""
    from talonx_quant.indicators import compute_indicators

    buf = _seed_buffer(config.min_bars_required)
    df = buf.get_dataframe("AAPL")

    snapshot = compute_indicators(df, config)

    assert snapshot.volume_avg is not None
    assert snapshot.volume_surge_ratio is not None


def test_volume_baseline_resets_at_the_regular_session_open(config):
    """The buffer's LAST bar is exactly the regular session's FIRST bar
    (09:30 ET), every bar before it pre-market -- the 20-bar volume
    baseline must reset to None here (only 1 same-session bar exists),
    rather than reaching back across the session boundary and blending
    in pre-market volume -- Dual Volume Baselines."""
    from talonx_quant.indicators import compute_indicators

    # Same construction as the ATR-reset regression test: 119 minutes
    # before 13:30 UTC (09:30 ET) puts the last of 120 bars exactly on
    # the regular-session open.
    start = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc) - timedelta(minutes=config.min_bars_required - 1)
    buf = _seed_buffer(config.min_bars_required, start=start)
    df = buf.get_dataframe("AAPL")

    assert df["session"].iloc[-1] == "regular"
    assert df["session"].iloc[-2] == "pre_market"

    snapshot = compute_indicators(df, config)

    assert snapshot.volume_avg is None
    assert snapshot.volume_surge_ratio is None


def test_volume_baseline_recovers_once_enough_regular_session_bars_accumulate(config):
    """Same session-crossing setup, but with volume_avg_period bars of
    regular session AFTER the open -- the baseline should be populated
    again, computed purely from the regular-session bars."""
    from talonx_quant.indicators import compute_indicators

    start = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc) - timedelta(
        minutes=config.min_bars_required - config.volume_avg_period - 5
    )
    buf = _seed_buffer(config.min_bars_required, start=start)
    df = buf.get_dataframe("AAPL")

    regular_bars = int((df["session"] == "regular").sum())
    assert regular_bars >= config.volume_avg_period

    snapshot = compute_indicators(df, config)

    assert snapshot.volume_avg is not None
    assert snapshot.volume_surge_ratio is not None


# --- Structural R:R pivots (prior completed regular-session R1/S1) -------

def test_compute_daily_pivots_returns_none_with_no_prior_session():
    from talonx_quant.indicators import compute_daily_pivots

    buf = RollingBarBuffer(max_bars_per_symbol=50)
    start = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc)  # 09:30 ET
    for i in range(10):
        buf.add_bar(
            symbol="AAPL", timestamp=start + timedelta(minutes=15 * i),
            open_=100.0, high=101.0, low=99.0, close=100.5, volume=1000.0,
        )
    df = buf.get_dataframe("AAPL")

    pivots = compute_daily_pivots(df, start + timedelta(minutes=15 * 10))

    assert pivots is None


def test_compute_daily_pivots_computes_classic_floor_pivot_from_prior_session():
    from talonx_quant.indicators import compute_daily_pivots

    buf = RollingBarBuffer(max_bars_per_symbol=100)
    # Prior day's regular session (2026-08-03, 09:30-11:00 ET): high=110, low=90, close=100.
    prior_start = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc)
    bars = [
        (prior_start, 100.0, 105.0, 95.0, 100.0),
        (prior_start + timedelta(minutes=15), 100.0, 110.0, 95.0, 105.0),
        (prior_start + timedelta(minutes=30), 105.0, 108.0, 90.0, 100.0),  # session high 110, low 90
    ]
    for ts, o, h, l, c in bars:
        buf.add_bar(symbol="AAPL", timestamp=ts, open_=o, high=h, low=l, close=c, volume=1000.0)

    # Next day's regular session (2026-08-04) -- the "current" bar.
    current_ts = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)
    buf.add_bar(symbol="AAPL", timestamp=current_ts, open_=101.0, high=102.0, low=100.0, close=101.0, volume=1000.0)
    df = buf.get_dataframe("AAPL")

    pivots = compute_daily_pivots(df, current_ts)

    # P = (110 + 90 + 100) / 3 = 100; R1 = 2P - low = 110; S1 = 2P - high = 90
    assert pivots is not None
    assert pivots.pivot == pytest.approx(100.0)
    assert pivots.resistance == pytest.approx(110.0)
    assert pivots.support == pytest.approx(90.0)


def test_compute_daily_pivots_ignores_pre_market_bars():
    from talonx_quant.indicators import compute_daily_pivots

    buf = RollingBarBuffer(max_bars_per_symbol=100)
    prior_regular_start = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc)  # 09:30 ET
    prior_premarket_start = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)  # 04:00 ET

    # Pre-market bar with an extreme high that must NOT leak into the pivot.
    buf.add_bar(
        symbol="AAPL", timestamp=prior_premarket_start, open_=100.0,
        high=500.0, low=1.0, close=100.0, volume=500.0,
    )
    buf.add_bar(
        symbol="AAPL", timestamp=prior_regular_start, open_=100.0,
        high=110.0, low=90.0, close=100.0, volume=1000.0,
    )

    current_ts = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)
    buf.add_bar(symbol="AAPL", timestamp=current_ts, open_=101.0, high=102.0, low=100.0, close=101.0, volume=1000.0)
    df = buf.get_dataframe("AAPL")

    pivots = compute_daily_pivots(df, current_ts)

    assert pivots is not None
    assert pivots.resistance == pytest.approx(110.0)  # not derived from the 500.0 pre-market high
    assert pivots.support == pytest.approx(90.0)


def test_compute_daily_pivots_uses_the_most_recent_prior_session_only():
    from talonx_quant.indicators import compute_daily_pivots

    buf = RollingBarBuffer(max_bars_per_symbol=100)
    two_days_ago = datetime(2026, 8, 2, 13, 30, tzinfo=timezone.utc)
    yesterday = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc)

    buf.add_bar(symbol="AAPL", timestamp=two_days_ago, open_=100.0, high=200.0, low=10.0, close=100.0, volume=1000.0)
    buf.add_bar(symbol="AAPL", timestamp=yesterday, open_=100.0, high=110.0, low=90.0, close=100.0, volume=1000.0)

    current_ts = datetime(2026, 8, 4, 14, 0, tzinfo=timezone.utc)
    buf.add_bar(symbol="AAPL", timestamp=current_ts, open_=101.0, high=102.0, low=100.0, close=101.0, volume=1000.0)
    df = buf.get_dataframe("AAPL")

    pivots = compute_daily_pivots(df, current_ts)

    assert pivots is not None
    assert pivots.resistance == pytest.approx(110.0)  # from yesterday, not the 2-day-old 200.0 high
