"""
tests/test_insider_pipeline.py
------------------------------
Task 96D -- end-to-end: ingest (bulk + XML) -> InsiderStore + parent
INSIDER_TRANSACTION event -> build_insider_activity. Bulk/XML overlap does
not duplicate.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from talonx_ingest.intelligence.insider.language_safety import scan_insider_activity
from talonx_ingest.intelligence.insider.pipeline import (
    build_insider_activity,
    ingest_bulk_rows,
    ingest_form4_xml,
)
from talonx_ingest.intelligence.insider.store import InsiderStore
from talonx_ingest.intelligence.store import EventStore

_ACC = "0001214156-26-000005"
_ACCEPT = datetime(2026, 2, 12, 20, 5, tzinfo=timezone.utc)

_XML = """<?xml version="1.0"?>
<ownershipDocument><documentType>4</documentType><periodOfReport>2026-02-10</periodOfReport>
<issuer><issuerCik>0000320193</issuerCik><issuerName>Apple Inc.</issuerName>
<issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerCik>0001214156</rptOwnerCik>
<rptOwnerName>MAESTRI LUCA</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>SVP, CFO</officerTitle>
</reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction>
<securityTitle><value>Common Stock</value></securityTitle>
<transactionDate><value>2026-02-10</value></transactionDate>
<transactionCoding><transactionCode>S</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>5000</value></transactionShares>
<transactionPricePerShare><value>232.50</value></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
<ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
</nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>"""

_BULK_NONDERIV = [{
    "ACCESSION_NUMBER": _ACC, "SECURITY_TITLE": "Common Stock", "TRANS_DATE": "10-FEB-2026",
    "TRANS_CODE": "S", "TRANS_SHARES": "5000", "TRANS_PRICEPERSHARE": "232.50",
    "TRANS_ACQUIRED_DISP_CD": "D", "DIRECT_INDIRECT_OWNERSHIP": "D", "ISSUERCIK": "0000320193",
}]
_BULK_SUBS = [{
    "ACCESSION_NUMBER": _ACC, "DOCUMENT_TYPE": "4", "ISSUERCIK": "0000320193",
    "ISSUERTRADINGSYMBOL": "AAPL", "ISSUERNAME": "Apple Inc.",
    "FILING_DATE": "12-FEB-2026", "PERIOD_OF_REPORT": "10-FEB-2026",
}]
_BULK_OWNERS = [{
    "ACCESSION_NUMBER": _ACC, "RPTOWNERCIK": "0001214156", "RPTOWNERNAME": "MAESTRI LUCA",
    "RPTOWNER_RELATIONSHIP": "Officer", "RPTOWNER_TITLE": "SVP, CFO",
}]


@pytest.fixture
def stores(tmp_path):
    db = tmp_path / "l.db"
    es = EventStore(db)
    ins = InsiderStore(db)
    yield ins, es
    ins.close()
    es.close()


def test_xml_ingest_creates_parent_event_and_transaction(stores):
    ins, es = stores
    res = ingest_form4_xml(ins, _XML, accession=_ACC, accepted_at_utc=_ACCEPT, event_store=es)
    assert res.transactions_new == 1
    assert res.parent_events_created == 1
    assert es.has_event("SEC:0001214156-26-000005:INSIDER_TRANSACTION")
    t = ins.query_transactions(symbol="AAPL")[0]
    assert t.event_id == "SEC:0001214156-26-000005:INSIDER_TRANSACTION"
    assert t.classification.value == "OPEN_MARKET_SALE"
    assert t.transaction_value == 1_162_500.0
    assert t.accepted_at_utc == _ACCEPT


def test_bulk_then_xml_no_duplicate(stores):
    ins, es = stores
    r1 = ingest_bulk_rows(ins, nonderiv_rows=_BULK_NONDERIV, submissions_rows=_BULK_SUBS,
                          owner_rows=_BULK_OWNERS, symbols=["AAPL"], event_store=es)
    assert r1.transactions_new == 1
    r2 = ingest_form4_xml(ins, _XML, accession=_ACC, accepted_at_utc=_ACCEPT, event_store=es)
    assert r2.transactions_new == 0            # same content-hash id -> merge, no new row
    assert ins.count_transactions() == 1
    t = ins.query_transactions(symbol="AAPL")[0]
    assert t.accepted_at_utc == _ACCEPT        # XML acceptance merged in over the bulk row


def test_idempotent_reingest(stores):
    ins, es = stores
    ingest_form4_xml(ins, _XML, accession=_ACC, accepted_at_utc=_ACCEPT, event_store=es)
    res = ingest_form4_xml(ins, _XML, accession=_ACC, accepted_at_utc=_ACCEPT, event_store=es)
    assert res.transactions_new == 0
    assert res.parent_events_created == 0
    assert ins.count_transactions() == 1


def test_build_activity_from_store(stores):
    ins, es = stores
    ingest_form4_xml(ins, _XML, accession=_ACC, accepted_at_utc=_ACCEPT, event_store=es)
    act = build_insider_activity(ins, "AAPL", as_of_date=date(2026, 2, 20))
    assert act.symbol == "AAPL"
    assert {a.window_calendar_days for a in act.open_market_aggregates} == {10, 30, 90}
    a30 = next(a for a in act.open_market_aggregates if a.window_calendar_days == 30)
    assert a30.total_sale_value == 1_162_500.0
    assert a30.net_value == -1_162_500.0
    cfo = next(s for s in act.role_subsets if s.subset == "CFO" and s.window_calendar_days == 30)
    assert cfo.sale_count == 1
    assert scan_insider_activity(act) == []
    assert act.evidence and act.evidence[0].transform == "insider_rolling_aggregate@v1"


def test_activity_causal_cutoff_excludes_future_filings(stores):
    ins, es = stores
    ingest_form4_xml(ins, _XML, accession=_ACC, accepted_at_utc=_ACCEPT, event_store=es)
    # as-of before the filing was accepted -> the transaction is not yet knowable
    act = build_insider_activity(ins, "AAPL", as_of_date=date(2026, 2, 11))
    assert act.transactions == ()
    a30 = next(a for a in act.open_market_aggregates if a.window_calendar_days == 30)
    assert a30.transaction_count == 0
