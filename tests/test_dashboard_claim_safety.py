"""
tests/test_dashboard_claim_safety.py
------------------------------------
Task 96G -- Phase 20: claim safety over rendered dashboard text/pages.
"""
from __future__ import annotations

import pytest

from talonx_ingest.intelligence.dashboard.claim_safety import (
    PredictiveLanguageError,
    assert_clean_page,
    scan_page,
    scan_text,
)
from talonx_ingest.intelligence.dashboard.config import CLAIM_POLICY_SHORT, DISCLAIMER_SHORT


@pytest.mark.parametrize(
    "bad",
    [
        "this is a buy opportunity",
        "bearish on the quarter",
        "expected decline next week",
        "likely winner",
        "top pick for the month",
        "attractive entry point",
        "strong sell",
        "high conviction idea",
    ],
)
def test_predictive_phrases_rejected(bad):
    assert scan_text(bad)
    with pytest.raises(PredictiveLanguageError):
        assert_clean_page(f"<p>{bad}</p>")


@pytest.mark.parametrize(
    "ok",
    [
        "CEO reported an open-market sale of $2.3m",
        "purchase of 40,000 shares",
        "Revenue decreased 12% year over year",
        "Risk Factors changed above the frozen material threshold",
        "8-K Item 1.01 — Buy-Sell Agreement",
        "3 distinct insiders reported open-market sales within 30 days",
    ],
)
def test_factual_wording_allowed(ok):
    assert scan_text(ok) == []
    assert_clean_page(f"<article>{ok}</article>")


def test_frozen_policy_text_is_allow_listed_in_page_scan():
    # the disclaimer legitimately enumerates prohibited words ("...buy or sell...")
    page = f"<footer>{DISCLAIMER_SHORT}<br>{CLAIM_POLICY_SHORT}</footer>"
    assert scan_page(page) == []
    assert_clean_page(page)                       # does not raise


def test_markup_is_stripped_before_scan():
    # a css class name or attribute must not trip the scanner
    assert scan_page('<div class="band-low" data-x="sell">Quarterly report</div>') == []
