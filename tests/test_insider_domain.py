"""
tests/test_insider_domain.py
----------------------------
Task 96D -- insider domain value objects: immutability, no predictive field.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from talonx_ingest.intelligence.insider.domain import (
    InsiderActivity,
    InsiderCluster,
    InsiderFiling,
    InsiderRole,
    InsiderTransaction,
    OwnershipFormType,
    RoleSubsetAggregate,
    RollingOpenMarketAggregate,
    TransactionClass,
)

_NOW = datetime(2026, 2, 12, 20, 5, tzinfo=timezone.utc)

_FORBIDDEN = {
    "expected_return", "direction", "sentiment", "sentiment_score", "signal",
    "recommendation", "target_price", "probability", "bullish", "bearish",
    "conviction", "alpha", "insider_alpha", "smart_money", "score", "rating",
}


def _txn(**kw):
    base = dict(
        transaction_id="F4TX:0001214156-26-000005:abc123",
        accession="0001214156-26-000005",
        issuer_cik="0000320193",
        symbol="aapl",
        classification=TransactionClass.OPEN_MARKET_SALE,
    )
    base.update(kw)
    return InsiderTransaction(**base)


def test_transaction_defaults_and_schema_version():
    t = _txn()
    assert t.schema_version == "insider_transaction@v1"
    assert t.form_type is OwnershipFormType.FORM_4
    assert t.owner_role is InsiderRole.OTHER
    assert t.data_quality_flags == ()
    assert t.is_open_market_discretionary is True


def test_transaction_is_frozen():
    t = _txn()
    with pytest.raises(ValidationError):
        t.symbol = "MSFT"


def test_transaction_rejects_unknown_field():
    with pytest.raises(ValidationError):
        _txn(insider_alpha=0.5)


def test_no_predictive_field_on_any_model():
    for model in (
        InsiderTransaction, InsiderFiling, InsiderActivity, InsiderCluster,
        RollingOpenMarketAggregate, RoleSubsetAggregate,
    ):
        assert not (set(model.model_fields) & _FORBIDDEN), model.__name__


def test_transaction_json_roundtrip():
    t = _txn(
        owner_roles=(InsiderRole.CFO,),
        transaction_shares=5000.0,
        price_per_share=232.5,
        transaction_value=1_162_500.0,
        transaction_date=date(2026, 2, 10),
        accepted_at_utc=_NOW,
    )
    assert InsiderTransaction.model_validate_json(t.model_dump_json()) == t


def test_activity_defaults():
    a = InsiderActivity(symbol="AAPL", issuer_cik="0000320193", as_of_date=date(2026, 2, 15))
    assert a.schema_version == "insider_activity@v1"
    assert a.open_market_aggregates == ()
    assert a.clusters == ()
