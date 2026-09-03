"""
tests/test_intelligence_taxonomy.py
-----------------------------------
Task 96A -- deterministic form + items -> event_type classification.
"""
from __future__ import annotations

import pytest

from talonx_ingest.intelligence.domain import DataQualityFlag, EventType
from talonx_ingest.intelligence.taxonomy import (
    base_form,
    classify_filing,
    is_amendment,
    normalize_items,
)


@pytest.mark.parametrize(
    "item,expected",
    [
        ("2.02", EventType.EARNINGS_RESULTS),
        ("1.01", EventType.MATERIAL_AGREEMENT),
        ("1.02", EventType.AGREEMENT_TERMINATED),
        ("2.01", EventType.ACQUISITION_DISPOSITION),
        ("2.03", EventType.DEBT_FINANCING),
        ("2.05", EventType.RESTRUCTURING),
        ("5.02", EventType.EXECUTIVE_CHANGE),
        ("7.01", EventType.REGULATION_FD),
        ("8.01", EventType.OTHER_MATERIAL_EVENT),
    ],
)
def test_single_item_8k_maps_to_expected_type(item, expected):
    res = classify_filing("8-K", item)
    assert res.event_types == (expected,)
    assert res.classifications[0].triggering_items == (item,)


def test_item_9_01_alone_is_unclassified_not_dropped():
    res = classify_filing("8-K", "9.01")
    assert res.event_types == (EventType.UNCLASSIFIED_8K,)
    assert "9.01" in res.all_items


def test_multi_item_8k_yields_one_event_per_distinct_type():
    res = classify_filing("8-K", "5.02,1.01,9.01")
    assert set(res.event_types) == {EventType.EXECUTIVE_CHANGE, EventType.MATERIAL_AGREEMENT}
    assert DataQualityFlag.MULTI_ITEM_FILING.value in res.flags
    assert res.all_items == ("5.02", "1.01", "9.01")  # every raw item preserved


def test_earnings_plus_regfd_are_two_events():
    res = classify_filing("8-K", "2.02,7.01,9.01")
    assert set(res.event_types) == {EventType.EARNINGS_RESULTS, EventType.REGULATION_FD}


def test_10q_and_10k_classification():
    assert classify_filing("10-Q", "").event_types == (EventType.QUARTERLY_FILING,)
    assert classify_filing("10-K", None).event_types == (EventType.ANNUAL_FILING,)


def test_amendment_of_periodic_flags_amendment_but_keeps_type():
    res = classify_filing("10-Q/A", "")
    assert res.event_types == (EventType.QUARTERLY_FILING,)
    assert res.is_amendment is True
    assert DataQualityFlag.AMENDMENT.value in res.flags


def test_8ka_with_recognised_item_still_classifies_by_item():
    res = classify_filing("8-K/A", "8.01")
    assert res.event_types == (EventType.OTHER_MATERIAL_EVENT,)
    assert res.is_amendment is True
    assert DataQualityFlag.AMENDMENT.value in res.flags


def test_8ka_with_no_recognised_item_is_filing_amendment():
    res = classify_filing("8-K/A", "9.01")
    assert res.event_types == (EventType.FILING_AMENDMENT,)


def test_8k_with_no_items_flags_missing_item_metadata():
    res = classify_filing("8-K", "")
    assert res.event_types == (EventType.UNCLASSIFIED_8K,)
    assert DataQualityFlag.MISSING_ITEM_METADATA.value in res.flags


def test_8k_with_unknown_item_flags_non_standard_code():
    res = classify_filing("8-K", "9.99")
    assert res.event_types == (EventType.UNCLASSIFIED_8K,)
    assert DataQualityFlag.NON_STANDARD_ITEM_CODE.value in res.flags


def test_unsupported_form():
    res = classify_filing("SC 13D", "")
    assert res.event_types == (EventType.UNSUPPORTED_FORM,)
    assert DataQualityFlag.UNSUPPORTED_FORM.value in res.flags


def test_insider_form_reserved_type():
    assert classify_filing("4", "").event_types == (EventType.INSIDER_TRANSACTION,)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2.02,9.01", ("2.02", "9.01")),
        ("Item 2.02, Item 9.01", ("2.02", "9.01")),
        (["5.02", "1.01"], ("5.02", "1.01")),
        ("2.02 2.02", ("2.02",)),  # de-duplicated
        (None, ()),
        ("", ()),
    ],
)
def test_normalize_items(raw, expected):
    assert normalize_items(raw) == expected


def test_is_amendment_and_base_form():
    assert is_amendment("8-K/A") is True
    assert is_amendment("8-K") is False
    assert base_form("10-q/a") == "10-Q"


def test_classification_is_deterministic():
    a = classify_filing("8-K", "2.02,7.01,9.01")
    b = classify_filing("8-K", "2.02,7.01,9.01")
    assert a == b
