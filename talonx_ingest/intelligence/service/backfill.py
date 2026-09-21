"""
talonx_ingest.intelligence.service.backfill
===========================================
Bounded, idempotent, resumable historical backfill (Phases 4–5).

Scope per :class:`IngestionScope`: for each effective watchlist symbol,
pull 8-K / 10-Q / 10-K filing history and Form 4 (optionally 3/5) ownership
history back to ``history_start`` (default 900 days) — no further.

* **bounded**   — nothing older than ``history_start``; per-symbol filing
  and Form-4 caps (``ServiceConfig``).
* **idempotent** — every write goes through the same 96A/96D upserts the
  poller uses; a re-run creates zero duplicates.
* **resumable**  — a ``(symbol, source, form)`` unit marked ``completed``
  in :class:`BackfillCheckpointStore` is skipped; an interrupted unit
  re-runs harmlessly and converges.
* **rate-limited / cached** — all SEC I/O goes through ``EdgarClient`` and
  the on-disk document caches.

Live polling always has priority over backfill — that ordering is enforced
by the runner, not here.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from talonx_ingest.intelligence.domain import (
    EventType,
    FreshnessStatus,
    SourceType,
)
from talonx_ingest.intelligence.edgar_normalize import iter_normalized_filings
from talonx_ingest.intelligence.identity import event_id as make_event_id
from talonx_ingest.intelligence.service._ingest import (
    ingest_symbol_filings,
    load_submissions_window,
)
from talonx_ingest.intelligence.service._insider import ingest_form_ownership
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.observability import ServiceMetrics
from talonx_ingest.intelligence.service.retry import classify_error
from talonx_ingest.intelligence.service.scope import IngestionScope
from talonx_ingest.intelligence.service.stores import StoreBundle

logger = logging.getLogger("talonx_ingest.intelligence.service.backfill")

_SUBMISSIONS_SOURCE = "edgar_submissions"
_OWNERSHIP_SOURCE = "edgar_form4_xml"


@dataclass
class SymbolBackfillResult:
    symbol: str
    cik: str
    filings_seen: int = 0
    events_new: int = 0
    events_existing: int = 0
    ownership_filings: int = 0
    ownership_transactions: int = 0
    new_event_ids: list[str] = field(default_factory=list)
    units_completed: list[str] = field(default_factory=list)
    units_skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class BackfillReport:
    started_at_utc: datetime
    symbols: list[str] = field(default_factory=list)
    per_symbol: list[SymbolBackfillResult] = field(default_factory=list)
    total_new_events: int = 0
    total_ownership_filings: int = 0
    duration_seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            "started_at_utc": self.started_at_utc.isoformat(),
            "symbols": self.symbols,
            "total_new_events": self.total_new_events,
            "total_ownership_filings": self.total_ownership_filings,
            "duration_seconds": self.duration_seconds,
            "per_symbol": [
                {
                    "symbol": r.symbol, "cik": r.cik,
                    "filings_seen": r.filings_seen,
                    "events_new": r.events_new, "events_existing": r.events_existing,
                    "ownership_filings": r.ownership_filings,
                    "ownership_transactions": r.ownership_transactions,
                    "units_completed": r.units_completed,
                    "units_skipped": r.units_skipped,
                    "errors": r.errors,
                }
                for r in self.per_symbol
            ],
        }


class Backfill:
    def __init__(
        self,
        stores: StoreBundle,
        client,
        *,
        config: ServiceConfig,
        scope: IngestionScope,
        metrics: ServiceMetrics | None = None,
        enrichment=None,
    ):
        self.stores = stores
        self.client = client
        self.config = config
        self.scope = scope
        self.metrics = metrics or ServiceMetrics()
        self.enrichment = enrichment

    # ------------------------------------------------------------------
    async def run(
        self,
        *,
        symbols: list[str] | None = None,
        enrich: bool = True,
        now: datetime | None = None,
    ) -> BackfillReport:
        now = now or datetime.now(timezone.utc)
        t0 = time.monotonic()
        wanted = {s.upper() for s in symbols} if symbols else None
        targets = [r for r in self.scope.resolved if wanted is None or r.symbol in wanted]
        report = BackfillReport(started_at_utc=now, symbols=[r.symbol for r in targets])

        cp = self.stores.checkpoints
        insider_forms = self.config.effective_insider_forms()
        self.metrics.backfill_units_total = len(targets) * (
            len(self.config.filing_forms) + 1
        )

        for rs in targets:
            sr = SymbolBackfillResult(symbol=rs.symbol, cik=rs.cik)
            try:
                await self._filings_for_symbol(rs, sr, now)
            except Exception as exc:  # noqa: BLE001
                sr.errors.append(f"filings: {exc}")
                logger.exception("backfill filings failed for %s", rs.symbol)
            try:
                await self._ownership_for_symbol(rs, sr, insider_forms, now)
            except Exception as exc:  # noqa: BLE001
                sr.errors.append(f"ownership: {exc}")
                logger.exception("backfill ownership failed for %s", rs.symbol)

            if enrich and self.enrichment is not None and sr.new_event_ids:
                for eid in list(dict.fromkeys(sr.new_event_ids)):
                    try:
                        await self.enrichment.process_event(eid, origin="backfill", now=now)
                    except Exception as exc:  # noqa: BLE001
                        sr.errors.append(f"enrich {eid}: {exc}")

            report.per_symbol.append(sr)
            report.total_new_events += sr.events_new
            report.total_ownership_filings += sr.ownership_filings
            self.metrics.backfill_units_complete += len(sr.units_completed)

        report.duration_seconds = round(time.monotonic() - t0, 3)
        cp_summary = cp.summary()
        self.metrics.backfill_units_total = cp_summary["units"]
        self.metrics.backfill_units_complete = cp_summary["completed"]
        return report

    # ------------------------------------------------------------------
    async def _filings_for_symbol(self, rs, sr: SymbolBackfillResult, now: datetime) -> None:
        cp = self.stores.checkpoints
        since = self.config.history_start(now)
        forms = self.config.filing_forms

        pending = [
            f for f in forms
            if not (c := cp.get(rs.symbol, _SUBMISSIONS_SOURCE, f)) or not c.completed
        ]
        for f in forms:
            if f not in pending:
                sr.units_skipped.append(f"{_SUBMISSIONS_SOURCE}:{f}")
        if not pending:
            return

        for f in pending:
            cp.ensure(rs.symbol, _SUBMISSIONS_SOURCE, f, cik=rs.cik, history_start=since)
            cp.record_attempt(rs.symbol, _SUBMISSIONS_SOURCE, f)

        try:
            window = await load_submissions_window(self.client, rs.cik, since_date=since)
        except Exception as exc:  # noqa: BLE001
            for f in pending:
                cp.mark_error(rs.symbol, _SUBMISSIONS_SOURCE, f, f"window fetch: {exc}")
            raise

        for f in pending:
            si = ingest_symbol_filings(
                self.stores.events, window,
                symbol=rs.symbol, forms=(f,), since_date=since, now=now,
                freshness=FreshnessStatus.UNKNOWN,
                limit=self.config.backfill_max_filings_per_symbol,
            )
            sr.filings_seen += si.filings_seen
            sr.events_new += si.events_new
            sr.events_existing += si.events_existing
            sr.new_event_ids.extend(si.new_event_ids)
            self.metrics.backfill_filings_fetched += si.filings_seen
            self.metrics.events_stored += si.events_new
            self.metrics.events_duplicate_suppressed += si.events_existing
            cp.record_progress(
                rs.symbol, _SUBMISSIONS_SOURCE, f,
                earliest_processed_date=si.earliest_filing_date,
                latest_processed_date=si.latest_filing_date,
                last_accession=si.last_accession,
                filings_seen_delta=si.filings_seen,
                events_written_delta=si.events_new,
                completed=True, clear_error=True,
            )
            sr.units_completed.append(f"{_SUBMISSIONS_SOURCE}:{f}")

    # ------------------------------------------------------------------
    async def _ownership_for_symbol(
        self, rs, sr: SymbolBackfillResult, insider_forms, now: datetime
    ) -> None:
        cp = self.stores.checkpoints
        since = self.config.history_start(now)
        unit = cp.get(rs.symbol, _OWNERSHIP_SOURCE, "4")
        if unit and unit.completed:
            sr.units_skipped.append(f"{_OWNERSHIP_SOURCE}:4")
            return
        cp.ensure(rs.symbol, _OWNERSHIP_SOURCE, "4", cik=rs.cik, history_start=since)
        cp.record_attempt(rs.symbol, _OWNERSHIP_SOURCE, "4")

        try:
            window = await load_submissions_window(self.client, rs.cik, since_date=since)
        except Exception as exc:  # noqa: BLE001
            cp.mark_error(rs.symbol, _OWNERSHIP_SOURCE, "4", f"window fetch: {exc}")
            raise

        seen = 0
        cap = self.config.backfill_max_form4_per_symbol
        earliest = latest = None
        last_acc = None
        for nf in iter_normalized_filings(window, symbol=rs.symbol, forms=insider_forms):
            fdate = nf.filing_date or (
                nf.acceptance_datetime.date() if nf.acceptance_datetime else None
            )
            if fdate is not None and fdate < since:
                continue
            if seen >= cap:
                break
            seen += 1
            last_acc = nf.accession
            if fdate is not None:
                earliest = fdate if earliest is None or fdate < earliest else earliest
                latest = fdate if latest is None or fdate > latest else latest

            eid = make_event_id(
                SourceType.SEC_EDGAR_SUBMISSIONS, nf.accession, EventType.INSIDER_TRANSACTION
            )
            if self.stores.events.has_event(eid):
                self.metrics.backfill_filings_skipped += 1
                continue
            outcome = await ingest_form_ownership(
                self.client, self.stores.insider, self.stores.events,
                cik=rs.cik, accession=nf.accession, symbol=rs.symbol,
                form_type=nf.form, accepted_at_utc=nf.acceptance_datetime,
                primary_document=nf.primary_document,
                cache_dir=self.config.state_dir / "form_ownership_xml_cache",
            )
            if outcome.ok:
                sr.ownership_filings += 1
                sr.ownership_transactions += outcome.transactions_total
                self.metrics.insider_filings += 1
                self.metrics.insider_transactions += outcome.transactions_total
                if self.stores.events.has_event(eid):
                    sr.new_event_ids.append(eid)
            else:
                self.metrics.insider_parse_failures += 1
                sr.errors.append(f"form4 {nf.accession}: {outcome.error}")
                dec = classify_error(outcome.error or "")
                if dec.retryable:
                    cp.mark_error(rs.symbol, _OWNERSHIP_SOURCE, "4", outcome.error or "unknown")

        cp.record_progress(
            rs.symbol, _OWNERSHIP_SOURCE, "4",
            earliest_processed_date=earliest, latest_processed_date=latest,
            last_accession=last_acc,
            filings_seen_delta=seen, events_written_delta=sr.ownership_filings,
            completed=True,
            clear_error=not any("form4" in e for e in sr.errors),
        )
        sr.units_completed.append(f"{_OWNERSHIP_SOURCE}:4")
