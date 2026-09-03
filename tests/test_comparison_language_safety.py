"""
tests/test_comparison_language_safety.py
----------------------------------------
Task 96C -- machine-generated comparison labels must carry no predictive /
directional language.
"""
from __future__ import annotations

import pytest

from talonx_ingest.intelligence.comparison.language_safety import (
    PredictiveLanguageError,
    assert_clean,
    scan_text,
)


@pytest.mark.parametrize(
    "bad",
    [
        "this is a bullish change",
        "time to sell",
        "expected return is negative",
        "price target lowered",
        "the outlook has deteriorated",
        "likely to underperform peers",
        "a clear red flag for investors",
        "this looks undervalued",
        "we recommend caution",
        "bad news in the risk factors",
    ],
)
def test_prohibited_phrases_detected(bad):
    assert scan_text(bad)
    with pytest.raises(PredictiveLanguageError):
        assert_clean(bad)


@pytest.mark.parametrize(
    "ok",
    [
        "Risk Factors section changed materially (diff ratio 0.41)",
        "12 new passages of at least 40 words detected in MD&A",
        "negative-risk term count increased by 6",
        "Revenue changed +18% year over year (first-filed XBRL)",
        "Liquidity and Capital Resources section length increased 22%",
        "prior comparable filing: 0000320193-25-000040 (10-Q)",
        "section not found in current filing",
    ],
)
def test_descriptive_labels_pass(ok):
    assert scan_text(ok) == []
    assert_clean(ok)  # no raise


def test_none_and_empty_are_clean():
    assert scan_text(None) == []
    assert_clean(None, "", "   ")
