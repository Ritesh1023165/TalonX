"""
tests/test_insider_bulk_xml.py
------------------------------
Task 96D -- SEC bulk row-group parsing and Form 3/4/5 ownership XML
parsing produce the same canonical objects.
"""
from __future__ import annotations

from datetime import date

from talonx_ingest.intelligence.insider.bulk import BulkTables, parse_row_groups
from talonx_ingest.intelligence.insider.domain import (
    OwnershipFormType,
    TransactionClass,
)
from talonx_ingest.intelligence.insider.ownership_xml import parse_ownership_xml

_ACC = "0001214156-26-000005"

_XML = """<?xml version="1.0"?>
<ownershipDocument>
 <documentType>4</documentType>
 <periodOfReport>2026-02-10</periodOfReport>
 <issuer><issuerCik>0000320193</issuerCik><issuerName>Apple Inc.</issuerName>
   <issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>
 <reportingOwner>
   <reportingOwnerId><rptOwnerCik>0001214156</rptOwnerCik><rptOwnerName>MAESTRI LUCA</rptOwnerName></reportingOwnerId>
   <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>SVP, CFO</officerTitle></reportingOwnerRelationship>
 </reportingOwner>
 <nonDerivativeTable>
   <nonDerivativeTransaction>
     <securityTitle><value>Common Stock</value></securityTitle>
     <transactionDate><value>2026-02-10</value></transactionDate>
     <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
     <transactionAmounts>
       <transactionShares><value>5000</value></transactionShares>
       <transactionPricePerShare><value>232.50</value></transactionPricePerShare>
       <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
     </transactionAmounts>
     <postTransactionAmounts><sharesOwnedFollowingTransaction><value>110000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
     <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
   </nonDerivativeTransaction>
 </nonDerivativeTable>
 <derivativeTable>
   <derivativeTransaction>
     <securityTitle><value>Restricted Stock Unit</value></securityTitle>
     <transactionDate><value>2026-02-10</value></transactionDate>
     <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
     <transactionAmounts>
       <transactionShares><value>2000</value></transactionShares>
       <transactionPricePerShare><value>0</value></transactionPricePerShare>
       <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
     </transactionAmounts>
     <ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
   </derivativeTransaction>
 </derivativeTable>
</ownershipDocument>"""


def test_ownership_xml_parses_nonderiv_and_deriv():
    filing, txns = parse_ownership_xml(_XML, accession=_ACC)
    assert filing.form_type is OwnershipFormType.FORM_4
    assert filing.symbol == "AAPL"
    assert filing.issuer_cik == "0000320193"
    assert filing.n_transactions == 2
    assert filing.owner_ciks == ("0001214156",)
    by_cls = {t.classification for t in txns}
    assert TransactionClass.OPEN_MARKET_SALE in by_cls
    assert TransactionClass.EXERCISE_OR_CONVERSION in by_cls
    sale = next(t for t in txns if t.classification is TransactionClass.OPEN_MARKET_SALE)
    assert sale.transaction_value == 1_162_500.0
    assert sale.owner_role.value == "CFO"
    assert sale.transaction_date == date(2026, 2, 10)
    assert sale.shares_owned_after == 110000.0
    deriv = next(t for t in txns if t.is_derivative)
    assert deriv.transaction_value is None
    assert "derivative_not_valued" in deriv.data_quality_flags


def test_amendment_xml():
    xml = _XML.replace("<documentType>4</documentType>", "<documentType>4/A</documentType>")
    filing, txns = parse_ownership_xml(xml, accession=_ACC)
    assert filing.form_type is OwnershipFormType.FORM_4_A
    assert filing.is_amendment is True
    assert all("amendment" in t.data_quality_flags for t in txns)


def test_malformed_xml_is_handled():
    filing, txns = parse_ownership_xml("<not valid", accession=_ACC)
    assert txns == []
    assert "ownership_xml_parse_failed" in filing.data_quality_flags


# --- bulk -----------------------------------------------------------

