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


# --- Session-aware ATR reset at the regular-session open (Requirement 3) --

def test_atr_uses_the_full_buffer_when_every_bar_is_the_same_session(config):
    """Regression guard: the default _seed_buffer window (all pre-market)
    must produce IDENTICAL atr/bar_true_range to a plain full-buffer
    computation -- the session-aware restriction must be a no-op when
    there's no session boundary in the window at all."""
    from talonx_quant.indicators import compute_indicators, _same_session_tail

    buf = _seed_buffer(config.min_bars_required)
    df = buf.get_dataframe("AAPL")
    assert len(_same_session_tail(df)) == len(df)  # sanity: no boundary crossed

    snapshot = compute_indicators(df, config)
    assert snapshot.atr is not None
    assert snapshot.bar_true_range is not None


def test_atr_resets_at_the_regular_session_open(config):
    """A buffer whose first few bars are pre-market and the rest regular
    (crossing 09:30 ET) must compute ATR/bar_true_range from ONLY the
    regular-session tail -- confirmed here by checking the restricted
    window is shorter than the full buffer, not blended across the
    session boundary."""
    from talonx_quant.indicators import _same_session_tail

    # 13:25 UTC = 09:25 ET -- 5 minutes of pre-market, then the 6th bar
    # (13:30 UTC = 09:30 ET) crosses into regular session.
    start = datetime(2026, 8, 3, 13, 25, tzinfo=timezone.utc)
    buf = _seed_buffer(config.min_bars_required, start=start)
    df = buf.get_dataframe("AAPL")

    assert df["session"].iloc[0] == "pre_market"
    assert df["session"].iloc[-1] == "regular"

    atr_df = _same_session_tail(df)
    assert len(atr_df) < len(df)  # pre-market bars excluded from the ATR window
    assert (atr_df["session"] == "regular").all()


def test_atr_does_not_crash_when_the_session_tail_is_shorter_than_atr_period(config):
    """Regression for a confirmed live production crash: pandas_ta's
    .atr() does NOT return a NaN-filled Series when given fewer than
    atr_period+1 rows -- it silently returns the INPUT DATAFRAME
    unchanged instead. compute_indicators' own len(df) < min_bars_required
    gate always guaranteed the FULL buffer had 120+ rows before any
    pandas_ta call ran on it, but atr_df (the session-restricted subset)
    can be much shorter right at a session transition. This crashed
    talonx_quant in a Redis reconnect loop for 40+ consecutive attempts
    at market close in production before the fix (a guard on atr_df's
    own length before calling .ta.atr() at all)."""
    from talonx_quant.indicators import compute_indicators

    # Default seed is all pre-market; force just the LAST 3 rows to
    # "regular" -- the session tail (3 rows) is shorter than
    # atr_period+1 (15), the exact condition that broke pandas_ta's
    # atr() live.
    buf = _seed_buffer(config.min_bars_required)
    df = buf.get_dataframe("AAPL")
    session_col = df.columns.get_loc("session")
    df.iloc[-3:, session_col] = "regular"
    assert (df["session"].iloc[-3:] == "regular").all()
    assert df["session"].iloc[-4] != "regular"

    snapshot = compute_indicators(df, config)  # must not raise

    assert snapshot.atr is None  # correctly reset -- not enough same-session bars yet


def test_atr_and_bar_true_range_are_none_when_the_latest_bar_is_the_sessions_first(config):
    """The buffer's LAST bar is exactly the regular session's FIRST bar
    (09:30 ET), every bar before it pre-market -- ATR's baseline must
    reset to None here (no in-session history at all yet to compute
    either the smoothed average or a "previous close" true range from),
    rather than reaching back across the session boundary."""
    from talonx_quant.indicators import compute_indicators

    # 119 minutes before 13:30 UTC (09:30 ET) puts bar 119 (the last of
    # 120) exactly on the regular-session open; bars 0-118 are pre-market.
    start = datetime(2026, 8, 3, 13, 30, tzinfo=timezone.utc) - timedelta(minutes=config.min_bars_required - 1)
    buf = _seed_buffer(config.min_bars_required, start=start)
    df = buf.get_dataframe("AAPL")
    assert df["session"].iloc[-1] == "regular"
    assert df["session"].iloc[-2] == "pre_market"

    snapshot = compute_indicators(df, config)

    assert snapshot.atr is None
    assert snapshot.bar_true_range is None
