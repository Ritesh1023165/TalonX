"""
talonx_ingest.intelligence.comparison.domain
============================================
Immutable value objects for the filing-comparison engine.

Hard rule (``PRODUCT_CLAIM_POLICY.md`` / ``RISK_LANGUAGE_POLICY.md``):
nothing here encodes a prediction, direction, sentiment, severity judgement
or expected return. Metrics describe *what changed*; interpretation is out
of scope. ``extra="forbid"`` rejects any stray field.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

from talonx_ingest.intelligence.comparison.config import COMPARISON_SCHEMA_VERSION
from talonx_ingest.intelligence.domain import EvidenceRecord

_FROZEN = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------
class SectionType(str, Enum):
    RISK_FACTORS = "risk_factors"
    MDNA = "mdna"
    LIQUIDITY = "liquidity"


class SectionStatus(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    MULTIPLE_MATCHES = "MULTIPLE_MATCHES"


class ComparisonMethod(str, Enum):
    # 1 - difflib.SequenceMatcher(None, prior_words, current_words).quick_ratio()
    SEQUENCEMATCHER_QUICKRATIO_WORDLIST_V1 = "sequencematcher_quickratio_wordlist_v1"


class PassageChangeType(str, Enum):
    NEW_IN_CURRENT = "NEW_IN_CURRENT"
    REMOVED_SINCE_PRIOR = "REMOVED_SINCE_PRIOR"


class KeywordCategory(str, Enum):
    NEGATIVE_RISK = "negative_risk"
    POSITIVE_BUSINESS = "positive_business"


class XbrlPeriodComparison(str, Enum):
    YOY = "YOY"
    QOQ = "QOQ"


class ComparisonQualityFlag(str, Enum):
    MISSING_PRIOR_FILING = "missing_prior_filing"
    PRIOR_IS_FIRST_FILING = "prior_is_first_filing"
    AMENDMENT_INVOLVED = "amendment_involved"
    CURRENT_DOCUMENT_UNAVAILABLE = "current_document_unavailable"
    PRIOR_DOCUMENT_UNAVAILABLE = "prior_document_unavailable"
    SECTION_NOT_FOUND = "section_not_found"
    AMBIGUOUS_SECTION = "ambiguous_section"
    XBRL_CONCEPT_MISSING = "xbrl_concept_missing"
    XBRL_UNAVAILABLE = "xbrl_unavailable"
    FISCAL_PERIOD_MISMATCH = "fiscal_period_mismatch"
    PARSER_FALLBACK_USED = "parser_fallback_used"
    NORMALIZATION_FALLBACK = "normalization_fallback"
    LOW_QUALITY_COMPARISON = "low_quality_comparison"
    PRIOR_FORM_MISMATCH = "prior_form_mismatch"


# ---------------------------------------------------------------------------
# value objects
# ---------------------------------------------------------------------------
class WholeDocumentChange(BaseModel):
    model_config = _FROZEN

    method: ComparisonMethod = ComparisonMethod.SEQUENCEMATCHER_QUICKRATIO_WORDLIST_V1
    prior_word_count: int
    current_word_count: int
    word_count_delta: int
    prior_char_count: int
    current_char_count: int
    char_count_delta: int
    quick_ratio: float                     # difflib.SequenceMatcher.quick_ratio()
    diff_ratio: float                      # 1 - quick_ratio  (fraction changed)
    added_word_count: int                  # from get_opcodes insert/replace blocks
    removed_word_count: int                # from get_opcodes delete/replace blocks
    changed_fraction: float                # (added + removed) / max(1, prior+current words)
    material_threshold: float
    exceeds_material_threshold: bool


class SectionChange(BaseModel):
    model_config = _FROZEN

    section_type: SectionType
    status: SectionStatus
    prior_present: bool
    current_present: bool
    prior_char_count: int | None = None
    current_char_count: int | None = None
    char_count_delta: int | None = None
    pct_char_delta: float | None = None
    prior_word_count: int | None = None
    current_word_count: int | None = None
    word_count_delta: int | None = None
    quick_ratio: float | None = None
    diff_ratio: float | None = None
    added_word_count: int | None = None
    removed_word_count: int | None = None
    prior_text_hash: str | None = None
    current_text_hash: str | None = None
    material_threshold: float | None = None
    exceeds_material_threshold: bool | None = None
    header_matched_current: str | None = None
    header_matched_prior: str | None = None


class KeywordChange(BaseModel):
    model_config = _FROZEN

    category: KeywordCategory
    term: str
    prior_count: int
    current_count: int
    delta: int


class KeywordCategorySummary(BaseModel):
    model_config = _FROZEN

    category: KeywordCategory
    prior_total: int
    current_total: int
    total_delta: int
    terms_increased: tuple[str, ...] = ()
    terms_decreased: tuple[str, ...] = ()


class XbrlChange(BaseModel):
    model_config = _FROZEN

    field: str
    taxonomy: str | None = None
    concept: str | None = None
    unit: str | None = None
    comparison: XbrlPeriodComparison
    prior_period_end: date | None = None
    current_period_end: date | None = None
    prior_value: float | None = None
    current_value: float | None = None
    absolute_delta: float | None = None
    relative_delta: float | None = None       # (current - prior) / abs(prior)
    prior_filed_accession: str | None = None
    current_filed_accession: str | None = None
    prior_filed_date: date | None = None
    current_filed_date: date | None = None
    status: str = "FOUND"                      # FOUND / CONCEPT_MISSING / NO_PRIOR / PERIOD_MISMATCH / UNAVAILABLE
    quality_flags: tuple[str, ...] = ()


class PassageChange(BaseModel):
    model_config = _FROZEN

    change_type: PassageChangeType
    section: str                              # SectionType value, or "whole_document"
    index: int                                # deterministic order within (change_type, section)
    word_count: int
    char_count: int
    text: str
    truncated: bool = False
    prior_word_offset: int | None = None
    current_word_offset: int | None = None


class FilingComparison(BaseModel):
    """Canonical output. Immutable once built; a re-run with the same
    ``comparison_id`` upserts, never duplicates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    comparison_id: str
    schema_version: str = COMPARISON_SCHEMA_VERSION

    symbol: str
    company_name: str

    current_event_id: str
    prior_event_id: str | None
    current_accession: str
    prior_accession: str | None

    form_type: str
    base_form: str

    current_accepted_at_utc: datetime | None
    prior_accepted_at_utc: datetime | None
    current_report_period_end: date | None = None
    prior_report_period_end: date | None = None

    comparison_method: ComparisonMethod = ComparisonMethod.SEQUENCEMATCHER_QUICKRATIO_WORDLIST_V1

    current_document_hash: str | None = None
    prior_document_hash: str | None = None
    current_document_url: str | None = None
    prior_document_url: str | None = None

    whole_document_change: WholeDocumentChange | None = None
    section_changes: tuple[SectionChange, ...] = ()
    keyword_changes: tuple[KeywordChange, ...] = ()
    keyword_category_summaries: tuple[KeywordCategorySummary, ...] = ()
    xbrl_changes: tuple[XbrlChange, ...] = ()
    new_passages: tuple[PassageChange, ...] = ()
    removed_passages: tuple[PassageChange, ...] = ()

    data_quality_flags: tuple[str, ...] = ()
    evidence: tuple[EvidenceRecord, ...] = ()
    created_at_utc: datetime
