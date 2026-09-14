"""
tests/test_service_enrichment.py
--------------------------------
Task 96B — Gate G (96C), Gate I (96E eval/recompute), Gate J (96F enqueue,
no dup spam), Gate M (failure isolation: enrichment failure never loses the
base event), Gate V (claim safety preserved). Offline.
"""
from __future__ import annotations

import asyncio

import pytest

from talonx_ingest.intelligence.comparison.retrieval import FilingArchiveCache
from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.service import enrichment as enr_mod
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
from talonx_ingest.intelligence.service.state_machine import ProcessingStage
from talonx_ingest.intelligence.service.stores import StoreBundle
from talonx_ingest.intelligence.service._ingest import ingest_symbol_filings

from tests._service_helpers import FakeEdgarClient, make_submissions


def _prep(tmp_path):
    cfg = ServiceConfig(ledger_path=str(tmp_path / "l.db"), state_dir=tmp_path / "s",
                        history_days=3650, enable_xbrl=False)
    stores = StoreBundle.open(cfg.ledger())
    client = FakeEdgarClient(submissions={"0000012345": make_submissions()})
    subs = make_submissions()
    si = ingest_symbol_filings(stores.events, subs, symbol="FAKE",
                               forms=("8-K", "10-Q", "10-K"))
    engine = EnrichmentEngine(
        stores, client, config=cfg,
        cache=FilingArchiveCache(client, cache_dir=tmp_path / "c"),
    )
    return cfg, stores, client, engine, si.new_event_ids


def _tenq_event_id(stores):
    evs = stores.events.query_events(event_type=EventType.QUARTERLY_FILING)
    return evs[0].event_id


def test_happy_path_runs_all_layers(tmp_path):
    cfg, stores, client, engine, ids = _prep(tmp_path)
    for eid in ids:
        oc = asyncio.run(engine.process_event(eid))
    tenq = _tenq_event_id(stores)
    row = stores.processing.get(tenq)
    assert row is not None
    assert row.significance_state == "DONE"
    assert row.delivery_state in ("DONE",)
    assert stores.significance.get_for_event(tenq) is not None
    # a durable outbox row exists, nothing SENT
    assert stores.outbox.counts_by_state().get("SENT", 0) == 0
    stores.close()


def test_comparison_exception_isolated_from_base_event(tmp_path, monkeypatch):
    cfg, stores, client, engine, ids = _prep(tmp_path)
    tenq = _tenq_event_id(stores)

    async def _boom(*a, **k):
        raise RuntimeError("simulated 96C blow-up: database is locked")

    monkeypatch.setattr(enr_mod, "run_comparison_for_event", _boom)
    oc = asyncio.run(engine.process_event(tenq))

    # base event still present and untouched
    assert stores.events.get_event(tenq) is not None
    # comparison failed, but significance STILL ran (deferred enrichment)
    row = stores.processing.get(tenq)
    assert row.comparison_state == "FAILED"
    assert row.significance_state == "DONE"
    assert stores.significance.get_for_event(tenq) is not None
    # row is retryable, not terminal, and has a retry_after
    assert row.stage in (ProcessingStage.FAILED_RETRYABLE, ProcessingStage.PARTIAL)
    assert row.retry_after_utc is not None
    stores.close()


def test_recompute_when_comparison_lands_later(tmp_path):
    cfg, stores, client, engine, ids = _prep(tmp_path)
    tenq = _tenq_event_id(stores)

    # 1st pass: force "no comparison yet" by pointing docs at an unavailable url
    async def _no_doc(url):
        if url.endswith(".xml"):
            from tests._service_helpers import FORM4_XML
            return FORM4_XML
        raise RuntimeError("temporarily unavailable")

    client.fetch_document = _no_doc  # type: ignore
    asyncio.run(engine.process_event(tenq))
    sig1 = stores.significance.get_for_event(tenq)
    assert sig1 is not None
    fp1 = sig1.input_fingerprint

    # 2nd pass: docs available -> comparison persists -> fingerprint should move
    from tests._service_helpers import _TENQ_HTML_A  # noqa

    async def _doc_ok(url):
        from tests._service_helpers import FORM4_XML, _TENQ_HTML_A, _TENQ_HTML_B
        if url.endswith(".xml"):
            return FORM4_XML
        return _TENQ_HTML_B if "prior" in url else _TENQ_HTML_A

    client.fetch_document = _doc_ok  # type: ignore
    oc = asyncio.run(engine.process_event(tenq))
    assert stores.comparisons.get_comparison_for_current_event(tenq) is not None
    sig2 = stores.significance.get_for_event(tenq)
    assert sig2 is not None
    # a substantive input (the comparison) arrived -> recompute happened
    assert sig2.input_fingerprint != fp1
    stores.close()


