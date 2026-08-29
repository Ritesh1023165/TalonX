"""
tests/conftest.py
--------------------
Shared fixtures. Keeps individual test files focused on behavior, not
setup boilerplate.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from talonx_ingest.edgar.models import CompanyRef, FilingMetadata
from talonx_ingest.news.models import NewsArticle


def pytest_addoption(parser):
    """Explicit opt-in destination for Task 83-R2 rehearsal evidence.

    The default is ``None``, so ordinary and partial test runs cannot write
    the committed matrix.
    """
    parser.addoption(
        "--task83-r2-matrix-output", action="store", default=None,
        help="temporary CSV destination for a complete scenarios 21-33 run",
    )


@pytest.fixture
def company() -> CompanyRef:
    return CompanyRef(ticker="AAPL", cik="0000320193", name="Apple Inc.")


@pytest.fixture
def filing(company: CompanyRef) -> FilingMetadata:
    return FilingMetadata(
        company=company,
        accession_number="0000320193-24-000123",
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        report_date=date(2024, 9, 28),
        primary_document="aapl-20240928.htm",
    )


def make_filing(
    company: CompanyRef, accession_number: str, form_type: str = "10-K"
) -> FilingMetadata:
    """Non-fixture helper for tests that need several distinct filings."""
    return FilingMetadata(
        company=company,
        accession_number=accession_number,
        form_type=form_type,
        filing_date=date(2024, 1, 1),
        report_date=None,
        primary_document="doc.htm",
    )


@pytest.fixture
def news_article() -> NewsArticle:
    return NewsArticle(
        ticker="AAPL",
        title="Apple announces new product",
        url="https://example.com/articles/apple-new-product",
        source="rss:finance.yahoo.com",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        summary="Apple today announced a new product that analysts expect to drive revenue.",
    )


def make_article(url: str, ticker: str = "AAPL") -> NewsArticle:
    """Non-fixture helper for tests that need several distinct articles."""
    return NewsArticle(
        ticker=ticker,
        title=f"Article at {url}",
        url=url,
        source="rss:test",
        published_at=datetime.now(timezone.utc),
        summary="Some article body text.",
    )


@pytest.fixture
def ledger_path(tmp_path):
    return tmp_path / "test_ledger.db"
