"""
tests/test_insider_store.py
---------------------------
Task 96D -- InsiderStore: persist / read / restart / idempotent upsert /
order-independent bulk-vs-XML merge / additive migration.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from talonx_ingest.intelligence.insider.domain import (
    AcquiredDisposed,
    InsiderFiling,
    InsiderRole,
    InsiderTransaction,
    OwnershipFormType,
    OwnershipNature,
    TransactionClass,
)
from talonx_ingest.intelligence.insider.store import InsiderStore

_NOW = datetime(2026, 2, 12, 20, 5, tzinfo=timezone.utc)


def _txn(tid="F4TX:0001214156-26-000005:abc", **kw):
    base = dict(
        transaction_id=tid,
        accession="0001214156-26-000005",
        issuer_cik="0000320193",
        symbol="AAPL",
        company_name="Apple Inc.",
        accepted_at_utc=_NOW,
        filing_date=date(2026, 2, 12),
        transaction_date=date(2026, 2, 10),
        owner_cik="0001214156",
        owner_name="MAESTRI LUCA",
        owner_role=InsiderRole.CFO,
        owner_roles=(InsiderRole.CFO,),
        is_officer=True,
        officer_title="SVP, CFO",
        form_type=OwnershipFormType.FORM_4,
        transaction_code="S",
        classification=TransactionClass.OPEN_MARKET_SALE,
        security_title="Common Stock",
        transaction_shares=5000.0,
        price_per_share=232.5,
        transaction_value=1_162_500.0,
        acquired_disposed=AcquiredDisposed.DISPOSED,
        ownership_nature=OwnershipNature.DIRECT,
        shares_owned_after=110000.0,
        signed_open_market_shares=-5000.0,
        signed_open_market_value=-1_162_500.0,
        source_reference="SEC_EDGAR_ARCHIVES:x",
        data_quality_flags=(),
    )
    base.update(kw)
    return InsiderTransaction(**base)


def _filing(**kw):
    base = dict(
        insider_filing_id="0001214156-26-000005",
        accession="0001214156-26-000005",
        symbol="AAPL",
        issuer_cik="0000320193",
        company_name="Apple Inc.",
        form_type=OwnershipFormType.FORM_4,
        accepted_at_utc=_NOW,
        filing_date=date(2026, 2, 12),
        period_of_report=date(2026, 2, 10),
        n_transactions=1,
        n_owners=1,
        owner_ciks=("0001214156",),
        owner_names=("MAESTRI LUCA",),
        source_reference="SEC_EDGAR_ARCHIVES:x",
        ingested_at_utc=_NOW,
    )
    base.update(kw)
    return InsiderFiling(**base)


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "shared.db"


def test_schema_and_tables(store_path):
    with InsiderStore(store_path) as st:
        assert st.schema_version() == 1
        names = {
            r[0] for r in st._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {"insider_filings", "insider_transactions", "insider_filing_evidence"} <= names


def test_insert_read_roundtrip(store_path):
    t = _txn()
    with InsiderStore(store_path) as st:
        assert st.upsert_transaction(t) is True
        got = st.get_transaction(t.transaction_id)
    assert got == t


def test_idempotent_upsert(store_path):
    t = _txn()
    with InsiderStore(store_path) as st:
        assert st.upsert_transaction(t) is True
        assert st.upsert_transaction(t) is False
        assert st.upsert_transaction(t) is False
        assert st.count_transactions() == 1


def test_order_independent_merge_keeps_acceptance(store_path):
    incomplete = _txn(
        accepted_at_utc=None, event_id=None, source_reference="SEC_FORM345_BULK",
        data_quality_flags=("filing_date_used_as_acceptance", "missing_acceptance_timestamp"),
    )
    complete = _txn(accepted_at_utc=_NOW, source_reference="SEC_EDGAR_ARCHIVES:x")
    with InsiderStore(store_path) as st:
        st.upsert_transaction(incomplete)
        st.upsert_transaction(complete)
        a = st.get_transaction(complete.transaction_id)
    with InsiderStore(tmp := store_path.parent / "rev.db") as st2:
        st2.upsert_transaction(complete)
        st2.upsert_transaction(incomplete)
        b = st2.get_transaction(complete.transaction_id)
    assert a.accepted_at_utc == _NOW == b.accepted_at_utc
    assert "missing_acceptance_timestamp" not in a.data_quality_flags
    assert a == b


def test_state_persists_across_reopen(store_path):
    with InsiderStore(store_path) as st:
        st.upsert_batch(_filing(), [_txn()])
    with InsiderStore(store_path) as st2:
        assert st2.count_transactions() == 1
        assert st2.count_filings() == 1
        assert st2.get_filing("0001214156-26-000005").symbol == "AAPL"


def test_query_filters(store_path):
    with InsiderStore(store_path) as st:
        st.upsert_transaction(_txn(tid="t1", transaction_date=date(2026, 2, 10)))
        st.upsert_transaction(_txn(tid="t2", classification=TransactionClass.GRANT_OR_AWARD,
                                   transaction_code="A", transaction_date=date(2026, 2, 11),
                                   signed_open_market_shares=None, signed_open_market_value=None))
        st.upsert_transaction(_txn(tid="t3", owner_cik="9999", transaction_date=date(2026, 1, 1)))
        assert len(st.query_transactions(symbol="AAPL")) == 3
        assert len(st.query_transactions(symbol="AAPL", open_market_only=True)) == 2
        assert len(st.query_transactions(owner_cik="9999")) == 1
        assert len(st.query_transactions(since=date(2026, 2, 1))) == 2
        assert len(st.query_transactions(classification=TransactionClass.GRANT_OR_AWARD)) == 1


def test_additive_migration_preserves_event_store(tmp_path):
    from talonx_ingest.intelligence.domain import (
        EventType, FreshnessStatus, SessionBucket, SourceType, TextEvent,
    )
    from talonx_ingest.intelligence.store import EventStore

    db = tmp_path / "ingestion_ledger.db"
    with EventStore(db) as es:
        es.upsert_event(TextEvent(
            event_id="SEC:0001214156-26-000005:INSIDER_TRANSACTION", symbol="AAPL",
            company_name="Apple Inc.", source_type=SourceType.SEC_EDGAR_SUBMISSIONS,
            source_record_id="0001214156-26-000005", event_type=EventType.INSIDER_TRANSACTION,
            form_type="4", accession="0001214156-26-000005", accepted_at_utc=_NOW,
            session_bucket=SessionBucket.UNKNOWN, ingested_at_utc=_NOW,
            freshness=FreshnessStatus.UNKNOWN,
        ))
    with InsiderStore(db) as st:
        st.upsert_batch(_filing(), [_txn()])
        tables = {
            r[0] for r in st._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "text_events" in tables and "insider_transactions" in tables
    with EventStore(db) as es2:
        assert es2.has_event("SEC:0001214156-26-000005:INSIDER_TRANSACTION")
        assert es2.schema_version() == 1
