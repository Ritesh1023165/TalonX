"""
talonx_ingest.intelligence.service.broad_discovery
===================================================
Task 131 Directive 4: expand the SEC poller target list to the 626-name
Discovery Universe v1 liquid universe (validated offline by Task 130/130A/
130B research, net@20bps +2.02%, N=153) -- ADDITIVELY, opt-in, and within
the SAME process/scope as the existing product watchlist ingestion so the
SEC API budget (:data:`talonx_ingest.config.settings.edgar.max_requests_per_second`,
default 8 req/s) is genuinely SHARED, not doubled by a second process with
its own independent token bucket.

``BROAD_DISCOVERY`` is OFF by default (``TALONX_INTEL_ENABLE_BROAD_DISCOVERY``
unset/false) -- the existing 39-name product watchlist ingestion is
completely unaffected unless an operator explicitly opts in. When enabled,
:func:`extend_scope_with_broad_discovery` unions the 626-name population
(resolved through the SAME authoritative :class:`CikDirectory` every other
symbol in this service uses) into the existing :class:`IngestionScope`,
tagging which symbols came from which source (``origin_by_symbol``) so
downstream consumers (the dashboard, Directive 5) can keep the two views
separate without a second scope/process/rate-limiter.

This does NOT change which symbols V2 (``talonx_v2.service.V2Service``)
will actually TRADE -- that remains governed entirely by its own,
separately-configured ``execution_allowlist`` (Task 117). Broadening
ingestion coverage only broadens what data EXISTS to evaluate; it is not,
by itself, an execution-scope change.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path

from talonx_ingest.intelligence.service.cik_directory import CikDirectory
from talonx_ingest.intelligence.service.scope import IngestionScope
from talonx_ingest.intelligence.service.watchlist_source import ResolvedSymbol

logger = logging.getLogger("talonx_ingest.intelligence.service.broad_discovery")

# Checked-in sample INPUT, alongside cik_overrides.json -- NOT under
# /results/ (gitignored, generated-output only per this repo's own
# .gitignore convention). This file is a real, loaded runtime dependency
# of load_discovery_universe_v1() below, not merely a documentation
# pointer, so it must actually ship with the repo.
DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parent / "data" / "discovery_universe_v1_626.json"
)

ORIGIN_PRODUCT_WATCHLIST = "PRODUCT_WATCHLIST"
ORIGIN_BROAD_DISCOVERY = "BROAD_DISCOVERY"


def broad_discovery_enabled() -> bool:
    return os.environ.get("TALONX_INTEL_ENABLE_BROAD_DISCOVERY", "").strip().lower() in (
        "1", "true", "yes", "on")


def load_discovery_universe_v1(path: Path | None = None) -> tuple[str, ...]:
    p = path or DEFAULT_MANIFEST_PATH
    if not p.is_file():
        logger.warning("broad_discovery manifest not found at %s -- returning empty universe", p)
        return ()
    data = json.loads(p.read_text(encoding="utf-8"))
    return tuple(sorted({s.strip().upper() for s in data.get("symbols", []) if s.strip()}))


def _load_cik_manifest(path: Path | None = None) -> dict:
    p = path or DEFAULT_MANIFEST_PATH
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("cik_manifest", {})


@dataclass(frozen=True)
class BroadDiscoveryResolution:
    universe_n: int
    resolved: tuple[ResolvedSymbol, ...]
    unresolved: tuple[tuple[str, str], ...]   # (symbol, reason)


def resolve_broad_discovery(
    directory: CikDirectory | None = None, *, manifest_path: Path | None = None,
    already_covered: frozenset[str] = frozenset(),
) -> BroadDiscoveryResolution:
    """Task 131 Remediation Directive 6: resolves the 626-name universe
    from the STATIC, VERSIONED ``CIK_MANIFEST_V1`` embedded in the
    manifest file itself -- NOT a live CikDirectory lookup. This
    population is a frozen, historical, point-in-time research set (Task
    130B) that legitimately includes delisted/acquired/renamed names a
    live lookup against CURRENT SEC company_tickers.json would silently
    drop -- a static, dated snapshot is the MORE correct choice here, not
    merely a cautious one. ``directory`` is accepted (unused) only for
    backward-compatible call-site signatures; it is NOT consulted for
    symbols covered by the static manifest. Symbols already covered by
    the product watchlist are excluded here (the union happens once, in
    extend_scope_with_broad_discovery)."""
    p = manifest_path or DEFAULT_MANIFEST_PATH
    universe = load_discovery_universe_v1(p)
    cik_manifest = _load_cik_manifest(p)
    resolved_map: dict = cik_manifest.get("resolved", {})
    unresolved_map = {u["symbol"]: u["reason"] for u in cik_manifest.get("unresolved", [])}

    resolved: list[ResolvedSymbol] = []
    unresolved: list[tuple[str, str]] = []
    for sym in universe:
        if sym in already_covered:
            continue
        if sym in resolved_map:
            r = resolved_map[sym]
            resolved.append(ResolvedSymbol(sym, r["cik"], r["company_name"],
                                          f"{r['source']} (CIK_MANIFEST_V1 static snapshot)"))
        elif sym in unresolved_map:
            unresolved.append((sym, unresolved_map[sym]))
        else:
            unresolved.append((sym, "not_present_in_static_CIK_MANIFEST_V1"))
    resolved.sort(key=lambda r: r.symbol)
    unresolved.sort()
    return BroadDiscoveryResolution(universe_n=len(universe), resolved=tuple(resolved),
                                    unresolved=tuple(unresolved))


def extend_scope_with_broad_discovery(
    scope: IngestionScope, directory: CikDirectory, *, manifest_path: Path | None = None,
) -> tuple[IngestionScope, dict[str, str]]:
    """Returns (extended_scope, origin_by_symbol). If broad discovery is
    not enabled (:func:`broad_discovery_enabled`), returns ``scope``
    UNCHANGED and every symbol tagged PRODUCT_WATCHLIST -- byte-identical
    to pre-Task-131 behaviour."""
    origin_by_symbol = {s: ORIGIN_PRODUCT_WATCHLIST for s in scope.symbols}
    if not broad_discovery_enabled():
        return scope, origin_by_symbol

    already = frozenset(scope.symbols)
    bd = resolve_broad_discovery(directory, manifest_path=manifest_path, already_covered=already)
    if bd.unresolved:
        logger.info("broad_discovery: %d/%d symbols unresolved (no CIK mapping / known non-filer)",
                   len(bd.unresolved), bd.universe_n)
    for r in bd.resolved:
        origin_by_symbol[r.symbol] = ORIGIN_BROAD_DISCOVERY

    extended_resolved = tuple(sorted((*scope.resolved, *bd.resolved), key=lambda r: r.symbol))
    extended_symbols = tuple(r.symbol for r in extended_resolved)
    extended = replace(scope, symbols=extended_symbols, resolved=extended_resolved)
    logger.info("broad_discovery ENABLED: scope extended %d -> %d symbols (+%d)",
               len(scope.symbols), len(extended_symbols), len(bd.resolved))
    return extended, origin_by_symbol
