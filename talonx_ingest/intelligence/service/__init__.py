"""
talonx_ingest.intelligence.service
==================================
Task 96B — the **operational ingestion flow** that keeps the already-built
Risk & Event Intelligence product (96A/96C/96D/96E/96F/96G) continuously
fed from SEC EDGAR.

This package is strictly additive and self-contained:

* it *reads* the watchlist (`talonx_watchlist`) and *writes* only additive
  tables in the existing ``ingestion_ledger.db`` (via the 96A/96C/96D/96E
  stores and its own checkpoint/state tables);
* it never imports ``talonx_quant`` / ``talonx_core.decision`` /
  ``talonx_paper`` / ``talonx_piv`` / any order path;
* it runs as its **own** process (``python -m talonx_ingest.intelligence.service``),
  not through the trading engine.

Sub-modules
-----------
``config``            immutable ``ServiceConfig`` (+ ``from_env``)
``cik_directory``     symbol -> CIK -> company, SEC-sourced, disk-cached
``watchlist_source``  authoritative watchlist resolution report
``scope``             product-driven ``IngestionScope`` (symbols/forms/history)
``checkpoint_store``  resumable historical-backfill cursor state
``state_store``       per-event processing state machine persistence
``state_machine``     the ``ProcessingStage`` model + transitions
``retry``             retryable-vs-terminal error classification
``observability``     intelligence-only counters (kept apart from quant metrics)
``poller``            continuous incremental EDGAR polling
``backfill``          bounded, idempotent, resumable historical backfill
``enrichment``        drive 96C/96D/96E/96F for newly-stored events
``runner``            supervised service loop (singleton, heartbeat, priority)
``__main__``          CLI entrypoint: backfill / poll / once / status / replay
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "96b.1"
