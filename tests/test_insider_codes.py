"""
tests/test_insider_codes.py
---------------------------
Task 96D -- SEC transaction-code classification. P/S separated from
A/M/G/F/etc; unknown stays visible.
"""
from __future__ import annotations

import pytest

from talonx_ingest.intelligence.insider.codes import (
    classify_transaction_code,
    is_open_market_discretionary,
)
from talonx_ingest.intelligence.insider.domain import TransactionClass


@pytest.mark.parametrize(
    "code,expected",
    [
        ("P", TransactionClass.OPEN_MARKET_PURCHASE),
        ("S", TransactionClass.OPEN_MARKET_SALE),
        ("A", TransactionClass.GRANT_OR_AWARD),
        ("M", TransactionClass.EXERCISE_OR_CONVERSION),
        ("C", TransactionClass.EXERCISE_OR_CONVERSION),
        ("X", TransactionClass.EXERCISE_OR_CONVERSION),
        ("G", TransactionClass.GIFT),
        ("F", TransactionClass.TAX_WITHHOLDING),
        ("D", TransactionClass.SALE_OR_DISPOSITION_TO_ISSUER),
        ("W", TransactionClass.INHERITANCE),
        ("I", TransactionClass.PLAN_DISCRETIONARY),
        ("J", TransactionClass.OTHER_ACQ_DISP),
        ("K", TransactionClass.EQUITY_SWAP),
        ("U", TransactionClass.TENDER_OF_SHARES),
    ],
)
def test_code_classification(code, expected):
    cls, flags = classify_transaction_code(code)
    assert cls is expected
    assert flags == ()


def test_only_p_and_s_are_open_market_discretionary():
    assert is_open_market_discretionary(TransactionClass.OPEN_MARKET_PURCHASE)
    assert is_open_market_discretionary(TransactionClass.OPEN_MARKET_SALE)
    for c in (
        TransactionClass.GRANT_OR_AWARD, TransactionClass.EXERCISE_OR_CONVERSION,
        TransactionClass.GIFT, TransactionClass.TAX_WITHHOLDING,
        TransactionClass.SALE_OR_DISPOSITION_TO_ISSUER, TransactionClass.PLAN_DISCRETIONARY,
    ):
        assert not is_open_market_discretionary(c)


def test_unknown_code_is_unclassified_and_flagged():
    cls, flags = classify_transaction_code("Q")
    assert cls is TransactionClass.UNCLASSIFIED
    assert "unknown_transaction_code" in flags


def test_missing_code_is_unclassified():
    cls, flags = classify_transaction_code(None)
    assert cls is TransactionClass.UNCLASSIFIED
    assert "unknown_transaction_code" in flags


def test_holding_row_is_initial_holding():
    cls, flags = classify_transaction_code(None, is_holding=True)
    assert cls is TransactionClass.INITIAL_HOLDING
    assert "initial_holding" in flags


def test_lowercase_and_whitespace_tolerated():
    assert classify_transaction_code("  p ")[0] is TransactionClass.OPEN_MARKET_PURCHASE
