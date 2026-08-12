"""
tests/test_ledger.py
------------------------
Tests storage.ledger.IngestionLedger -- the SQLite-backed incremental
ingestion tracker. Uses real sqlite3 (stdlib, no mocking needed).
"""
from __future__ import annotations

from talonx_ingest.storage.ledger import IngestionLedger
from tests.conftest import make_article, make_filing


def test_fresh_ledger_all_filings_unseen(ledger_path, company):
    filings = [make_filing(company, f"acc-{i}") for i in range(3)]
    with IngestionLedger(ledger_path) as ledger:
        assert len(ledger.filter_unseen(filings)) == 3


def test_marking_ingested_removes_from_unseen(ledger_path, company):
    filings = [make_filing(company, f"acc-{i}") for i in range(3)]
    with IngestionLedger(ledger_path) as ledger:
        ledger.mark_ingested(filings[0], chunk_count=150)
        ledger.mark_ingested(filings[1], chunk_count=200)

        unseen = ledger.filter_unseen(filings)
        assert [f.accession_number for f in unseen] == [filings[2].accession_number]


def test_is_ingested_direct_check(ledger_path, filing):
    with IngestionLedger(ledger_path) as ledger:
        assert ledger.is_ingested(filing.accession_number) is False
        ledger.mark_ingested(filing, chunk_count=10)
        assert ledger.is_ingested(filing.accession_number) is True


def test_state_persists_across_reopen(ledger_path, filing):
    with IngestionLedger(ledger_path) as ledger:
        ledger.mark_ingested(filing, chunk_count=10)

    # Reopen as a fresh connection -- must survive
    with IngestionLedger(ledger_path) as ledger2:
        assert ledger2.is_ingested(filing.accession_number) is True


def test_stats_by_ticker(ledger_path, company):
    filings = [make_filing(company, f"acc-{i}") for i in range(2)]
    with IngestionLedger(ledger_path) as ledger:
        for f in filings:
            ledger.mark_ingested(f, chunk_count=50)
        stats = ledger.stats_by_ticker("AAPL")
        assert len(stats) == 2
        assert {row["accession_number"] for row in stats} == {f.accession_number for f in filings}


def test_forget_ticker_resets_state(ledger_path, company):
    filings = [make_filing(company, f"acc-{i}") for i in range(2)]
    with IngestionLedger(ledger_path) as ledger:
        for f in filings:
            ledger.mark_ingested(f, chunk_count=50)

        removed = ledger.forget_ticker("AAPL")
        assert removed == 2
        assert len(ledger.filter_unseen(filings)) == 2  # both unseen again


def test_filter_unseen_empty_input_returns_empty(ledger_path):
    with IngestionLedger(ledger_path) as ledger:
        assert ledger.filter_unseen([]) == []


# ------------------------------------------------------------------
# News article tracking (separate table, same dedup philosophy)
# ------------------------------------------------------------------

def test_news_articles_unseen_by_default(ledger_path):
    articles = [make_article(f"https://example.com/{i}") for i in range(3)]
    with IngestionLedger(ledger_path) as ledger:
        assert len(ledger.filter_unseen_articles(articles)) == 3


def test_news_articles_marked_ingested_are_skipped(ledger_path):
    articles = [make_article(f"https://example.com/{i}") for i in range(3)]
    with IngestionLedger(ledger_path) as ledger:
        ledger.mark_news_ingested(articles[0], chunk_count=2)

        unseen = ledger.filter_unseen_articles(articles)
        assert len(unseen) == 2
        assert ledger.is_news_ingested(articles[0].article_id) is True
        assert ledger.is_news_ingested(articles[1].article_id) is False


def test_filing_and_news_ledgers_are_independent(ledger_path, filing, news_article):
    """A filing accession number and an article's hashed ID live in separate
    tables -- marking one ingested must never affect the other's lookup."""
    with IngestionLedger(ledger_path) as ledger:
        ledger.mark_ingested(filing, chunk_count=100)

        assert ledger.is_ingested(filing.accession_number) is True
        assert ledger.is_news_ingested(filing.accession_number) is False
        assert ledger.is_news_ingested(news_article.article_id) is False


# --- Structured financials tracking (Phase 2 LONG_TERM path) ---------------

def test_fresh_ledger_has_no_ingested_fiscal_year(ledger_path):
    with IngestionLedger(ledger_path) as ledger:
        assert ledger.latest_ingested_fiscal_year("0000320193") is None


def test_mark_financials_ingested_records_the_latest_fiscal_year(ledger_path):
    with IngestionLedger(ledger_path) as ledger:
        ledger.mark_financials_ingested("AAPL", "0000320193", [2023, 2024, 2025])

        assert ledger.latest_ingested_fiscal_year("0000320193") == 2025


def test_mark_financials_ingested_is_idempotent(ledger_path):
    with IngestionLedger(ledger_path) as ledger:
        ledger.mark_financials_ingested("AAPL", "0000320193", [2024, 2025])
        ledger.mark_financials_ingested("AAPL", "0000320193", [2025])  # re-run, overlapping year

        assert ledger.latest_ingested_fiscal_year("0000320193") == 2025


def test_financials_ledger_is_per_cik(ledger_path):
    with IngestionLedger(ledger_path) as ledger:
        ledger.mark_financials_ingested("AAPL", "0000320193", [2025])

        assert ledger.latest_ingested_fiscal_year("0000789019") is None  # MSFT's CIK, untouched


def test_financials_state_persists_across_reopen(ledger_path):
    with IngestionLedger(ledger_path) as ledger:
        ledger.mark_financials_ingested("AAPL", "0000320193", [2025])

    with IngestionLedger(ledger_path) as ledger2:
        assert ledger2.latest_ingested_fiscal_year("0000320193") == 2025
