"""
talonx_ingest.intelligence.comparison.whatchanged
=================================================
Canonical machine-readable ``what_changed`` structure built from a
``FilingComparison``.

This is a data contract for downstream layers (significance engine,
Telegram, dashboard). It carries **no presentation formatting** and **no
predictive/directional field**. ``notable_changes`` is a list of
structured facts (type + metric + value), never prose.
"""
from __future__ import annotations

from talonx_ingest.intelligence.comparison.config import (
    NEW_MATERIAL_PASSAGES_MIN_COUNT,
    PASSAGE_MIN_WORDS,
)
from talonx_ingest.intelligence.comparison.domain import (
    FilingComparison,
    KeywordCategory,
    SectionType,
)

_SECTION_KEY = {
    SectionType.RISK_FACTORS: "risk_factors",
    SectionType.MDNA: "mdna",
    SectionType.LIQUIDITY: "liquidity",
}
_PASSAGE_EXCERPT_CHARS = 600


def _iso(dt):
    return dt.isoformat() if dt is not None else None


def _whole(c: FilingComparison) -> dict | None:
    w = c.whole_document_change
    if w is None:
        return None
    return {
        "method": w.method.value,
        "diff_ratio": w.diff_ratio,
        "quick_ratio": w.quick_ratio,
        "prior_word_count": w.prior_word_count,
        "current_word_count": w.current_word_count,
        "word_count_delta": w.word_count_delta,
        "char_count_delta": w.char_count_delta,
        "added_word_count": w.added_word_count,
        "removed_word_count": w.removed_word_count,
        "changed_fraction": w.changed_fraction,
        "material_threshold": w.material_threshold,
        "exceeds_material_threshold": w.exceeds_material_threshold,
    }


def _section(sc) -> dict:
    return {
        "status": sc.status.value,
        "prior_present": sc.prior_present,
        "current_present": sc.current_present,
        "prior_char_count": sc.prior_char_count,
        "current_char_count": sc.current_char_count,
        "char_count_delta": sc.char_count_delta,
        "pct_char_delta": sc.pct_char_delta,
        "word_count_delta": sc.word_count_delta,
        "diff_ratio": sc.diff_ratio,
        "quick_ratio": sc.quick_ratio,
        "added_word_count": sc.added_word_count,
        "removed_word_count": sc.removed_word_count,
        "material_threshold": sc.material_threshold,
        "exceeds_material_threshold": sc.exceeds_material_threshold,
    }


def _passages(passages) -> list[dict]:
    out = []
    for p in passages:
        out.append(
            {
                "section": p.section,
                "index": p.index,
                "word_count": p.word_count,
                "char_count": p.char_count,
                "truncated": p.truncated,
                "text_excerpt": p.text[:_PASSAGE_EXCERPT_CHARS],
            }
        )
    return out


def _notable_changes(c: FilingComparison) -> list[dict]:
    """Structured facts only. No prose, no direction."""
    facts: list[dict] = []
    w = c.whole_document_change
    if w is not None and w.exceeds_material_threshold:
        facts.append(
            {
                "kind": "whole_document_changed_materially",
                "metric": "diff_ratio",
                "value": w.diff_ratio,
                "threshold": w.material_threshold,
            }
        )
    for sc in c.section_changes:
        if sc.exceeds_material_threshold:
            facts.append(
                {
                    "kind": "section_changed_materially",
                    "section": _SECTION_KEY[sc.section_type],
                    "metric": "diff_ratio",
                    "value": sc.diff_ratio,
                    "threshold": sc.material_threshold,
                }
            )
    new_rf_mdna = [
        p for p in c.new_passages if p.section in ("risk_factors", "mdna")
    ]
    if len(new_rf_mdna) >= NEW_MATERIAL_PASSAGES_MIN_COUNT:
        facts.append(
            {
                "kind": "new_material_passages",
                "metric": "count",
                "value": len(new_rf_mdna),
                "min_words_each": PASSAGE_MIN_WORDS,
            }
        )
    for s in c.keyword_category_summaries:
        if s.total_delta != 0:
            facts.append(
                {
                    "kind": "keyword_category_count_changed",
                    "category": s.category.value,
                    "metric": "count_delta",
                    "value": s.total_delta,
                    "terms_increased": list(s.terms_increased),
                    "terms_decreased": list(s.terms_decreased),
                }
            )
    for x in c.xbrl_changes:
        if x.status == "FOUND" and x.relative_delta is not None:
            facts.append(
                {
                    "kind": "xbrl_value_changed",
                    "field": x.field,
                    "comparison": x.comparison.value,
                    "metric": "relative_delta",
                    "value": x.relative_delta,
                    "absolute_delta": x.absolute_delta,
                    "concept": x.concept,
                }
            )
    return facts


def build_what_changed(c: FilingComparison) -> dict:
    sections = {
        _SECTION_KEY[sc.section_type]: _section(sc) for sc in c.section_changes
    }
    kw_by_cat = {
        KeywordCategory.NEGATIVE_RISK.value: None,
        KeywordCategory.POSITIVE_BUSINESS.value: None,
    }
    for s in c.keyword_category_summaries:
        kw_by_cat[s.category.value] = {
            "prior_total": s.prior_total,
            "current_total": s.current_total,
            "total_delta": s.total_delta,
            "terms_increased": list(s.terms_increased),
            "terms_decreased": list(s.terms_decreased),
        }
    return {
        "comparison_id": c.comparison_id,
        "schema_version": c.schema_version,
        "symbol": c.symbol,
        "company_name": c.company_name,
        "form_type": c.form_type,
        "base_form": c.base_form,
        "current_event_id": c.current_event_id,
        "prior_event_id": c.prior_event_id,
        "current_accession": c.current_accession,
        "prior_accession": c.prior_accession,
        "current_accepted_at_utc": _iso(c.current_accepted_at_utc),
        "prior_accepted_at_utc": _iso(c.prior_accepted_at_utc),
        "current_report_period_end": _iso(c.current_report_period_end),
        "prior_report_period_end": _iso(c.prior_report_period_end),
        "has_prior": c.prior_accession is not None,
        "whole_document": _whole(c),
        "sections": sections,
        "keywords": {
            "by_category": kw_by_cat,
            "terms": [
                {
                    "category": k.category.value,
                    "term": k.term,
                    "prior_count": k.prior_count,
                    "current_count": k.current_count,
                    "delta": k.delta,
                }
                for k in c.keyword_changes
            ],
        },
        "xbrl": [
            {
                "field": x.field,
                "concept": x.concept,
                "comparison": x.comparison.value,
                "prior_value": x.prior_value,
                "current_value": x.current_value,
                "absolute_delta": x.absolute_delta,
                "relative_delta": x.relative_delta,
                "prior_period_end": _iso(x.prior_period_end),
                "current_period_end": _iso(x.current_period_end),
                "status": x.status,
                "quality_flags": list(x.quality_flags),
            }
            for x in c.xbrl_changes
        ],
        "new_passages": _passages(c.new_passages),
        "removed_passages": _passages(c.removed_passages),
        "notable_changes": _notable_changes(c),
        "quality_flags": list(c.data_quality_flags),
    }
