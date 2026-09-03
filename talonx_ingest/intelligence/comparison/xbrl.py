"""
talonx_ingest.intelligence.comparison.xbrl
==========================================
First-filed XBRL numeric deltas (YoY / QoQ) for a filing comparison.

Causal-safety rule (Task 95C/95H/95I): for any ``(concept, unit, period
end)`` use the value from the **earliest** ``filed`` record -- never the
most-recently-filed one, which could be a later restatement. No analyst
consensus, no surprise, no forecast. Missing / ambiguous facts are
reported as such, never guessed.

Pure functions over the SEC ``companyconcept`` JSON shape
(``{"units": {"<unit>": [ {"start","end","val","fy","fp","form","filed","accn"} ]}}``).
The orchestrator does the fetching.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from talonx_ingest.intelligence.comparison.config import XBRL_FIELDS
from talonx_ingest.intelligence.comparison.domain import (
    ComparisonQualityFlag,
    XbrlChange,
    XbrlPeriodComparison,
)

_END_TOL_DAYS = 6            # current period-end fuzzy match
_YOY_OFFSET_DAYS = 365
_QOQ_OFFSET_DAYS = 91
_PRIOR_TOL_DAYS = 25        # how far a prior period-end may sit from the ideal offset
_DURATION_TOL_DAYS = 20    # flow-concept duration must match within this


@dataclass(frozen=True)
class _Fact:
    end: date
    start: date | None
    val: float
    filed: date
    accession: str | None
    form: str | None
    fp: str | None

    @property
    def duration_days(self) -> int | None:
        return (self.end - self.start).days if self.start else None


def _parse_date(s) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _facts(concept_json: dict | None, unit: str) -> list[_Fact]:
    if not isinstance(concept_json, dict):
        return []
    rows = (concept_json.get("units") or {}).get(unit) or []
    out: list[_Fact] = []
    for r in rows:
        end = _parse_date(r.get("end"))
        filed = _parse_date(r.get("filed"))
        if end is None or filed is None or "val" not in r:
            continue
        try:
            val = float(r["val"])
        except (TypeError, ValueError):
            continue
        out.append(
            _Fact(
                end=end,
                start=_parse_date(r.get("start")),
                val=val,
                filed=filed,
                accession=r.get("accn"),
                form=r.get("form"),
                fp=r.get("fp"),
            )
        )
    return out


def _first_filed_for_end(
    facts: list[_Fact],
    target_end: date,
    *,
    end_tol: int,
    want_duration: int | None,
) -> tuple[_Fact | None, bool]:
    """Return (fact, fuzzy_end_used). ``fact`` is the earliest-``filed``
    record whose ``end`` is within ``end_tol`` days of ``target_end`` and
    (for flow concepts) whose duration matches ``want_duration``."""
    cands: list[_Fact] = []
    for f in facts:
        if abs((f.end - target_end).days) > end_tol:
            continue
        if want_duration is not None and f.duration_days is not None:
            if abs(f.duration_days - want_duration) > _DURATION_TOL_DAYS:
                continue
        cands.append(f)
    if not cands:
        return None, False
    best_exact = [f for f in cands if f.end == target_end]
    pool = best_exact or cands
    chosen = min(pool, key=lambda f: (f.filed, f.end.isoformat()))
    return chosen, not bool(best_exact)


def compute_xbrl_changes(
    *,
    current_period_end: date | None,
    concept_data: dict[tuple[str, str], dict | None],
    base_form: str,
) -> tuple[XbrlChange, ...]:
    """``concept_data`` maps ``(taxonomy, concept)`` -> its companyconcept
    JSON (or ``None`` if the fetch found nothing). One YoY and one QoQ
    ``XbrlChange`` per field in ``XBRL_FIELDS`` (QoQ only for 10-Q)."""
    if current_period_end is None:
        return (
            XbrlChange(
                field="(all)",
                comparison=XbrlPeriodComparison.YOY,
                status="UNAVAILABLE",
                quality_flags=(ComparisonQualityFlag.XBRL_UNAVAILABLE.value,),
            ),
        )

    changes: list[XbrlChange] = []
    comparisons = [XbrlPeriodComparison.YOY]
    if base_form == "10-Q":
        comparisons.append(XbrlPeriodComparison.QOQ)

    for spec in XBRL_FIELDS:
        field = spec["field"]
        unit = spec["unit"]

        chosen_json = None
        chosen_key: tuple[str, str] | None = None
        for tax, concept in spec["concepts"]:
            j = concept_data.get((tax, concept))
            if _facts(j, unit):
                chosen_json, chosen_key = j, (tax, concept)
                break

        if chosen_json is None:
            for cmp in comparisons:
                changes.append(
                    XbrlChange(
                        field=field,
                        unit=unit,
                        comparison=cmp,
                        status="CONCEPT_MISSING",
                        quality_flags=(ComparisonQualityFlag.XBRL_CONCEPT_MISSING.value,),
                    )
                )
            continue

        facts = _facts(chosen_json, unit)
        # infer this field's typical quarterly duration (flow concepts have a start)
        durations = [f.duration_days for f in facts if f.duration_days is not None]
        want_dur = 91 if durations and min(durations) < 130 else None

        current_fact, cur_fuzzy = _first_filed_for_end(
            facts, current_period_end, end_tol=_END_TOL_DAYS, want_duration=want_dur
        )
        if current_fact is None:
            for cmp in comparisons:
                changes.append(
                    XbrlChange(
                        field=field, taxonomy=chosen_key[0], concept=chosen_key[1], unit=unit,
                        comparison=cmp, current_period_end=current_period_end,
                        status="CONCEPT_MISSING",
                        quality_flags=(ComparisonQualityFlag.XBRL_CONCEPT_MISSING.value,),
                    )
                )
            continue

        for cmp in comparisons:
            offset = _YOY_OFFSET_DAYS if cmp is XbrlPeriodComparison.YOY else _QOQ_OFFSET_DAYS
            target = date.fromordinal(current_fact.end.toordinal() - offset)
            prior_fact, prior_fuzzy = _first_filed_for_end(
                facts, target, end_tol=_PRIOR_TOL_DAYS, want_duration=want_dur
            )
            flags: list[str] = []
            if cur_fuzzy or prior_fuzzy:
                flags.append(ComparisonQualityFlag.PARSER_FALLBACK_USED.value)

            if prior_fact is None:
                changes.append(
                    XbrlChange(
                        field=field, taxonomy=chosen_key[0], concept=chosen_key[1], unit=unit,
                        comparison=cmp,
                        current_period_end=current_fact.end,
                        current_value=current_fact.val,
                        current_filed_accession=current_fact.accession,
                        current_filed_date=current_fact.filed,
                        status="NO_PRIOR",
                        quality_flags=tuple(flags),
                    )
                )
                continue

            # duration sanity for flow concepts
            if (
                want_dur is not None
                and current_fact.duration_days is not None
                and prior_fact.duration_days is not None
                and abs(current_fact.duration_days - prior_fact.duration_days) > _DURATION_TOL_DAYS
            ):
                changes.append(
                    XbrlChange(
                        field=field, taxonomy=chosen_key[0], concept=chosen_key[1], unit=unit,
                        comparison=cmp,
                        current_period_end=current_fact.end, current_value=current_fact.val,
                        prior_period_end=prior_fact.end, prior_value=prior_fact.val,
                        current_filed_accession=current_fact.accession,
                        prior_filed_accession=prior_fact.accession,
                        current_filed_date=current_fact.filed, prior_filed_date=prior_fact.filed,
                        status="PERIOD_MISMATCH",
                        quality_flags=tuple(
                            flags + [ComparisonQualityFlag.FISCAL_PERIOD_MISMATCH.value]
                        ),
                    )
                )
                continue

            abs_delta = current_fact.val - prior_fact.val
            rel_delta = (
                abs_delta / abs(prior_fact.val) if prior_fact.val not in (0, 0.0) else None
            )
            changes.append(
                XbrlChange(
                    field=field, taxonomy=chosen_key[0], concept=chosen_key[1], unit=unit,
                    comparison=cmp,
                    prior_period_end=prior_fact.end, current_period_end=current_fact.end,
                    prior_value=prior_fact.val, current_value=current_fact.val,
                    absolute_delta=abs_delta,
                    relative_delta=round(rel_delta, 6) if rel_delta is not None else None,
                    prior_filed_accession=prior_fact.accession,
                    current_filed_accession=current_fact.accession,
                    prior_filed_date=prior_fact.filed, current_filed_date=current_fact.filed,
                    status="FOUND",
                    quality_flags=tuple(flags),
                )
            )

    return tuple(changes)


def utc_today() -> date:
    return datetime.utcnow().date()
