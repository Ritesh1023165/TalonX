"""
talonx_ingest.intelligence.comparison.normalize
===============================================
Deterministic HTML -> comparable-text normalisation for filing diffing.

Layers on top of ``talonx_ingest.processing.cleaner.clean_filing_html``
(reused unchanged): strip inline-XBRL leftovers, strip deterministic page
furniture (page numbers, "Table of Contents", rule lines), lower-case, and
collapse all runs of whitespace to a single space. The result is one flat
string suitable for header-regex section extraction and word-list diffing.

Never removes a disclosure section. The normalised text is hashed so any
comparison can be reproduced.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from talonx_ingest.intelligence.comparison.config import (
    INLINE_XBRL_PATTERNS,
    PAGE_FURNITURE_PATTERNS,
)
from talonx_ingest.intelligence.comparison.domain import ComparisonQualityFlag
from talonx_ingest.intelligence.comparison.identity import content_hash

logger = logging.getLogger("talonx_ingest.intelligence.comparison.normalize")

_WS_RE = re.compile(r"\s+")
_CRUDE_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class NormalizedDoc:
    text: str                    # normalised, lower-cased, single-spaced
    words: tuple[str, ...]       # text.split() -- the diff unit
    char_count: int
    word_count: int
    text_hash: str
    flags: tuple[str, ...] = field(default_factory=tuple)


def _html_to_text(raw_html: str) -> tuple[str, list[str]]:
    flags: list[str] = []
    try:
        from talonx_ingest.processing.cleaner import clean_filing_html

        text = clean_filing_html(raw_html)
        if text and text.strip():
            return text, flags
    except Exception as exc:  # noqa: BLE001 - fall back, never crash a comparison
        logger.warning("clean_filing_html failed (%s); crude tag-strip fallback", exc)
    flags.append(ComparisonQualityFlag.NORMALIZATION_FALLBACK.value)
    return _CRUDE_TAG_RE.sub(" ", raw_html or ""), flags


def normalize_filing_text(raw_html: str) -> NormalizedDoc:
    text, flags = _html_to_text(raw_html)

    for pat in INLINE_XBRL_PATTERNS:
        text = pat.sub(" ", text)
    for pat in PAGE_FURNITURE_PATTERNS:
        text = pat.sub("\n", text)

    text = text.lower()
    text = _WS_RE.sub(" ", text).strip()

    words = tuple(text.split())
    return NormalizedDoc(
        text=text,
        words=words,
        char_count=len(text),
        word_count=len(words),
        text_hash=content_hash(text),
        flags=tuple(flags),
    )


def normalize_plaintext(text: str) -> NormalizedDoc:
    """Same normalisation for text that is already tag-free (e.g. a section
    already carved out of a NormalizedDoc, or a test fixture)."""
    t = text or ""
    for pat in INLINE_XBRL_PATTERNS:
        t = pat.sub(" ", t)
    for pat in PAGE_FURNITURE_PATTERNS:
        t = pat.sub("\n", t)
    t = _WS_RE.sub(" ", t.lower()).strip()
    words = tuple(t.split())
    return NormalizedDoc(
        text=t, words=words, char_count=len(t), word_count=len(words),
        text_hash=content_hash(t),
    )
