"""
talonx_ingest.intelligence.comparison.diff
==========================================
Deterministic word-level document and section diff, plus new/removed
passage extraction. ``difflib`` only -- no NLP, no scoring, no direction.

Whole-doc / section change magnitude =
``1 - difflib.SequenceMatcher(None, prior_words, current_words).quick_ratio()``
(the Task 95H/95I metric). Added / removed word counts and passages come
from ``get_opcodes()``.
"""
from __future__ import annotations

from difflib import SequenceMatcher

from talonx_ingest.intelligence.comparison.config import (
    PASSAGE_MAX_CHARS,
    PASSAGE_MIN_WORDS,
)
from talonx_ingest.intelligence.comparison.domain import (
    ComparisonMethod,
    ComparisonQualityFlag,
    PassageChange,
    PassageChangeType,
    SectionChange,
    SectionStatus,
    SectionType,
    WholeDocumentChange,
)
from talonx_ingest.intelligence.comparison.identity import content_hash
from talonx_ingest.intelligence.comparison.sections import SectionExtract

# Above this combined word count we skip the O(n*m) opcode walk and derive
# added/removed from |Δ words| only (quick_ratio itself stays cheap).
_OPCODE_WORD_CAP = 160_000


def _quick_ratio(prior_words, current_words) -> float:
    return SequenceMatcher(None, prior_words, current_words, autojunk=False).quick_ratio()


def _opcode_counts(prior_words, current_words):
    """Return (added, removed, opcodes|None). opcodes is None when the pair
    is too large to walk."""
    if len(prior_words) + len(current_words) > _OPCODE_WORD_CAP:
        return None, None, None
    sm = SequenceMatcher(None, prior_words, current_words, autojunk=False)
    added = removed = 0
    ops = sm.get_opcodes()
    for tag, i1, i2, j1, j2 in ops:
        if tag in ("insert", "replace"):
            added += j2 - j1
        if tag in ("delete", "replace"):
            removed += i2 - i1
    return added, removed, ops


def whole_document_diff(
    prior_words: list[str],
    current_words: list[str],
    *,
    prior_char_count: int,
    current_char_count: int,
    threshold: float,
) -> tuple[WholeDocumentChange, list[str]]:
    flags: list[str] = []
    qr = _quick_ratio(prior_words, current_words)
    added, removed, _ = _opcode_counts(prior_words, current_words)
    if added is None:
        flags.append(ComparisonQualityFlag.LOW_QUALITY_COMPARISON.value)
        delta = len(current_words) - len(prior_words)
        added = max(delta, 0)
        removed = max(-delta, 0)
    total = max(1, len(prior_words) + len(current_words))
    diff_ratio = round(1.0 - qr, 6)
    change = WholeDocumentChange(
        method=ComparisonMethod.SEQUENCEMATCHER_QUICKRATIO_WORDLIST_V1,
        prior_word_count=len(prior_words),
        current_word_count=len(current_words),
        word_count_delta=len(current_words) - len(prior_words),
        prior_char_count=prior_char_count,
        current_char_count=current_char_count,
        char_count_delta=current_char_count - prior_char_count,
        quick_ratio=round(qr, 6),
        diff_ratio=diff_ratio,
        added_word_count=added,
        removed_word_count=removed,
        changed_fraction=round((added + removed) / total, 6),
        material_threshold=threshold,
        exceeds_material_threshold=diff_ratio >= threshold,
    )
    return change, flags


