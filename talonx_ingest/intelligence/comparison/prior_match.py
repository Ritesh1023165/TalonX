"""
talonx_ingest.intelligence.comparison.prior_match
=================================================
Deterministic resolution of the *prior comparable filing* for a 10-Q /
10-K, from the Task 96A ``text_events`` store.

Rule (Task 95H/95I): the prior comparable filing is the most recent
**original** filing of the **same base form** (``10-Q`` for a 10-Q, ``10-K``
for a 10-K) whose ``acceptanceDateTime`` is strictly before the current
filing's. Amendments (``/A``) are never the base -- they are stored with
``form_type`` ``"10-Q/A"`` / ``"10-K/A"``, so an exact ``form_type ==
base`` query excludes them for free.

A 10-Q is never compared against a 10-K (and vice versa) for the primary
section-diff metrics.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from talonx_ingest.intelligence.comparison.config import PRIOR_MATCH_LOOKBACK
from talonx_ingest.intelligence.comparison.domain import ComparisonQualityFlag
from talonx_ingest.intelligence.domain import TextEvent
from talonx_ingest.intelligence.store import EventStore
from talonx_ingest.intelligence.taxonomy import base_form, is_amendment

_COMPARABLE_BASE_FORMS = ("10-Q", "10-K")


@dataclass(frozen=True)
class PriorMatchResult:
    current_event: TextEvent
    prior_event: TextEvent | None
    base_form: str
    flags: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""

    @property
    def has_prior(self) -> bool:
        return self.prior_event is not None


def resolve_prior_comparable(
    store: EventStore,
    current_event: TextEvent,
    *,
    lookback: int = PRIOR_MATCH_LOOKBACK,
) -> PriorMatchResult:
    base = base_form(current_event.form_type)
    flags: list[str] = []

    if base not in _COMPARABLE_BASE_FORMS:
        return PriorMatchResult(
            current_event,
            None,
            base,
            (ComparisonQualityFlag.PRIOR_FORM_MISMATCH.value,),
            f"current form {current_event.form_type!r} is not 10-Q/10-K",
        )

    if is_amendment(current_event.form_type):
        flags.append(ComparisonQualityFlag.AMENDMENT_INVOLVED.value)

    if current_event.accepted_at_utc is None:
        return PriorMatchResult(
            current_event,
            None,
            base,
            tuple(flags + [ComparisonQualityFlag.MISSING_PRIOR_FILING.value]),
            "current filing has no acceptance timestamp; cannot order a prior",
        )

    candidates = store.query_events(
        symbol=current_event.symbol,
        form_type=base,                       # exact -> excludes "10-Q/A" etc.
        until=current_event.accepted_at_utc,
        newest_first=True,
        limit=lookback + 2,
    )

    prior: TextEvent | None = None
    for cand in candidates:
        if cand.accession == current_event.accession:
            continue
        if cand.accepted_at_utc is None or cand.accepted_at_utc >= current_event.accepted_at_utc:
            continue
        prior = cand
        break

    if prior is None:
        return PriorMatchResult(
            current_event,
            None,
            base,
            tuple(
                flags
                + [
                    ComparisonQualityFlag.MISSING_PRIOR_FILING.value,
                    ComparisonQualityFlag.PRIOR_IS_FIRST_FILING.value,
                ]
            ),
            f"no prior original {base} for {current_event.symbol} before "
            f"{current_event.accepted_at_utc.isoformat()}",
        )

    return PriorMatchResult(
        current_event,
        prior,
        base,
        tuple(flags),
        f"prior = {prior.accession} ({base}) accepted {prior.accepted_at_utc.isoformat()}",
    )
