"""
talonx_ingest.intelligence.service.scope
========================================
The product-driven :class:`IngestionScope` (``INGESTION_SCOPE_SPEC.md``).

Ingestion is NOT "every SEC filing ever published". Scope is:

1. symbols  = resolvable active watchlist (``watchlist_source``)
2. forms    = the forms the MVP product consumes — filing forms
   (8-K / 10-Q / 10-K) for 96A/96C, insider form 4 (optionally 3/5) for 96D
3. history  = a bounded lookback (default 900 days) — enough for prior
   10-Q / 10-K comparison, insider rolling context, and significance rarity
   context, and no more.

``resolve_scope`` is pure given (config, watchlist store, CIK directory);
it performs no network I/O of its own (the directory is already loaded).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from talonx_ingest.intelligence.service.cik_directory import CikDirectory
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.watchlist_source import (
    ResolvedSymbol,
    WatchlistResolution,
    resolve_watchlist,
)


@dataclass(frozen=True)
class IngestionScope:
    symbols: tuple[str, ...]                 # == watchlist.effective
    resolved: tuple[ResolvedSymbol, ...]
    filing_forms: tuple[str, ...]
    insider_forms: tuple[str, ...]
    history_days: int
    history_start: date
    watchlist: WatchlistResolution
    generated_at_utc: datetime

    @property
    def all_forms(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.filing_forms, *self.insider_forms)))

    def cik_for(self, symbol: str) -> str | None:
        return self.watchlist.cik_for(symbol)

    def as_dict(self) -> dict:
        return {
            "generated_at_utc": self.generated_at_utc.isoformat(),
            "history_days": self.history_days,
            "history_start": self.history_start.isoformat(),
            "filing_forms": list(self.filing_forms),
            "insider_forms": list(self.insider_forms),
            "symbols": list(self.symbols),
            "resolved": [
                {"symbol": r.symbol, "cik": r.cik, "company_name": r.company_name,
                 "source": r.source}
                for r in self.resolved
            ],
            "watchlist_counts": self.watchlist.counts,
            "excluded": [
                {"symbol": e.symbol, "reason": e.reason} for e in self.watchlist.excluded
            ],
            "unresolved": [
                {"symbol": u.symbol, "reason": u.reason}
                for u in self.watchlist.unresolved
            ],
            "warnings": list(self.watchlist.warnings),
        }


def resolve_scope(
    *,
    config: ServiceConfig,
    watchlist_store,
    directory: CikDirectory,
    now: datetime | None = None,
) -> IngestionScope:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    wl = resolve_watchlist(
        watchlist_store,
        directory,
        explicit_exclusions=config.explicit_exclusions,
        include_paused=config.include_paused,
        now=now,
    )
    return IngestionScope(
        symbols=wl.effective,
        resolved=wl.resolvable,
        filing_forms=tuple(config.filing_forms),
        insider_forms=config.effective_insider_forms(),
        history_days=config.history_days,
        history_start=config.history_start(now),
        watchlist=wl,
        generated_at_utc=now,
    )
