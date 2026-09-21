"""
tests/test_insider_identity.py
------------------------------
Task 96D -- deterministic content-addressed transaction identity; bulk and
XML routes converge; genuine duplicates get an ordinal.
"""
from __future__ import annotations

from datetime import date

from talonx_ingest.intelligence.insider.identity import (
    insider_filing_id,
    transaction_id_base,
    with_ordinal,
)
from talonx_ingest.intelligence.insider.normalize import resolve_ordinals


def _base(**kw):
    d = dict(
        accession="0001214156-26-000005",
        owner_cik="0001214156",
        transaction_date=date(2026, 2, 10),
        transaction_code="S",
        security_title="Common Stock",
        shares=5000.0,
        price=232.5,
        acquired_disposed="D",
        ownership_nature="D",
        is_derivative=False,
    )
    d.update(kw)
    return transaction_id_base(**d)


def test_deterministic_and_stable():
    assert _base() == _base()
    assert _base().startswith("F4TX:0001214156-26-000005:")


def test_accession_normalised():
    assert _base(accession="000121415626000005") == _base(accession="0001214156-26-000005")


def test_field_changes_change_the_id():
    assert _base() != _base(shares=5001.0)
    assert _base() != _base(transaction_code="P")
    assert _base() != _base(price=232.6)
    assert _base() != _base(transaction_date=date(2026, 2, 11))


def test_bulk_and_xml_same_transaction_converge():
    # bulk gives "5000" as a string, XML gives "5000" -- both float 5000.0
    from_bulk = _base(shares=float("5000"), price=float("232.50"))
    from_xml = _base(shares=5000.0, price=232.5)
    assert from_bulk == from_xml


def test_with_ordinal():
    b = _base()
    assert with_ordinal(b, 0) == b
    assert with_ordinal(b, 1) == f"{b}#1"


def test_resolve_ordinals_for_identical_rows():
    ids = ["A", "A", "B", "A"]
    assert resolve_ordinals(ids) == [0, 1, 0, 2]


def test_insider_filing_id_is_canonical_accession():
    assert insider_filing_id("000121415626000005") == "0001214156-26-000005"
