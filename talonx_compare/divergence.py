"""Task 83 §2 -- divergence classification.

Given an aligned (Original, PIV) pair for one (trading_date, stage, symbol)
key, classify how -- if at all -- the two pipelines disagreed. Every
divergence falls into exactly one of these nine classes. Agreement here is
OPERATIONAL agreement only; it is explicitly NOT evidence about alpha or
profitability (see ``AGREEMENT_IS_NOT_ALPHA``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .identity import ComparisonRecord

# --- the nine divergence classes ---
FEED_INPUT_DIFFERENCE = "FEED_INPUT_DIFFERENCE"
READINESS_DIFFERENCE = "READINESS_DIFFERENCE"
FRESHNESS_EXCLUSION = "FRESHNESS_EXCLUSION"
QUANT_GATE_DIFFERENCE = "QUANT_GATE_DIFFERENCE"
DECISION_DIFFERENCE = "DECISION_DIFFERENCE"
ALERT_DELIVERY_DIFFERENCE = "ALERT_DELIVERY_DIFFERENCE"
EXECUTION_MODE_DIFFERENCE = "EXECUTION_MODE_DIFFERENCE"
LATE_OR_MISSING_STAGE = "LATE_OR_MISSING_STAGE"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"

DIVERGENCE_CLASSES = (
    FEED_INPUT_DIFFERENCE, READINESS_DIFFERENCE, FRESHNESS_EXCLUSION,
    QUANT_GATE_DIFFERENCE, DECISION_DIFFERENCE, ALERT_DELIVERY_DIFFERENCE,
    EXECUTION_MODE_DIFFERENCE, LATE_OR_MISSING_STAGE, SOURCE_UNAVAILABLE,
)

AGREEMENT_IS_NOT_ALPHA = (
    "Operational agreement/divergence measures whether the two runtimes "
    "processed the same inputs the same way. It is NOT a profitability, "
    "expectancy, or alpha signal. Strategy status: UNVALIDATED. "
    "Profitability: UNDETERMINED."
)

# which divergence class a given stage's disagreement maps to
_STAGE_CLASS = {
    "warmup": READINESS_DIFFERENCE,
    "readiness": READINESS_DIFFERENCE,
    "freshness": FRESHNESS_EXCLUSION,
    "quant": QUANT_GATE_DIFFERENCE,
    "brain": DECISION_DIFFERENCE,
    "core": DECISION_DIFFERENCE,
    "decision": DECISION_DIFFERENCE,
    "dispatch": ALERT_DELIVERY_DIFFERENCE,
    "telegram": ALERT_DELIVERY_DIFFERENCE,
    "shadow": EXECUTION_MODE_DIFFERENCE,
    "lifecycle": EXECUTION_MODE_DIFFERENCE,
    "reconciliation": EXECUTION_MODE_DIFFERENCE,
    "eod": EXECUTION_MODE_DIFFERENCE,
    "market": FEED_INPUT_DIFFERENCE,
}


@dataclass(frozen=True)
class Divergence:
    trading_date: str
    stage: str
    symbol: str
    divergence_class: str
    detail: str
    original_fingerprint: str | None
    piv_fingerprint: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trading_date": self.trading_date,
            "stage": self.stage,
            "symbol": self.symbol,
            "divergence_class": self.divergence_class,
            "detail": self.detail,
            "original_fingerprint": self.original_fingerprint,
            "piv_fingerprint": self.piv_fingerprint,
            "note": AGREEMENT_IS_NOT_ALPHA,
        }


def classify_divergence(
    original: ComparisonRecord | None,
    piv: ComparisonRecord | None,
    *,
    original_source_health_ok: bool = True,
    piv_source_health_ok: bool = True,
) -> Divergence | None:
    """Return a Divergence, or None if the pair genuinely agrees.

    Precedence:
      1. a required source was unavailable            -> SOURCE_UNAVAILABLE
      2. exactly one side has a record for this key   -> LATE_OR_MISSING_STAGE
      3. feed inputs (source_bar_time) differ         -> FEED_INPUT_DIFFERENCE
      4. execution classes differ                     -> EXECUTION_MODE_DIFFERENCE
      5. outcome / reason codes differ                -> stage-mapped class
      6. otherwise                                    -> agreement (None)
    """
    if not original_source_health_ok or not piv_source_health_ok:
        which = []
        if not original_source_health_ok:
            which.append("ORIGINAL")
        if not piv_source_health_ok:
            which.append("PIV")
        stage = (original or piv).stage if (original or piv) else "?"
        sym = (original or piv).symbol if (original or piv) else ""
        td = (original or piv).trading_date if (original or piv) else "?"
        return Divergence(td, stage, sym, SOURCE_UNAVAILABLE,
                          f"source health not OK for: {', '.join(which)}",
                          original.payload_fingerprint if original else None,
                          piv.payload_fingerprint if piv else None)

    if (original is None) ^ (piv is None):
        present = original or piv
        missing = "PIV" if original is not None else "ORIGINAL"
        return Divergence(present.trading_date, present.stage, present.symbol,
                          LATE_OR_MISSING_STAGE,
                          f"{missing} has no record for this (date, stage, symbol)",
                          original.payload_fingerprint if original else None,
                          piv.payload_fingerprint if piv else None)

    if original is None and piv is None:
        return None

    td, stage, sym = original.trading_date, original.stage, original.symbol

    if (original.source_bar_time or None) != (piv.source_bar_time or None):
        return Divergence(td, stage, sym, FEED_INPUT_DIFFERENCE,
                          f"source_bar_time differs: ORIGINAL={original.source_bar_time!r} "
                          f"PIV={piv.source_bar_time!r}",
                          original.payload_fingerprint, piv.payload_fingerprint)

    if original.execution_class != piv.execution_class:
        return Divergence(td, stage, sym, EXECUTION_MODE_DIFFERENCE,
                          f"execution_class differs: ORIGINAL={original.execution_class} "
                          f"PIV={piv.execution_class}",
                          original.payload_fingerprint, piv.payload_fingerprint)

    if original.payload_fingerprint == piv.payload_fingerprint:
        return None  # genuine agreement

    outcome_diff = original.decision_outcome != piv.decision_outcome
    codes_diff = original.reason_codes != piv.reason_codes
    if outcome_diff or codes_diff:
        klass = _STAGE_CLASS.get(stage, DECISION_DIFFERENCE)
        bits = []
        if outcome_diff:
            bits.append(f"outcome ORIGINAL={original.decision_outcome!r} PIV={piv.decision_outcome!r}")
        if codes_diff:
            bits.append(f"reason_codes ORIGINAL={list(original.reason_codes)} PIV={list(piv.reason_codes)}")
        return Divergence(td, stage, sym, klass, "; ".join(bits),
                          original.payload_fingerprint, piv.payload_fingerprint)

    # fingerprints differ but outcome + codes + feed + exec-class all match:
    # a payload-level difference in some non-identity field. Map to the
    # stage's class as the least-surprising bucket.
    return Divergence(td, stage, sym, _STAGE_CLASS.get(stage, DECISION_DIFFERENCE),
                      "payload fingerprint differs with matching outcome/codes/feed/exec-class",
                      original.payload_fingerprint, piv.payload_fingerprint)
