"""ERM nominee validation plumbing -- window / owner-decision configuration (NO data access here).

A ValidationConfig is immutable and canonically hashed. Owner decisions are explicit fields; a field left None is
OWNER_DECISION_PENDING and `require_decided()` rejects it. Nothing in this module selects a window or approves a decision.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date

HYPOTHESIS = "GAP_UP_10|SHORT|H10|L1"
SPEC = "ERM_NOMINEE_CORRECTION_SPEC_V2.1"
RULES_VERSION = "ERM_NOMINEE_CORRECTION_V2.1"

# Window presets (r8 §8). DEV is the development period, used only for implementation parity.
WINDOWS = {
    "DEV": (date(2019, 1, 2), date(2023, 12, 29)),
    "A": (date(2024, 1, 2), date(2024, 12, 31)),
    "B": (date(2024, 1, 2), date(2026, 9, 30)),
}
STOCK_COST_BPS = 30                      # frozen map C6 (L1), round trip
ETF_COST_SENSITIVITIES_BPS = (0, 12, 20)  # descriptive only, never gating
MIN_SAMPLE_FLOOR = {"n_valid": 100, "distinct_dates": 40}   # applies only if the owner adopts it


class OwnerDecisionPending(RuntimeError):
    """A required owner decision is not recorded."""


@dataclass(frozen=True)
class OwnerDecisions:
    """None = OWNER_DECISION_PENDING. Values are recorded owner answers, never defaults."""
    window: str | None = None                   # "A" | "B"
    task75_reserve_acknowledged: bool | None = None
    min_sample_floor_adopted: bool | None = None
    etf_cost_bps: float | None = None           # proposed 4 (unmeasured assumption)
    procedural_amendments_approved: bool | None = None
    decision_record: str | None = None          # reference to the owner's written decision (commit / document)

    def pending(self) -> list[str]:
        return [k for k, v in asdict(self).items() if v is None]


@dataclass(frozen=True)
class ValidationConfig:
    window_id: str                               # "DEV" (parity only) | "A" | "B"
    decisions: OwnerDecisions = field(default_factory=OwnerDecisions)

    @property
    def start(self) -> date:
        return WINDOWS[self.window_id][0]

    @property
    def end(self) -> date:
        return WINDOWS[self.window_id][1]

    def canonical(self) -> dict:
        return {"hypothesis": HYPOTHESIS, "spec": SPEC, "rules_version": RULES_VERSION, "window_id": self.window_id,
                "start": self.start.isoformat(), "end": self.end.isoformat(),
                "stock_cost_bps": STOCK_COST_BPS, "etf_cost_sensitivities_bps": list(ETF_COST_SENSITIVITIES_BPS),
                "min_sample_floor": MIN_SAMPLE_FLOOR, "decisions": asdict(self.decisions)}

    def config_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.canonical(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def require_decided(self) -> None:
        """Fail closed on every pending owner decision and on any inconsistency with the decided window."""
        if self.window_id not in WINDOWS:
            raise ValueError(f"unknown window {self.window_id!r}")
        if self.window_id == "DEV":
            raise OwnerDecisionPending("DEV is a parity configuration, never a validation window")
        p = self.decisions.pending()
        if p:
            raise OwnerDecisionPending("OWNER_DECISION_PENDING: " + ", ".join(p))
        if self.decisions.window != self.window_id:
            raise OwnerDecisionPending(f"configured window {self.window_id} != owner decision {self.decisions.window}")
        if self.decisions.task75_reserve_acknowledged is not True:
            raise OwnerDecisionPending("Task75 reserved windows lie inside every validation window: acknowledgement required")
        if self.decisions.procedural_amendments_approved is not True:
            raise OwnerDecisionPending("procedural amendments not approved")
