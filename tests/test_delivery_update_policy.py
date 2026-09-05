"""
tests/test_delivery_update_policy.py
-----------------------------------
Task 96F -- Phase 14: when an already-sent alert may be updated.
"""
from __future__ import annotations

from talonx_ingest.intelligence.delivery.update_policy import (
    DECISION_NEW,
    DECISION_SUPPRESS_DUPLICATE,
    DECISION_SUPPRESS_NOOP,
    DECISION_UPDATE,
    classify_update,
)

_SENT = (
    "🟡 MEDIUM INFORMATION SIGNIFICANCE\nAAPL\n\n"
    "Quarterly report (Form 10-Q)\nAccepted: 2026-09-03 14:00 UTC\n\n"
    "What changed:\n• Risk Factors changed above the material threshold — change magnitude 20%\n\n"
    "ℹ️ Information, not advice."
)


def test_new_when_nothing_sent():
    d = classify_update(prior_sent_text=None, prior_band=None, new_text="x", new_band="LOW")
    assert d.decision == DECISION_NEW and d.should_enqueue


def test_duplicate_suppressed_by_hash():
    d = classify_update(
        prior_sent_text=_SENT, prior_band="MEDIUM", new_text=_SENT, new_band="MEDIUM",
        prior_content_hash="h1", new_content_hash="h1",
    )
    assert d.decision == DECISION_SUPPRESS_DUPLICATE and not d.should_enqueue


def test_band_change_is_an_update():
    d = classify_update(
        prior_sent_text=_SENT, prior_band="MEDIUM",
        new_text=_SENT.replace("MEDIUM", "HIGH"), new_band="HIGH",
        prior_content_hash="h1", new_content_hash="h2",
    )
    assert d.decision == DECISION_UPDATE and "band changed" in d.reason


def test_material_fact_added_is_an_update():
    new = _SENT.replace(
        "change magnitude 20%",
        "change magnitude 20%\n• Reported revenue YoY change +24%",
    )
    d = classify_update(
        prior_sent_text=_SENT, prior_band="MEDIUM", new_text=new, new_band="MEDIUM",
        prior_content_hash="h1", new_content_hash="h2",
    )
    assert d.decision == DECISION_UPDATE


def test_cosmetic_change_is_noop():
    new = _SENT.replace("Accepted: 2026-09-03 14:00 UTC", "Accepted: 2026-09-03 14:00 UTC ")
    d = classify_update(
        prior_sent_text=_SENT, prior_band="MEDIUM", new_text=new + "\n(minor)", new_band="MEDIUM",
        prior_content_hash="h1", new_content_hash="h2",
    )
    assert d.decision == DECISION_SUPPRESS_NOOP and not d.should_enqueue
