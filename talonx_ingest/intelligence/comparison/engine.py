"""
talonx_ingest.intelligence.comparison.engine
============================================
Orchestration for the filing-comparison engine.

``compare_filings(...)``       -- pure: raw HTML of both filings (+ optional
                                 XBRL concept JSON) -> ``FilingComparison``.
``run_comparison_for_event``   -- async I/O: resolve the prior comparable
                                 from the Task 96A store, fetch documents +
                                 XBRL via ``EdgarClient``, call
                                 ``compare_filings``. Returns the object;
                                 the caller persists it.

Nothing here delivers, scores significance, or renders. No trading import.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime

from talonx_ingest.intelligence.comparison.config import (
    DIFF_TRANSFORM,
    KEYWORD_TRANSFORM,
    MATERIAL_CHANGE_THRESHOLDS,
    NORMALIZE_TRANSFORM,
    PASSAGE_TRANSFORM,
    PRIOR_MATCH_TRANSFORM,
    RETRIEVAL_TRANSFORM,
    SECTION_EXTRACT_TRANSFORM,
    XBRL_FIELDS,
    XBRL_TRANSFORM,
)
from talonx_ingest.intelligence.comparison.diff import (
    extract_passages,
    section_diff,
    whole_document_diff,
)
from talonx_ingest.intelligence.comparison.domain import (
    ComparisonMethod,
    ComparisonQualityFlag,
    FilingComparison,
    SectionType,
)
from talonx_ingest.intelligence.comparison.identity import comparison_id, content_hash
from talonx_ingest.intelligence.comparison.keywords import keyword_deltas
from talonx_ingest.intelligence.comparison.language_safety import assert_clean
from talonx_ingest.intelligence.comparison.normalize import normalize_filing_text
from talonx_ingest.intelligence.comparison.prior_match import (
    PriorMatchResult,
    resolve_prior_comparable,
)
from talonx_ingest.intelligence.comparison.retrieval import FilingArchiveCache
from talonx_ingest.intelligence.comparison.sections import extract_sections
from talonx_ingest.intelligence.comparison.xbrl import compute_xbrl_changes
from talonx_ingest.intelligence.domain import EvidenceRecord, SourceType, utc_now
from talonx_ingest.intelligence.taxonomy import base_form

logger = logging.getLogger("talonx_ingest.intelligence.comparison.engine")

_SECTION_THRESHOLD_KEY = {
    SectionType.RISK_FACTORS: "risk_factors",
    SectionType.MDNA: "mdna",
    SectionType.LIQUIDITY: "liquidity",
}
_PASSAGE_SECTIONS = (SectionType.RISK_FACTORS, SectionType.MDNA)


def _ev(transform, *, url=None, ts=None, input_hash=None, notes=None) -> EvidenceRecord:
    return EvidenceRecord(
        source_provider=SourceType.SEC_EDGAR_ARCHIVES,
        source_record_id="filing_comparison",
        source_url=url,
        exact_timestamp=ts,
        retrieved_at=utc_now(),
        transform=transform,
        input_hash=input_hash,
        notes=notes,
    )


def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for x in items:
        if x and x not in seen:
            seen.append(x)
    return tuple(seen)


def compare_filings(
    *,
    symbol: str,
    company_name: str,
    current_event_id: str,
    prior_event_id: str | None,
    current_accession: str,
    prior_accession: str | None,
    form_type: str,
    current_accepted_at_utc: datetime | None,
    prior_accepted_at_utc: datetime | None,
    current_html: str | None,
    prior_html: str | None,
    current_report_period_end: date | None = None,
    prior_report_period_end: date | None = None,
    current_document_url: str | None = None,
    prior_document_url: str | None = None,
    concept_data: dict[tuple[str, str], dict | None] | None = None,
    extra_flags: Iterable[str] = (),
    now: datetime | None = None,
) -> FilingComparison:
    now = now or utc_now()
    base = base_form(form_type)
    flags: list[str] = list(extra_flags)
    evidence: list[EvidenceRecord] = []

    cid = comparison_id(current_accession, prior_accession)

    evidence.append(
        _ev(
            PRIOR_MATCH_TRANSFORM,
            notes=(
                f"current={current_accession} prior={prior_accession or 'NONE'} base_form={base}"
            ),
            input_hash=content_hash(current_accession, prior_accession or "NONE"),
        )
    )

    # --- normalise -------------------------------------------------
    cur_doc = prior_doc = None
    cur_hash = prior_hash = None
    if current_html is None:
        flags.append(ComparisonQualityFlag.CURRENT_DOCUMENT_UNAVAILABLE.value)
    else:
        cur_doc = normalize_filing_text(current_html)
        cur_hash = cur_doc.text_hash
        flags.extend(cur_doc.flags)
    if prior_accession is None:
        flags.append(ComparisonQualityFlag.MISSING_PRIOR_FILING.value)
    elif prior_html is None:
        flags.append(ComparisonQualityFlag.PRIOR_DOCUMENT_UNAVAILABLE.value)
    else:
        prior_doc = normalize_filing_text(prior_html)
        prior_hash = prior_doc.text_hash
        flags.extend(prior_doc.flags)

    evidence.append(
        _ev(
            RETRIEVAL_TRANSFORM + ":current",
            url=current_document_url,
            ts=current_accepted_at_utc,
            input_hash=cur_hash,
            notes=f"current primary document; hash={cur_hash}",
        )
    )
    if prior_accession is not None:
        evidence.append(
            _ev(
                RETRIEVAL_TRANSFORM + ":prior",
                url=prior_document_url,
                ts=prior_accepted_at_utc,
                input_hash=prior_hash,
                notes=f"prior primary document; hash={prior_hash}",
            )
        )
    evidence.append(
        _ev(
            NORMALIZE_TRANSFORM,
            input_hash=content_hash(cur_hash or "", prior_hash or ""),
            notes="clean_filing_html -> strip inline-xbrl/page-furniture -> lower -> single-space",
        )
    )

    whole_document_change = None
    section_changes: list = []
    new_passages: list = []
    removed_passages: list = []
    keyword_changes: tuple = ()
    keyword_summaries: tuple = ()

    if cur_doc is not None and prior_doc is not None:
        whole_document_change, wflags = whole_document_diff(
            list(prior_doc.words),
            list(cur_doc.words),
            prior_char_count=prior_doc.char_count,
            current_char_count=cur_doc.char_count,
            threshold=MATERIAL_CHANGE_THRESHOLDS["whole_document"],
        )
        flags.extend(wflags)

        cur_sections = extract_sections(cur_doc.text, base)
        prior_sections = extract_sections(prior_doc.text, base)
        evidence.append(
            _ev(
                SECTION_EXTRACT_TRANSFORM,
                notes="; ".join(
                    f"{k.value}:cur={cur_sections[k].status.value}/"
                    f"prior={prior_sections[k].status.value}"
                    for k in SectionType
                ),
                input_hash=content_hash(
                    *[cur_sections[k].text_hash for k in SectionType],
                    *[prior_sections[k].text_hash for k in SectionType],
                ),
            )
        )
        for st in SectionType:
            thr = MATERIAL_CHANGE_THRESHOLDS.get(_SECTION_THRESHOLD_KEY[st])
            sc, sflags = section_diff(st, prior_sections[st], cur_sections[st], threshold=thr)
            section_changes.append(sc)
            flags.extend(sflags)

        for st in _PASSAGE_SECTIONS:
            ps = prior_sections[st]
            cs = cur_sections[st]
            if ps.present and cs.present:
                nnew, nrem = extract_passages(
                    ps.text.split(), cs.text.split(), section=st.value
                )
                new_passages.extend(nnew)
                removed_passages.extend(nrem)
        evidence.append(
            _ev(
                PASSAGE_TRANSFORM,
                notes=f"new={len(new_passages)} removed={len(removed_passages)} (RF+MD&A, >=40 words)",
            )
        )

        keyword_changes, keyword_summaries = keyword_deltas(prior_doc.text, cur_doc.text)
        evidence.append(
            _ev(
                KEYWORD_TRANSFORM,
                notes="frozen lexicon (FILING_RESEARCH_PROTOCOL.md section 7); counts only",
                input_hash=content_hash(prior_hash or "", cur_hash or ""),
            )
        )

    # --- XBRL --------------------------------------------------------
    xbrl_changes: tuple = ()
    if concept_data is None:
        flags.append(ComparisonQualityFlag.XBRL_UNAVAILABLE.value)
    else:
        xbrl_changes = compute_xbrl_changes(
            current_period_end=current_report_period_end,
            concept_data=concept_data,
            base_form=base,
        )
        for xc in xbrl_changes:
            flags.extend(xc.quality_flags)
        evidence.append(
            _ev(
                XBRL_TRANSFORM,
                notes=(
                    "first-filed companyconcept selection; fields="
                    + ",".join(s["field"] for s in XBRL_FIELDS)
                ),
            )
        )

    # --- quality roll-up -----------------------------------------
    if cur_doc is None or prior_doc is None:
        flags.append(ComparisonQualityFlag.LOW_QUALITY_COMPARISON.value)

    dq = _dedupe(flags)

    for e in evidence:
        assert_clean(e.notes)

    return FilingComparison(
        comparison_id=cid,
        symbol=symbol.upper(),
        company_name=company_name,
        current_event_id=current_event_id,
        prior_event_id=prior_event_id,
        current_accession=current_accession,
        prior_accession=prior_accession,
        form_type=form_type,
        base_form=base,
        current_accepted_at_utc=current_accepted_at_utc,
        prior_accepted_at_utc=prior_accepted_at_utc,
        current_report_period_end=current_report_period_end,
        prior_report_period_end=prior_report_period_end,
        comparison_method=ComparisonMethod.SEQUENCEMATCHER_QUICKRATIO_WORDLIST_V1,
        current_document_hash=cur_hash,
        prior_document_hash=prior_hash,
        current_document_url=current_document_url,
        prior_document_url=prior_document_url,
        whole_document_change=whole_document_change,
        section_changes=tuple(section_changes),
        keyword_changes=tuple(keyword_changes),
        keyword_category_summaries=tuple(keyword_summaries),
        xbrl_changes=tuple(xbrl_changes),
        new_passages=tuple(new_passages),
        removed_passages=tuple(removed_passages),
        data_quality_flags=dq,
        evidence=tuple(evidence),
        created_at_utc=now,
    )


# ---------------------------------------------------------------------------
# async orchestrator
# ---------------------------------------------------------------------------
async def _fetch_concepts(client, cik) -> dict[tuple[str, str], dict | None]:
    from talonx_ingest.edgar.client import EdgarClientError

    seen: dict[tuple[str, str], dict | None] = {}
    for spec in XBRL_FIELDS:
        for tax, concept in spec["concepts"]:
            if (tax, concept) in seen:
                continue
            try:
                seen[(tax, concept)] = await client.get_company_concept(cik, tax, concept)
            except EdgarClientError:
                seen[(tax, concept)] = None
            except Exception as exc:  # noqa: BLE001
                logger.warning("companyconcept %s/%s failed: %s", tax, concept, exc)
                seen[(tax, concept)] = None
    return seen


async def run_comparison_for_event(
    store,
    client,
    current_event_id: str,
    *,
    cache: FilingArchiveCache | None = None,
    fetch_xbrl: bool = True,
    now: datetime | None = None,
) -> FilingComparison:
    ev = store.get_event(current_event_id)
    if ev is None:
        raise KeyError(f"event not in store: {current_event_id}")

    pm: PriorMatchResult = resolve_prior_comparable(store, ev)
    cache = cache or FilingArchiveCache(client)

    cur_fetch = await cache.fetch_primary_document(
        accession=ev.accession, primary_document_url=ev.primary_document_url
    )
    prior_fetch = None
    if pm.prior_event is not None:
        prior_fetch = await cache.fetch_primary_document(
            accession=pm.prior_event.accession,
            primary_document_url=pm.prior_event.primary_document_url,
        )

    concept_data = None
    if fetch_xbrl and ev.report_period_end is not None and base_form(ev.form_type) in ("10-Q", "10-K"):
        cik = ev.accession.split("-")[0]
        concept_data = await _fetch_concepts(client, cik)

    return compare_filings(
        symbol=ev.symbol,
        company_name=ev.company_name,
        current_event_id=ev.event_id,
        prior_event_id=pm.prior_event.event_id if pm.prior_event else None,
        current_accession=ev.accession,
        prior_accession=pm.prior_event.accession if pm.prior_event else None,
        form_type=ev.form_type,
        current_accepted_at_utc=ev.accepted_at_utc,
        prior_accepted_at_utc=pm.prior_event.accepted_at_utc if pm.prior_event else None,
        current_report_period_end=ev.report_period_end,
        prior_report_period_end=pm.prior_event.report_period_end if pm.prior_event else None,
        current_html=cur_fetch.raw_html,
        prior_html=prior_fetch.raw_html if prior_fetch else None,
        current_document_url=ev.primary_document_url,
        prior_document_url=pm.prior_event.primary_document_url if pm.prior_event else None,
        concept_data=concept_data,
        extra_flags=pm.flags,
        now=now,
    )
