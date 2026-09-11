"""
tests/test_intelligence_edgar_normalize.py
------------------------------------------
Task 96A -- raw EDGAR submissions JSON -> NormalizedFiling.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from talonx_ingest.intelligence.domain import DataQualityFlag
from talonx_ingest.intelligence.edgar_normalize import (
    build_urls,
    iter_normalized_filings,
    normalize_exhibits,
    parse_acceptance_datetime,
)


def _submissions() -> dict:
    return {
        "cik": 320193,
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q", "8-K/A", "4"],
                "accessionNumber": [
                    "0000320193-26-000070",
                    "0000320193-26-000065",
                    "0000320193-26-000051",
                    "0000320193-26-000052",
                ],
                "acceptanceDateTime": [
                    "2026-07-31T18:05:12.000Z",
                    "2026-07-31T18:10:00.000Z",
                    "",
                    "2026-06-10T20:00:00.000Z",
                ],
                "filingDate": ["2026-07-31", "2026-07-31", "2026-06-16", "2026-06-10"],
                "reportDate": ["", "2026-06-27", "", ""],
                "primaryDocument": ["a.htm", "b.htm", "", "form4.xml"],
                "items": ["2.02,9.01", "", "8.01", ""],
            }
        },
    }


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-07-31T18:05:12.000Z", datetime(2026, 7, 31, 18, 5, 12, tzinfo=timezone.utc)),
        ("2026-07-31T18:05:12Z", datetime(2026, 7, 31, 18, 5, 12, tzinfo=timezone.utc)),
        ("2026-07-31T14:05:12-04:00", datetime(2026, 7, 31, 18, 5, 12, tzinfo=timezone.utc)),
        ("2026-07-31 18:05:12", datetime(2026, 7, 31, 18, 5, 12, tzinfo=timezone.utc)),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_acceptance_datetime(raw, expected):
    assert parse_acceptance_datetime(raw) == expected


def test_iter_normalized_filings_reads_acceptance_and_items():
    filings = {f.accession: f for f in iter_normalized_filings(_submissions(), symbol="AAPL")}
    earn = filings["0000320193-26-000070"]
    assert earn.form == "8-K"
    assert earn.acceptance_datetime == datetime(2026, 7, 31, 18, 5, 12, tzinfo=timezone.utc)
    assert earn.items == ("2.02", "9.01")
    assert earn.cik == "0000320193"
    assert earn.symbol == "AAPL"
    assert earn.company_name == "Apple Inc."
    assert earn.primary_document_url.endswith("/000032019326000070/a.htm")
    assert earn.filing_index_url.endswith("/000032019326000070/0000320193-26-000070-index.htm")
    assert earn.is_amendment is False


def test_iter_normalized_filings_form_filter_includes_amendments():
    got = list(iter_normalized_filings(_submissions(), symbol="AAPL", forms=("8-K",)))
    forms = sorted(f.form for f in got)
    assert forms == ["8-K", "8-K/A"]


def test_missing_acceptance_timestamp_flagged():
    amend = next(
        f for f in iter_normalized_filings(_submissions(), symbol="AAPL")
        if f.accession == "0000320193-26-000051"
    )
    assert amend.acceptance_datetime is None
    assert DataQualityFlag.MISSING_ACCEPTANCE_TIMESTAMP.value in amend.flags
    assert DataQualityFlag.PRIMARY_DOCUMENT_UNAVAILABLE.value in amend.flags
    assert amend.is_amendment is True


def test_periodic_missing_report_period_end_flagged():
    subs = _submissions()
    subs["filings"]["recent"]["reportDate"][1] = ""
    q = next(
        f for f in iter_normalized_filings(subs, symbol="AAPL")
        if f.accession == "0000320193-26-000065"
    )
    assert DataQualityFlag.MISSING_REPORT_PERIOD_END.value in q.flags


def test_report_date_parsed_for_10q():
    q = next(
        f for f in iter_normalized_filings(_submissions(), symbol="AAPL")
        if f.form == "10-Q"
    )
    assert q.report_date == date(2026, 6, 27)


def test_malformed_accession_row_is_skipped():
    subs = _submissions()
    subs["filings"]["recent"]["accessionNumber"][0] = "not-valid"
    accs = {f.accession for f in iter_normalized_filings(subs, symbol="AAPL")}
    assert "0000320193-26-000070" not in accs
    assert "0000320193-26-000065" in accs


def test_build_urls():
    idx, directory = build_urls("0000320193", "0000320193-26-000070")
    assert directory == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000070"
    assert idx.endswith("/0000320193-26-000070-index.htm")


def test_normalize_exhibits_from_index_json():
    index_json = {
        "directory": {
            "item": [
                {"name": "a.htm", "type": "8-K", "sequence": "1", "description": "8-K"},
                {"name": "ex99-1.htm", "type": "EX-99.1", "sequence": "2", "description": "Press release"},
                "not-a-dict",
                {"type": "GRAPHIC", "sequence": "3"},  # no name -> skipped
            ]
        }
    }
    ex = normalize_exhibits(index_json, "0000320193", "0000320193-26-000070")
    assert [e.filename for e in ex] == ["a.htm", "ex99-1.htm"]
    assert ex[1].document_type == "EX-99.1"
    assert ex[1].source_url.endswith("/000032019326000070/ex99-1.htm")


def test_normalize_exhibits_tolerates_garbage():
    assert normalize_exhibits({}, "0000320193", "0000320193-26-000070") == ()
    assert normalize_exhibits(None, "0000320193", "0000320193-26-000070") == ()
