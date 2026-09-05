"""
tests/test_service_scope_watchlist.py
-------------------------------------
Task 96B — Pass Gate A (product-driven scope) + Gate B (watchlist
integrity). Every bucket is explicit and counted; nothing is mapped
silently.
"""
from __future__ import annotations

from datetime import datetime, timezone

from talonx_ingest.intelligence.service.cik_directory import CikDirectory
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.scope import resolve_scope
from talonx_ingest.intelligence.service.watchlist_source import resolve_watchlist

from tests._service_helpers import FakeWatchlistStore, wl_row


def _directory() -> CikDirectory:
    return CikDirectory.from_company_tickers(
        {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
            "2": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA Corp"},
        }
    )


def test_buckets_are_disjoint_and_counted():
    wl = FakeWatchlistStore(
        [
            wl_row("AAPL"),
            wl_row("MSFT"),
            wl_row("NVDA", status="paused"),          # -> excluded
            wl_row("SKHY"),                            # known non-filer -> unresolved
            wl_row("ZZZZ"),                            # unknown -> unresolved
        ]
    )
    res = resolve_watchlist(wl, _directory(), explicit_exclusions=("MSFT",))
    c = res.counts
    assert c["configured"] == 5
    assert c["active"] == 3            # AAPL, MSFT, SKHY, ZZZZ minus paused NVDA -> wait
    # AAPL, MSFT, SKHY, ZZZZ are active; NVDA paused. MSFT is config-excluded.
    assert set(res.active) == {"AAPL", "SKHY", "ZZZZ"}
    assert {e.symbol for e in res.excluded} == {"NVDA", "MSFT"}
    assert {u.symbol for u in res.unresolved} == {"SKHY", "ZZZZ"}
    assert res.effective == ("AAPL",)
    # disjointness
    eff = set(res.effective)
    assert eff.isdisjoint({e.symbol for e in res.excluded})
    assert eff.isdisjoint({u.symbol for u in res.unresolved})


def test_non_filer_reason_is_explicit():
    wl = FakeWatchlistStore([wl_row("SPCX"), wl_row("AAPL")])
    res = resolve_watchlist(wl, _directory())
    reasons = {u.symbol: u.reason for u in res.unresolved}
    assert "known_non_filer" in reasons["SPCX"]
    assert res.effective == ("AAPL",)


def test_duplicate_cik_is_warned():
    d = CikDirectory.from_company_tickers(
        {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 320193, "ticker": "APLE", "title": "Apple Inc. (dup)"},
        }
    )
    wl = FakeWatchlistStore([wl_row("AAPL"), wl_row("APLE")])
    res = resolve_watchlist(wl, d)
    assert any("multiple symbols map to CIK" in w for w in res.warnings)


def test_scope_bounds_forms_and_history():
    cfg = ServiceConfig(history_days=900)
    wl = FakeWatchlistStore([wl_row("AAPL"), wl_row("MSFT")])
    now = datetime(2026, 9, 3, tzinfo=timezone.utc)
    scope = resolve_scope(config=cfg, watchlist_store=wl, directory=_directory(), now=now)
    assert scope.filing_forms == ("8-K", "10-Q", "10-K")
    assert scope.insider_forms == ("4",)
    assert scope.history_start == now.date().replace(year=2024, month=3, day=17)
    assert set(scope.symbols) == {"AAPL", "MSFT"}
    d = scope.as_dict()
    assert d["watchlist_counts"]["effective"] == 2
    assert "8-K" in d["filing_forms"] and "20-F" not in d["filing_forms"]


def test_optional_insider_forms_toggle():
    cfg = ServiceConfig(include_optional_insider_forms=True)
    assert set(cfg.effective_insider_forms()) == {"4", "3", "5"}
    assert ServiceConfig().effective_insider_forms() == ("4",)
