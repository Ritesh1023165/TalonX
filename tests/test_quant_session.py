"""
tests/test_quant_session.py
--------------------------------
Tests talonx_quant.session.get_session's pre-market/regular/closed
classification (America/New_York), including the DST-sensitive UTC
offset (EDT = UTC-4 in August, when these fixtures are dated).
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_quant.session import get_entry_blackout, get_session


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
