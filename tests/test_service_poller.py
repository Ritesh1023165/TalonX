"""
tests/test_service_poller.py
----------------------------
Task 96B — Gate D (incremental polling), Gate E (quiet health), Gate F
(96A events), Gate N (transient failure recovery), Gate Q (idempotency).
Offline: FakeEdgarClient.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from talonx_ingest.intelligence.domain import SourceType
from talonx_ingest.intelligence.freshness import SourceFreshnessTracker
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
from talonx_ingest.intelligence.service.poller import EdgarPoller
from talonx_ingest.intelligence.service.scope import resolve_scope
from talonx_ingest.intelligence.service.stores import StoreBundle
from talonx_ingest.intelligence.service.cik_directory import CikDirectory
from talonx_ingest.intelligence.comparison.retrieval import FilingArchiveCache

from tests._service_helpers import (
    FakeEdgarClient,
    FakeWatchlistStore,
    make_submissions,
    wl_row,
)


def _setup(tmp_path, rows=None, fail_ciks=None):
    cfg = ServiceConfig(ledger_path=str(tmp_path / "l.db"), state_dir=tmp_path / "state",
                        history_days=3650)
    stores = StoreBundle.open(cfg.ledger())
    client = FakeEdgarClient(
        submissions={"0000012345": make_submissions(rows=rows)},
        fail_submissions_for=set(fail_ciks or []),
    )
    directory = CikDirectory.from_company_tickers(
        {"0": {"cik_str": 12345, "ticker": "FAKE", "title": "Fake Industries Inc."}}
    )
    wl = FakeWatchlistStore([wl_row("FAKE")])
    scope = resolve_scope(config=cfg, watchlist_store=wl, directory=directory)
    enrich = EnrichmentEngine(
        stores, client, config=cfg,
        cache=FilingArchiveCache(client, cache_dir=tmp_path / "cache"),
    )
    poller = EdgarPoller(stores, client, config=cfg, scope=scope, enrichment=enrich)
    return cfg, stores, client, poller


def test_new_filings_become_events_and_enrich(tmp_path):
    cfg, stores, client, poller = _setup(tmp_path)
    res = asyncio.run(poller.poll_once())
    assert res.symbols_polled == 1 and res.symbols_failed == 0
    assert len(res.new_event_ids) >= 3
    assert res.submissions_freshness == "FRESH"
    # 96A events landed
    assert stores.events.count_events() >= 3
    # 96E significance ran for at least one
    assert stores.significance.count() >= 1
    # 96F durable outbox row(s), none SENT (dry-run enqueue only)
    counts = stores.outbox.counts_by_state()
    assert counts.get("PENDING", 0) >= 1
    assert counts.get("SENT", 0) == 0
    stores.close()


def test_second_poll_is_idempotent(tmp_path):
    cfg, stores, client, poller = _setup(tmp_path)
    asyncio.run(poller.poll_once())
    n_events = stores.events.count_events()
    n_txns = stores.insider.count_transactions()
    res2 = asyncio.run(poller.poll_once())
    assert res2.new_event_ids == []
    assert res2.new_form4_filings == 0
    assert stores.events.count_events() == n_events
    assert stores.insider.count_transactions() == n_txns
    stores.close()


def test_quiet_cycle_is_not_a_failure(tmp_path):
    cfg, stores, client, poller = _setup(tmp_path)
    asyncio.run(poller.poll_once())          # consumes everything
    res2 = asyncio.run(poller.poll_once())   # nothing new
    assert res2.new_event_ids == []
    snap = SourceFreshnessTracker(stores.events).snapshot(SourceType.SEC_EDGAR_SUBMISSIONS)
    assert snap.status.value == "FRESH"      # quiet != STALE/DOWN
    assert snap.consecutive_failures == 0
    stores.close()


def test_transient_source_failure_then_recovery(tmp_path):
    cfg, stores, client, poller = _setup(tmp_path, fail_ciks=["0000012345"])
    r1 = asyncio.run(poller.poll_once())
    assert r1.symbols_failed == 1 and r1.symbols_polled == 0
    assert r1.errors and "429" in r1.errors[0]
    # recover
    client.fail_submissions_for = set()
    r2 = asyncio.run(poller.poll_once())
    assert r2.symbols_polled == 1
    assert len(r2.new_event_ids) >= 3
    snap = SourceFreshnessTracker(stores.events).snapshot(SourceType.SEC_EDGAR_SUBMISSIONS)
    assert snap.status.value == "FRESH"
    stores.close()
