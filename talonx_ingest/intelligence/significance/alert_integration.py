"""
talonx_ingest.intelligence.significance.alert_integration
=======================================================
Fold an evaluated ``InformationSignificance`` into a Task 96A
``AlertCard`` — the band, the ordered reason strings, a compact reason
summary, and the evidence references.

No rendering (that is Task 96F Telegram / 96G dashboard). No trade
direction. The card's own ``summary_fields`` predictive-key guard still
applies; the keys written here are plainly factual.
"""
from __future__ import annotations

from talonx_ingest.intelligence.domain import AlertCard
from talonx_ingest.intelligence.significance.domain import InformationSignificance
from talonx_ingest.intelligence.significance.language_safety import (
    assert_clean_significance,
)


def apply_significance(
    card: AlertCard,
    sig: InformationSignificance,
    *,
    max_reasons: int = 6,
) -> AlertCard:
    """Return a copy of ``card`` with the significance band + reasons set.

    Raises ``PredictiveLanguageError`` if the significance carries any
    prohibited language (fail closed — a bad label must never reach a
    delivery surface)."""
    if sig.event_id != card.event_id:
        raise ValueError(
            f"significance.event_id {sig.event_id!r} != card.event_id {card.event_id!r}"
        )
    assert_clean_significance(sig)

    reason_strings = tuple(sig.reason_strings()[:max_reasons])

    summary = dict(card.summary_fields)
    summary["information_significance"] = sig.band.value
    summary["information_significance_score"] = str(sig.score)
    summary["significance_ruleset"] = sig.ruleset_version
    if sig.band_caps_applied:
        summary["significance_notes"] = "; ".join(sig.band_caps_applied)

    return card.model_copy(
        update={
            "significance": sig.band,
            "significance_reasons": reason_strings,
            "summary_fields": summary,
        }
    )
