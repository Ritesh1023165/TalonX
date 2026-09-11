"""
talonx_ingest.intelligence.delivery.update_policy
================================================
When may an already-sent alert be re-sent as an UPDATE, and when must a
re-render be suppressed as noise? (``TELEGRAM_UPDATE_POLICY.md``)

Deterministic. Keyed on the rendered ``content_hash`` and the significance
band — never on wall-clock time, never on a watchlist re-ordering, never
on a harmless formatting tweak (a formatting-only change is a
``render_version`` bump, which produces a *different* ``delivery_id`` and
is therefore a separate first-time delivery, not an update to this one).
"""
from __future__ import annotations

from dataclasses import dataclass

DECISION_NEW = "NEW"                       # no prior delivery for this delivery_id
DECISION_UPDATE = "UPDATE"                 # prior SENT; material change -> re-send as UPDATE
DECISION_SUPPRESS_DUPLICATE = "SUPPRESS_DUPLICATE"   # identical to what was sent
DECISION_SUPPRESS_NOOP = "SUPPRESS_NOOP"   # changed, but not materially enough to re-notify


@dataclass(frozen=True)
class UpdateDecision:
    decision: str
    reason: str

    @property
    def should_enqueue(self) -> bool:
        return self.decision in (DECISION_NEW, DECISION_UPDATE)


#: substantive fact prefixes — a change in one of these lines is a real
#: content change worth an UPDATE. (The rendered body is line-based.)
_MATERIAL_MARKERS = (
    "changed above the material threshold",
    "new multi-sentence passage",
    "Reported ",
    "distinct insiders reported",
    "Largest single open-market transaction",
    "Risk-term lexicon count change",
    "Data limitations:",
    "Source feed was",
)


def _material_lines(text: str) -> frozenset[str]:
    return frozenset(
        ln.strip()
        for ln in text.splitlines()
        if any(m in ln for m in _MATERIAL_MARKERS)
    )


def classify_update(
    *,
    prior_sent_text: str | None,
    prior_band: str | None,
    new_text: str,
    new_band: str | None,
    prior_content_hash: str | None = None,
    new_content_hash: str | None = None,
) -> UpdateDecision:
    """``prior_sent_text`` is ``None`` when nothing was ever sent for this
    ``delivery_id``."""
    if prior_sent_text is None:
        return UpdateDecision(DECISION_NEW, "no prior delivery")

    if prior_content_hash is not None and new_content_hash is not None:
        if prior_content_hash == new_content_hash:
            return UpdateDecision(DECISION_SUPPRESS_DUPLICATE, "rendered text unchanged")
    elif prior_sent_text == new_text:
        return UpdateDecision(DECISION_SUPPRESS_DUPLICATE, "rendered text unchanged")

    if new_band != prior_band:
        return UpdateDecision(
            DECISION_UPDATE, f"significance band changed {prior_band} -> {new_band}"
        )

    added = _material_lines(new_text) - _material_lines(prior_sent_text)
    removed = _material_lines(prior_sent_text) - _material_lines(new_text)
    if added or removed:
        return UpdateDecision(
            DECISION_UPDATE,
            f"material fact lines changed (+{len(added)}/-{len(removed)})",
        )

    return UpdateDecision(
        DECISION_SUPPRESS_NOOP, "text differs only in non-material lines"
    )
