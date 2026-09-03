"""
tests/test_comparison_sections.py
---------------------------------
Task 96C -- section extraction with explicit ambiguity handling.
"""
from __future__ import annotations

from talonx_ingest.intelligence.comparison.normalize import normalize_plaintext
from talonx_ingest.intelligence.comparison.sections import extract_sections
from talonx_ingest.intelligence.comparison.domain import SectionStatus, SectionType

_RF_BODY = "the company faces significant competition regulatory and supply chain risk. " * 30
_MDNA_BODY = "revenue increased due to higher unit volumes and pricing during the period. " * 30
_LIQ_BODY = "we believe existing cash and operating cash flow are sufficient for twelve months. " * 20


def _doc_10q(rf=_RF_BODY, mdna=_MDNA_BODY, liq=_LIQ_BODY, toc=True):
    toc_block = (
        "table of contents item 1a. risk factors 14 "
        "item 2. management's discussion and analysis 20 "
    ) if toc else ""
    return normalize_plaintext(
        f"{toc_block}"
        f"item 1a. risk factors {rf} "
        f"item 2. management's discussion and analysis of financial condition and results of operations "
        f"{mdna} liquidity and capital resources {liq} "
        f"item 3. quantitative and qualitative disclosures about market risk none here"
    ).text


def test_all_three_sections_found_in_10q():
    secs = extract_sections(_doc_10q(), "10-Q")
    for st in SectionType:
        assert secs[st].status is SectionStatus.FOUND, st
        assert secs[st].present
        assert secs[st].word_count > 50
    assert "competition regulatory" in secs[SectionType.RISK_FACTORS].text


def test_toc_line_is_not_mistaken_for_the_section():
    # the TOC has "item 1a. risk factors 14" then almost immediately "item 2." --
    # too short to be a real section; the real body further down must win.
    secs = extract_sections(_doc_10q(toc=True), "10-Q")
    rf = secs[SectionType.RISK_FACTORS]
    assert rf.status is SectionStatus.FOUND
    assert rf.word_count > 100          # got the body, not the 3-word TOC entry
    assert rf.start_offset > 60         # not offset 0 (the TOC)


def test_missing_section_reports_not_found():
    doc = normalize_plaintext(
        "item 1a. risk factors " + _RF_BODY + " item 3. other stuff " * 5
    ).text
    secs = extract_sections(doc, "10-Q")
    assert secs[SectionType.RISK_FACTORS].status is SectionStatus.FOUND
    assert secs[SectionType.MDNA].status is SectionStatus.NOT_FOUND
    assert secs[SectionType.MDNA].present is False
    assert secs[SectionType.MDNA].text == ""


def test_only_toc_match_is_ambiguous_not_fabricated():
    # "item 1a. risk factors" appears once, immediately followed by "item 2."
    doc = normalize_plaintext(
        "table of contents item 1a. risk factors 5 item 2. md&a 9 "
        "item 2. management's discussion and analysis " + _MDNA_BODY
    ).text
    secs = extract_sections(doc, "10-Q")
    rf = secs[SectionType.RISK_FACTORS]
    assert rf.status is SectionStatus.AMBIGUOUS
    assert rf.present is False
    assert rf.text == ""
    assert rf.raw_match_count >= 1


def test_multiple_real_matches_flag():
    body = "item 1a. risk factors " + _RF_BODY + " item 5. controls "
    doc = normalize_plaintext(body + " " + body).text
    rf = extract_sections(doc, "10-K")[SectionType.RISK_FACTORS]
    assert rf.status is SectionStatus.MULTIPLE_MATCHES
    assert rf.real_match_count == 2


def test_extraction_is_deterministic():
    d = _doc_10q()
    a = extract_sections(d, "10-Q")
    b = extract_sections(d, "10-Q")
    assert {k: v.text_hash for k, v in a.items()} == {k: v.text_hash for k, v in b.items()}
