"""
tests/test_delivery_claim_safety.py
-----------------------------------
Task 96F -- Phase 12: context-aware claim safety over rendered text.
A factual SEC "sale"/"purchase" must pass; a predictive construct must not.
"""
from __future__ import annotations

import pytest

from talonx_ingest.intelligence.delivery.claim_safety import (
    PredictiveLanguageError,
    assert_clean,
    scan_rendered,
)


@pytest.mark.parametrize(
    "bad",
    [
        "This is a buy signal.",
        "strong sell here",
        "bullish on the quarter",
        "bearish disclosure",
        "expected return is positive",
        "price target raised",
        "high conviction idea",
        "smart money is buying",
        "insider alpha detected",
        "likely to rise next week",
        "the stock will move higher",
        "should buy the dip",
        "outperform rating",
    ],
)
def test_predictive_language_is_rejected(bad):
    assert scan_rendered(bad)
    with pytest.raises(PredictiveLanguageError):
        assert_clean(bad)


@pytest.mark.parametrize(
    "ok",
    [
        "CEO reported an open-market sale of $2.3m",
        "3 insiders reported open-market sales within 30 days",
        "Largest single open-market transaction: $4.20m",
        "40,000 shares were sold by the CFO on 2026-08-14",
        "8-K Item 1.01 — Buy-Sell Agreement executed",
        "Stock Purchase Agreement filed as Exhibit 10.1",
        "Reported revenue YoY change +24%",
        "Risk Factors changed above the material threshold — change magnitude 41%",
        "Information, not advice. TalonX makes no prediction about future price or returns.",
        "Regulation FD disclosure (8-K Item 7.01)",
        "Insiders (30d): 2 reported open-market purchase(s); 1 reported open-market sale(s)",
    ],
)
def test_factual_transaction_wording_is_allowed(ok):
    assert scan_rendered(ok) == [], ok
    assert_clean(ok)


def test_bare_buy_sell_without_context_flagged():
    assert any("buy" in v or "sell" in v for v in scan_rendered("time to buy"))
    assert scan_rendered("just sell") != []


def test_empty_text_is_clean():
    assert scan_rendered("") == []
    assert scan_rendered(None) == []
