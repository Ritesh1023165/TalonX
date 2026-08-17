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


# ------------------------------------------------------------------
# 2026-08-17 real-data smoke test fix: a gap spanning a WEEKEND used to
# have its Saturday/Sunday 09:30-16:00-ET-shaped windows misclassified
# as unexpected intra-session gaps (get_session() classifies purely by
# time-of-day, with no notion of the calendar date) -- 390 minutes x 2
# weekend days = exactly 780 false-positive "unexpected" bars on real
# data spanning a single weekend. None of the tests above ever spans an
# actual weekend (2026-01-05/06 are a Mon/Tue), which is exactly why
# this went uncaught until real data exposed it.
# ------------------------------------------------------------------

def test_weekend_gap_between_friday_and_monday_is_fully_expected():
    # TEST 1 -- WEEKEND GAP: Friday regular session + Monday regular
    # session, Saturday/Sunday entirely absent -- the weekend's own
    # regular-session-shaped window must contribute ZERO unexpected bars.
    friday = _regular_session_frame("2026-01-09", n=390)   # Fri, full regular session
    monday = _regular_session_frame("2026-01-12", n=390)   # following Mon, full regular session
    df = pd.concat([friday, monday], ignore_index=True)

    report = check_data_quality(df, symbol="AAPL")
    assert report.unexpected_intra_session_gap_bars == 0
    assert report.expected_session_gap_bars == report.missing_bars
    assert report.expected_session_gap_bars > 0  # the weekend gap itself was still counted, just as EXPECTED


def test_a_genuine_intraday_gap_is_still_detected():
    # TEST 2 -- REAL INTRA-DAY GAP: 09:30, 09:31, 09:32, [missing 09:33,
    # 09:34], 09:35 -- the fix must not blunt real gap detection.
    part1 = _regular_session_frame("2026-01-05", n=3)                         # 09:30-09:32 ET
    part2 = _regular_session_frame("2026-01-05", n=1, start_offset_min=5)     # 09:35 ET
    df = pd.concat([part1, part2], ignore_index=True)

    report = check_data_quality(df, symbol="AAPL")
    assert report.unexpected_intra_session_gap_bars == 2  # 09:33, 09:34
    assert report.expected_session_gap_bars == 0
    assert report.missing_bars == 2


def test_weekend_gap_plus_a_genuine_monday_gap_are_both_classified_correctly():
    # TEST 3 -- WEEKEND + REAL GAP: Friday full session, weekend absent,
    # Monday with its OWN genuine intra-session hole. The weekend must
    # contribute 0 unexpected bars AND the Monday hole must still be
    # caught -- proves the fix doesn't just disable gap detection wholesale.
    friday = _regular_session_frame("2026-01-09", n=390)                              # Fri, full session
    monday_part1 = _regular_session_frame("2026-01-12", n=10)                         # Mon 09:30-09:39
    monday_part2 = _regular_session_frame("2026-01-12", n=375, start_offset_min=15)   # Mon 09:45-16:00 (5 missing: 09:40-09:44)
    df = pd.concat([friday, monday_part1, monday_part2], ignore_index=True)

    report = check_data_quality(df, symbol="AAPL")
    assert report.unexpected_intra_session_gap_bars == 5   # only Monday's genuine 09:40-09:44 hole
    assert report.expected_session_gap_bars > 0             # the weekend gap, correctly EXPECTED
    assert report.expected_session_gap_bars + report.unexpected_intra_session_gap_bars == report.missing_bars


def test_weekend_gap_matches_the_exact_780_bar_smoke_test_finding():
    # Regression-pins the EXACT real-world number from the 2026-08-17
    # smoke test: a single weekend inside a downloaded range used to add
    # 390 (Sat) + 390 (Sun) = 780 false-positive unexpected gap bars.
    friday = _regular_session_frame("2026-01-09", n=390)
    monday = _regular_session_frame("2026-01-12", n=390)
    df = pd.concat([friday, monday], ignore_index=True)

    report = check_data_quality(df, symbol="AAPL")
    assert report.unexpected_intra_session_gap_bars == 0  # was 780 before this fix