def _bulk_tables():
    t = BulkTables()
    t.submissions[_ACC] = {
        "ACCESSION_NUMBER": _ACC, "DOCUMENT_TYPE": "4", "ISSUERCIK": "0000320193",
        "ISSUERTRADINGSYMBOL": "AAPL", "ISSUERNAME": "Apple Inc.",
        "FILING_DATE": "12-FEB-2026", "PERIOD_OF_REPORT": "10-FEB-2026",
    }
    t.owners[_ACC] = [{
        "ACCESSION_NUMBER": _ACC, "RPTOWNERCIK": "0001214156", "RPTOWNERNAME": "MAESTRI LUCA",
        "RPTOWNER_RELATIONSHIP": "Officer", "RPTOWNER_TITLE": "SVP, CFO",
    }]
    t.nonderiv_trans[_ACC] = [{
        "ACCESSION_NUMBER": _ACC, "NONDERIV_TRANS_SK": "999", "SECURITY_TITLE": "Common Stock",
        "TRANS_DATE": "10-FEB-2026", "TRANS_CODE": "S", "TRANS_SHARES": "5000",
        "TRANS_PRICEPERSHARE": "232.50", "TRANS_ACQUIRED_DISP_CD": "D",
        "DIRECT_INDIRECT_OWNERSHIP": "D", "SHRS_OWND_FOLWNG_TRANS": "110000",
    }]
    return t


def test_bulk_parse_row_groups():
    groups = list(parse_row_groups(_bulk_tables(), symbols=["AAPL"]))
    assert len(groups) == 1
    filing, txns = groups[0]
    assert filing.symbol == "AAPL"
    assert filing.filing_date == date(2026, 2, 12)
    assert len(txns) == 1
    assert txns[0].classification is TransactionClass.OPEN_MARKET_SALE
    assert txns[0].transaction_value == 1_162_500.0
    assert txns[0].source_row_sk == "999"
    # no acceptance timestamp available from the bulk -> flagged
    assert "filing_date_used_as_acceptance" in txns[0].data_quality_flags


def test_bulk_and_xml_transaction_ids_match():
    _, xml_txns = parse_ownership_xml(_XML, accession=_ACC)
    _, bulk_txns = list(parse_row_groups(_bulk_tables(), symbols=["AAPL"]))[0]
    xml_sale = next(t for t in xml_txns if t.classification is TransactionClass.OPEN_MARKET_SALE)
    assert xml_sale.transaction_id == bulk_txns[0].transaction_id


def test_bulk_symbol_filter_excludes_others():
    t = _bulk_tables()
    t.submissions["0000000000-26-000001"] = {
        "ACCESSION_NUMBER": "0000000000-26-000001", "DOCUMENT_TYPE": "4",
        "ISSUERTRADINGSYMBOL": "MSFT", "ISSUERCIK": "0000789019",
    }
    t.nonderiv_trans["0000000000-26-000001"] = [{
        "ACCESSION_NUMBER": "0000000000-26-000001", "TRANS_CODE": "S", "TRANS_DATE": "01-FEB-2026",
        "TRANS_SHARES": "1", "TRANS_PRICEPERSHARE": "1",
    }]
    syms = {f.symbol for f, _ in parse_row_groups(t, symbols=["AAPL"])}
    assert syms == {"AAPL"}


def test_form3_with_no_transactions_is_initial_holding():
    t = BulkTables()
    acc = "0000000000-26-000009"
    t.submissions[acc] = {"ACCESSION_NUMBER": acc, "DOCUMENT_TYPE": "3",
                          "ISSUERTRADINGSYMBOL": "AAPL", "ISSUERCIK": "0000320193"}
    t.nonderiv_holding[acc] = [{"ACCESSION_NUMBER": acc, "SECURITY_TITLE": "Common Stock",
                                "SHRS_OWND_FOLWNG_TRANS": "5000", "DIRECT_INDIRECT_OWNERSHIP": "D"}]
    filing, txns = list(parse_row_groups(t, symbols=["AAPL"]))[0]
    assert filing.form_type is OwnershipFormType.FORM_3
    assert txns[0].classification is TransactionClass.INITIAL_HOLDING
    assert txns[0].is_open_market_discretionary is False
