"""
talonx_ingest.intelligence.service.watchlist_source
==================================================
One authoritative watchlist resolution for the ingestion service
(``WATCHLIST_INGESTION_CONTRACT.md``).

``resolve_watchlist`` takes the deployed :class:`TickerWatchlistStore` and a
:class:`CikDirectory` and returns a :class:`WatchlistResolution` that names,
without ambiguity:

* ``configured``  — every row in the watchlist store
* ``active``      — rows with ``status='active'`` (what ingestion considers)
* ``excluded``    — paused rows + explicit config exclusions, each with a reason
* ``resolvable``  — active symbols with a confident SEC CIK
* ``unresolved``  — active symbols with no CIK / a known non-filer, each with a reason
* ``effective``   — ``[r.symbol for r in resolvable]`` — the ingestion universe

Deterministic: same store + directory + exclusions -> identical result.
This is the module that ends the historical 43-vs-42 watchlist ambiguity —
every bucket is explicit and counted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from talonx_ingest.intelligence.service.cik_directory import CikDirectory, CikRef


@dataclass(frozen=True)
class ResolvedSymbol:
    symbol: str
    cik: str
    company_name: str
    source: str


@dataclass(frozen=True)
class ExcludedSymbol:
    symbol: str
    reason: str          # "paused" | "config_exclusion"


@dataclass(frozen=True)
class UnresolvedSymbol:
    symbol: str
    reason: str          # "known_non_filer: ..." | "no_sec_cik_mapping"


@dataclass(frozen=True)
class WatchlistResolution:
    configured: tuple[str, ...]
    active: tuple[str, ...]
    excluded: tuple[ExcludedSymbol, ...]
    resolvable: tuple[ResolvedSymbol, ...]
    unresolved: tuple[UnresolvedSymbol, ...]
    effective: tuple[str, ...]
    as_of_utc: datetime
    watchlist_db_path: str
    directory_from_cache: bool
    directory_size: int
    warnings: tuple[str, ...] = field(default_factory=tuple)

    # -- convenience counts (for logs / status / metrics) --------------
    @property
    def counts(self) -> dict[str, int]:
        return {
            "configured": len(self.configured),
            "active": len(self.active),
            "excluded": len(self.excluded),
            "resolvable": len(self.resolvable),
            "unresolved": len(self.unresolved),
            "effective": len(self.effective),
        }

    def cik_for(self, symbol: str) -> str | None:
        s = symbol.upper()
        for r in self.resolvable:
            if r.symbol == s:
                return r.cik
        return None

    def summary_line(self) -> str:
        c = self.counts
        return (
            f"watchlist: configured={c['configured']} active={c['active']} "
            f"excluded={c['excluded']} resolvable={c['resolvable']} "
            f"unresolved={c['unresolved']} -> effective={c['effective']}"
        )


def resolve_watchlist(
    watchlist_store,
    directory: CikDirectory,
    *,
    explicit_exclusions: tuple[str, ...] = (),
    include_paused: bool = False,
    now: datetime | None = None,
) -> WatchlistResolution:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    rows = watchlist_store.list_tickers()
    configured = tuple(sorted({r["symbol"].strip().upper() for r in rows}))
    exclude_set = {s.strip().upper() for s in explicit_exclusions if s.strip()}

    status_by_symbol = {r["symbol"].strip().upper(): r.get("status", "active") for r in rows}

    active: list[str] = []
    excluded: list[ExcludedSymbol] = []
    for sym in configured:
        status = status_by_symbol.get(sym, "active")
        if sym in exclude_set:
            excluded.append(ExcludedSymbol(sym, "config_exclusion"))
            continue
        if status != "active" and not include_paused:
            excluded.append(ExcludedSymbol(sym, f"status={status}"))
            continue
        active.append(sym)

    resolvable: list[ResolvedSymbol] = []
    unresolved: list[UnresolvedSymbol] = []
    for sym in active:
        non_filer = directory.known_non_filer(sym)
        if non_filer:
            unresolved.append(UnresolvedSymbol(sym, f"known_non_filer: {non_filer}"))
            continue
        ref: CikRef | None = directory.resolve(sym)
        if ref is None:
            unresolved.append(UnresolvedSymbol(sym, "no_sec_cik_mapping"))
            continue
        resolvable.append(
            ResolvedSymbol(sym, ref.cik, ref.company_name, ref.source)
        )

    resolvable.sort(key=lambda r: r.symbol)
    unresolved.sort(key=lambda r: r.symbol)
    excluded.sort(key=lambda r: r.symbol)
    effective = tuple(r.symbol for r in resolvable)

    warnings: list[str] = []
    if not effective:
        warnings.append("no effective symbols — ingestion universe is empty")
    dup_ciks: dict[str, list[str]] = {}
    for r in resolvable:
        dup_ciks.setdefault(r.cik, []).append(r.symbol)
    for cik, syms in dup_ciks.items():
        if len(syms) > 1:
            warnings.append(f"multiple symbols map to CIK {cik}: {', '.join(syms)}")

    db_path = str(getattr(watchlist_store, "path", "")) or "<unknown>"
    return WatchlistResolution(
        configured=configured,
        active=tuple(active),
        excluded=tuple(excluded),
        resolvable=tuple(resolvable),
        unresolved=tuple(unresolved),
        effective=effective,
        as_of_utc=now,
        watchlist_db_path=db_path,
        directory_from_cache=directory.from_cache,
        directory_size=len(directory),
        warnings=tuple(warnings),
    )
