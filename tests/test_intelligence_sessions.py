"""
tests/test_intelligence_sessions.py
-----------------------------------
Task 96A -- session bucketing of an event's acceptanceDateTime.
Covers BMO/RTH/AMC boundaries, DST, NYSE holidays, half-days, weekends,
the missing-timestamp case, and the calendar-unavailable fallback.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from talonx_ingest.intelligence import sessions
from talonx_ingest.intelligence.domain import DataQualityFlag, SessionBucket


def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


# --- BMO / RTH / AMC boundaries (summer, EDT = UTC-4) -----------------

def test_bmo_before_open_summer():
    # 09:00 ET = 13:00 UTC in August
    r = sessions.bucket_session(_utc(2026, 8, 6, 13, 0))
    assert r.bucket is SessionBucket.BMO


def test_rth_at_open_boundary_summer():
    # 09:30 ET = 13:30 UTC
    r = sessions.bucket_session(_utc(2026, 8, 6, 13, 30))
    assert r.bucket is SessionBucket.RTH


def test_rth_just_before_close_summer():
    # 15:59 ET = 19:59 UTC
    r = sessions.bucket_session(_utc(2026, 8, 6, 19, 59))
    assert r.bucket is SessionBucket.RTH


def test_amc_at_close_boundary_summer():
    # 16:00 ET = 20:00 UTC
    r = sessions.bucket_session(_utc(2026, 8, 6, 20, 0))
    assert r.bucket is SessionBucket.AMC


# --- DST: same wall-clock ET, different UTC offset -------------------

def test_dst_winter_open_is_1430_utc():
    # 09:30 ET in January = 14:30 UTC (EST, UTC-5)
    assert sessions.bucket_session(_utc(2026, 1, 21, 14, 30)).bucket is SessionBucket.RTH
    assert sessions.bucket_session(_utc(2026, 1, 21, 14, 29)).bucket is SessionBucket.BMO


def test_dst_summer_open_is_1330_utc():
    # 09:30 ET in July = 13:30 UTC (EDT, UTC-4)
    assert sessions.bucket_session(_utc(2026, 7, 21, 13, 30)).bucket is SessionBucket.RTH
    assert sessions.bucket_session(_utc(2026, 7, 21, 13, 29)).bucket is SessionBucket.BMO


# --- non-trading days ---------------------------------------------

def test_weekend_is_non_trading_day():
    r = sessions.bucket_session(_utc(2026, 8, 8, 15, 0))  # Saturday
    assert r.bucket is SessionBucket.NON_TRADING_DAY
    assert r.reason == "weekend"


def test_nyse_holiday_is_non_trading_day():
    # 2025-12-25 Christmas, a weekday
    r = sessions.bucket_session(_utc(2025, 12, 25, 15, 0))
    assert r.bucket is SessionBucket.NON_TRADING_DAY
    assert r.reason == "nyse_holiday"


def test_mlk_day_2026_is_non_trading_day():
    # 2026-01-19 MLK Jr. Day
    r = sessions.bucket_session(_utc(2026, 1, 19, 15, 0))
    assert r.bucket is SessionBucket.NON_TRADING_DAY
    assert r.reason == "nyse_holiday"


# --- half day -----------------------------------------------------

def test_half_day_after_1pm_close_is_amc():
    # 2025-11-28 (day after Thanksgiving) closes 13:00 ET = 18:00 UTC.
    r = sessions.bucket_session(_utc(2025, 11, 28, 18, 30))  # 13:30 ET
    assert r.bucket is SessionBucket.AMC
    assert r.reason == "half_day_amc"


def test_half_day_before_1pm_is_rth():
    r = sessions.bucket_session(_utc(2025, 11, 28, 17, 0))  # 12:00 ET
    assert r.bucket is SessionBucket.RTH


# --- missing / naive timestamps ---------------------------------

def test_missing_timestamp_is_unknown_and_flagged():
    r = sessions.bucket_session(None)
    assert r.bucket is SessionBucket.UNKNOWN
    assert DataQualityFlag.MISSING_ACCEPTANCE_TIMESTAMP.value in r.flags


def test_naive_timestamp_assumed_utc():
    naive = datetime(2026, 8, 6, 20, 0)  # == 16:00 ET
    assert sessions.bucket_session(naive).bucket is SessionBucket.AMC


# --- calendar-unavailable fallback ------------------------------

def test_fallback_when_calendar_unavailable(monkeypatch):
    sessions._reset_calendar_cache()
    monkeypatch.setattr(sessions, "_get_calendar", lambda: None)
    r = sessions.bucket_session(_utc(2026, 8, 6, 20, 0))  # weekday 16:00 ET
    assert r.bucket is SessionBucket.AMC
    assert DataQualityFlag.SESSION_CALENDAR_UNAVAILABLE.value in r.flags
    assert DataQualityFlag.AMBIGUOUS_SESSION_BUCKET.value in r.flags
    weekend = sessions.bucket_session(_utc(2026, 8, 8, 15, 0))
    assert weekend.bucket is SessionBucket.NON_TRADING_DAY
    sessions._reset_calendar_cache()


def test_far_future_out_of_calendar_bounds_falls_back(monkeypatch):
    sessions._reset_calendar_cache()
    r = sessions.bucket_session(_utc(2099, 6, 1, 20, 0))
    # weekday-only fallback still yields a usable bucket + the flag
    assert r.bucket in (SessionBucket.AMC, SessionBucket.NON_TRADING_DAY)
    assert DataQualityFlag.SESSION_CALENDAR_UNAVAILABLE.value in r.flags
    sessions._reset_calendar_cache()


def test_deterministic():
    ts = _utc(2026, 8, 6, 13, 45)
    assert sessions.bucket_session(ts) == sessions.bucket_session(ts)
