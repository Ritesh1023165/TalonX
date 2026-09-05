"""
tests/test_comparison_xbrl.py
-----------------------------
Task 96C -- first-filed XBRL YoY/QoQ deltas; restatement leakage control.
"""
from __future__ import annotations

from datetime import date

from talonx_ingest.intelligence.comparison.domain import XbrlPeriodComparison
from talonx_ingest.intelligence.comparison.xbrl import compute_xbrl_changes

_REV_KEY = ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax")
_EPS_KEY = ("us-gaap", "EarningsPerShareDiluted")


def _rev_json(rows):
    return {"units": {"USD": rows}}


def _all_none():
    from talonx_ingest.intelligence.comparison.config import XBRL_FIELDS

    d = {}
    for spec in XBRL_FIELDS:
        for k in spec["concepts"]:
            d[k] = None
    return d


def test_first_filed_value_used_not_restatement():
    cd = _all_none()
    cd[_REV_KEY] = _rev_json(
        [
            {"start": "2024-10-01", "end": "2024-12-31", "val": 100, "filed": "2025-02-01", "accn": "orig"},
            {"start": "2024-10-01", "end": "2024-12-31", "val": 999, "filed": "2025-12-01", "accn": "restated"},
            {"start": "2025-10-01", "end": "2025-12-31", "val": 130, "filed": "2026-02-01", "accn": "cur"},
        ]
    )
    changes = compute_xbrl_changes(current_period_end=date(2025, 12, 31), concept_data=cd, base_form="10-Q")
    yoy = next(c for c in changes if c.field == "revenue" and c.comparison is XbrlPeriodComparison.YOY)
    assert yoy.status == "FOUND"
    assert yoy.prior_value == 100.0            # NOT 999
    assert yoy.prior_filed_accession == "orig"
    assert yoy.current_value == 130.0
    assert yoy.relative_delta == 0.3


def test_missing_concept_reported_not_fabricated():
    changes = compute_xbrl_changes(
        current_period_end=date(2025, 12, 31), concept_data=_all_none(), base_form="10-Q"
    )
    assert changes
    assert all(c.status == "CONCEPT_MISSING" for c in changes)
    assert all("xbrl_concept_missing" in c.quality_flags for c in changes)


def test_no_prior_period():
    cd = _all_none()
    cd[_EPS_KEY] = _rev_json_units_eps(
        [{"start": "2025-10-01", "end": "2025-12-31", "val": 1.3, "filed": "2026-02-01", "accn": "cur"}]
    )
    changes = compute_xbrl_changes(current_period_end=date(2025, 12, 31), concept_data=cd, base_form="10-Q")
    eps_yoy = next(c for c in changes if c.field == "eps_diluted" and c.comparison is XbrlPeriodComparison.YOY)
    assert eps_yoy.status == "NO_PRIOR"
    assert eps_yoy.current_value == 1.3
    assert eps_yoy.prior_value is None


def test_qoq_only_for_10q_not_10k():
    cd = _all_none()
    cd[_REV_KEY] = _rev_json(
        [
            {"start": "2024-10-01", "end": "2024-12-31", "val": 100, "filed": "2025-02-01", "accn": "a"},
            {"start": "2025-10-01", "end": "2025-12-31", "val": 130, "filed": "2026-02-01", "accn": "b"},
        ]
    )
    q = compute_xbrl_changes(current_period_end=date(2025, 12, 31), concept_data=cd, base_form="10-Q")
    k = compute_xbrl_changes(current_period_end=date(2025, 12, 31), concept_data=cd, base_form="10-K")
    assert {c.comparison for c in q if c.field == "revenue"} == {
        XbrlPeriodComparison.YOY, XbrlPeriodComparison.QOQ
    }
    assert {c.comparison for c in k if c.field == "revenue"} == {XbrlPeriodComparison.YOY}


def test_no_current_period_end_is_unavailable():
    changes = compute_xbrl_changes(current_period_end=None, concept_data=_all_none(), base_form="10-Q")
    assert len(changes) == 1
    assert changes[0].status == "UNAVAILABLE"
    assert "xbrl_unavailable" in changes[0].quality_flags


def test_deterministic():
    cd = _all_none()
    cd[_REV_KEY] = _rev_json(
        [
            {"start": "2024-10-01", "end": "2024-12-31", "val": 100, "filed": "2025-02-01", "accn": "a"},
            {"start": "2025-10-01", "end": "2025-12-31", "val": 130, "filed": "2026-02-01", "accn": "b"},
        ]
    )
    a = compute_xbrl_changes(current_period_end=date(2025, 12, 31), concept_data=cd, base_form="10-Q")
    b = compute_xbrl_changes(current_period_end=date(2025, 12, 31), concept_data=cd, base_form="10-Q")
    assert a == b


def _rev_json_units_eps(rows):
    return {"units": {"USD/shares": rows}}
