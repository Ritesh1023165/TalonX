"""
talonx_ingest.intelligence.significance.domain
==============================================
Immutable value objects for the Information Significance Engine.

Hard rule: nothing here encodes a prediction, a direction, a probability of
a return, an expected return, an alpha/opportunity score or a
recommendation. ``score`` is an internal deterministic **attention** total,
not a probability and not a forecast. ``extra="forbid"`` rejects stray
fields.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from talonx_ingest.intelligence.domain import SignificanceBand
from talonx_ingest.intelligence.significance.config import (
    RULESET_VERSION,
    SIGNIFICANCE_SCHEMA_VERSION,
)

_FROZEN = ConfigDict(frozen=True, extra="forbid")

# keys / codes that must never appear in a component code or reason code --
# they would imply a predictive or directional claim.
_FORBIDDEN_CODE_TOKENS: frozenset[str] = frozenset(
    {
        "buy", "sell", "hold", "bullish", "bearish", "long", "short",
        "alpha", "edge", "opportunity", "conviction", "signal_strength",
        "expected_return", "target", "forecast", "outlook", "upside",
        "downside", "probability", "recommend",
    }
)


class SignificanceComponent(BaseModel):
    """One scoring category's contribution. The machine-readable half of
    explainability (Phase 14). ``points`` is already capped for the
    category; the raw pre-cap value is in ``raw_points`` for the audit."""

    model_config = _FROZEN

    code: str                       # e.g. "filing_change", "insider_activity"
    points: int                     # capped contribution to the score
    raw_points: int                 # pre-cap sum of this category's rule hits
    substantive: bool               # counts toward the HIGH/CRITICAL floor
    detail: str = ""                # language-safe machine description

    @field_validator("code")
    @classmethod
    def _clean_code(cls, v: str) -> str:
        low = v.strip().lower()
        bad = sorted(t for t in _FORBIDDEN_CODE_TOKENS if t in low)
        if bad:
            raise ValueError(f"component code implies a predictive claim: {bad}")
        return v


class SignificanceReason(BaseModel):
    """One human-facing explanation line. Every non-zero scoring rule hit
    produces exactly one of these; the sum of ``points`` across reasons
    equals the final ``score`` (Phase 14 invariant)."""

    model_config = _FROZEN

    code: str                       # stable machine code, e.g. "MATERIAL_8K_ITEM"
    description: str                # language-safe human text
    points: int                     # may be negative (quality penalty, score cap)
    component: str                  # owning component code
    evidence_ref: str | None = None  # comparison_id / transaction_id / "event_store:..." / accession

    @field_validator("code")
    @classmethod
    def _clean_code(cls, v: str) -> str:
        low = v.strip().lower()
        bad = sorted(t for t in _FORBIDDEN_CODE_TOKENS if t in low)
        if bad:
            raise ValueError(f"reason code implies a predictive claim: {bad}")
        return v


class InformationSignificance(BaseModel):
    """Canonical output. Immutable; a re-evaluation with the same
    ``significance_id`` upserts, never duplicates. A ``RULESET_VERSION``
    bump changes the id so history is preserved."""

    model_config = _FROZEN

    significance_id: str
    schema_version: str = SIGNIFICANCE_SCHEMA_VERSION
    ruleset_version: str = RULESET_VERSION

    event_id: str
    symbol: str

    score: int
    band: SignificanceBand
    raw_score: int                  # pre cap/floor, pre band-policy

    reasons: tuple[SignificanceReason, ...] = ()
    components: tuple[SignificanceComponent, ...] = ()

    substantive_points: int = 0
    substantive_families: int = 0

    data_quality_flags: tuple[str, ...] = ()
    inputs_present: tuple[str, ...] = ()      # "event" / "comparison" / "insider" / "watchlist"
    band_caps_applied: tuple[str, ...] = ()   # human-readable cap reasons

    input_fingerprint: str
    evaluated_at_utc: datetime

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    def reason_strings(self) -> tuple[str, ...]:
        """The ordered reason descriptions, for an ``AlertCard`` /
        ranking row."""
        return tuple(r.description for r in self.reasons)

    def points_check(self) -> bool:
        """Phase 14 invariant: reasons sum to the score."""
        return sum(r.points for r in self.reasons) == self.score
