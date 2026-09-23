"""
talonx_premarket -- broad-universe PRE-MARKET RESEARCH engine (research / alert lane only)
=========================================================================================
Scans a broad, auditable universe of US-listed common equities during the US pre-market,
computes explainable features (gap, activity, liquidity, structure, SEC catalysts), applies
hard DATA/SAFETY gates only for genuine invalidity, scores the rest with fixed weights, and
emits RESEARCH alerts (WATCH / BULLISH_SETUP / BEARISH_SETUP / MATERIAL_UPDATE / INVALIDATED),
then tracks post-open outcomes.

Boundaries (enforced by tests):
* never trades, never creates an order/intent, never touches a V2 ledger or V2 outbox;
* never emits a V2 TRADE_EVENT -- research alerts use the isolated RESEARCH destination only;
* nothing in the frozen V2 release imports this package;
* weights/thresholds are frozen in ``config.PREMARKET_RESEARCH_V1`` (fingerprinted) and were
  fixed BEFORE the 2026-09-23 shadow replay was run.
"""

ENGINE_NAME = "PREMARKET_RESEARCH"
