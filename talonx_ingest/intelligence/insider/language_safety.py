"""
talonx_ingest.intelligence.insider.language_safety
==================================================
Predictive/directional-language guard for machine-generated insider labels
and notes. Reuses the Task 96C scanner and adds insider-specific
prohibited phrases ("insider alpha", "smart money", "conviction buy", …).

Applies to engine-authored strings only -- not to raw SEC values
(officer titles, security names, footnote text).
"""
from __future__ import annotations

import re

from talonx_ingest.intelligence.comparison.language_safety import (
    PROHIBITED_TERMS as _BASE_TERMS,
)
from talonx_ingest.intelligence.comparison.language_safety import (
    PredictiveLanguageError,
)

__all__ = [
    "PROHIBITED_TERMS",
    "PredictiveLanguageError",
    "scan_text",
    "assert_clean",
    "scan_insider_activity",
]

_INSIDER_EXTRA = frozenset(
    {
        "insider alpha", "smart money", "conviction buy", "conviction sell",
        "insider signal", "informative buying", "informative selling",
        "cluster buy signal", "cluster sell signal", "bullish cluster",
        "bearish cluster", "insider sentiment", "smart-money", "informed trading",
    }
)
PROHIBITED_TERMS: frozenset[str] = _BASE_TERMS | _INSIDER_EXTRA

_PATTERNS: dict[str, re.Pattern] = {
    t: re.compile(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", re.IGNORECASE)
    for t in PROHIBITED_TERMS
}


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
            f"machine-generated insider label contains prohibited term(s): {sorted(hits)}"
        )


def scan_insider_activity(activity) -> list[str]:
    """Walk the engine-authored strings of an ``InsiderActivity`` and
    return (path, term) violations. Skips raw SEC text (owner names,
    security titles, officer titles, footnote text)."""
    out: list[str] = []
    for i, ev in enumerate(getattr(activity, "evidence", ()) or ()):
        for term in scan_text(getattr(ev, "notes", None)):
            out.append(f"evidence[{i}].notes:{term}")
    for i, agg in enumerate(getattr(activity, "open_market_aggregates", ()) or ()):
        for term in scan_text(getattr(agg, "value_coverage_note", None)):
            out.append(f"open_market_aggregates[{i}].value_coverage_note:{term}")
    for i, cl in enumerate(getattr(activity, "clusters", ()) or ()):
        for term in scan_text(getattr(cl, "kind", None)):
            out.append(f"clusters[{i}].kind:{term}")
    return out
