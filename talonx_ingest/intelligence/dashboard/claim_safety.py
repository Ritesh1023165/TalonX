"""
talonx_ingest.intelligence.dashboard.claim_safety
=================================================
Claim-safety scan over every machine-generated dashboard string / page
(``PRODUCT_CLAIM_POLICY.md`` / ``RISK_LANGUAGE_POLICY.md``).

Reuses the Task 96F context-aware scanner (`delivery.claim_safety`) —
predictive / advice constructs are rejected; factual SEC transaction
wording ("open-market sale", "purchase of 40,000 shares", "Revenue
decreased 12%") is allowed. HTML tags / entities are stripped before the
scan so page markup is not mistaken for prose.
"""
from __future__ import annotations

import re

from talonx_ingest.intelligence.delivery.claim_safety import (
    PredictiveLanguageError,
    scan_rendered as _delivery_scan,
)

__all__ = [
    "PredictiveLanguageError",
    "scan_text",
    "scan_page",
    "assert_clean",
    "assert_clean_page",
]

_TAG = re.compile(r"<[^>]+>")
_ENTITY = re.compile(r"&[a-zA-Z]+;|&#\d+;")
#: verbatim SEC filing text embedded on a page (passage excerpts) is NOT
#: machine-generated prose — it is quoted primary-source bytes and may
#: legitimately contain financial words. It is excluded from the page
#: claim scan, exactly as Task 96C/96F exclude raw passage text.
_FILING_EXCERPT = re.compile(
    r'<blockquote class="filing-excerpt">.*?</blockquote>', re.IGNORECASE | re.DOTALL
)

#: extra dashboard-only prohibited constructs (help text can be tempting)
_EXTRA = (
    "likely winner", "likely loser", "buy opportunity", "sell opportunity",
    "top pick", "top opportunities", "best stock", "worst stock",
    "should own", "must own", "attractive entry", "attractive valuation",
    "expected decline", "expected gain", "expected drop", "expected rise",
    "poised to", "set to rally", "set to fall", "due for a",
)
_EXTRA_RE = [
    re.compile(r"(?<![a-z0-9])" + re.escape(p) + r"(?![a-z0-9])", re.IGNORECASE) for p in _EXTRA
]


def _strip_markup(html: str) -> str:
    return _ENTITY.sub(" ", _TAG.sub(" ", html or ""))


def _policy_allowlist() -> tuple[str, ...]:
    """The frozen, human-reviewed product-policy / disclaimer / help strings.
    They are the *authority* on what the product does not claim and
    legitimately enumerate prohibited words ("no page uses the words buy,
    sell, ..."). They are stripped before the scan so the scanner still
    catches machine-generated prose everywhere else on the page. Imported
    lazily to avoid an import cycle."""
    from talonx_ingest.intelligence.dashboard.config import (
        CLAIM_POLICY_SHORT,
        DISCLAIMER_SHORT,
        EVIDENCE_PHILOSOPHY,
        EVIDENCE_STATEMENTS,
        SIGNIFICANCE_HELP,
    )

    return (
        DISCLAIMER_SHORT,
        CLAIM_POLICY_SHORT,
        SIGNIFICANCE_HELP,
        EVIDENCE_PHILOSOPHY,
        *EVIDENCE_STATEMENTS,
    )


def _strip_policy(text: str) -> str:
    for phrase in _policy_allowlist():
        if phrase:
            text = text.replace(phrase, " ")
    return text


def scan_text(text: str | None) -> list[str]:
    if not text:
        return []
    hits = list(_delivery_scan(text))
    for pat, phrase in zip(_EXTRA_RE, _EXTRA):
        if pat.search(text):
            hits.append(f"phrase:{phrase}")
    return sorted(set(hits))


def scan_page(html: str | None) -> list[str]:
    body = _FILING_EXCERPT.sub(" ", html or "")
    return scan_text(_strip_policy(_strip_markup(body)))


def assert_clean(text: str | None) -> None:
    v = scan_text(text)
    if v:
        raise PredictiveLanguageError(f"dashboard text contains prohibited claim language: {v}")


def assert_clean_page(html: str | None) -> None:
    v = scan_page(html)
    if v:
        raise PredictiveLanguageError(f"dashboard page contains prohibited claim language: {v}")
