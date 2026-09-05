"""
talonx_ingest.intelligence.service.state_machine
================================================
The explicit per-event processing state model
(``INTELLIGENCE_PROCESSING_STATE_SPEC.md``).

One SEC filing flows:

    DISCOVERED
      -> NORMALIZED         (96A build_events_from_filing succeeded)
      -> STORED             (TextEvent persisted to the 96A EventStore)
      -> ENRICHMENT_PENDING (a downstream deterministic step is owed:
                             96C comparison for 10-Q/10-K, 96D insider parse
                             for Form 4)
      -> ENRICHED           (every owed enrichment step is done OR terminally
                             flagged with a quality flag)
      -> SIGNIFICANCE_EVALUATED  (96E evaluate_event persisted / confirmed)
      -> DELIVERY_QUEUED    (96F enqueue_card wrote a durable outbox row,
                             or delivery is intentionally suppressed/dry-run)
      -> COMPLETE

Off the happy path:

    PARTIAL           at least one stage is flagged incomplete but the base
                      event is preserved and the rest of the pipeline ran
    FAILED_RETRYABLE  a stage raised a transient error; retry_after is set
    FAILED_TERMINAL   a stage raised a data-quality / non-retryable error;
                      recorded, observable, not retried

The base ``STORED`` state is never rolled back by a later failure
(``FAILURE ISOLATION``, Phase 16): an enrichment failure moves the row to
PARTIAL / FAILED_*, it does not delete the TextEvent.
"""
from __future__ import annotations

from enum import Enum


class ProcessingStage(str, Enum):
    DISCOVERED = "DISCOVERED"
    NORMALIZED = "NORMALIZED"
    STORED = "STORED"
    ENRICHMENT_PENDING = "ENRICHMENT_PENDING"
    ENRICHED = "ENRICHED"
    SIGNIFICANCE_EVALUATED = "SIGNIFICANCE_EVALUATED"
    DELIVERY_QUEUED = "DELIVERY_QUEUED"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_TERMINAL = "FAILED_TERMINAL"


#: stages from which the pipeline still has work to do
OPEN_STAGES: frozenset[ProcessingStage] = frozenset(
    {
        ProcessingStage.DISCOVERED,
        ProcessingStage.NORMALIZED,
        ProcessingStage.STORED,
        ProcessingStage.ENRICHMENT_PENDING,
        ProcessingStage.ENRICHED,
        ProcessingStage.SIGNIFICANCE_EVALUATED,
        ProcessingStage.PARTIAL,
        ProcessingStage.FAILED_RETRYABLE,
    }
)

#: terminal-for-now stages the scheduler will not pick up again
CLOSED_STAGES: frozenset[ProcessingStage] = frozenset(
    {ProcessingStage.COMPLETE, ProcessingStage.DELIVERY_QUEUED, ProcessingStage.FAILED_TERMINAL}
)

#: linear "happy path" order — used to know how far a row got
HAPPY_PATH: tuple[ProcessingStage, ...] = (
    ProcessingStage.DISCOVERED,
    ProcessingStage.NORMALIZED,
    ProcessingStage.STORED,
    ProcessingStage.ENRICHMENT_PENDING,
    ProcessingStage.ENRICHED,
    ProcessingStage.SIGNIFICANCE_EVALUATED,
    ProcessingStage.DELIVERY_QUEUED,
    ProcessingStage.COMPLETE,
)


def stage_rank(stage: ProcessingStage) -> int:
    try:
        return HAPPY_PATH.index(stage)
    except ValueError:
        return -1


def is_open(stage: ProcessingStage) -> bool:
    return stage in OPEN_STAGES


def is_retryable(stage: ProcessingStage) -> bool:
    return stage in (
        ProcessingStage.FAILED_RETRYABLE,
        ProcessingStage.PARTIAL,
        ProcessingStage.ENRICHMENT_PENDING,
    )
