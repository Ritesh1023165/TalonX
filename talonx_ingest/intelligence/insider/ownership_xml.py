"""
talonx_ingest.intelligence.insider.ownership_xml
===============================================
Parse one SEC Form 3/4/5 ``<ownershipDocument>`` XML into the same
canonical ``InsiderFiling`` + ``InsiderTransaction`` objects the bulk
parser produces, so a filing seen through both routes deduplicates.

``xml.etree.ElementTree`` only -- no NLP, no external schema.
"""
from __future__ import annotations

import logging
from datetime import datetime
from xml.etree import ElementTree as ET

from talonx_ingest.intelligence.identity import normalize_accession
from talonx_ingest.intelligence.insider.config import XML_PARSE_TRANSFORM
from talonx_ingest.intelligence.insider.domain import (
    InsiderFiling,
    InsiderQualityFlag,
    InsiderTransaction,
    OwnershipFormType,
)
from talonx_ingest.intelligence.insider.normalize import (
    FilingContext,
    OwnerContext,
    RawTransactionRow,
    normalize_transaction,
    parse_date_any,
    resolve_ordinals,
    transaction_base_id,
)

logger = logging.getLogger("talonx_ingest.intelligence.insider.ownership_xml")

TRANSFORM = XML_PARSE_TRANSFORM


def _txt(node, path: str) -> str | None:
    if node is None:
        return None
    el = node.find(path)
    if el is None or el.text is None:
        return None
    v = el.text.strip()
    return v or None


def _val(node, path: str) -> str | None:
    """Ownership XML nests most values as ``<x><value>…</value></x>``; try
    that first, then the element's own text."""
    if node is None:
        return None
    el = node.find(path)
    if el is None:
        return None
    inner = el.find("value")
    if inner is not None and inner.text:
        return inner.text.strip() or None
    return (el.text or "").strip() or None


def _bool(node, path: str) -> bool:
    v = (_val(node, path) or _txt(node, path) or "").strip().lower()
    return v in ("1", "true", "y", "yes")


def _form_type(doc_type: str | None, is_amendment_hint: bool) -> tuple[OwnershipFormType, bool]:
    d = (doc_type or "4").strip().upper().replace(" ", "").replace("-A", "/A")
    if is_amendment_hint and not d.endswith("/A"):
        d = d + "/A"
    try:
        return OwnershipFormType(d), d.endswith("/A")
    except ValueError:
        return OwnershipFormType.UNKNOWN, d.endswith("/A")


