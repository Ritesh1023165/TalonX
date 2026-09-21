"""
talonx_ingest.intelligence.significance.language_safety
=====================================================
Guard against predictive / directional / advice language in the
machine-generated significance labels — component ``detail`` strings,
reason ``description`` / ``code`` strings, and ``band_caps_applied`` notes.

Reuses the Task 96C scanner (``comparison.language_safety``) and adds a
small significance-specific term set. **Not** applied to raw filing text
(verbatim SEC bytes) or to keyword-lexicon terms (data values).
"""
from __future__ import annotations

from talonx_ingest.intelligence.comparison.language_safety import (
    PROHIBITED_TERMS as _BASE_TERMS,
)
from talonx_ingest.intelligence.comparison.language_safety import (
    PredictiveLanguageError,
    scan_text as _base_scan,
)

__all__ = [
    "PROHIBITED_TERMS",
    "PredictiveLanguageError",
    "scan_text",
    "assert_clean",
    "scan_significance",
    "assert_clean_significance",
]

_EXTRA_TERMS: frozenset[str] = frozenset(
    {
        "opportunity score",         # the design's explicitly-banned alt name
        "signal strength",
        "priority to buy",
        "priority to sell",
        "act now",
        "must see",
        "must-see",
        "trade idea",
        "position size",
        "take profit",
        "stop loss",
        "market-moving",
        "will move",
        "should move",
        "high conviction",
        "smart money",
        "insider alpha",
    }
)
PROHIBITED_TERMS: frozenset[str] = _BASE_TERMS | _EXTRA_TERMS

import re as _re  # noqa: E402

_EXTRA_PATTERNS = {
    t: _re.compile(r"(?<![a-z0-9])" + _re.escape(t) + r"(?![a-z0-9])", _re.IGNORECASE)
    for t in _EXTRA_TERMS
}


def scan_text(text: str | None) -> list[str]:
    hits = set(_base_scan(text))
    if text:
        hits.update(t for t, pat in _EXTRA_PATTERNS.items() if pat.search(text))
    return sorted(hits)


def assert_clean(*strings: str | None) -> None:
    bad: set[str] = set()
    for s in strings:
        bad.update(scan_text(s))
    if bad:
        raise PredictiveLanguageError(
            f"significance label contains prohibited term(s): {sorted(bad)}"
        )


def scan_significance(sig) -> list[str]:
    """Return every ``(field_path, term)`` violation in an
    ``InformationSignificance``. Clean -> empty list."""
    out: list[str] = []
    for i, c in enumerate(getattr(sig, "components", ()) or ()):
        for term in scan_text(getattr(c, "detail", None)):
            out.append(f"components[{i}].detail:{term}")
        for term in scan_text(getattr(c, "code", None)):
            out.append(f"components[{i}].code:{term}")
    for i, r in enumerate(getattr(sig, "reasons", ()) or ()):
        for term in scan_text(getattr(r, "description", None)):
            out.append(f"reasons[{i}].description:{term}")
        for term in scan_text(getattr(r, "code", None)):
            out.append(f"reasons[{i}].code:{term}")
    for i, note in enumerate(getattr(sig, "band_caps_applied", ()) or ()):
        for term in scan_text(note):
            out.append(f"band_caps_applied[{i}]:{term}")
    return out


def assert_clean_significance(sig) -> None:
    v = scan_significance(sig)
    if v:
        raise PredictiveLanguageError(f"significance object contains prohibited language: {v}")
