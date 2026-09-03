"""
tests/test_intelligence_store_migration.py
------------------------------------------
Task 96A -- opening EventStore against a DB that predates it must be
non-destructive: every existing IngestionLedger table and row survives,
and the new event-intelligence tables appear.
"""
from __future__ import annotations

from datetime import date

from talonx_ingest.intelligence.store import EventStore
from talonx_ingest.storage.ledger import IngestionLedger
from tests.conftest import make_filing


def test_old_ledger_db_migrates_additively(tmp_path, company):
    db = tmp_path / "ingestion_ledger.db"

    # 1. an "old" DB: only the IngestionLedger schema + a couple of rows
    with IngestionLedger(db) as ledger:
        ledger.mark_ingested(make_filing(company, "0000320193-24-000001"), chunk_count=10)
        ledger.mark_ingested(make_filing(company, "0000320193-24-000002"), chunk_count=20)
        ledger.mark_financials_ingested("AAPL", company.cik, [2023, 2024])

    # 2. open the event store on the SAME file
    with EventStore(db) as store:
        assert store.schema_version() == 1
        tables = {
            r[0]
            for r in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "ingested_filings" in tables            # old table preserved
        assert "ingested_financials" in tables
        assert "text_events" in tables                 # new tables added
        assert "source_freshness" in tables

    # 3. the old ledger still reads its rows back, unchanged
    with IngestionLedger(db) as ledger2:
        assert ledger2.is_ingested("0000320193-24-000001") is True
        assert ledger2.is_ingested("0000320193-24-000002") is True
        assert ledger2.latest_ingested_fiscal_year(company.cik) == 2024


def test_event_store_open_is_repeatable(tmp_path):
    db = tmp_path / "x.db"
    EventStore(db).close()
    EventStore(db).close()
    with EventStore(db) as store:  # third open, still fine, version stable
        assert store.schema_version() == 1


def test_new_db_has_both_schemas_regardless_of_open_order(tmp_path):
    db = tmp_path / "y.db"
    EventStore(db).close()
    with IngestionLedger(db) as ledger:
        ledger.mark_ingested(
            _min_filing(), chunk_count=1
        ) if False else None  # ledger schema created on open
        tables = {
            r[0]
            for r in ledger._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "ingested_filings" in tables
    assert "text_events" in tables


def _min_filing():
    from talonx_ingest.edgar.models import CompanyRef, FilingMetadata

    return FilingMetadata(
        company=CompanyRef(ticker="AAPL", cik="0000320193", name="Apple Inc."),
        accession_number="0000320193-24-000009",
        form_type="10-K",
        filing_date=date(2024, 1, 1),
        report_date=None,
        primary_document="d.htm",
    )
