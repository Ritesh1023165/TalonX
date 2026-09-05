"""
talonx_ingest.intelligence.insider
==================================
Task 96D -- deterministic insider-activity intelligence from SEC Form
3/4/5 ownership filings.

    SEC Form 3/4/5  (quarterly bulk TSV  |  per-filing ownership XML)
          │
          ├─ parse ─ classify code ─ normalise role ─ value ────┐
          │                                                     │
          └────────────────────────── canonical InsiderTransaction
                                                                │
                     rolling open-market (P/S) aggregates ┐     │
                     clusters ┐  role subsets ┐            │     │
                              └──────────────┴────────────┴─────┴─ InsiderActivity

It answers *"what insider activity was reported, by whom, of what type,
and at what scale?"* and **never** *"what will the stock do?"* -- there is
no predictive, directional, sentiment, expected-return or "insider alpha"
field anywhere in this package, and machine-generated labels are
lint-checked (`language_safety`).

Deterministic (regex + arithmetic only), causal (condition on the filing's
acceptance instant, not the transaction date), explainable (every value
carries an `EvidenceRecord`), £0, no AI/NLP.

Additive: it reads / writes its own `insider_*` tables in the same SQLite
file the Task 96A `EventStore` uses, links each filing to an
`INSIDER_TRANSACTION` `text_events` parent event, and touches no trading
module.
"""
from __future__ import annotations

from talonx_ingest.intelligence.insider.domain import (
    AcquiredDisposed,
    InsiderActivity,
    InsiderCluster,
    InsiderFiling,
    InsiderQualityFlag,
    InsiderRole,
    InsiderTransaction,
    OwnershipFormType,
    OwnershipNature,
    RoleSubsetAggregate,
    RollingOpenMarketAggregate,
    TransactionClass,
)

__all__ = [
    "AcquiredDisposed",
    "InsiderActivity",
    "InsiderCluster",
    "InsiderFiling",
    "InsiderQualityFlag",
    "InsiderRole",
    "InsiderTransaction",
    "OwnershipFormType",
    "OwnershipNature",
    "RoleSubsetAggregate",
    "RollingOpenMarketAggregate",
    "TransactionClass",
]
