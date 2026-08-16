"""
tests/test_backtest_data_gaps.py
-------------------------------------
talonx_backtest.data: expected-vs-unexpected missing-bar classification
(spec section 6). A gap outside the REGULAR session (overnight/weekend,
OR a pre-market minute the dataset simply never covered -- extremely
common and not itself a defect) is EXPECTED; a gap DURING the regular
09:30-16:00 ET session is UNEXPECTED and worth investigating.
"""
from __future__ import annotations

import pandas as pd
import pytest

from talonx_backtest.data import check_data_quality


def _regular_session_frame(day: str, n: int = 30, start_offset_min: int = 0) -> pd.DataFrame:
    """`n` consecutive 1-min bars starting `start_offset_min` minutes
    after 09:30 ET on `day` (e.g. "2026-01-05"), tz-aware UTC. January
    is EST (UTC-5): 09:30 ET = 14:30 UTC."""
    start = pd.Timestamp(f"{day} 14:30:00", tz="UTC") + pd.Timedelta(minutes=start_offset_min)
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts, "symbol": "AAPL", "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "volume": 1000.0,
    })


def test_overnight_gap_between_two_trading_days_is_fully_expected():
    day1 = _regular_session_frame("2026-01-05", n=390)          # Mon, FULL regular session (09:30-16:00 ET)
    day2 = _regular_session_frame("2026-01-06", n=390)          # Tue, FULL regular session
    df = pd.concat([day1, day2], ignore_index=True)

    report = check_data_quality(df, symbol="AAPL")
    assert report.unexpected_intra_session_gap_bars == 0
    assert report.expected_session_gap_bars > 0
    assert report.expected_session_gap_bars == report.missing_bars


def test_gap_inside_the_regular_session_is_unexpected():
    day1 = _regular_session_frame("2026-01-05", n=15)                                    # 09:30-09:44 ET
    day1_later = _regular_session_frame("2026-01-05", n=15, start_offset_min=25)          # 09:55-10:09 ET
    # 10 missing minutes (09:45-09:54 ET) squarely inside the regular session
    df = pd.concat([day1, day1_later], ignore_index=True)

    report = check_data_quality(df, symbol="AAPL")
    assert report.unexpected_intra_session_gap_bars == 10
    assert report.expected_session_gap_bars == 0
    assert report.missing_bars == 10


def test_regular_session_only_dataset_with_no_premarket_data_is_not_flagged_unexpected():
    # A dataset that only ever covers 09:30-16:00 ET (extremely common
    # -- many vendors don't provide pre-market bars) must NOT have its
    # pre-market absence counted as "unexpected" -- only true gaps
    # WITHIN the regular session should be.
    day1 = _regular_session_frame("2026-01-05", n=390)  # full regular session, Mon
    day2 = _regular_session_frame("2026-01-06", n=390)  # full regular session, Tue
    df = pd.concat([day1, day2], ignore_index=True)

    report = check_data_quality(df, symbol="AAPL")
    assert report.unexpected_intra_session_gap_bars == 0


def test_split_gap_counts_sum_to_total_missing_bars():
    day1_part1 = _regular_session_frame("2026-01-05", n=10)                          # 09:30-09:39
    day1_part2 = _regular_session_frame("2026-01-05", n=380, start_offset_min=15)     # 09:45-16:00 (5 missing: 09:40-09:44)
    day2 = _regular_session_frame("2026-01-06", n=390)                                # next day, full session (overnight gap)
    df = pd.concat([day1_part1, day1_part2, day2], ignore_index=True)

    report = check_data_quality(df, symbol="AAPL")
    assert report.expected_session_gap_bars + report.unexpected_intra_session_gap_bars == report.missing_bars
    assert report.unexpected_intra_session_gap_bars == 5  # the 09:40-09:44 intra-session hole
    assert report.expected_session_gap_bars > 0            # the overnight gap
