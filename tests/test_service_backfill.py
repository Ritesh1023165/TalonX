"""
tests/test_service_backfill.py
------------------------------
Task 96B — Gate C (resumable + idempotent), Gate O (priority: bounded),
Gate P (restart), plus history-bound enforcement. Offline.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from talonx_ingest.intelligence.comparison.retrieval import FilingArchiveCache
from talonx_ingest.intelligence.service.backfill import Backfill
from talonx_ingest.intelligence.service.cik_directory import CikDirectory
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
from talonx_ingest.intelligence.service.scope import resolve_scope
from talonx_ingest.intelligence.service.stores import StoreBundle

from tests._service_helpers import (
    FakeEdgarClient,
    FakeWatchlistStore,
    make_submissions,
    wl_row,
)


def _setup(tmp_path, *, history_days=3650):
    cfg = ServiceConfig(
        ledger_path=str(tmp_path / "l.db"), state_dir=tmp_path / "state",
        history_days=history_days,
    )
    stores = StoreBundle.open(cfg.ledger())
    client = FakeEdgarClient(submissions={"0000012345": make_submissions()})
    directory = CikDirectory.from_company_tickers(
        {"0": {"cik_str": 12345, "ticker": "FAKE", "title": "Fake Industries Inc."}}
    )
    scope = resolve_scope(config=cfg, watchlist_store=FakeWatchlistStore([wl_row("FAKE")]),
                          directory=directory)
    enrich = EnrichmentEngine(stores, client, config=cfg,
                              cache=FilingArchiveCache(client, cache_dir=tmp_path / "c"))
    bf = Backfill(stores, client, config=cfg, scope=scope, enrichment=enrich)
    return cfg, stores, client, bf


def test_backfill_completes_units_and_is_resumable(tmp_path):
    cfg, stores, client, bf = _setup(tmp_path)
    rep = asyncio.run(bf.run())
    sr = rep.per_symbol[0]
    assert set(sr.units_completed) == {
        "edgar_submissions:8-K", "edgar_submissions:10-Q", "edgar_submissions:10-K",
        "edgar_form4_xml:4",
    }
    assert sr.events_new >= 3
    assert sr.ownership_filings >= 1
    n_events = stores.events.count_events()

    # second run: every unit is skipped, nothing re-created
    rep2 = asyncio.run(bf.run())
    sr2 = rep2.per_symbol[0]
    assert sr2.units_completed == []
    assert sorted(sr2.units_skipped) == sorted(sr.units_completed)
    assert sr2.events_new == 0
    assert stores.events.count_events() == n_events
    stores.close()


def test_backfill_restart_mid_way_resumes(tmp_path):
    cfg, stores, client, bf = _setup(tmp_path)
    # simulate a prior partial run: only 8-K done
    stores.checkpoints.ensure("FAKE", "edgar_submissions", "8-K")
    stores.checkpoints.record_progress("FAKE", "edgar_submissions", "8-K", completed=True,
                                       clear_error=True)
    rep = asyncio.run(bf.run())
    sr = rep.per_symbol[0]
    assert "edgar_submissions:8-K" in sr.units_skipped
    assert "edgar_submissions:10-Q" in sr.units_completed
    assert stores.checkpoints.summary()["pending"] == 0
    stores.close()


def test_backfill_respects_history_bound(tmp_path):
    # 10-day window: only the 2026-06-* filings qualify, the 2026-03-05 10-Q does not
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    cfg, stores, client, bf = _setup(tmp_path, history_days=10)
    rep = asyncio.run(bf.run(now=now))
    q = stores.checkpoints.get("FAKE", "edgar_submissions", "10-Q")
    assert q.completed
    # the older prior 10-Q (2026-03-05) is outside the 10-day window -> not stored
    tenq_events = stores.events.query_events(form_type="10-Q")
    accns = {e.accession for e in tenq_events}
    assert "0000012345-26-000009" in accns
    assert "0000012345-26-000004" not in accns
    stores.close()
