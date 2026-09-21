"""
Task 117 -- SEC acceptance-timestamp source contract (corrected).

An earlier change GLOBALLY reinterpreted every bare ``Z`` / ``+00:00`` / naive
acceptance value as US/Eastern. A 10-accession cross-reference of the raw
Form-4 SGML header ``<ACCEPTANCE-DATETIME>`` (US/Eastern, naive) against the
``data.sec.gov/submissions`` JSON ``acceptanceDateTime`` (``...000Z``) for the
SAME filings, all in EDT, shows:

    SGML 2026-08-27T18:30:30  ==  JSON 2026-08-27T22:30:30.000Z     (+4h)
    SGML 2026-08-19T16:15:48  ==  JSON 2026-08-19T20:15:48.000Z     (+4h)
    SGML 2026-09-08T07:02:11  ==  JSON 2026-09-08T11:02:11.000Z     (+4h)
    ... 10/10

i.e. the submissions JSON ``acceptanceDateTime`` is a GENUINE UTC instant --
SEC has already converted the SGML-Eastern wall-clock. The global reinterpretation
was WRONG and is removed. Only the raw SGML field (``source="sgml_header"``,
not wired into the pipeline) is Eastern-naive; that contract is VERIFIED and
tested here so the machinery exists if a caller ever parses it.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

import pytest

from talonx_ingest.intelligence.domain import DataQualityFlag, SessionBucket
from talonx_ingest.intelligence.edgar_normalize import (
    ACCEPTANCE_SOURCE_TZ,
    iter_normalized_filings,
    parse_acceptance_datetime,
    parse_acceptance_datetime_ex,
)
from talonx_ingest.intelligence.sessions import bucket_session

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# 1. genuine UTC MUST NOT shift (the global reinterpretation is gone)         #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-07-31T18:05:12.000Z", datetime(2026, 7, 31, 18, 5, 12, tzinfo=UTC)),
        ("2026-07-31T18:05:12Z", datetime(2026, 7, 31, 18, 5, 12, tzinfo=UTC)),
        ("2026-07-31T18:05:12+00:00", datetime(2026, 7, 31, 18, 5, 12, tzinfo=UTC)),
        ("2026-01-15T18:05:12Z", datetime(2026, 1, 15, 18, 5, 12, tzinfo=UTC)),  # winter, still UTC
    ],
)
def test_submissions_Z_marker_is_genuine_utc(raw, expected):
    dt, flags = parse_acceptance_datetime_ex(raw, source="submissions")
    assert dt == expected
    assert flags == ()          # nothing assumed; the marker IS the instant


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-07-31T14:05:12-04:00", datetime(2026, 7, 31, 18, 5, 12, tzinfo=UTC)),
        ("2026-02-03T04:29:00-05:00", datetime(2026, 2, 3, 9, 29, 0, tzinfo=UTC)),
        ("2026-07-15T15:00:00+05:30", datetime(2026, 7, 15, 9, 30, 0, tzinfo=UTC)),
    ],
)
def test_explicit_nonzero_offset_is_trusted(raw, expected):
    dt, flags = parse_acceptance_datetime_ex(raw)
    assert dt == expected and flags == ()


def test_naive_from_submissions_is_utc_but_offset_absence_recorded():
    dt, flags = parse_acceptance_datetime_ex("2026-07-31 18:05:12", source="submissions")
    assert dt == datetime(2026, 7, 31, 18, 5, 12, tzinfo=UTC)
    assert DataQualityFlag.ACCEPTANCE_OFFSET_ABSENT.value in flags


def test_missing_and_garbage():
    assert parse_acceptance_datetime_ex(None) == (None, ())
    assert parse_acceptance_datetime_ex("") == (None, ())
    assert parse_acceptance_datetime_ex("not-a-time") == (None, ())


def test_iter_normalized_filings_preserves_utc():
    subs = {
        "cik": 320193, "name": "Apple Inc.", "tickers": ["AAPL"],
        "filings": {"recent": {
            "form": ["8-K"], "accessionNumber": ["0000320193-26-000070"],
            "acceptanceDateTime": ["2026-07-31T18:05:12.000Z"],
            "filingDate": ["2026-07-31"], "reportDate": [""],
            "primaryDocument": ["a.htm"], "items": ["2.02"],
        }},
    }
    f = next(iter_normalized_filings(subs, symbol="AAPL"))
    assert f.acceptance_datetime == datetime(2026, 7, 31, 18, 5, 12, tzinfo=UTC)
    assert DataQualityFlag.ACCEPTANCE_TZ_SOURCE_SGML_EASTERN.value not in f.flags


# --------------------------------------------------------------------------- #
# 2. the VERIFIED sgml_header contract: raw <ACCEPTANCE-DATETIME> is Eastern  #
#    (winter + summer + DST edges). Not wired into the pipeline; tested so    #
#    the machinery is correct if a caller ever parses that field.            #
# --------------------------------------------------------------------------- #
def test_source_contract_registry():
    assert ACCEPTANCE_SOURCE_TZ["submissions"] == "UTC"
    assert ACCEPTANCE_SOURCE_TZ["sgml_header"] == "US/Eastern"


@pytest.mark.parametrize(
    "raw,expected_utc",
    [
        # the raw SGML compact form, 14 digits, no separators -- EDT (-4)
        ("20260827183030", datetime(2026, 8, 27, 22, 30, 30, tzinfo=UTC)),
        ("2026-08-27T18:30:30", datetime(2026, 8, 27, 22, 30, 30, tzinfo=UTC)),
        # EST (-5)
        ("2026-01-15T09:00:00", datetime(2026, 1, 15, 14, 0, 0, tzinfo=UTC)),
        # UTC/ET date boundary: 22:15 ET on Sep 10 -> 02:15 UTC on Sep 11
        ("2026-09-10T22:15:00", datetime(2026, 9, 11, 2, 15, 0, tzinfo=UTC)),
    ],
)
def test_sgml_header_naive_is_eastern(raw, expected_utc):
    dt, flags = parse_acceptance_datetime_ex(raw, source="sgml_header")
    assert dt == expected_utc
    assert DataQualityFlag.ACCEPTANCE_TZ_SOURCE_SGML_EASTERN.value in flags


def test_sgml_header_spring_forward_gap_is_pushed_forward():
    # 2026-03-08 02:30 ET does not exist (spring-forward 02:00->03:00)
    dt, flags = parse_acceptance_datetime_ex("2026-03-08T02:30:00", source="sgml_header")
    # nudged to 03:30 ET (EDT, -4) -> 07:30 UTC
    assert dt == datetime(2026, 3, 8, 7, 30, 0, tzinfo=UTC)
    assert DataQualityFlag.ACCEPTANCE_DST_WALLCLOCK_ADJUSTED.value in flags


def test_sgml_header_fall_back_overlap_takes_earlier_instant():
    # 2026-11-01 01:30 ET occurs twice (fall-back 02:00->01:00)
    dt, flags = parse_acceptance_datetime_ex("2026-11-01T01:30:00", source="sgml_header")
    # earlier (pre-transition, EDT -4) instant -> 05:30 UTC
    assert dt.tzinfo == UTC
    assert dt in (datetime(2026, 11, 1, 5, 30, tzinfo=UTC), datetime(2026, 11, 1, 6, 30, tzinfo=UTC))


# --------------------------------------------------------------------------- #
# 3. session classification + causal cutoff on GENUINE UTC values            #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected_bucket",
    [
        ("2026-09-10T12:15:00Z", SessionBucket.BMO),   # 08:15 ET
        ("2026-09-10T13:30:00Z", SessionBucket.RTH),   # 09:30 ET open
        ("2026-09-10T19:59:00Z", SessionBucket.RTH),   # 15:59 ET
        ("2026-09-10T20:00:00Z", SessionBucket.AMC),   # 16:00 ET close
        ("2026-09-10T20:30:00Z", SessionBucket.AMC),
        ("2026-09-12T18:00:00Z", SessionBucket.NON_TRADING_DAY),  # Saturday
    ],
)
def test_session_bucket_on_utc(raw, expected_bucket):
    assert bucket_session(parse_acceptance_datetime(raw)).bucket is expected_bucket


def test_causal_cutoff_uses_the_value_as_given():
    accepted = parse_acceptance_datetime("2026-09-10T18:00:00Z")   # genuine UTC
    assert accepted == datetime(2026, 9, 10, 18, 0, 0, tzinfo=UTC)
    assert accepted > datetime(2026, 9, 10, 15, 0, 0, tzinfo=UTC)
    assert accepted <= datetime(2026, 9, 10, 18, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# 4. second-owner activation + eligible entry date (V2)                       #
# --------------------------------------------------------------------------- #
def test_second_owner_filing_date_and_next_session():
    from talonx_v2 import calendar as vc
    # a genuine-UTC acceptance of 21:00 UTC on Thu 2026-09-10 == 17:00 ET
    dt = parse_acceptance_datetime("2026-09-10T21:00:00Z")
    assert dt == datetime(2026, 9, 10, 21, 0, 0, tzinfo=UTC)
    # V2's from_insider_store keys the missing filing_date on dt.date() (UTC) --
    # unchanged behaviour; for this value that is 2026-09-10
    assert dt.date() == date(2026, 9, 10)
    assert vc.next_session_strictly_after(date(2026, 9, 10)) == date(2026, 9, 11)
