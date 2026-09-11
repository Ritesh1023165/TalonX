"""
talonx_ingest.intelligence.taxonomy
===================================
Deterministic ``form + items -> event_type`` classification. Pure
functions, no I/O, no NLP. A filing whose items map to nothing known is
still classified (``UNCLASSIFIED_8K`` / ``FILING_AMENDMENT`` /
``UNSUPPORTED_FORM``) and flagged -- never dropped.

A single 8-K carrying several material items yields several
``EventClassification`` results, one per distinct ``event_type``. Every
raw item code is returned in ``all_items`` regardless.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from talonx_ingest.intelligence.domain import DataQualityFlag, EventType

# 8-K item code -> event type. Item 9.01 ("Financial Statements and
# Exhibits") is an exhibit carrier, not a standalone event -- it is
# recorded in all_items but never classifies on its own.
_ITEM_MAP: dict[str, EventType] = {
    "1.01": EventType.MATERIAL_AGREEMENT,
    "1.02": EventType.AGREEMENT_TERMINATED,
    "1.03": EventType.OTHER_MATERIAL_EVENT,   # bankruptcy / receivership
    "2.01": EventType.ACQUISITION_DISPOSITION,
    "2.02": EventType.EARNINGS_RESULTS,
    "2.03": EventType.DEBT_FINANCING,
    "2.04": EventType.DEBT_FINANCING,          # triggering events on an obligation
    "2.05": EventType.RESTRUCTURING,
    "2.06": EventType.MATERIAL_IMPAIRMENT,
    "3.01": EventType.DELISTING_NOTICE,
    "3.02": EventType.UNREGISTERED_EQUITY_SALE,
    "3.03": EventType.OTHER_MATERIAL_EVENT,   # modification of security-holder rights
    "4.01": EventType.OTHER_MATERIAL_EVENT,   # change in certifying accountant
    "4.02": EventType.OTHER_MATERIAL_EVENT,   # non-reliance on prior financials
    "5.01": EventType.OTHER_MATERIAL_EVENT,   # change in control
    "5.02": EventType.EXECUTIVE_CHANGE,
    "5.03": EventType.CHARTER_BYLAW_AMENDMENT,
    "5.07": EventType.SHAREHOLDER_VOTE_RESULT,
    "7.01": EventType.REGULATION_FD,
    "8.01": EventType.OTHER_MATERIAL_EVENT,
}

_EXHIBIT_CARRIER_ITEMS = frozenset({"9.01"})

_PERIODIC_MAP: dict[str, EventType] = {
    "10-Q": EventType.QUARTERLY_FILING,
    "10-K": EventType.ANNUAL_FILING,
}

_INSIDER_FORMS = frozenset({"3", "4", "5"})

_ITEM_TOKEN_RE = re.compile(r"(\d{1,2}\.\d{2})")


@dataclass(frozen=True)
class EventClassification:
    event_type: EventType
    triggering_items: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClassificationResult:
    classifications: tuple[EventClassification, ...]
    all_items: tuple[str, ...]
    is_amendment: bool
    flags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def event_types(self) -> tuple[EventType, ...]:
        return tuple(c.event_type for c in self.classifications)


def is_amendment(form: str) -> bool:
    return str(form or "").strip().upper().endswith("/A")


def base_form(form: str) -> str:
    """``8-K/A`` -> ``8-K``. Case/space tolerant."""
    f = str(form or "").strip().upper()
    return f[:-2] if f.endswith("/A") else f


def normalize_items(items: Iterable[str] | str | None) -> tuple[str, ...]:
    """Accepts a list, a comma/space-joined string, or ``None``. Returns
    canonical ``X.YY`` codes, order preserved, de-duplicated. Tolerates
    ``"Item 2.02"``, ``"2.02,9.01"``, ``["2.02", "9.01"]``."""
    if items is None:
        return ()
    if isinstance(items, str):
        raw_tokens = re.split(r"[,\s;]+", items)
    else:
        raw_tokens: list[str] = []
        for entry in items:
            raw_tokens.extend(re.split(r"[,\s;]+", str(entry)))
    out: list[str] = []
    for tok in raw_tokens:
        m = _ITEM_TOKEN_RE.search(tok)
        if not m:
            continue
        code = m.group(1)
        if len(code.split(".")[0]) == 1:  # normalise "2.02" already fine; keep as-is
            pass
        if code not in out:
            out.append(code)
    return tuple(out)


def classify_filing(form: str, items: Iterable[str] | str | None) -> ClassificationResult:
    """Deterministic classification of one filing."""
    amend = is_amendment(form)
    bform = base_form(form)
    all_items = normalize_items(items)
    flags: list[str] = []
    if amend:
        flags.append(DataQualityFlag.AMENDMENT.value)

    # ---- periodic ---------------------------------------------------
    if bform in _PERIODIC_MAP:
        return ClassificationResult(
            classifications=(EventClassification(_PERIODIC_MAP[bform]),),
            all_items=all_items,
            is_amendment=amend,
            flags=tuple(flags),
        )

    # ---- insider (enum reserved; no pipeline in 96A) --------------
    if bform in _INSIDER_FORMS:
        return ClassificationResult(
            classifications=(EventClassification(EventType.INSIDER_TRANSACTION),),
            all_items=all_items,
            is_amendment=amend,
            flags=tuple(flags),
        )

    # ---- 8-K -----------------------------------------------------
    if bform == "8-K":
        material = [c for c in all_items if c not in _EXHIBIT_CARRIER_ITEMS]
        if not all_items:
            flags.append(DataQualityFlag.MISSING_ITEM_METADATA.value)
        recognised: list[EventClassification] = []
        seen_types: set[EventType] = set()
        unknown_material: list[str] = []
        for code in material:
            et = _ITEM_MAP.get(code)
            if et is None:
                unknown_material.append(code)
                continue
            if et in seen_types:
                # merge triggering items into the existing classification
                recognised = [
                    EventClassification(
                        c.event_type,
                        c.triggering_items + (code,) if c.event_type == et else c.triggering_items,
                    )
                    for c in recognised
                ]
                continue
            seen_types.add(et)
            recognised.append(EventClassification(et, (code,)))

        if unknown_material:
            flags.append(DataQualityFlag.NON_STANDARD_ITEM_CODE.value)
        if len(recognised) > 1:
            flags.append(DataQualityFlag.MULTI_ITEM_FILING.value)

        if recognised:
            return ClassificationResult(
                classifications=tuple(recognised),
                all_items=all_items,
                is_amendment=amend,
                flags=tuple(flags),
            )

        # nothing recognised
        fallback = EventType.FILING_AMENDMENT if amend else EventType.UNCLASSIFIED_8K
        return ClassificationResult(
            classifications=(EventClassification(fallback, tuple(unknown_material)),),
            all_items=all_items,
            is_amendment=amend,
            flags=tuple(flags),
        )

    # ---- anything else ----------------------------------------
    flags.append(DataQualityFlag.UNSUPPORTED_FORM.value)
    return ClassificationResult(
        classifications=(EventClassification(EventType.UNSUPPORTED_FORM),),
        all_items=all_items,
        is_amendment=amend,
        flags=tuple(flags),
    )
