"""
tests/test_insider_language_safety.py
-------------------------------------
Task 96D -- machine-generated insider labels carry no predictive /
directional / "insider alpha" language.
"""
from __future__ import annotations

import pytest

from talonx_ingest.intelligence.insider.language_safety import (
    PredictiveLanguageError,
    assert_clean,
    scan_text,
)


@pytest.mark.parametrize(
    "bad",
    [
        "insider alpha detected",
        "smart money is accumulating",
        "conviction buy by the CEO",
        "bullish cluster of purchases",
        "bearish insider signal",
        "informative selling ahead of results",
        "expected return from following insiders",
        "this is a sell signal",
    ],
)
def test_prohibited_phrases(bad):
    assert scan_text(bad)
    with pytest.raises(PredictiveLanguageError):
        assert_clean(bad)


@pytest.mark.parametrize(
    "ok",
    [
        "CEO reported an open-market purchase",
        "Three insiders reported open-market sales over 20 calendar days",
        "Net reported open-market activity: -$4.2m",
        "Transaction code S",
        "Ownership is indirect",
        "MULTIPLE_OPEN_MARKET_SELLERS",
        "1 of 3 open-market transactions had a usable price",
        "CFO open-market sale reported (5,000 shares)",
    ],
)
def test_descriptive_labels_pass(ok):
    assert scan_text(ok) == []
    assert_clean(ok)


def test_none_and_empty_clean():
    assert scan_text(None) == []
    assert_clean(None, "", "   ")