def section_diff(
    section_type: SectionType,
    prior: SectionExtract,
    current: SectionExtract,
    *,
    threshold: float | None,
) -> tuple[SectionChange, list[str]]:
    flags: list[str] = []
    prior_present = prior.status in (SectionStatus.FOUND, SectionStatus.MULTIPLE_MATCHES)
    current_present = current.status in (SectionStatus.FOUND, SectionStatus.MULTIPLE_MATCHES)

    if SectionStatus.AMBIGUOUS in (prior.status, current.status):
        flags.append(ComparisonQualityFlag.AMBIGUOUS_SECTION.value)
    if SectionStatus.MULTIPLE_MATCHES in (prior.status, current.status):
        flags.append(ComparisonQualityFlag.PARSER_FALLBACK_USED.value)
    if not (prior_present and current_present):
        flags.append(ComparisonQualityFlag.SECTION_NOT_FOUND.value)

    if not (prior_present and current_present):
        status = (
            current.status if not current_present else prior.status
        )
        return (
            SectionChange(
                section_type=section_type,
                status=status,
                prior_present=prior_present,
                current_present=current_present,
                prior_char_count=prior.char_count if prior_present else None,
                current_char_count=current.char_count if current_present else None,
                prior_text_hash=prior.text_hash if prior_present else None,
                current_text_hash=current.text_hash if current_present else None,
                header_matched_current=current.header_matched,
                header_matched_prior=prior.header_matched,
            ),
            flags,
        )

    pw, cw = prior.text.split(), current.text.split()
    qr = _quick_ratio(pw, cw)
    added, removed, _ = _opcode_counts(pw, cw)
    if added is None:
        delta = len(cw) - len(pw)
        added, removed = max(delta, 0), max(-delta, 0)
    diff_ratio = round(1.0 - qr, 6)
    char_delta = current.char_count - prior.char_count
    pct = round(char_delta / prior.char_count, 6) if prior.char_count else None
    change = SectionChange(
        section_type=section_type,
        status=SectionStatus.MULTIPLE_MATCHES
        if SectionStatus.MULTIPLE_MATCHES in (prior.status, current.status)
        else SectionStatus.FOUND,
        prior_present=True,
        current_present=True,
        prior_char_count=prior.char_count,
        current_char_count=current.char_count,
        char_count_delta=char_delta,
        pct_char_delta=pct,
        prior_word_count=len(pw),
        current_word_count=len(cw),
        word_count_delta=len(cw) - len(pw),
        quick_ratio=round(qr, 6),
        diff_ratio=diff_ratio,
        added_word_count=added,
        removed_word_count=removed,
        prior_text_hash=prior.text_hash,
        current_text_hash=current.text_hash,
        material_threshold=threshold,
        exceeds_material_threshold=(diff_ratio >= threshold) if threshold is not None else None,
        header_matched_current=current.header_matched,
        header_matched_prior=prior.header_matched,
    )
    return change, flags


def extract_passages(
    prior_words: list[str],
    current_words: list[str],
    *,
    section: str,
    min_words: int = PASSAGE_MIN_WORDS,
) -> tuple[list[PassageChange], list[PassageChange]]:
    """New (inserted) and removed (deleted) contiguous blocks of >=
    ``min_words`` words. Deterministic order by position. Raw text only --
    no summary."""
    if len(prior_words) + len(current_words) > _OPCODE_WORD_CAP:
        return [], []
    sm = SequenceMatcher(None, prior_words, current_words, autojunk=False)
    new: list[PassageChange] = []
    removed: list[PassageChange] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace") and (j2 - j1) >= min_words:
            new.append(
                _passage(PassageChangeType.NEW_IN_CURRENT, section, current_words, j1, j2,
                         current_offset=j1)
            )
        if tag in ("delete", "replace") and (i2 - i1) >= min_words:
            removed.append(
                _passage(PassageChangeType.REMOVED_SINCE_PRIOR, section, prior_words, i1, i2,
                         prior_offset=i1)
            )
    for idx, p in enumerate(new):
        new[idx] = p.model_copy(update={"index": idx})
    for idx, p in enumerate(removed):
        removed[idx] = p.model_copy(update={"index": idx})
    return new, removed


def _passage(change_type, section, words, a, b, *, prior_offset=None, current_offset=None):
    text = " ".join(words[a:b])
    truncated = len(text) > PASSAGE_MAX_CHARS
    if truncated:
        text = text[:PASSAGE_MAX_CHARS]
    return PassageChange(
        change_type=change_type,
        section=section,
        index=0,
        word_count=b - a,
        char_count=len(text),
        text=text,
        truncated=truncated,
        prior_word_offset=prior_offset,
        current_word_offset=current_offset,
    )
