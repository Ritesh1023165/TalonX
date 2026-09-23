"""
Frozen configuration for the pre-market research engine.

Every threshold and weight lives here, in one immutable object with a content fingerprint.
``PREMARKET_RESEARCH_V1`` was fixed before the 2026-09-23 shadow replay and must not be changed
in response to replay outcomes; a change is a new version with a new fingerprint.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class ScoreWeights:
    """Points per component (sum = 100). Each component is a 0..1 quality scaled by its weight."""
    gap: float = 30.0            # |gap| relative to the symbol's own typical daily range (ATR%)
    activity: float = 25.0       # pre-market share volume as a fraction of 20-session ADV
    liquidity: float = 15.0      # pre-market dollar volume (log-scaled)
    catalyst: float = 15.0       # SEC filing / insider evidence in the causal window
    structure: float = 10.0      # price outside the previous session's range in the gap direction
    data_confidence: float = 5.0  # number of pre-market bars behind the price

    def total(self) -> float:
        return self.gap + self.activity + self.liquidity + self.catalyst + self.structure + self.data_confidence


@dataclass(frozen=True)
class PremarketConfig:
    version: str = "PREMARKET_RESEARCH_V1"

    # ---- provider (verified empirically 2026-09-23; see DATA_CONTRACT.md) ----
    feed: str = "sip"                      # IEX has no extended-hours bars; SIP does
    sip_delay_minutes: int = 15            # subscription: SIP data newer than 15 min is refused (HTTP 403)
    adjustment: str = "split"
    bars_symbols_per_request: int = 200
    bars_page_limit: int = 10000
    max_requests_per_minute: int = 180     # Alpaca data API limit is 200/min; keep headroom
    daily_lookback_sessions: int = 25

    # ---- session phases (America/New_York wall clock; derived via the XNYS calendar) ----
    premarket_start_et: str = "04:00"
    core_start_et: str = "07:00"
    near_open_start_et: str = "09:00"
    scan_interval_early_s: int = 900
    scan_interval_core_s: int = 300
    scan_interval_near_open_s: int = 300

    # ---- HARD gates: genuine invalidity only ----
    min_daily_sessions: int = 5            # need a previous close and a minimal history
    min_prev_close: float = 1.00           # sub-$1 prints are not researchable setups
    min_adv_dollar_20d: float = 1_000_000  # clearly insufficient liquidity
    max_premarket_staleness_min: int = 45  # last pre-market print older than this vs data as-of -> stale
    max_abs_gap_pct: float = 300.0         # beyond this treat as a bad print / unadjusted corporate action

    # ---- score scaling (component reaches 1.0 at these levels) ----
    gap_atr_multiple_full: float = 1.5
    activity_adv_fraction_full: float = 0.10
    liquidity_dollars_zero: float = 1e5
    liquidity_dollars_full: float = 1e7
    data_bars_full: int = 20
    catalyst_strong: float = 1.0           # 8-K / earnings / 2+ insider open-market buyers
    catalyst_other: float = 0.6            # any other SEC filing in the window

    # ---- classification ----
    watch_min_abs_gap_pct: float = 2.0
    watch_min_score: float = 40.0
    setup_min_abs_gap_pct: float = 3.0
    setup_min_score: float = 60.0
    setup_min_premarket_dollars: float = 500_000

    # ---- alert policy / dedup ----
    material_update_score_delta: float = 15.0
    material_update_gap_delta_pct: float = 3.0
    material_update_min_interval_s: int = 1800
    invalidate_abs_gap_below_pct: float = 1.0
    max_new_alerts_per_session: int = 25

    # ---- post-open confirmation ----
    confirm_horizon_min: int = 30

    weights: ScoreWeights = field(default_factory=ScoreWeights)

    def as_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        blob = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


PREMARKET_RESEARCH_V1 = PremarketConfig()
