"""
tests/test_significance_alert_integration.py
-------------------------------------------
Task 96E -- fold an InformationSignificance into a Task 96A AlertCard.
"""
from __future__ import annotations

import pytest

from talonx_ingest.intelligence.domain import EventType, SignificanceBand
from talonx_ingest.intelligence.pipeline import build_alert_card, build_events_from_filing
from talonx_ingest.intelligence.edgar_normalize import NormalizedFiling
from talonx_ingest.intelligence.significance import evaluate_significance
from talonx_ingest.intelligence.significance.alert_integration import apply_significance
from talonx_ingest.intelligence.significance.language_safety import PredictiveLanguageError
from _significance_helpers import NOW, mk_comparison, mk_event


def _card_for(ev):
    return build_alert_card(ev)


def test_apply_significance_sets_band_and_reasons():
    ev = mk_event(event_type=EventType.QUARTERLY_FILING, form_type="10-Q", items=(), age_hours=1)
    sig = evaluate_significance(ev, comparison=mk_comparison(event=ev, rf_diff=0.7), now=NOW)
    card = apply_significance(_card_for(ev), sig)

    assert card.significance is sig.band
    assert card.significance_reasons == sig.reason_strings()[:6]
    assert card.summary_fields["information_significance"] == sig.band.value
    assert card.summary_fields["information_significance_score"] == str(sig.score)
    assert card.summary_fields["significance_ruleset"] == sig.ruleset_version
    # card's own predictive-key guard still holds
    assert card.disclaimer.startswith("Information, not advice")


def test_event_id_mismatch_is_rejected():
    ev = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",))
    other = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",), accession="0000320193-26-999999")
    sig = evaluate_significance(other, now=NOW)
    with pytest.raises(ValueError):
        apply_significance(_card_for(ev), sig)


def test_bad_language_fails_closed():
    ev = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",))
    sig = evaluate_significance(ev, now=NOW).model_copy(
        update={"band_caps_applied": ("this is a strong buy",)}
    )
    with pytest.raises(PredictiveLanguageError):
        apply_significance(_card_for(ev), sig)


def test_caps_note_is_surfaced():
    ev = mk_event(event_type=EventType.RESTRUCTURING, items=("2.05",), age_hours=1)
    sig = evaluate_significance(ev, pinned=True, simultaneous_type_count=2, now=NOW)
    assert sig.band_caps_applied  # CRITICAL held to HIGH
    card = apply_significance(_card_for(ev), sig)
    assert "significance_notes" in card.summary_fields