def test_no_duplicate_delivery_on_reprocess(tmp_path):
    cfg, stores, client, engine, ids = _prep(tmp_path)
    eid = ids[0]
    asyncio.run(engine.process_event(eid))
    asyncio.run(engine.process_event(eid))
    asyncio.run(engine.process_event(eid))
    rows = [r for r in stores.outbox.query(limit=100) if r.event_id == eid]
    assert len(rows) == 1                     # one durable row, not three
    stores.close()


# ---------------------------------------------------------------------
# Task 134: a PERMANENTLY-partial comparison sub-state (a real, observed
# data-quality flag on old filings -- not a transient failure) must not
# keep a row open forever once delivery has genuinely completed.
# Confirmed live: 296 rows discovered 2026-09-04, still being re-selected
# and re-run (a real SEC comparison-fetch each time) on 2026-09-14, with
# significance_state/delivery_state already DONE and attempts always 0
# (record_error is never reached for this path, so no backoff ever
# applies) -- a genuine, demonstrated no-progress reprocessing loop.
# ---------------------------------------------------------------------

def test_rollup_stage_partial_comparison_with_delivery_done_is_complete():
    """Direct unit test of the fixed rollup rule, isolated from the async
    pipeline: base=PARTIAL (from comparison_state) + delivery_state=DONE
    -> COMPLETE, not PARTIAL. Regression guard for the exact bug found in
    Task 134 -- a PARTIAL stage is an OPEN_STAGES member, so leaving this
    at PARTIAL after delivery is genuinely done means next_for_processing
    re-selects it on every future cycle, forever, with no way to ever
    change comparison_state (a re-run cannot fix a permanent data-quality
    flag on an old filing)."""
    from dataclasses import dataclass

    from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
    from talonx_ingest.intelligence.service.state_store import ProcessingStateStore

    @dataclass
    class _Row:
        comparison_state: str
        attempts: int = 0

    row = _Row(comparison_state=ProcessingStateStore.PARTIAL)
    stage = EnrichmentEngine._rollup_stage(
        row, comparison_ok=True, sig_err=None,
        delivery_state=ProcessingStateStore.DONE, allow_delivery=True,
    )
    assert stage == ProcessingStage.COMPLETE


def test_rollup_stage_partial_comparison_without_delivery_done_stays_open():
    """The fix is scoped to `delivery_state == DONE` only -- a PARTIAL
    comparison whose delivery has NOT yet resolved must still stay open
    (PENDING delivery is a real reason to keep re-selecting the row)."""
    from dataclasses import dataclass

    from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
    from talonx_ingest.intelligence.service.state_store import ProcessingStateStore

    @dataclass
    class _Row:
        comparison_state: str
        attempts: int = 0

    row = _Row(comparison_state=ProcessingStateStore.PARTIAL)
    stage = EnrichmentEngine._rollup_stage(
        row, comparison_ok=True, sig_err=None,
        delivery_state=ProcessingStateStore.PENDING, allow_delivery=True,
    )
    assert stage == ProcessingStage.PARTIAL


def test_partial_comparison_flag_reaches_complete_and_stops_reprocessing(tmp_path, monkeypatch):
    """End-to-end through the real async pipeline: a comparison that
    returns the real `low_quality_comparison` data-quality flag
    (comparison_ok=True, comparison_state=PARTIAL) still reaches an
    overall CLOSED stage once delivery completes -- so the SCHEDULER
    (next_for_processing, which is what run_poll_loop's recovery pass
    actually calls every cycle -- see ProcessingStateStore.OPEN_STAGES)
    never re-selects it again. This is the actual guarantee that stops
    the reprocessing loop (not that a direct process_event() call would
    itself be a no-op -- it isn't; the fix is that nothing schedules
    that call anymore)."""
    from tests._significance_helpers import mk_comparison

    cfg, stores, client, engine, ids = _prep(tmp_path)
    tenq = _tenq_event_id(stores)
    ev = stores.events.get_event(tenq)

    async def _partial_flagged(*a, **k):
        return mk_comparison(event=ev, quality_flags=("low_quality_comparison",))

    monkeypatch.setattr(enr_mod, "run_comparison_for_event", _partial_flagged)
    asyncio.run(engine.process_event(tenq))

    row = stores.processing.get(tenq)
    assert row.comparison_state == "PARTIAL"       # caveat still observable
    assert row.delivery_state == "DONE"
    assert row.stage == ProcessingStage.COMPLETE   # closed, not stuck at PARTIAL

    # the scheduler that drives repeated recovery passes must no longer
    # pick this row up at all
    due = stores.processing.next_for_processing(limit=100)
    assert tenq not in [r.event_id for r in due]
    stores.close()
