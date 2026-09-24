"""
Versioned, fingerprinted configuration for the continuous engine.

``CONTINUOUS_RESEARCH_V1`` EMBEDS the frozen ``PREMARKET_RESEARCH_V1`` (weights, thresholds, hard gates incl. the
45-minute stale-price gate, lifecycle deltas) UNCHANGED. It adds only phase mechanics, pre-registered 2026-09-24
BEFORE any continuous-engine outcome existed (never tuned on Session-04 hindsight):

* cadence per phase (PREMARKET reuses V1's EARLY/CORE/NEAR_OPEN cadence exactly);
* ``stale_invalidates_phases``: where a STALE observation may INVALIDATE an existing identity. V1 only ever ran in
  PREMARKET, where thin prints are exceptional. After the close, thin/absent prints are the normal liquidity context,
  so in AFTER_HOURS a stale observation HOLDS the identity (no transition) instead of closing it. The stale gate
  itself is unchanged: a stale symbol can never CREATE a candidate in any phase;
* ``expire_after_idle_windows``: an identity not observed as alert-worthy for a whole trading window is closed as
  EXPIRED (a lifecycle bookkeeping state, never notified, never INVALIDATED).

Features in REGULAR / AFTER_HOURS are the same V1 feature definitions computed over the window-to-date extended
session (04:00 ET -> data as-of), reference = previous session close. That is new *semantics* (not a tuning) and
is why this config has its own version + fingerprint; PREMARKET classification is identical to V1 (tested).

``LAB_NOTIFY_POLICY_V1`` is the attention budget -- the ONLY place a Telegram budget exists. It never alters
detection, persistence or lifecycle.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from talonx_premarket.config import PREMARKET_RESEARCH_V1, PremarketConfig


def _fp(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ContinuousResearchConfig:
    version: str = "CONTINUOUS_RESEARCH_V1"
    base: PremarketConfig = field(default_factory=lambda: PREMARKET_RESEARCH_V1)
    regular_scan_interval_s: int = 300
    after_hours_scan_interval_s: int = 300
    unavailable_poll_s: int = 300
    stale_invalidates_phases: tuple[str, ...] = ("PREMARKET", "REGULAR")
    expire_after_idle_windows: int = 1
    feature_window: str = "EXTENDED_SESSION_TO_DATE_FROM_0400_ET"
    reference_price: str = "PREVIOUS_SESSION_CLOSE"
    outcome_model_pre_open: str = "PREMARKET_RESEARCH_V1.measure"
    outcome_model_post_open: str = "SINCE_FIRST_SEEN_V1"

    def as_dict(self) -> dict:
        d = asdict(self)
        d["base"] = {"version": self.base.version, "fingerprint": self.base.fingerprint()}
        return d

    def fingerprint(self) -> str:
        return _fp(self.as_dict())


@dataclass(frozen=True)
class NotificationPolicy:
    """Attention routing only. Budget values are configuration, NOT evidence-derived: the total keeps V1's 25 for a
    controlled comparison; ``setup_reserved`` guarantees WATCH can never consume the capacity later BULLISH/BEARISH
    setups need (WATCH may use at most total - reserved). No time-of-day buckets."""
    version: str = "LAB_NOTIFY_POLICY_V1"
    budget_scope: str = "TRADING_WINDOW"
    total_new_per_window: int = 25
    setup_reserved: int = 10
    priority: tuple[str, ...] = ("BULLISH_SETUP", "BEARISH_SETUP", "WATCH")
    material_update_only_if_surfaced: bool = True
    invalidated_only_if_surfaced: bool = True
    upgrade_of_unsurfaced_counts_as_new: bool = True
    deliver_by_minutes: int = 30
    phases_enabled: tuple[str, ...] = ("OVERNIGHT", "PREMARKET", "REGULAR", "AFTER_HOURS")

    def as_dict(self) -> dict:
        return asdict(self)

    def fingerprint(self) -> str:
        return _fp(self.as_dict())


CONTINUOUS_RESEARCH_V1 = ContinuousResearchConfig()
LAB_NOTIFY_POLICY_V1 = NotificationPolicy()
