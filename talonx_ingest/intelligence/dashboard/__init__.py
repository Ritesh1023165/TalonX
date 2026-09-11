"""
talonx_ingest.intelligence.dashboard
====================================
The Event-Intelligence Dashboard — a read-only web surface over the
already-complete deterministic intelligence pipeline (Task 96A events,
96C ``what_changed``, 96D ``InsiderActivity``, 96E ``InformationSignificance``,
96F delivery semantics).

It creates **no new intelligence**: no recompute, no market-data fetch, no
significance logic, no direction, no AI, £0. Every page is generated from
the canonical stores through a thin read API and carries the standing
``PRODUCT_CLAIM_POLICY`` disclaimer.

Isolation: this package imports only the intelligence stores, the 96F
claim-safety scanner, ``aiohttp`` and stdlib — never ``redis`` /
``talonx_quant`` / ``talonx_core.decision`` / ``talonx_paper`` /
``talonx_piv`` / ``talonx_compare`` / ``talonx_dispatch`` / ``streamlit``.
"""
from talonx_ingest.intelligence.dashboard.config import NAV_PAGES, RULESET_VERSION
from talonx_ingest.intelligence.dashboard.readapi import IntelligenceReadAPI

__all__ = ["NAV_PAGES", "RULESET_VERSION", "IntelligenceReadAPI"]
