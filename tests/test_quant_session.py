"""
tests/test_quant_session.py
--------------------------------
Tests talonx_quant.session.get_session's pre-market/regular/closed
classification (America/New_York), including the DST-sensitive UTC
offset (EDT = UTC-4 in August, when these fixtures are dated).
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_quant.session import get_session


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
