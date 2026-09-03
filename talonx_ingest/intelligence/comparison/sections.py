"""
talonx_ingest.intelligence.comparison.sections
==============================================
Deterministic section extraction from normalised filing text.

Supported: Risk Factors (``Item 1A``), MD&A (``Item 2`` in a 10-Q / ``Item
7`` in a 10-K), Liquidity and Capital Resources (a subsection of MD&A).

Method (Task 95H/95I): find every header match; keep only matches with a
real body (>= ``MIN_SECTION_BODY_CHARS`` before the next ``Item Nx.``
header) so table-of-contents lines are dropped; take the **last** real
match; the section runs to the next ``Item Nx.`` header (or a bounded cap
for the MD&A subsection). Status is explicit -- ``FOUND`` / ``NOT_FOUND`` /
``AMBIGUOUS`` (only TOC-style matches) / ``MULTIPLE_MATCHES`` (>1 real
match; the last is used and the caller is flagged). Never fabricates.
"""
from __future__ import annotations

from dataclasses import dataclass

from talonx_ingest.intelligence.comparison.config import (
    MIN_SECTION_BODY_CHARS,
    NEXT_ITEM_PATTERN,
    SECTION_HEADER_PATTERNS,
)
from talonx_ingest.intelligence.comparison.domain import SectionStatus, SectionType
from talonx_ingest.intelligence.comparison.identity import content_hash

_LIQUIDITY_MAX_CHARS = 25_000


@dataclass(frozen=True)
class SectionExtract:
    section_type: SectionType
    status: SectionStatus
    present: bool
    text: str
    char_count: int
    word_count: int
    text_hash: str
    header_matched: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    real_match_count: int = 0
    raw_match_count: int = 0


_KEY_TO_TYPE = {
    "risk_factors": SectionType.RISK_FACTORS,
    "mdna": SectionType.MDNA,
    "liquidity": SectionType.LIQUIDITY,
}


def _next_item_after(text: str, pos: int) -> int:
    m = NEXT_ITEM_PATTERN.search(text, pos)
    return m.start() if m else len(text)


def _empty(section_type: SectionType, status: SectionStatus, raw_matches: int) -> SectionExtract:
    return SectionExtract(
        section_type=section_type,
        status=status,
        present=False,
        text="",
        char_count=0,
        word_count=0,
        text_hash=content_hash(""),
        real_match_count=0,
        raw_match_count=raw_matches,
    )


def _extract_one(key: str, section_type: SectionType, text: str) -> SectionExtract:
    pattern = SECTION_HEADER_PATTERNS[key]
    matches = list(pattern.finditer(text))
    if not matches:
        return _empty(section_type, SectionStatus.NOT_FOUND, 0)

    real: list[tuple[int, int, str]] = []  # (body_start, header_start, header_text)
    for m in matches:
        body_start = m.end()
        if key == "liquidity":
            hard_end = min(len(text), body_start + _LIQUIDITY_MAX_CHARS)
            end = min(_next_item_after(text, body_start), hard_end)
        else:
            end = _next_item_after(text, body_start)
        if end - body_start >= MIN_SECTION_BODY_CHARS:
            real.append((body_start, m.start(), m.group(0)))

    if not real:
        # only TOC-style matches -- do not guess
        return _empty(section_type, SectionStatus.AMBIGUOUS, len(matches))

    body_start, header_start, header_text = real[-1]
    if key == "liquidity":
        hard_end = min(len(text), body_start + _LIQUIDITY_MAX_CHARS)
        end = min(_next_item_after(text, body_start), hard_end)
    else:
        end = _next_item_after(text, body_start)

    body = text[body_start:end].strip()
    status = SectionStatus.MULTIPLE_MATCHES if len(real) > 1 else SectionStatus.FOUND
    words = body.split()
    return SectionExtract(
        section_type=section_type,
        status=status,
        present=True,
        text=body,
        char_count=len(body),
        word_count=len(words),
        text_hash=content_hash(body),
        header_matched=header_text,
        start_offset=header_start,
        end_offset=end,
        real_match_count=len(real),
        raw_match_count=len(matches),
    )


def extract_sections(normalized_text: str, base_form: str) -> dict[SectionType, SectionExtract]:
    """Return an extract for every supported section (always all three keys
    present; ``status`` says whether each was located)."""
    out: dict[SectionType, SectionExtract] = {}
    for key, section_type in _KEY_TO_TYPE.items():
        out[section_type] = _extract_one(key, section_type, normalized_text or "")
    return out
