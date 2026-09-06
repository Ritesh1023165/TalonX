"""
talonx_v2.profile -- versioned strategy-profile selection (Phase 2 / 20)
======================================================================
The smallest safe profile-selection mechanism.  It does NOT fork the
runtime -- it only lets the system answer "which strategy profile is
active?" and lets V1 stay selectable and default.

Profiles
--------
ORIGINAL_V1            preserved, reproducible historical/control profile
                      (frozen thresholds 0.25 / 2 / 1.5 -- talonx_quant.config)
INSIDER_BUY_CLUSTER_V2 the Task 109 paper candidate
EXPERIMENTAL_V1        the pre-existing internal relaxed lane (talonx_signals)
                      -- listed for completeness, unchanged, still separate

Selection
---------
env ``TALONX_ACTIVE_STRATEGY_PROFILE`` -- default ``ORIGINAL_V1``.
Task 110 does NOT change the default.  A later task / Tuesday prep may
explicitly switch it.
"""
from __future__ import annotations

import os
from enum import Enum

ACTIVE_PROFILE_ENV = "TALONX_ACTIVE_STRATEGY_PROFILE"


class StrategyProfile(str, Enum):
    ORIGINAL_V1 = "ORIGINAL_V1"
    INSIDER_BUY_CLUSTER_V2 = "INSIDER_BUY_CLUSTER_V2"
    EXPERIMENTAL_V1 = "EXPERIMENTAL_V1"

    @property
    def is_v1(self) -> bool:
        return self is StrategyProfile.ORIGINAL_V1

    @property
    def is_v2(self) -> bool:
        return self is StrategyProfile.INSIDER_BUY_CLUSTER_V2


DEFAULT_PROFILE = StrategyProfile.ORIGINAL_V1


def active_profile(env: os._Environ | dict | None = None) -> StrategyProfile:
    """The currently-selected profile.  Unknown / unset -> ORIGINAL_V1
    (fail safe to the frozen baseline, never to V2)."""
    src = env if env is not None else os.environ
    raw = (src.get(ACTIVE_PROFILE_ENV) or "").strip().upper()
    if not raw:
        return DEFAULT_PROFILE
    try:
        return StrategyProfile(raw)
    except ValueError:
        return DEFAULT_PROFILE


def v1_is_selectable() -> bool:
    """V1 is always selectable -- it is never removed by V2 integration."""
    return True


def v2_is_selectable() -> bool:
    """V2 is selectable once talonx_v2 is importable (it always is here)."""
    return True
