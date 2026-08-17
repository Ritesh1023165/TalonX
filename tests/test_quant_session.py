"""
tests/test_quant_session.py
--------------------------------
Tests talonx_quant.session.get_session's pre-market/regular/closed
classification (America/New_York), including the DST-sensitive UTC
offset (EDT = UTC-4 in August, when these fixtures are dated).
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_quant.session import get_entry_blackout, get_session, is_operating_window_open


def test_pre_market_start_boundary_is_inclusive():
    # 04:00 ET = 08:00 UTC in August (EDT, UTC-4)
    assert get_session(datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)) == "pre_market"


def test_pre_market_before_start_is_closed():
    assert get_session(datetime(2026, 8, 7, 7, 59, tzinfo=timezone.utc)) == "closed"


def test_regular_session_start_boundary_is_regular_not_premarket():
    # 09:30 ET = 13:30 UTC
    assert get_session(datetime(2026, 8, 7, 13, 30, tzinfo=timezone.utc)) == "regular"


def test_just_before_regular_open_is_still_premarket():
    assert get_session(datetime(2026, 8, 7, 13, 29, tzinfo=timezone.utc)) == "pre_market"


def test_regular_session_midday():
    # 12:00 ET = 16:00 UTC
    assert get_session(datetime(2026, 8, 7, 16, 0, tzinfo=timezone.utc)) == "regular"


def test_after_close_is_closed():
    # 16:00 ET = 20:00 UTC -- close boundary itself is exclusive (closed)
    assert get_session(datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)) == "closed"


def test_naive_timestamp_is_treated_as_utc():
    naive = datetime(2026, 8, 7, 16, 0)  # no tzinfo -- same instant as the regular-session test above
    assert get_session(naive) == "regular"


# --- get_entry_blackout (09:30-09:45 / 15:30-16:00 ET) ---------------------

def test_opening_blackout_start_boundary_is_inclusive():
    # 09:30 ET = 13:30 UTC
    assert get_entry_blackout(datetime(2026, 8, 7, 13, 30, tzinfo=timezone.utc)) == "opening"


def test_opening_blackout_end_boundary_is_exclusive():
    # 09:45 ET = 13:45 UTC -- the boundary itself is regular trading, not blackout
    assert get_entry_blackout(datetime(2026, 8, 7, 13, 45, tzinfo=timezone.utc)) == "none"


def test_just_before_opening_blackout_is_none():
    assert get_entry_blackout(datetime(2026, 8, 7, 13, 29, tzinfo=timezone.utc)) == "none"


def test_closing_blackout_start_boundary_is_inclusive():
    # 15:30 ET = 19:30 UTC
    assert get_entry_blackout(datetime(2026, 8, 7, 19, 30, tzinfo=timezone.utc)) == "closing"


def test_closing_blackout_covers_up_to_market_close():
    # 15:59 ET = 19:59 UTC -- still closing blackout, one minute before close
    assert get_entry_blackout(datetime(2026, 8, 7, 19, 59, tzinfo=timezone.utc)) == "closing"


def test_at_market_close_is_no_longer_blackout():
    # 16:00 ET = 20:00 UTC -- session is "closed" by then, not a blackout state
    assert get_entry_blackout(datetime(2026, 8, 7, 20, 0, tzinfo=timezone.utc)) == "none"


def test_midday_is_not_blackout():
    # 12:00 ET = 16:00 UTC -- deep in the regular active window
    assert get_entry_blackout(datetime(2026, 8, 7, 16, 0, tzinfo=timezone.utc)) == "none"


def test_premarket_is_not_blackout():
    # 08:00 ET = 12:00 UTC -- get_entry_blackout only classifies the two
    # regular-session sub-windows; pre-market is simply "none" here (the
    # separate pre-market gates in consumer.py handle that session).
    assert get_entry_blackout(datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)) == "none"


# --- is_operating_window_open (2026-08-16 quant audit, round 5) -----------
# TalonX's own UK-local operating window (Mon-Fri 08:00-22:00
# Europe/London) -- a SEPARATE concept from the US-market ET session
# above. 2026-08-10 is a Monday in BST (UTC+1); 2026-01-05 is a Monday in
# GMT (UTC+0) -- both are exercised to prove real Europe/London handling,
# not a fixed offset.

def test_uk_window_open_boundary_is_inclusive_bst():
    # Monday 2026-08-10, BST (UTC+1): 08:00 local = 07:00 UTC
    assert is_operating_window_open(datetime(2026, 8, 10, 7, 0, tzinfo=timezone.utc)) is True


def test_uk_window_just_before_open_is_closed_bst():
    assert is_operating_window_open(datetime(2026, 8, 10, 6, 59, tzinfo=timezone.utc)) is False


def test_uk_window_midday_is_open_bst():
    # 14:00 local = 13:00 UTC
    assert is_operating_window_open(datetime(2026, 8, 10, 13, 0, tzinfo=timezone.utc)) is True


def test_uk_window_just_before_close_is_open_bst():
    # 21:59 local = 20:59 UTC
    assert is_operating_window_open(datetime(2026, 8, 10, 20, 59, tzinfo=timezone.utc)) is True


def test_uk_window_close_boundary_is_exclusive_bst():
    # 22:00 local = 21:00 UTC
    assert is_operating_window_open(datetime(2026, 8, 10, 21, 0, tzinfo=timezone.utc)) is False


def test_uk_window_late_evening_is_closed_bst():
    # 23:00 local = 22:00 UTC
    assert is_operating_window_open(datetime(2026, 8, 10, 22, 0, tzinfo=timezone.utc)) is False


def test_uk_window_open_boundary_is_inclusive_gmt():
    # Monday 2026-01-05, GMT (UTC+0): 08:00 local = 08:00 UTC
    assert is_operating_window_open(datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)) is True


def test_uk_window_just_before_open_is_closed_gmt():
    assert is_operating_window_open(datetime(2026, 1, 5, 7, 59, tzinfo=timezone.utc)) is False


def test_uk_window_close_boundary_is_exclusive_gmt():
    assert is_operating_window_open(datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc)) is False


def test_uk_window_just_before_close_is_open_gmt():
    assert is_operating_window_open(datetime(2026, 1, 5, 21, 59, tzinfo=timezone.utc)) is True


def test_saturday_is_always_closed():
    # Saturday 2026-08-08, mid-afternoon local time -- BST period
    assert is_operating_window_open(datetime(2026, 8, 8, 13, 0, tzinfo=timezone.utc)) is False


def test_sunday_is_always_closed():
    assert is_operating_window_open(datetime(2026, 8, 9, 13, 0, tzinfo=timezone.utc)) is False


def test_naive_timestamp_is_treated_as_utc_for_operating_window():
    naive = datetime(2026, 1, 5, 8, 0)  # no tzinfo -- same instant as the GMT open-boundary test above
    assert is_operating_window_open(naive) is True


def test_defaults_to_current_time_when_no_timestamp_given():
    # Just confirms the no-arg call path doesn't raise -- the actual
    # value is whatever "now" happens to be, not asserted here (every
    # other test in this section pins an explicit timestamp specifically
    # to stay deterministic).
    result = is_operating_window_open()
    assert isinstance(result, bool)


# --- DST transitions: 08:00/22:00 UK must remain the ACTUAL local
# boundary across the GMT<->BST changeover, not a fixed UTC offset.
# 2026-03-29 (UK clocks forward) and 2026-10-25 (UK clocks back) are both
# Sundays (closed anyway); the nearest weekdays on either side are
# compared instead, showing the SAME "08:00 local" resolves to a
# DIFFERENT UTC instant before/after each transition.

def test_gmt_to_bst_spring_transition_shifts_the_utc_open_boundary():
    # Friday 2026-03-27, still GMT: 08:00 local = 08:00 UTC.
    assert is_operating_window_open(datetime(2026, 3, 27, 8, 0, tzinfo=timezone.utc)) is True
    assert is_operating_window_open(datetime(2026, 3, 27, 7, 59, tzinfo=timezone.utc)) is False
    # Monday 2026-03-30, now BST (clocks sprang forward on 2026-03-29):
    # 08:00 local = 07:00 UTC -- a hardcoded UTC+0 offset would
    # incorrectly report 07:00 UTC as still closed here.
    assert is_operating_window_open(datetime(2026, 3, 30, 7, 0, tzinfo=timezone.utc)) is True
    assert is_operating_window_open(datetime(2026, 3, 30, 6, 59, tzinfo=timezone.utc)) is False


def test_bst_to_gmt_autumn_transition_shifts_the_utc_open_boundary():
    # Friday 2026-10-23, still BST: 08:00 local = 07:00 UTC.
    assert is_operating_window_open(datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)) is True
    assert is_operating_window_open(datetime(2026, 10, 23, 6, 59, tzinfo=timezone.utc)) is False
    # Monday 2026-10-26, now GMT (clocks fell back on 2026-10-25):
    # 08:00 local = 08:00 UTC -- a hardcoded UTC+1 offset would
    # incorrectly report 08:00 UTC as still closed (07:59 local) here.
    assert is_operating_window_open(datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)) is True
    assert is_operating_window_open(datetime(2026, 10, 26, 7, 59, tzinfo=timezone.utc)) is False
