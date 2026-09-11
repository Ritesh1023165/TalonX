"""
tests/test_comparison_diff.py
-----------------------------
Task 96C -- whole-document + section diff and passage extraction.
"""
from __future__ import annotations

from talonx_ingest.intelligence.comparison.diff import (
    extract_passages,
    section_diff,
    whole_document_diff,
)
from talonx_ingest.intelligence.comparison.domain import (
    PassageChangeType,
    SectionStatus,
    SectionType,
)
from talonx_ingest.intelligence.comparison.sections import SectionExtract
from talonx_ingest.intelligence.comparison.identity import content_hash


def _words(s):
    return s.split()


def test_identical_documents_zero_diff():
    w = _words("alpha beta gamma delta " * 20)
    change, flags = whole_document_diff(
        w, list(w), prior_char_count=100, current_char_count=100, threshold=0.13
    )
    assert change.diff_ratio == 0.0
    assert change.quick_ratio == 1.0
    assert change.added_word_count == 0 and change.removed_word_count == 0
    assert change.exceeds_material_threshold is False
    assert flags == []


def test_small_change_below_threshold():
    prior = _words("the quick brown fox " * 40)
    current = _words("the quick brown fox " * 40 + "one two three")
    change, _ = whole_document_diff(
        prior, current, prior_char_count=800, current_char_count=815, threshold=0.13
    )
    assert 0.0 < change.diff_ratio < 0.13
    assert change.added_word_count == 3
    assert change.removed_word_count == 0
    assert change.exceeds_material_threshold is False


def test_large_change_exceeds_threshold():
    prior = _words("alpha " * 100)
    current = _words("omega " * 100)
    change, _ = whole_document_diff(
        prior, current, prior_char_count=600, current_char_count=600, threshold=0.13
    )
    assert change.diff_ratio > 0.5
    assert change.exceeds_material_threshold is True
    assert change.added_word_count == 100 and change.removed_word_count == 100


def test_pure_insertion_and_deletion_counts():
    prior = _words("a b c d e f g h")
    current = _words("a b c NEW1 NEW2 NEW3 d e f g h")
    change, _ = whole_document_diff(prior, current, prior_char_count=1, current_char_count=1, threshold=0.5)
    assert change.added_word_count == 3
    assert change.removed_word_count == 0
    assert change.word_count_delta == 3


def _extract(section_type, text):
    return SectionExtract(
        section_type=section_type,
        status=SectionStatus.FOUND,
        present=True,
        text=text,
        char_count=len(text),
        word_count=len(text.split()),
        text_hash=content_hash(text),
        header_matched="item 1a. risk factors",
        start_offset=0,
        end_offset=len(text),
        real_match_count=1,
        raw_match_count=1,
    )


def test_section_diff_present_both():
    prior = _extract(SectionType.RISK_FACTORS, "risk one risk two risk three " * 20)
    current = _extract(SectionType.RISK_FACTORS, "risk one risk two risk three " * 10 + "a brand new disclosed risk " * 12)
    sc, flags = section_diff(SectionType.RISK_FACTORS, prior, current, threshold=0.1093)
    assert sc.status is SectionStatus.FOUND
    assert sc.diff_ratio > 0.1093
    assert sc.exceeds_material_threshold is True
    assert sc.char_count_delta == current.char_count - prior.char_count
    assert sc.pct_char_delta is not None


def test_section_diff_missing_one_side():
    prior = _extract(SectionType.MDNA, "some mdna text " * 30)
    absent = SectionExtract(
        section_type=SectionType.MDNA, status=SectionStatus.NOT_FOUND, present=False,
        text="", char_count=0, word_count=0, text_hash=content_hash(""),
    )
    sc, flags = section_diff(SectionType.MDNA, prior, absent, threshold=0.1659)
    assert sc.current_present is False
    assert sc.diff_ratio is None
    assert "section_not_found" in flags


def test_passages_new_and_removed_min_words():
    shared = _words("kept " * 60)
    gone = _words("alpha bravo charlie delta echo foxtrot golf hotel india juliet " * 6)  # 60 words, disjoint
    added = _words("mike november oscar papa quebec romeo sierra tango uniform victor " * 6)  # 60 words, disjoint
    prior = shared + gone
    current = shared + added
    new, removed = extract_passages(prior, current, section="risk_factors", min_words=40)
    assert len(new) >= 1 and len(removed) >= 1
    assert all(p.change_type is PassageChangeType.NEW_IN_CURRENT for p in new)
    assert all(p.change_type is PassageChangeType.REMOVED_SINCE_PRIOR for p in removed)
    assert all(p.word_count >= 40 for p in new + removed)
    assert [p.index for p in new] == list(range(len(new)))
    assert new[0].section == "risk_factors"


def test_passages_ignores_small_changes():
    prior = _words("stable content here " * 50)
    current = _words("stable content here " * 50 + "tiny addition")
    new, removed = extract_passages(prior, current, section="mdna", min_words=40)
    assert new == [] and removed == []


def test_diff_is_deterministic():
    p = _words("one two three four " * 30)
    c = _words("one two three four " * 20 + "five six seven eight " * 10)
    a, _ = whole_document_diff(p, c, prior_char_count=1, current_char_count=1, threshold=0.13)
    b, _ = whole_document_diff(p, c, prior_char_count=1, current_char_count=1, threshold=0.13)
    assert a == b
