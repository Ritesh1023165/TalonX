"""
tests/test_significance_language_safety.py
-----------------------------------------
Task 96E -- Phase 15 / 25: no predictive / directional / advice language
in machine-generated significance labels.
"""
from __future__ import annotations

import pytest

from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.significance import evaluate_significance
from talonx_ingest.intelligence.significance.language_safety import (
    PredictiveLanguageError,
    assert_clean,
    assert_clean_significance,
    scan_significance,
    scan_text,
)
from _significance_helpers import NOW, mk_comparison, mk_event


@pytest.mark.parametrize(
    "bad",
    [
        "this is a buy",
        "bearish disclosure",
        "expected return is high",
        "strong conviction",
        "insider alpha detected",
        "smart money is moving",
        "act now",
        "this is market-moving",
        "price target raised",
    ],
)
def test_prohibited_phrases_are_caught(bad):
    assert scan_text(bad)
    with pytest.raises(PredictiveLanguageError):
        assert_clean(bad)


@pytest.mark.parametrize(
    "ok",
    [
        "Risk Factors rewrite in the top decile of history (change magnitude 70%)",
        "3 distinct insiders reported open-market sellers within 30 days",
        "very large reported revenue YOY change (magnitude 55%; size only, not direction)",
        "this company is pinned on your watchlist (user priority, not market significance)",
        "count of frozen risk-term lexicon entries rose by 20 vs the prior filing",
        "Form 10-K annual report",
    ],
)
def test_allowed_descriptive_phrases_pass(ok):
    assert scan_text(ok) == []
    assert_clean(ok)


def test_scan_significance_on_a_rich_real_object():
    ev = mk_event(event_type=EventType.ANNUAL_FILING, form_type="10-K", items=("1.05",))
    fc = mk_comparison(
        event=ev, rf_diff=0.7, mdna_diff=0.3, whole_diff=0.4,
        revenue_rel_delta=-0.6, eps_rel_delta=0.9, neg_kw_delta=25,
    )
    sig = evaluate_significance(
        ev, comparison=fc, on_watchlist=True, pinned=True, simultaneous_type_count=3, now=NOW
    )
    assert scan_significance(sig) == []
    assert_clean_significance(sig)  # does not raise


def test_assert_clean_significance_raises_on_injected_bad_label():
    ev = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",))
    sig = evaluate_significance(ev, now=NOW)
    tampered = sig.model_copy(update={"band_caps_applied": ("bullish outlook confirmed",)})
    with pytest.raises(PredictiveLanguageError):
        assert_clean_significance(tampered)
