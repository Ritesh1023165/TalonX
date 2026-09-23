"""
talonx_ingest.intelligence.sec_time -- resolve SEC submissions-feed acceptance instants
=====================================================================================
Session 03 finding A2. ``data.sec.gov/submissions`` serves a fresh filing's
``acceptanceDateTime`` as the **New York wall clock labelled ``Z``** and re-renders
the same filing as the **true UTC** instant roughly 5.4-5.7 h after acceptance
(evidence: ``docs/research/evidence/v2_sec_filing_date_release_fix/TIMESTAMP_SEMANTICS.md``;
425-filing sample: every value observed <= 342.8 min after acceptance was ET-labelled,
every value observed >= 324.7 min after was true UTC). The stored ``accepted_at_utc``
therefore has MIXED semantics that depend on when TalonX observed it.

This module decides, for DISPLAY purposes only, which rendering a stored value was,
using facts TalonX already holds:

* ``raw``          -- the stored value (whatever SEC served, parsed as if UTC)
* ``observed_at``  -- when TalonX read it (``ingested_at_utc``; true UTC)
* ``filing_date``  -- SEC ``filingDate`` (the ET calendar day of acceptance)

It never guesses: when the evidence does not single out one rendering it returns
``AMBIGUOUS`` and callers show the filing date with "acceptance time unverified".
It is NOT used by V2 admission (V2 uses ``filing_date`` for dates and the untouched
legacy value for its loose dissemination guard -- see ``talonx_v2/form4_source.py``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

BASIS_TRUE_UTC = "TRUE_UTC_RENDERING"
BASIS_ET_LABELLED_Z = "ET_WALL_CLOCK_LABELLED_Z"
BASIS_AMBIGUOUS = "AMBIGUOUS"
BASIS_UNKNOWN = "UNKNOWN"

# SEC re-render window, from the 425-filing sample (min observed UTC rendering 324.7 min,
# max observed ET rendering 342.8 min). Margins widen the window outward, so a value is
# only classified when it falls clearly outside the band SEC could have rendered either way.
MIN_AGE_FOR_UTC_RENDERING = timedelta(minutes=315)
MAX_AGE_FOR_ET_RENDERING = timedelta(minutes=360)
CLOCK_SKEW = timedelta(minutes=2)


@dataclass(frozen=True)
class ResolvedAcceptance:
    utc: datetime | None          # the true acceptance instant, or None when not determinable
    basis: str                    # one of the BASIS_* constants
    raw: datetime | None          # the stored value, exactly as held (provenance)
    filing_date: date | None

    @property
    def new_york(self) -> datetime | None:
        return self.utc.astimezone(NY) if self.utc else None


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _et_label_to_utc(raw: datetime) -> datetime:
    """Treat the wall-clock digits of ``raw`` as America/New_York (DST-aware)."""
    naive = _as_utc(raw).replace(tzinfo=None)
    return naive.replace(tzinfo=NY).astimezone(timezone.utc)


def _plausible(candidate: datetime, *, rendered_as_utc: bool, observed_at: datetime | None,
               filing_date: date | None) -> bool:
    if filing_date is not None and candidate.astimezone(NY).date() != filing_date:
        return False
    if observed_at is None:
        return True
    age = observed_at - candidate
    if age < -CLOCK_SKEW:
        return False                      # accepted after we saw it: impossible
    if rendered_as_utc:
        return age >= MIN_AGE_FOR_UTC_RENDERING
    return age <= MAX_AGE_FOR_ET_RENDERING


def resolve_acceptance(raw: datetime | None, *, observed_at: datetime | None,
                       filing_date: date | None = None) -> ResolvedAcceptance:
    if raw is None:
        return ResolvedAcceptance(None, BASIS_UNKNOWN, None, filing_date)
    raw = _as_utc(raw)
    observed_at = _as_utc(observed_at) if observed_at is not None else None
    as_utc = raw
    as_et = _et_label_to_utc(raw)
    ok_utc = _plausible(as_utc, rendered_as_utc=True, observed_at=observed_at, filing_date=filing_date)
    ok_et = _plausible(as_et, rendered_as_utc=False, observed_at=observed_at, filing_date=filing_date)
    if ok_utc and not ok_et:
        return ResolvedAcceptance(as_utc, BASIS_TRUE_UTC, raw, filing_date)
    if ok_et and not ok_utc:
        return ResolvedAcceptance(as_et, BASIS_ET_LABELLED_Z, raw, filing_date)
    return ResolvedAcceptance(None, BASIS_AMBIGUOUS, raw, filing_date)


def format_acceptance(res: ResolvedAcceptance) -> str:
    """Operator text. Never labels a New York wall clock as UTC."""
    if res.utc is not None:
        ny = res.new_york
        return (f"SEC accepted {ny:%Y-%m-%d %H:%M:%S} ET "
                f"({res.utc:%Y-%m-%d %H:%M:%S} UTC)")
    if res.filing_date is not None:
        return f"SEC filing date {res.filing_date.isoformat()} (acceptance time unverified)"
    return "SEC acceptance time unknown"
