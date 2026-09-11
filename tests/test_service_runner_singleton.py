"""
tests/test_service_runner_singleton.py
--------------------------------------
Task 96B — Gate P (restart/heartbeat), Gate T (status view), Gate U
(execution independence), singleton lock. Offline.
"""
from __future__ import annotations

import asyncio
import os

from talonx_ingest.intelligence.service.cik_directory import CikDirectory
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.runner import IntelligenceService
from talonx_ingest.intelligence.service.singleton import (
    SingletonLock,
    read_heartbeat,
    write_heartbeat,
)
from talonx_ingest.intelligence.service import poller as poller_mod
from talonx_ingest.intelligence.service.scope import resolve_scope
from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
from talonx_ingest.intelligence.comparison.retrieval import FilingArchiveCache

from tests._service_helpers import (
    FakeEdgarClient,
    FakeWatchlistStore,
    make_submissions,
    wl_row,
)


# ---------------------------------------------------------------------------
# singleton lock
# ---------------------------------------------------------------------------
def test_singleton_lock_blocks_second_holder(tmp_path):
    p = tmp_path / "svc.lock"
    a = SingletonLock(p)
    assert a.acquire() is True
    b = SingletonLock(p)
    assert b.acquire() is False           # live pid (this process) holds it
    assert b.acquire(force=True) is True  # force override
    a.release()


def test_stale_lock_is_reclaimed(tmp_path):
    p = tmp_path / "svc.lock"
    p.write_text('{"pid": 999999999, "host": "%s", "started_at_utc": "x", "argv": []}'
                 % os.uname().nodename if hasattr(os, "uname") else
                 '{"pid": 999999999, "host": "nope-host", "started_at_utc": "x", "argv": []}',
                 encoding="utf-8")
    lock = SingletonLock(p)
    assert lock.acquire() is True         # dead/foreign pid -> reclaimed
    lock.release()


def test_heartbeat_roundtrip(tmp_path):
    hb = tmp_path / "hb.json"
    write_heartbeat(hb, {"mode": "poll", "x": 1})
    got = read_heartbeat(hb)
    assert got["mode"] == "poll" and got["x"] == 1
    assert "heartbeat_at_utc" in got and "pid" in got


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------
def _service(tmp_path, monkeypatch):
    cfg = ServiceConfig(ledger_path=str(tmp_path / "l.db"), state_dir=tmp_path / "state",
                        history_days=3650, poll_base_seconds=0.01)
    svc = IntelligenceService(cfg)

    client = FakeEdgarClient(submissions={"0000012345": make_submissions()})
    directory = CikDirectory.from_company_tickers(
        {"0": {"cik_str": 12345, "ticker": "FAKE", "title": "Fake Industries Inc."}}
    )

    async def _open(with_network=True):
        from talonx_ingest.intelligence.service.stores import StoreBundle

        svc.stores = StoreBundle.open(cfg.ledger())
        svc._watchlist = FakeWatchlistStore([wl_row("FAKE")])
        svc._owns_watchlist = True
        svc.client = client
        svc.directory = directory
        svc.scope = resolve_scope(config=cfg, watchlist_store=svc._watchlist, directory=directory)
        svc.enrichment = EnrichmentEngine(
            svc.stores, client, config=cfg, metrics=svc.metrics,
            cache=FilingArchiveCache(client, cache_dir=tmp_path / "c"),
        )
        from talonx_ingest.intelligence.service.poller import EdgarPoller
        from talonx_ingest.intelligence.service.backfill import Backfill

        svc.poller = EdgarPoller(svc.stores, client, config=cfg, scope=svc.scope,
                                 metrics=svc.metrics, enrichment=svc.enrichment)
        svc.backfill = Backfill(svc.stores, client, config=cfg, scope=svc.scope,
                                metrics=svc.metrics, enrichment=svc.enrichment)
        return svc

    monkeypatch.setattr(svc, "open", _open)
    return svc, cfg


def test_poll_loop_runs_bounded_and_writes_heartbeat(tmp_path, monkeypatch):
    svc, cfg = _service(tmp_path, monkeypatch)

    async def _go():
        await svc.open()
        try:
            out = await svc.run_poll_loop(max_cycles=2)
            return out
        finally:
            await svc.close()

    out = asyncio.run(_go())
    assert out["cycles"] == 2
    hb = read_heartbeat(cfg.heartbeat_path())
    assert hb is not None and hb["mode"] in ("poll", "poll:stopped")
    assert hb["metrics"]["events"]["stored"] >= 3
    # metrics snapshot file written too
    assert cfg.metrics_path().is_file()


def test_status_is_offline_safe(tmp_path, monkeypatch):
    svc, cfg = _service(tmp_path, monkeypatch)

    async def _go():
        await svc.open()
        try:
            asyncio.get_event_loop()
            return svc.status()
        finally:
            await svc.close()

    st = asyncio.run(_go())
    assert "watchlist" in st and "source_freshness" in st and "backfill" in st
    assert st["dry_run_delivery"] is True
    assert "processing_stages" in st


def test_poller_module_has_no_trading_imports():
    # Gate U / Gate X — the ingest service never reaches into execution.
    import talonx_ingest.intelligence.service as pkg
    import importlib
    import pkgutil

    forbidden = ("talonx_quant", "talonx_core.decision", "talonx_paper",
                 "talonx_piv", "talonx_backtest")
    for m in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"{pkg.__name__}.{m.name}")
        src = getattr(mod, "__file__", None)
        if not src:
            continue
        text = open(src, encoding="utf-8").read()
        for bad in forbidden:
            assert f"import {bad}" not in text and f"from {bad}" not in text, (
                f"{m.name} imports {bad}"
            )
