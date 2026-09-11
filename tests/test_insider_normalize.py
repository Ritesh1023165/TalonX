"""
tests/test_insider_normalize.py
-------------------------------
Task 96D -- canonicalisation: value calc, ownership, dates, signed flow.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from talonx_ingest.intelligence.insider.domain import (
    AcquiredDisposed,
    OwnershipFormType,
    OwnershipNature,
    TransactionClass,
)
from talonx_ingest.intelligence.insider.normalize import (
    FilingContext,
    OwnerContext,
    RawTransactionRow,
    normalize_transaction,
    parse_date_any,
)

_FC = FilingContext(
    accession="0001214156-26-000005",
    issuer_cik="0000320193",
    symbol="AAPL",
    company_name="Apple Inc.",
    form_type=OwnershipFormType.FORM_4,
    accepted_at_utc=datetime(2026, 2, 12, 20, 5, tzinfo=timezone.utc),
    filing_date=date(2026, 2, 12),
)
_OC = OwnerContext(
    owner_cik="0001214156", owner_name="MAESTRI LUCA", is_officer=True,
    officer_title="Senior Vice President, CFO",
)


def _n(raw, fc=_FC, oc=_OC, ordinal=0):
    return normalize_transaction(raw, fc, oc, ordinal=ordinal)


def test_parse_date_any_bulk_and_iso():
    assert parse_date_any("27-MAR-2019") == date(2019, 3, 27)
    assert parse_date_any("2026-02-10") == date(2026, 2, 10)
    assert parse_date_any("2026-02-10T00:00:00") == date(2026, 2, 10)
    assert parse_date_any("") is None
    assert parse_date_any("garbage") is None


def test_open_market_sale_value_and_signed_flow():
    t = _n(RawTransactionRow(transaction_code="S", transaction_date="10-FEB-2026",
                             shares="5000", price="232.50", acquired_disposed="D",
                             direct_indirect="D", security_title="Common Stock"))
    assert t.classification is TransactionClass.OPEN_MARKET_SALE
    assert t.transaction_value == 1_162_500.0
    assert t.signed_open_market_shares == -5000.0
    assert t.signed_open_market_value == -1_162_500.0
    assert t.acquired_disposed is AcquiredDisposed.DISPOSED
    assert t.ownership_nature is OwnershipNature.DIRECT
    assert t.data_quality_flags == ()


def test_open_market_purchase_positive_signed_flow():
    t = _n(RawTransactionRow(transaction_code="P", transaction_date="10-FEB-2026",
                             shares="1000", price="200", acquired_disposed="A"))
    assert t.classification is TransactionClass.OPEN_MARKET_PURCHASE
    assert t.signed_open_market_shares == 1000.0
    assert t.signed_open_market_value == 200_000.0


def test_missing_price_on_open_market_flags():
    t = _n(RawTransactionRow(transaction_code="S", transaction_date="10-FEB-2026",
                             shares="5000", price=None))
    assert t.transaction_value is None
    assert "missing_price" in t.data_quality_flags
    assert t.signed_open_market_value is None
    assert t.signed_open_market_shares == -5000.0   # shares still known


def test_zero_price_on_open_market_flags_missing():
    t = _n(RawTransactionRow(transaction_code="P", transaction_date="10-FEB-2026",
                             shares="1000", price="0"))
    assert t.transaction_value is None
    assert "missing_price" in t.data_quality_flags


def test_grant_with_no_price_is_not_applicable_not_missing():
    t = _n(RawTransactionRow(transaction_code="A", transaction_date="10-FEB-2026",
                             shares="10000", price=None, acquired_disposed="A"))
    assert t.classification is TransactionClass.GRANT_OR_AWARD
    assert t.transaction_value is None
    assert "not_applicable_price" in t.data_quality_flags
    assert "missing_price" not in t.data_quality_flags


def test_derivative_transaction_not_valued():
    t = _n(RawTransactionRow(table="DERIVATIVE", transaction_code="M",
                             transaction_date="10-FEB-2026", shares="2000", price="0"))
    assert t.is_derivative is True
    assert t.table == "DERIVATIVE"
    assert t.transaction_value is None
    assert "derivative_not_valued" in t.data_quality_flags


def test_indirect_ownership_flagged():
    t = _n(RawTransactionRow(transaction_code="S", transaction_date="10-FEB-2026",
                             shares="100", price="10", direct_indirect="I"))
    assert t.ownership_nature is OwnershipNature.INDIRECT
    assert "indirect_ownership" in t.data_quality_flags


def test_initial_holding_row():
    t = _n(RawTransactionRow(is_holding=True, security_title="Common Stock",
                             shares_owned_after="120000", direct_indirect="D"),
           fc=_FC.__class__(**{**_FC.__dict__, "form_type": OwnershipFormType.FORM_3}))
    assert t.classification is TransactionClass.INITIAL_HOLDING
    assert "initial_holding" in t.data_quality_flags
    assert t.transaction_value is None
    assert t.shares_owned_after == 120000.0


def test_missing_transaction_date_flag():
    t = _n(RawTransactionRow(transaction_code="S", transaction_date=None, shares="1", price="1"))
    assert "missing_transaction_date" in t.data_quality_flags


def test_ordinal_collision_flag():
    raw = RawTransactionRow(transaction_code="S", transaction_date="10-FEB-2026", shares="1", price="1")
    t0 = _n(raw, ordinal=0)
    t1 = _n(raw, ordinal=1)
    assert t0.transaction_id != t1.transaction_id
    assert "id_collision_ordinal" in t1.data_quality_flags
    assert "id_collision_ordinal" not in t0.data_quality_flags


def test_role_carried_through():
    t = _n(RawTransactionRow(transaction_code="S", transaction_date="10-FEB-2026", shares="1", price="1"))
    assert t.owner_role.value == "CFO"
    assert t.is_officer is True
    assert t.officer_title == "Senior Vice President, CFO"
