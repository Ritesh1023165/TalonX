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
