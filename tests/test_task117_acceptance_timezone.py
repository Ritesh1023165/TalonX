"""
Task 117 output-closure -- SEC EDGAR ``acceptanceDateTime`` timezone correctness.

SEC renders every acceptance wall-clock in US Eastern (the 5:30 PM ET cut-off
that rolls a filing to the next business day is an Eastern rule). The
``data.sec.gov/submissions`` feed nonetheless stamps the value with a bare
``...Z``. Treating that ``Z`` literally puts the acceptance instant 4h (EDT) /
5h (EST) in the past, which:

  * mis-buckets an after-close filing as RTH (``sessions.bucket_session``),
  * biases as-of replay causal cut-offs (a filing looks public ~4h early),
  * shifts a late-evening-ET filing onto the wrong UTC calendar day.

These tests pin the corrected behaviour: a bare Z / +00:00 / naive value is an
Eastern wall-clock; an explicit non-zero offset is trusted verbatim.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from talonx_ingest.intelligence.domain import DataQualityFlag, SessionBucket
from talonx_ingest.intelligence.edgar_normalize import (
    EDGAR_ACCEPTANCE_ASSUMES_EASTERN,
    parse_acceptance_datetime,
    parse_acceptance_datetime_ex,
)
from talonx_ingest.intelligence.sessions import bucket_session

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# 1. UTC persistence                                                          #
# --------------------------------------------------------------------------- #
def test_switch_is_on_by_default():
    assert EDGAR_ACCEPTANCE_ASSUMES_EASTERN is True


@pytest.mark.parametrize(
    "raw,expected_utc",
    [
        # EDT (UTC-4)
        ("2026-07-15T09:29:00Z", datetime(2026, 7, 15, 13, 29, 0, tzinfo=UTC)),
        ("2026-07-15T09:29:00.000Z", datetime(2026, 7, 15, 13, 29, 0, tzinfo=UTC)),
        ("2026-07-15T09:29:00+00:00", datetime(2026, 7, 15, 13, 29, 0, tzinfo=UTC)),
        ("2026-07-15 09:29:00", datetime(2026, 7, 15, 13, 29, 0, tzinfo=UTC)),
        # EST (UTC-5)
        ("2026-02-03T09:29:00Z", datetime(2026, 2, 3, 14, 29, 0, tzinfo=UTC)),
        # DST boundary: spring-forward is 2026-03-08 02:00 ET; 01:30 ET is EST (-5)
        ("2026-03-08T01:30:00Z", datetime(2026, 3, 8, 6, 30, 0, tzinfo=UTC)),
        # ...09:00 ET on 2026-03-09 (Mon) is EDT (-4)
        ("2026-03-09T09:00:00Z", datetime(2026, 3, 9, 13, 0, 0, tzinfo=UTC)),
        # fall-back is 2026-11-01 02:00 ET; by 09:00 ET that day it is EST (-5)
        ("2026-11-02T09:00:00Z", datetime(2026, 11, 2, 14, 0, 0, tzinfo=UTC)),
    ],
)
def test_bare_marker_is_eastern_wall_clock(raw, expected_utc):
    dt, flags = parse_acceptance_datetime_ex(raw)
    assert dt == expected_utc
    assert dt.tzinfo is not None and dt.utcoffset().total_seconds() == 0
    assert DataQualityFlag.ACCEPTANCE_TZ_ASSUMED_EASTERN.value in flags


@pytest.mark.parametrize(
    "raw,expected_utc",
    [
        ("2026-07-15T05:29:00-04:00", datetime(2026, 7, 15, 9, 29, 0, tzinfo=UTC)),
        ("2026-02-03T04:29:00-05:00", datetime(2026, 2, 3, 9, 29, 0, tzinfo=UTC)),
        ("2026-07-15T15:00:00+05:30", datetime(2026, 7, 15, 9, 30, 0, tzinfo=UTC)),
    ],
)
def test_explicit_offset_is_trusted_verbatim(raw, expected_utc):
    dt, flags = parse_acceptance_datetime_ex(raw)
    assert dt == expected_utc
    assert DataQualityFlag.ACCEPTANCE_TZ_ASSUMED_EASTERN.value not in flags


def test_missing_and_garbage():
    assert parse_acceptance_datetime_ex(None) == (None, ())
    assert parse_acceptance_datetime_ex("") == (None, ())
    assert parse_acceptance_datetime_ex("not-a-time") == (None, ())


# --------------------------------------------------------------------------- #
# 2. session classification -- pre-open / RTH / after-close                   #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected_bucket",
    [
        ("2026-09-10T08:15:00Z", SessionBucket.BMO),   # 08:15 ET  < 09:30
        ("2026-09-10T09:29:59Z", SessionBucket.BMO),   # one second before open
        ("2026-09-10T09:30:00Z", SessionBucket.RTH),   # the open
        ("2026-09-10T13:45:00Z", SessionBucket.RTH),
        ("2026-09-10T15:59:59Z", SessionBucket.RTH),   # one second before close
        ("2026-09-10T16:00:00Z", SessionBucket.AMC),   # the close
        ("2026-09-10T16:16:50Z", SessionBucket.AMC),   # the real ORCL earnings 8-K
        ("2026-09-10T20:30:00Z", SessionBucket.AMC),
        ("2026-09-12T12:00:00Z", SessionBucket.NON_TRADING_DAY),  # Saturday
    ],
)
def test_session_bucket_after_eastern_correction(raw, expected_bucket):
    dt = parse_acceptance_datetime(raw)
    assert bucket_session(dt).bucket is expected_bucket


def test_orcl_earnings_8k_is_after_close_not_rth():
    """The published audit's ORCL LT7/LT8 cards said 'regular hours' -- the
    persisted session_bucket was RTH. Oracle reports after the close; the real
    acceptance 16:16:50 ET is AMC. Regression for that mislabel."""
    dt = parse_acceptance_datetime("2026-09-10T16:16:50.000Z")
    assert dt == datetime(2026, 9, 10, 20, 16, 50, tzinfo=UTC)
    assert bucket_session(dt).bucket is SessionBucket.AMC


# --------------------------------------------------------------------------- #
# 3. date-boundary: a late-evening-ET filing belongs to the NEXT UTC day      #
# --------------------------------------------------------------------------- #
def test_late_evening_et_crosses_utc_midnight():
    # 22:15 ET on Sep 10 -> 02:15 UTC on Sep 11
    dt = parse_acceptance_datetime("2026-09-10T22:15:00Z")
    assert dt == datetime(2026, 9, 11, 2, 15, 0, tzinfo=UTC)
    assert dt.date() == date(2026, 9, 11)
    # ...but the ET calendar date (what V2's date-only cluster logic keys on)
    # is still Sep 10 -- the two-wrongs-cancel property that kept V2 entry
    # sessions correct under the bug is now explicit, not accidental.
    from zoneinfo import ZoneInfo
    assert dt.astimezone(ZoneInfo("America/New_York")).date() == date(2026, 9, 10)


# --------------------------------------------------------------------------- #
# 4. as-of replay causal cut-off                                             #
# --------------------------------------------------------------------------- #
def test_causal_cutoff_no_longer_admits_a_filing_four_hours_early():
    """A filing accepted 14:00 ET (18:00 UTC) must NOT satisfy a causal cut-off
    of 15:00 UTC. Under the bug it was stored as 14:00 UTC and wrongly passed."""
    accepted = parse_acceptance_datetime("2026-09-10T14:00:00Z")
    cutoff = datetime(2026, 9, 10, 15, 0, 0, tzinfo=UTC)
    assert accepted == datetime(2026, 9, 10, 18, 0, 0, tzinfo=UTC)
    assert accepted > cutoff            # correctly still in the future at 15:00 UTC


# --------------------------------------------------------------------------- #
# 5. second-insider activation + eligible entry session (V2 contract)         #
# --------------------------------------------------------------------------- #
def test_second_owner_after_close_still_enters_next_session():
    """A 2nd distinct owner's Form 4 accepted 17:00 ET Thursday disseminates
    after Thursday's close -> eligible entry session = Friday. The date used by
    V2 (ET calendar date of acceptance) is Thursday either way; the corrected
    UTC instant just no longer claims it was public 4h before the close."""
    from talonx_v2 import calendar as vc
    from zoneinfo import ZoneInfo
    dt = parse_acceptance_datetime("2026-09-10T17:00:00Z")   # Thu 17:00 ET
    assert dt == datetime(2026, 9, 10, 21, 0, 0, tzinfo=UTC)
    et_date = dt.astimezone(ZoneInfo("America/New_York")).date()
    assert et_date == date(2026, 9, 10)
    entry = vc.next_session_strictly_after(et_date)
    assert entry == date(2026, 9, 11)   # Friday
