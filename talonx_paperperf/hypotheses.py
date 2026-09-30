"""
PRE-REGISTERED forward hypotheses (FROZEN). A registered hypothesis is never edited: a change is a NEW id with a new
fingerprint, and results are only ever reported for sessions >= its validation start. The git commit that adds a
hypothesis is the registration evidence (it precedes every validation outcome).

SQF_V1 -- "shadow quality filter", registered 2026-09-30 before the first 2026-09-30 PAPER_SIGNAL existed.
  HYPOTHESIS_SOURCE = IN_SAMPLE_DERIVED_FROM_2026-09-28_TO_2026-09-29 (exploratory strata of the profitability
  forensic; see docs/research/evidence/2026-09-30_profitability_forensic.md). Not validated by those sessions.
  PASS only if ALL hold (each failing condition is recorded; missing data is UNKNOWN_DATA, never silently dropped):
    * actionable entry available (first 1-min SIP bar at/after the Telegram SENT time)
    * measured SIP NBBO spread at the actionable entry <= 25 bps
    * ADV20 (the Signal's own feature, $) >= 20,000,000
    * catalyst is not 8-K-ONLY: every ';'-separated catalyst segment starting with "8-K" (6-K / other filings /
      insider evidence => not 8-K-only)
  Evaluation: long, actionable entry, fixed +30 min exit, cost = max(V2 20 bps round-trip friction, measured spread).
  Other horizons are descriptive only. The filter changes no live Signal and sends nothing.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

UNKNOWN_DATA = "UNKNOWN_DATA"


@dataclass(frozen=True)
class ShadowFilter:
    hypothesis_id: str
    registered_utc: str
    source: str
    validation_start: str
    min_forward_sessions: int
    max_spread_bps: float
    min_adv20_usd: float
    exclude_8k_only: bool
    horizon: str
    cost_model: str
    entry: str

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]

    def decide(self, row: dict) -> tuple[bool, list[str]]:
        """(pass, fail_reasons) for one CONTROL Signal row of the forensic dataset."""
        reasons = []
        if not row.get("act_entry_price"):
            reasons.append("NO_ACTIONABLE_ENTRY")
        sp = row.get("spread_bps")
        if sp is None:
            reasons.append(f"SPREAD_{UNKNOWN_DATA}")
        elif sp > self.max_spread_bps:
            reasons.append("SPREAD_GT_25BPS")
        adv = row.get("adv20_usd")
        if adv is None:
            reasons.append(f"ADV20_{UNKNOWN_DATA}")
        elif adv < self.min_adv20_usd:
            reasons.append("ADV20_LT_20M")
        if self.exclude_8k_only and is_8k_only(row.get("catalyst")):
            reasons.append("CATALYST_8K_ONLY")
        return (not reasons), reasons


def is_8k_only(catalyst: str | None) -> bool:
    segs = [s.strip() for s in (catalyst or "").split(";") if s.strip()]
    return bool(segs) and all(s.upper().startswith("8-K") for s in segs)


SQF_V1 = ShadowFilter(
    hypothesis_id="SQF_V1", registered_utc="2026-09-30T08:10:00+00:00",
    source="IN_SAMPLE_DERIVED_FROM_2026-09-28_TO_2026-09-29", validation_start="2026-09-30", min_forward_sessions=10,
    max_spread_bps=25.0, min_adv20_usd=20_000_000.0, exclude_8k_only=True, horizon="30",
    cost_model="max(V2 friction 20 bps round trip, measured SIP NBBO spread at actionable entry)",
    entry="open of first 1-min SIP bar at/after Telegram SENT (ceil minute); never backdated")

REGISTRY = {SQF_V1.hypothesis_id: SQF_V1}


def control_fingerprint(promotion_policy_fp: str, promotion_version: str, discovery_config_fp: str,
                        premarket_config_fp: str) -> str:
    """CONTROL = the unchanged live PAPER_SIGNAL pipeline, identified by its policy / code / config fingerprints."""
    blob = json.dumps({"PROMOTION_POLICY": promotion_policy_fp, "promotion_component": promotion_version,
                       "CONTINUOUS_RESEARCH": discovery_config_fp, "PREMARKET_RESEARCH_V1": premarket_config_fp},
                      sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
