"""
talonx_v2 -- Active Paper V2 lane:  INSIDER_BUY_CLUSTER_V2
========================================================

Additive, isolated strategy lane (same isolation posture as
``talonx_signals`` -- the Experimental lane).  It implements the frozen
Task 109 contract (``results/task109_v2_freeze/v2_strategy_contract.md``)
and routes through a Quant -> Brain -> decision -> Original-paper-engine ->
official dispatch -> dashboard -> EOD *sequence* on its own dedicated
Redis channels (``talonx:v2:*``) and its own SQLite ledger
(``v2_lane.db``).

Design decision (Task 110, recorded in the final report as a FINDING):
the five frozen Original services (``talonx_quant`` / ``talonx_brain`` /
``talonx_core`` / ``talonx_paper`` / ``talonx_dispatch``) are **not
modified**.  V2 reuses their *pure* primitives (``talonx_paper.engine``
math, ``talonx_ingest.intelligence.insider`` classification,
``talonx_dispatch.formatter.escape_markdown``, ``talonx_ops`` read models
+ ``OfficialExternalRouter``) and mirrors the flow with its own stage
modules.  This keeps ``PRODUCTION_STRATEGY_UNCHANGED`` and V1 output
bit-identical, verifiably, while still being the same architectural path.

Long only.  Paper only.  No shorts.  No real capital.  No paid data.
No runtime AI/ML.
"""

from talonx_v2.profile import ACTIVE_PROFILE_ENV, StrategyProfile, active_profile
from talonx_v2.config import V2Config, V2_VERSION

__all__ = [
    "StrategyProfile",
    "active_profile",
    "ACTIVE_PROFILE_ENV",
    "V2Config",
    "V2_VERSION",
]
