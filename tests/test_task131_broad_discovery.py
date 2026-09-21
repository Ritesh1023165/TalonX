"""
Task 131 Directive 4 -- SEC poller target-list expansion to the 626-name
Discovery Universe v1, additively, opt-in (TALONX_INTEL_ENABLE_BROAD_
DISCOVERY), within the SAME process/scope so the shared SEC rate-limit
budget (default 8 req/s) is genuinely shared, not doubled.
"""
from __future__ import annotations

import json

from talonx_ingest.intelligence.service.broad_discovery import (
    ORIGIN_BROAD_DISCOVERY,
    ORIGIN_PRODUCT_WATCHLIST,
    broad_discovery_enabled,
    extend_scope_with_broad_discovery,
    load_discovery_universe_v1,
    resolve_broad_discovery,
)
from talonx_ingest.intelligence.service.cik_directory import CikDirectory
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.scope import IngestionScope
from talonx_ingest.intelligence.service.watchlist_source import ResolvedSymbol, WatchlistResolution
from datetime import datetime, timezone


def _manifest(tmp_path, symbols, *, cik_map: dict[str, int] | None = None):
    # Task 131 Remediation Directive 6: resolve_broad_discovery reads a
    # STATIC, VERSIONED cik_manifest block, not a live CikDirectory --
    # test fixtures build that block directly, matching the real
    # discovery_universe_v1_626.json's own shape.
    cik_map = cik_map or {}
    resolved = {s: {"cik": str(c).zfill(10), "company_name": f"{s} Inc.",
                    "source": "sec_company_tickers"} for s, c in cik_map.items()}
    unresolved = [{"symbol": s, "reason": "no_sec_cik_mapping"}
                 for s in symbols if s not in cik_map]
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({
        "symbols": symbols, "provenance": {},
        "cik_manifest": {"manifest_version": "CIK_MANIFEST_V1", "resolved": resolved,
                         "unresolved": unresolved},
    }))
    return p


def _directory(symbols_to_ciks: dict[str, int]):
    tickers = {str(i): {"cik_str": cik, "ticker": sym, "title": f"{sym} Inc."}
              for i, (sym, cik) in enumerate(symbols_to_ciks.items())}
    return CikDirectory.from_company_tickers(tickers)


def _empty_scope(symbols=("AAPL",), resolved=None):
    wl = WatchlistResolution(
        configured=symbols, active=symbols, excluded=(),
        resolvable=resolved or (ResolvedSymbol(symbols[0], "0000000001", "Apple Inc.", "sec_company_tickers"),),
        unresolved=(), effective=symbols, as_of_utc=datetime.now(timezone.utc),
        watchlist_db_path="<test>", directory_from_cache=False, directory_size=1)
    return IngestionScope(
        symbols=symbols, resolved=wl.resolvable, filing_forms=("8-K",), insider_forms=("4",),
        history_days=900, history_start=datetime.now(timezone.utc).date(), watchlist=wl,
        generated_at_utc=datetime.now(timezone.utc))


def test_load_discovery_universe_v1_reads_the_frozen_manifest(tmp_path):
    p = _manifest(tmp_path, ["ZZZ", "aaa", "AAA", "mmm"])
    universe = load_discovery_universe_v1(p)
    assert universe == ("AAA", "MMM", "ZZZ")     # sorted, upper-cased, de-duplicated


def test_disabled_by_default_scope_is_byte_identical(tmp_path, monkeypatch):
    monkeypatch.delenv("TALONX_INTEL_ENABLE_BROAD_DISCOVERY", raising=False)
    assert broad_discovery_enabled() is False
    scope = _empty_scope()
    directory = _directory({"AAPL": 1, "MSFT": 2, "GOOG": 3})
    extended, origin = extend_scope_with_broad_discovery(
        scope, directory, manifest_path=_manifest(tmp_path, ["MSFT", "GOOG"]))
    assert extended is scope                      # untouched, same object
    assert origin == {"AAPL": ORIGIN_PRODUCT_WATCHLIST}


def test_enabled_unions_the_broad_universe_additively(tmp_path, monkeypatch):
    monkeypatch.setenv("TALONX_INTEL_ENABLE_BROAD_DISCOVERY", "true")
    assert broad_discovery_enabled() is True
    scope = _empty_scope(symbols=("AAPL",))
    directory = _directory({"AAPL": 1, "MSFT": 2, "GOOG": 3, "NVDA": 4})
    manifest = _manifest(tmp_path, ["AAPL", "MSFT", "GOOG", "NVDA"],  # AAPL already covered
                         cik_map={"AAPL": 1, "MSFT": 2, "GOOG": 3, "NVDA": 4})
    extended, origin = extend_scope_with_broad_discovery(scope, directory, manifest_path=manifest)
    assert set(extended.symbols) == {"AAPL", "MSFT", "GOOG", "NVDA"}
    assert origin["AAPL"] == ORIGIN_PRODUCT_WATCHLIST
    assert origin["MSFT"] == ORIGIN_BROAD_DISCOVERY
    assert origin["GOOG"] == ORIGIN_BROAD_DISCOVERY
    assert origin["NVDA"] == ORIGIN_BROAD_DISCOVERY
    # every broad-discovery symbol resolved from the STATIC CIK_MANIFEST_V1
    resolved_syms = {r.symbol for r in extended.resolved}
    assert resolved_syms == {"AAPL", "MSFT", "GOOG", "NVDA"}
    assert all("CIK_MANIFEST_V1" in r.source for r in extended.resolved if r.symbol != "AAPL")


def test_broad_discovery_symbols_unresolvable_in_directory_are_excluded_not_silently_mapped(tmp_path):
    directory = _directory({"AAPL": 1, "MSFT": 2})  # GOOG missing from the static manifest
    manifest = _manifest(tmp_path, ["MSFT", "GOOG"], cik_map={"MSFT": 2})
    res = resolve_broad_discovery(directory, manifest_path=manifest)
    assert res.universe_n == 2
    resolved_syms = {r.symbol for r in res.resolved}
    assert resolved_syms == {"MSFT"}
    assert dict(res.unresolved) == {"GOOG": "no_sec_cik_mapping"}
