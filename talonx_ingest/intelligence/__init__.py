"""
talonx_ingest.intelligence
==========================
Event-intelligence foundation for the TalonX Risk & Event Intelligence
product (Task 96 product direction ``RISK_AND_EVENT_INTELLIGENCE_SYSTEM``).

This package is the canonical domain model and persistent event store for
causally-timestamped SEC disclosure events. It is deliberately isolated
from every trading path in the repository:

  * no import of ``talonx_quant`` / ``talonx_core.decision`` / ``talonx_paper``
    / ``talonx_piv``;
  * no Redis pub/sub, no ChromaDB, no order/execution code;
  * no predictive scoring, no BUY/SELL/direction/return output.

It ends at the event-store boundary. Delivery (Telegram, dashboard),
deterministic filing-diff analysis, insider aggregation and the
Information Significance engine are later, separately-authorised
workstreams (Task 96B+).

Sub-modules
-----------
``domain``           canonical ``TextEvent`` / ``AlertCard`` value objects + enums
``identity``         deterministic, restart-stable logical identity
``taxonomy``         deterministic ``form + items -> event_type`` mapping
``sessions``         ``accepted_at_utc -> BMO/RTH/AMC/NON_TRADING_DAY`` bucketing
``edgar_normalize``  raw EDGAR submissions record -> ``NormalizedFiling``
``store``            ``EventStore`` (additive tables in ``ingestion_ledger.db``)
``freshness``        per-source ``FRESH/STALE/UNKNOWN/DOWN`` state
``pipeline``         thin orchestrator: filings -> events -> store (no delivery)
``config``           freshness thresholds + transform-version constants
"""
from __future__ import annotations

from talonx_ingest.intelligence.domain import (
    AlertCard,
    DataQualityFlag,
    EvidenceRecord,
    ExhibitRef,
    FreshnessStatus,
    SessionBucket,
    SignificanceBand,
    SourceType,
    TextEvent,
)
from talonx_ingest.intelligence.domain import EventType

__all__ = [
    "AlertCard",
    "DataQualityFlag",
    "EventType",
    "EvidenceRecord",
    "ExhibitRef",
    "FreshnessStatus",
    "SessionBucket",
    "SignificanceBand",
    "SourceType",
    "TextEvent",
]
