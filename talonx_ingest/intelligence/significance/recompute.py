"""
talonx_ingest.intelligence.significance.recompute
================================================
Deterministic invalidation policy — *when* a stored significance must be
re-evaluated (``SIGNIFICANCE_RECOMPUTE_POLICY.md``).

A significance is recomputed when, and only when:

1. there is no stored score for the event under the current ruleset;
2. the stored ``ruleset_version`` differs from the current one
   (a reviewed weight/threshold change);
3. the recomputed ``input_fingerprint`` differs from the stored one —
   i.e. a *substantive* input changed: a ``FilingComparison`` arrived after
   the base event, an ``InsiderActivity`` gained transactions in the
   window, the watchlist/pinned state changed, a stale source recovered,
   or the rarity / simultaneous-event context moved across a band edge.

Recency (wall-clock ``now``) is deliberately NOT in the fingerprint, so
the passage of time alone never forces a recompute — the caller may still
re-evaluate opportunistically (e.g. on dashboard load) to refresh the
recency contribution.
"""
from __future__ import annotations

from dataclasses import dataclass

from talonx_ingest.intelligence.significance.config import RULESET_VERSION
from talonx_ingest.intelligence.significance.domain import InformationSignificance


@dataclass(frozen=True)
class RecomputeDecision:
    needed: bool
    reason: str


def needs_recompute(
    existing: InformationSignificance | None,
    *,
    new_fingerprint: str,
    ruleset_version: str = RULESET_VERSION,
) -> RecomputeDecision:
    if existing is None:
        return RecomputeDecision(True, "no stored significance for this event + ruleset")
    if existing.ruleset_version != ruleset_version:
        return RecomputeDecision(
            True,
            f"ruleset changed: stored {existing.ruleset_version!r} -> current {ruleset_version!r}",
        )
    if existing.input_fingerprint != new_fingerprint:
        return RecomputeDecision(True, "a substantive input changed (fingerprint mismatch)")
    return RecomputeDecision(False, "inputs and ruleset unchanged")
