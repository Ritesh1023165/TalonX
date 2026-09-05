"""
talonx_ingest.intelligence.comparison.language_safety
====================================================
Guard against predictive / directional / sentiment language in
machine-generated comparison labels and notes
(``PRODUCT_CLAIM_POLICY.md`` / ``RISK_LANGUAGE_POLICY.md``).

Scope: strings the ENGINE generates -- evidence notes, prior-match
reasons, ``what_changed`` label/summary fields. **Not** applied to raw
extracted passage text (that is verbatim filing bytes) or to keyword
lexicon terms (data values like "decline in demand").
"""
from __future__ import annotations

import re

__all__ = [
    "PROHIBITED_TERMS",
    "PredictiveLanguageError",
    "scan_text",
    "assert_clean",
    "scan_comparison",
]

# Prohibited in any machine-generated label. Kept lower-case; matched
# case-insensitively with alnum boundaries so "sell" does not fire inside
# "sells" ... actually it should also catch "sells" -> boundary on the
# LEFT only for verb forms; keep simple: whole-token match.
PROHIBITED_TERMS: frozenset[str] = frozenset(
    {
        "buy", "sell", "hold", "bullish", "bearish", "avoid", "overweight",
        "underweight", "outperform", "underperform", "positive signal",
        "negative signal", "risk-off", "risk-on", "expected return",
        "price target", "target price", "outlook", "forecast", "conviction",
        "opportunity score", "should buy", "should sell", "likely to fall",
        "likely to rise", "likely to decline", "likely to underperform",
        "likely to outperform", "probability of gain", "probability of loss",
        "upside", "downside", "undervalued", "overvalued", "recommend",
        "recommendation", "good news", "bad news", "red flag", "warning sign",
    }
)

_PATTERNS: dict[str, re.Pattern] = {
    t: re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", re.IGNORECASE)
    for t in PROHIBITED_TERMS
}


class PredictiveLanguageError(ValueError):
    """Raised when a machine-generated label contains prohibited language."""


def scan_text(text: str | None) -> list[str]:
    if not text:
        return []
    return sorted(t for t, pat in _PATTERNS.items() if pat.search(text))


def assert_clean(*strings: str | None) -> None:
    hits: set[str] = set()
    for s in strings:
        hits.update(scan_text(s))
    if hits:
        raise PredictiveLanguageError(
            f"machine-generated label contains prohibited term(s): {sorted(hits)}"
        )


def scan_comparison(comparison) -> list[str]:
    """Walk the engine-authored string fields of a ``FilingComparison`` and
    return every (field_path, term) violation. Skips raw passage text and
    keyword terms."""
    violations: list[str] = []

    for i, ev in enumerate(getattr(comparison, "evidence", ()) or ()):
        for term in scan_text(getattr(ev, "notes", None)):
            violations.append(f"evidence[{i}].notes:{term}")

    wc = getattr(comparison, "what_changed_labels", None)
    for j, label in enumerate(wc or ()):
        for term in scan_text(label):
            violations.append(f"label[{j}]:{term}")

    return violations
