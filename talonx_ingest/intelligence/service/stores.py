"""
talonx_ingest.intelligence.service.stores
=========================================
``StoreBundle`` — opens every canonical intelligence store (96A/96C/96D/96E
+ 96F outbox) and this service's own checkpoint/state stores against ONE
ledger path, and closes them together.

All of these are additive-table stores in the same ``ingestion_ledger.db``;
opening them here does not migrate or mutate any existing table.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from talonx_ingest.config import settings
from talonx_ingest.intelligence.comparison.store import FilingComparisonStore
from talonx_ingest.intelligence.delivery.outbox import DeliveryOutbox
from talonx_ingest.intelligence.insider.store import InsiderStore
from talonx_ingest.intelligence.service.checkpoint_store import BackfillCheckpointStore
from talonx_ingest.intelligence.service.state_store import ProcessingStateStore
from talonx_ingest.intelligence.significance.store import SignificanceStore
from talonx_ingest.intelligence.store import EventStore


@dataclass
class StoreBundle:
    ledger_path: str
    events: EventStore
    comparisons: FilingComparisonStore
    insider: InsiderStore
    significance: SignificanceStore
    outbox: DeliveryOutbox
    checkpoints: BackfillCheckpointStore
    processing: ProcessingStateStore

    @classmethod
    def open(cls, ledger_path: str | Path | None = None) -> "StoreBundle":
        lp = str(ledger_path or settings.ledger.path)
        return cls(
            ledger_path=lp,
            events=EventStore(lp),
            comparisons=FilingComparisonStore(lp),
            insider=InsiderStore(lp),
            significance=SignificanceStore(lp),
            outbox=DeliveryOutbox(lp),
            checkpoints=BackfillCheckpointStore(lp),
            processing=ProcessingStateStore(lp),
        )

    def close(self) -> None:
        for s in (
            self.events, self.comparisons, self.insider, self.significance,
            self.outbox, self.checkpoints, self.processing,
        ):
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "StoreBundle":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