def parse_ownership_xml(
    xml_text: str,
    *,
    accession: str,
    accepted_at_utc: datetime | None = None,
    event_id: str | None = None,
    symbol_hint: str | None = None,
    form_type_hint: str | None = None,
    source_reference: str | None = None,
    ingested_at_utc: datetime | None = None,
) -> tuple[InsiderFiling, list[InsiderTransaction]]:
    from talonx_ingest.intelligence.domain import utc_now

    now = ingested_at_utc or utc_now()
    acc = normalize_accession(accession)
    src = source_reference or f"SEC_EDGAR_ARCHIVES:{acc}"

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("ownership XML parse failed for %s: %s", acc, exc)
        filing = InsiderFiling(
            insider_filing_id=acc, accession=acc, event_id=event_id,
            symbol=(symbol_hint or "").upper(), issuer_cik="",
            form_type=OwnershipFormType.UNKNOWN, accepted_at_utc=accepted_at_utc,
            source_reference=src, ingested_at_utc=now,
            data_quality_flags=("ownership_xml_parse_failed",),
        )
        return filing, []

    doc_type = _txt(root, "documentType")
    period = parse_date_any(_txt(root, "periodOfReport"))
    # amendment ONLY from an explicit "/A" in documentType or the caller's
    # form-type hint. (aff10b5One is a Rule 10b5-1 plan indicator, NOT an
    # amendment marker.)
    is_amend_hint = "/A" in (doc_type or "") or (form_type_hint or "").upper().endswith("/A")
    form_type, is_amend = _form_type(doc_type or form_type_hint, is_amend_hint)

    issuer = root.find("issuer")
    issuer_cik = (_txt(issuer, "issuerCik") or "").strip()
    issuer_name = _txt(issuer, "issuerName") or ""
    symbol = (_txt(issuer, "issuerTradingSymbol") or symbol_hint or "").upper()

    owners: list[OwnerContext] = []
    for ro in root.findall("reportingOwner"):
        rel = ro.find("reportingOwnerRelationship")
        oid = ro.find("reportingOwnerId")
        owners.append(
            OwnerContext(
                owner_cik=(_txt(oid, "rptOwnerCik") or "").strip() or None,
                owner_name=_txt(oid, "rptOwnerName") or "",
                is_director=_bool(rel, "isDirector"),
                is_officer=_bool(rel, "isOfficer"),
                is_ten_percent_owner=_bool(rel, "isTenPercentOwner"),
                is_other=_bool(rel, "isOther"),
                officer_title=_txt(rel, "officerTitle"),
            )
        )
    if not owners:
        owners = [OwnerContext(owner_cik=None, owner_name="")]
    primary = owners[0]

    filed_date = None  # ownership XML has no filing_date element; comes from submissions/context
    fc_flags: list[str] = []
    if accepted_at_utc is None:
        fc_flags.append(InsiderQualityFlag.FILING_DATE_USED_AS_ACCEPTANCE.value)

    fc = FilingContext(
        accession=acc,
        issuer_cik=issuer_cik,
        symbol=symbol,
        company_name=issuer_name,
        form_type=form_type,
        is_amendment=is_amend,
        amends_accession=None,
        accepted_at_utc=accepted_at_utc,
        filing_date=filed_date,
        period_of_report=period,
        source_reference=src,
        event_id=event_id,
        flags=tuple(fc_flags),
    )

    raws: list[tuple[RawTransactionRow, OwnerContext]] = []
    nd = root.find("nonDerivativeTable")
    if nd is not None:
        for t in nd.findall("nonDerivativeTransaction"):
            raws.append((_nd_trans(t), primary))
        for h in nd.findall("nonDerivativeHolding"):
            raws.append((_nd_holding(h), primary))
    dv = root.find("derivativeTable")
    if dv is not None:
        for t in dv.findall("derivativeTransaction"):
            raws.append((_dv_trans(t), primary))

    if not raws and form_type in (OwnershipFormType.FORM_3, OwnershipFormType.FORM_3_A):
        raws.append((RawTransactionRow(is_holding=True), primary))

    base_ids = [transaction_base_id(raw, fc, oc) for raw, oc in raws]
    ordinals = resolve_ordinals(base_ids)
    txns = [
        normalize_transaction(raw, fc, oc, ordinal=o)
        for (raw, oc), o in zip(raws, ordinals)
    ]

    owner_ciks = tuple(dict.fromkeys(o.owner_cik for o in owners if o.owner_cik))
    filing = InsiderFiling(
        insider_filing_id=acc,
        accession=acc,
        event_id=event_id,
        symbol=symbol,
        issuer_cik=issuer_cik,
        company_name=issuer_name,
        form_type=form_type,
        is_amendment=is_amend,
        amends_accession=None,
        accepted_at_utc=accepted_at_utc,
        filing_date=filed_date,
        period_of_report=period,
        n_transactions=len(txns),
        n_owners=len(owner_ciks) or len(owners),
        owner_ciks=owner_ciks,
        owner_names=tuple(dict.fromkeys(o.owner_name for o in owners if o.owner_name)),
        source_reference=src,
        ingested_at_utc=now,
        data_quality_flags=tuple(fc_flags),
    )
    return filing, txns


def _nd_trans(t) -> RawTransactionRow:
    coding = t.find("transactionCoding")
    amt = t.find("transactionAmounts")
    post = t.find("postTransactionAmounts")
    own = t.find("ownershipNature")
    return RawTransactionRow(
        table="NONDERIVATIVE",
        is_holding=False,
        security_title=_val(t, "securityTitle"),
        transaction_date=_val(t, "transactionDate"),
        transaction_code=_txt(coding, "transactionCode"),
        acquired_disposed=_val(amt, "transactionAcquiredDisposedCode"),
        shares=_val(amt, "transactionShares"),
        price=_val(amt, "transactionPricePerShare"),
        shares_owned_after=_val(post, "sharesOwnedFollowingTransaction"),
        direct_indirect=_val(own, "directOrIndirectOwnership"),
        nature_of_ownership=_val(own, "natureOfOwnership"),
        amount_footnoted=amt is not None and amt.find(".//footnoteId") is not None,
    )


def _nd_holding(h) -> RawTransactionRow:
    post = h.find("postTransactionAmounts")
    own = h.find("ownershipNature")
    return RawTransactionRow(
        table="NONDERIVATIVE",
        is_holding=True,
        security_title=_val(h, "securityTitle"),
        shares_owned_after=_val(post, "sharesOwnedFollowingTransaction"),
        direct_indirect=_val(own, "directOrIndirectOwnership"),
        nature_of_ownership=_val(own, "natureOfOwnership"),
    )


def _dv_trans(t) -> RawTransactionRow:
    coding = t.find("transactionCoding")
    amt = t.find("transactionAmounts")
    post = t.find("postTransactionAmounts")
    own = t.find("ownershipNature")
    return RawTransactionRow(
        table="DERIVATIVE",
        is_holding=False,
        security_title=_val(t, "securityTitle"),
        transaction_date=_val(t, "transactionDate"),
        transaction_code=_txt(coding, "transactionCode"),
        acquired_disposed=_val(amt, "transactionAcquiredDisposedCode"),
        shares=_val(amt, "transactionShares"),
        price=_val(amt, "transactionPricePerShare"),
        shares_owned_after=_val(post, "sharesOwnedFollowingTransaction"),
        direct_indirect=_val(own, "directOrIndirectOwnership"),
        nature_of_ownership=_val(own, "natureOfOwnership"),
    )
