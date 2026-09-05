"""
tests/test_significance_domain.py
--------------------------------
Task 96E -- the immutable output model + its predictive-language guards.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from talonx_ingest.intelligence.domain import SignificanceBand
from talonx_ingest.intelligence.significance.domain import (
    InformationSignificance,
    SignificanceComponent,
    SignificanceReason,
)
from talonx_ingest.intelligence.significance.identity import significance_id
from _significance_helpers import NOW


def _reason(code="EVENT_TYPE_BASE", points=2):
    return SignificanceReason(
        code=code, description="a 10-K was filed", points=points, component="event_type_base"
    )


def test_models_are_frozen():
    r = _reason()
    with pytest.raises(ValidationError):
        r.points = 5


def test_component_rejects_predictive_code():
    for bad in ("buy_signal", "alpha_score", "expected_return_component", "bullish_flag"):
        with pytest.raises(ValidationError):
            SignificanceComponent(
                code=bad, points=1, raw_points=1, substantive=True
            )


def test_reason_rejects_predictive_code():
    with pytest.raises(ValidationError):
        SignificanceReason(
            code="CONVICTION_HIGH", description="x", points=1, component="c"
        )


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        SignificanceReason(
            code="OK", description="x", points=1, component="c", direction="up"
        )


def test_points_check_and_reason_strings():
    sig = InformationSignificance(
        significance_id=significance_id("SEC:x:EARNINGS_RESULTS"),
        event_id="SEC:x:EARNINGS_RESULTS",
        symbol="aapl",
        score=3,
        band=SignificanceBand.MEDIUM,
        raw_score=3,
        reasons=(_reason(points=2), _reason(code="RECENT_ARRIVAL", points=1)),
        components=(),
        input_fingerprint="deadbeef",
        evaluated_at_utc=NOW,
    )
    assert sig.symbol == "AAPL"
    assert sig.points_check() is True
    assert sig.reason_strings() == ("a 10-K was filed", "a 10-K was filed")


def test_points_check_false_when_reasons_do_not_sum():
    sig = InformationSignificance(
        significance_id="SIG:x:information-significance-v1",
        event_id="x",
        symbol="AAPL",
        score=5,
        band=SignificanceBand.HIGH,
        raw_score=5,
        reasons=(_reason(points=2),),
        components=(),
        input_fingerprint="x",
        evaluated_at_utc=NOW,
    )
    assert sig.points_check() is False
