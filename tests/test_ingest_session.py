"""
tests/test_ingest_session.py
--------------------------------
Tests talonx_ingest.session.get_session_state/is_premarket_window --
Dynamic ET Timezone requirement-doc gap fix: session state derived via
zoneinfo.ZoneInfo("America/New_York"), replacing run_talonx.PreMarketPoller's
old flat, hardcoded UTC time-of-day window. Includes a DST-crossing check
(EDT in August vs. EST in January -- the exact scenario a fixed UTC
window can't correctly cover both sides of).
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_ingest.session import get_session_state, is_premarket_window


# --- get_session_state ------------------------------------------------

def test_pre_market_start_boundary_is_inclusive():
    # 04:00 ET = 08:00 UTC in August (EDT, UTC-4)
    assert get_session_state(datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)) == "pre_market"


def test_pre_market_before_start_is_closed():
    assert get_session_state(datetime(2026, 8, 7, 7, 59, tzinfo=timezone.utc)) == "closed"


def test_regular_session_start_boundary_is_regular_not_premarket():
    # 09:30 ET = 13:30 UTC
    assert get_session_state(datetime(2026, 8, 7, 13, 30, tzinfo=timezone.utc)) == "regular"


def test_just_before_regular_open_is_still_premarket():
    assert get_session_state(datetime(2026, 8, 7, 13, 29, tzinfo=timezone.utc)) == "pre_market"


def test_after_close_is_after_hours():
    # 16:00 ET = 20:00 UTC
    assert get_session_state(datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)) == "after_hours"


def test_after_hours_end_boundary_is_closed():
    # 20:00 ET = 00:00 UTC (next day)
    assert get_session_state(datetime(2026, 8, 8, 0, 0, tzinfo=timezone.utc)) == "closed"


def test_naive_timestamp_is_treated_as_utc():
    naive = datetime(2026, 8, 7, 16, 0)  # no tzinfo -- same instant as the regular-session test above
    assert get_session_state(naive) == "regular"


def test_weekend_is_always_closed_regardless_of_time_of_day():
    # 2026-08-08 is a Saturday; 13:00 UTC = 09:00 ET, squarely inside the
    # pre-market TIME-of-day window, but weekends are always closed.
    saturday = datetime(2026, 8, 8, 13, 0, tzinfo=timezone.utc)
    assert get_session_state(saturday) == "closed"


def test_sunday_is_always_closed():
    sunday = datetime(2026, 8, 9, 13, 0, tzinfo=timezone.utc)
    assert get_session_state(sunday) == "closed"


def test_defaults_to_now_when_no_timestamp_given():
    # Just confirm this doesn't raise and returns a valid classification.
    result = get_session_state()
    assert result in ("pre_market", "regular", "after_hours", "closed")


# --- DST correctness (the exact gap the old flat-UTC-window had) --------

def test_premarket_open_is_correct_across_dst_edt():
    # 04:00 ET during EDT (August, UTC-4) = 08:00 UTC.
    assert get_session_state(datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)) == "pre_market"
    # The SAME 08:00 UTC instant during EST would be 03:00 ET (before
    # pre-market opens) -- confirms this isn't just checking a fixed UTC
    # range, but actually converting through the local EDT offset.


def test_premarket_open_is_correct_across_dst_est():
    # 04:00 ET during EST (January, UTC-5) = 09:00 UTC -- one hour LATER
    # in UTC than the EDT case above, the exact shift a flat UTC window
    # can't correctly straddle for both seasons at once.
    assert get_session_state(datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc)) == "pre_market"
    assert get_session_state(datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)) == "closed"  # still 03:00 ET


def test_regular_open_is_correct_across_dst_est():
    # 09:30 ET during EST (January) = 14:30 UTC, not 13:30 UTC (the EDT figure).
    assert get_session_state(datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)) == "regular"
    assert get_session_state(datetime(2026, 1, 5, 13, 30, tzinfo=timezone.utc)) == "pre_market"


# --- is_premarket_window -------------------------------------------------

def test_is_premarket_window_true_during_premarket():
    assert is_premarket_window(datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)) is True


def test_is_premarket_window_false_during_regular():
    assert is_premarket_window(datetime(2026, 8, 7, 16, 0, tzinfo=timezone.utc)) is False


def test_is_premarket_window_false_on_weekend_even_at_premarket_time():
    saturday_premarket = datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc)
    assert is_premarket_window(saturday_premarket) is False
