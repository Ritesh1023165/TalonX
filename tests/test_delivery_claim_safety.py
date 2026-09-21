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


# ---------------------------------------------------------------------
# Task 137: a company's own factual, SEC-sourced name that happens to
# contain "buy"/"sell" (e.g. "Best Buy") must not be misclassified as
# predictive/advice language -- the exact, confirmed, deterministic
# false positive behind all 35 real FAILED_RETRYABLE BBY rows.
# ---------------------------------------------------------------------

def test_company_name_containing_bare_buy_is_not_flagged_when_given():
    text = "BEST BUY CO INC filed a Form 8-K today."
    assert scan_rendered(text) == ["token:buy"]           # without context: the real prior bug
    assert scan_rendered(text, company_name="BEST BUY CO INC") == []
    assert_clean(text, company_name="BEST BUY CO INC")    # does not raise


def test_company_name_exemption_does_not_weaken_real_predictive_detection():
    # a genuine predictive PHRASE touching the same word is still caught,
    # even with the company name present.
    text = "BEST BUY CO INC is a strong buy right now."
    v = scan_rendered(text, company_name="BEST BUY CO INC")
    assert "phrase:strong buy" in v


def test_company_name_exemption_does_not_hide_an_unrelated_bare_buy():
    # a bare "buy" that is NOT part of the company name's own text is
    # still flagged -- the exemption is scoped to the exact name string,
    # not a blanket "buy is fine somewhere in this card" relaxation.
    text = "insiders should buy more shares of XYZ based on this filing."
    v = scan_rendered(text, company_name="BEST BUY CO INC")
    assert "token:buy" in v


def test_short_or_missing_company_name_is_ignored():
    # a too-short/degenerate company_name (e.g. a data-quality gap) must
    # not accidentally exempt unrelated text via a coincidental overlap.
    assert scan_rendered("time to buy", company_name="") == ["token:buy"]
    assert scan_rendered("time to buy", company_name="A") == ["token:buy"]
    assert scan_rendered("time to buy", company_name=None) == ["token:buy"]


def test_enqueue_card_passes_the_events_company_name_through(monkeypatch):
    """End-to-end through the real call site: enqueue_card must pass the
    card's own company_name into assert_clean, not just scan_rendered
    directly -- the actual path that produced the real BBY rejections."""
    import talonx_ingest.intelligence.delivery.pipeline as dp

    captured = {}
    real_assert_clean = dp.assert_clean

    def _spy(text, *, company_name=None):
        captured["company_name"] = company_name
        return real_assert_clean(text, company_name=company_name)

    monkeypatch.setattr(dp, "assert_clean", _spy)

    from _delivery_helpers import make_card
    from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox

    card, _ = make_card(symbol="BBY", company="BEST BUY CO INC")
    ob = DeliveryOutbox(":memory:")
    dp.enqueue_card(card, outbox=ob)
    assert captured["company_name"] == "BEST BUY CO INC"
    ob.close()
