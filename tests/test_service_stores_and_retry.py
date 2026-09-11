"""
tests/test_service_stores_and_retry.py
--------------------------------------
Task 96B — checkpoint store (Gate C: resumable + idempotent), processing
state store (Gate L: partial/retry/terminal observable), retry policy
(Gate N), state-machine invariants.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from talonx_ingest.intelligence.service.checkpoint_store import BackfillCheckpointStore
from talonx_ingest.intelligence.service.retry import (
    RetryClass,
    backoff_seconds,
    classify_error,
)
from talonx_ingest.intelligence.service.state_machine import (
    CLOSED_STAGES,
    OPEN_STAGES,
    ProcessingStage,
    stage_rank,
)
from talonx_ingest.intelligence.service.state_store import ProcessingStateStore


# ---------------------------------------------------------------------------
# retry
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,expected",
    [
        ("HTTP 429 Too Many Requests", RetryClass.RETRYABLE),
        ("GET x -> 503", RetryClass.RETRYABLE),
        ("asyncio.TimeoutError: timed out", RetryClass.RETRYABLE),
        ("sqlite3.OperationalError: database is locked", RetryClass.RETRYABLE),
        ("Exhausted 4 retries for https://data.sec.gov/...", RetryClass.RETRYABLE),
        ("EdgarClientError: Ticker 'ZZZZ' not found in SEC ticker map", RetryClass.TERMINAL),
        ("unsupported form 20-F", RetryClass.TERMINAL),
        ("GET x -> 404: not found", RetryClass.TERMINAL),
        ("no comparable prior filing exists", RetryClass.TERMINAL),
    ],
)
def test_classify_error(text, expected):
    assert classify_error(text).cls is expected


def test_backoff_is_monotone_and_capped():
    a = [backoff_seconds(i, base=30, cap=3600) for i in range(1, 10)]
    assert a == sorted(a)
    assert a[-1] <= 3600


# ---------------------------------------------------------------------------
# state machine
# ---------------------------------------------------------------------------
def test_stage_sets_partition():
    assert OPEN_STAGES.isdisjoint(CLOSED_STAGES)
    assert ProcessingStage.COMPLETE in CLOSED_STAGES
    assert ProcessingStage.FAILED_RETRYABLE in OPEN_STAGES
    assert stage_rank(ProcessingStage.COMPLETE) > stage_rank(ProcessingStage.STORED)
    assert stage_rank(ProcessingStage.PARTIAL) == -1


# ---------------------------------------------------------------------------
# checkpoint store
# ---------------------------------------------------------------------------
def test_checkpoint_resume_and_idempotency(tmp_path):
    db = tmp_path / "l.db"
    cp = BackfillCheckpointStore(db)
    cp.ensure("AAPL", "edgar_submissions", "10-Q", cik="0000320193", history_start="2024-01-01")
    cp.record_attempt("AAPL", "edgar_submissions", "10-Q")
    cp.record_progress(
        "AAPL", "edgar_submissions", "10-Q",
        earliest_processed_date="2024-02-01", latest_processed_date="2026-06-01",
        last_accession="0000320193-26-000009", filings_seen_delta=5, events_written_delta=5,
        completed=True, clear_error=True,
    )
    assert cp.pending_units([("AAPL", "edgar_submissions", "10-Q"),
                             ("AAPL", "edgar_submissions", "8-K")]) == [
        ("AAPL", "edgar_submissions", "8-K")
    ]
    got = cp.get("AAPL", "edgar_submissions", "10-Q")
    assert got.completed and got.events_written == 5 and got.error_state is None
    cp.close()

    # reopen: state survived, still completed
    cp2 = BackfillCheckpointStore(db)
    assert cp2.get("AAPL", "edgar_submissions", "10-Q").completed
    s = cp2.summary()
    assert s["completed"] == 1 and s["pending"] == 0
    cp2.close()


def test_checkpoint_error_then_recovery(tmp_path):
    cp = BackfillCheckpointStore(tmp_path / "l.db")
    cp.ensure("MSFT", "edgar_form4_xml", "4")
    cp.mark_error("MSFT", "edgar_form4_xml", "4", "HTTP 429")
    assert cp.get("MSFT", "edgar_form4_xml", "4").error_state == "HTTP 429"
    cp.record_progress("MSFT", "edgar_form4_xml", "4", completed=True, clear_error=True)
    row = cp.get("MSFT", "edgar_form4_xml", "4")
    assert row.completed and row.error_state is None
    cp.close()


# ---------------------------------------------------------------------------
# processing state store
# ---------------------------------------------------------------------------
def test_processing_states_observable(tmp_path):
    ps = ProcessingStateStore(tmp_path / "l.db")
    ps.ensure("EVT:1", symbol="AAPL", event_type="QUARTERLY_FILING", form_type="10-Q",
              stage=ProcessingStage.STORED, comparison_state=ProcessingStateStore.PENDING)
    ps.set_stage("EVT:1", ProcessingStage.ENRICHMENT_PENDING, detail="96C")
    ps.set_substate("EVT:1", comparison_state=ProcessingStateStore.PARTIAL, detail="low quality")
    ps.set_substate("EVT:1", significance_state=ProcessingStateStore.DONE)
    ps.set_stage("EVT:1", ProcessingStage.PARTIAL)

    now = datetime.now(timezone.utc)
    ps.record_error("EVT:1", error="prior doc unavailable", retryable=True,
                    retry_after_utc=now - timedelta(minutes=1))
    due = ps.due_for_retry(now=now)
    assert [r.event_id for r in due] == ["EVT:1"]

    ps.record_error("EVT:2-terminal", error="unsupported form", retryable=False)  # no row -> update noop
    ps.ensure("EVT:2", symbol="X", stage=ProcessingStage.STORED)
    ps.record_error("EVT:2", error="unsupported form 20-F", retryable=False)
    assert ps.get("EVT:2").stage is ProcessingStage.FAILED_TERMINAL
    assert ps.get("EVT:2") not in ps.due_for_retry(now=now)

    counts = ps.counts_by_stage()
    assert counts.get("FAILED_RETRYABLE", 0) >= 1
    assert counts.get("FAILED_TERMINAL", 0) >= 1
    assert ps.total() == 2
    assert len(ps.logs("EVT:1")) >= 4
    ps.close()
