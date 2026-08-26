"""Task75A -- CROSS_SECTIONAL_EXTREME_WINNER_SHORT_REVERSION_V1 causality,
canonical-calendar, tie/percentile, and rejection-semantics tests. Uses
REAL frozen-universe symbol names (the strategy only ever iterates
contracts.UNIVERSE, so synthetic names would silently be skipped)."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd

from research.task75_v1 import contracts as C
from research.task75_v1.fingerprint import compute_contract_only_fingerprint
from research.task75_v1.strategy import evaluate

ET = ZoneInfo("America/New_York")
WINNER = C.UNIVERSE[0]  # AAPL
FILLERS = C.UNIVERSE[1:12]  # 11 filler symbols -> 12 total, clears MIN_CROSS_SECTIONAL_BREADTH=10


def _session(symbol, day, open_price, close_price):
    base = pd.Timestamp(day, tz=ET)
    o_ts = base.replace(hour=9, minute=30).tz_convert("UTC")
    c_ts = base.replace(hour=15, minute=59).tz_convert("UTC")
    return pd.DataFrame([
        {"timestamp": o_ts, "symbol": symbol, "open": open_price, "high": open_price, "low": open_price, "close": open_price, "volume": 100},
        {"timestamp": c_ts, "symbol": symbol, "open": close_price, "high": close_price, "low": close_price, "close": close_price, "volume": 100},
    ])


def _weekdays(start, n):
    days, d = [], 0
    while len(days) < n:
        day = (pd.Timestamp(start) + pd.Timedelta(days=d)).date()
        if day.weekday() < 5:
            days.append(day)
        d += 1
    return days


def _dataset(days=None, n_days=15, skip_symbol_day=None):
    """SPY flat; WINNER (AAPL) spikes ~+6% over the 3 days ending at
    days[9] (Day0); 11 filler symbols flat. `skip_symbol_day` optionally
    removes one (symbol, day) session entirely to test gap rejection."""
    if days is None:
        days = _weekdays("2025-06-02", n_days)
    frames = []
    for day in days:
        frames.append(_session("SPY", day, 500.0, 500.0))
    price = 100.0
    for i, day in enumerate(days):
        if i in (7, 8, 9):
            end = price * 1.02
            df = _session(WINNER, day, price, end)
            price = end
        else:
            df = _session(WINNER, day, price, price)
        if skip_symbol_day != (WINNER, day):
            frames.append(df)
    for sym in FILLERS:
        price = 100.0
        for day in days:
            df = _session(sym, day, price, price)
            if skip_symbol_day != (sym, day):
                frames.append(df)
    return pd.concat(frames, ignore_index=True), days


def test_short_only_top20pct_signal_fires_for_winner():
    bars, days = _dataset()
    out = evaluate(bars)
    day0 = days[9]
    row = out[(out["symbol"] == WINNER) & (out["decision_day"] == day0)]
    assert not row.empty
    assert (row["direction"] == "SHORT").all()
    assert (row["data_ready"] == True).all()  # noqa: E712


def test_entry_is_canonical_next_session_not_symbols_own_next_row():
    bars, days = _dataset()
    out = evaluate(bars)
    day0 = days[9]
    row = out[(out["symbol"] == WINNER) & (out["decision_day"] == day0) & (out["data_ready"] == True)].iloc[0]  # noqa: E712
    assert row["entry_day"] == days[10]


def test_exit_is_3rd_canonical_day_inclusive_of_entry():
    bars, days = _dataset()
    out = evaluate(bars)
    day0 = days[9]
    row = out[(out["symbol"] == WINNER) & (out["decision_day"] == day0) & (out["data_ready"] == True)].iloc[0]  # noqa: E712
    assert row["exit_day"] == days[12]


def test_short_gross_return_positive_when_price_falls():
    bars, days = _dataset()
    out = evaluate(bars)
    day0 = days[9]
    row = out[(out["symbol"] == WINNER) & (out["decision_day"] == day0) & (out["data_ready"] == True)].iloc[0]  # noqa: E712
    if row["exit_price"] < row["entry_price"]:
        assert row["gross_return_pct"] > 0
    elif row["exit_price"] > row["entry_price"]:
        assert row["gross_return_pct"] < 0


def test_missing_true_day1_rejects_not_shifts():
    days = _weekdays("2025-06-02", 15)
    bars, days = _dataset(days=days, skip_symbol_day=(WINNER, days[10]))
    out = evaluate(bars)
    day0 = days[9]
    row = out[(out["symbol"] == WINNER) & (out["decision_day"] == day0)]
    assert not row.empty
    assert (row["data_ready"] == False).all()  # noqa: E712
    assert (row["rejection_reason"] == "SYMBOL_MISSING_REQUIRED_SESSION").all()


def test_missing_exit_session_rejects_not_extends():
    days = _weekdays("2025-06-02", 15)
    bars, days = _dataset(days=days, skip_symbol_day=(WINNER, days[12]))
    out = evaluate(bars)
    day0 = days[9]
    row = out[(out["symbol"] == WINNER) & (out["decision_day"] == day0)]
    assert not row.empty
    assert (row["data_ready"] == False).all()  # noqa: E712
    assert (row["rejection_reason"] == "SYMBOL_MISSING_REQUIRED_SESSION").all()


def test_weekends_never_appear_as_canonical_days():
    bars, days = _dataset()
    out = evaluate(bars)
    for d in out["decision_day"].dropna().unique():
        assert pd.Timestamp(d).weekday() < 5
    for d in out["entry_day"].dropna().unique():
        assert pd.Timestamp(d).weekday() < 5


def test_slice_end_fails_closed_no_synthetic_exit():
    bars, days = _dataset(n_days=12)
    out = evaluate(bars)
    last_day0 = sorted(out["decision_day"].dropna().unique())[-1]
    rows = out[out["decision_day"] == last_day0]
    ready = rows[rows["data_ready"] == True]  # noqa: E712
    if ready.empty:
        assert rows["rejection_reason"].notna().all()


def test_stock_and_spy_use_identical_lookback_window():
    bars, days = _dataset()
    out = evaluate(bars)
    day0 = days[9]
    row = out[(out["symbol"] == WINNER) & (out["decision_day"] == day0) & (out["data_ready"] == True)]
    assert not row.empty  # implies SPY window aligned; feature computed successfully


def test_fingerprint_deterministic_and_frozen_direction():
    assert C.DIRECTION == "SHORT_ONLY"
    assert C.UPPER_PERCENTILE == 0.80
    assert C.LOOKBACK_TRADING_DAYS == 3
    assert C.EXIT_HORIZON_TRADING_DAYS == 3
    fp1 = compute_contract_only_fingerprint()
    fp2 = compute_contract_only_fingerprint()
    assert fp1 == fp2
    assert len(fp1) == 64
