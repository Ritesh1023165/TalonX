"""
talonx_ingest.intelligence.service.poller
=========================================
Continuous incremental SEC EDGAR polling (Phases 6–9).

Per cycle, for each effective watchlist symbol:

* fetch the company submissions feed (``filings.recent`` only — no
  full-history re-fetch);
* normalise + store any 8-K / 10-Q / 10-K within the history window that is
  not already in the 96A store (idempotent — the store dedupes on
  ``event_id``);
* detect Form 4/3/5 accessions not yet seen and ingest their ownership XML
  (96D);
* record a single successful/failed poll on the ``SourceFreshnessTracker``
  for ``SEC_EDGAR_SUBMISSIONS`` (and ``SEC_FORM345_BULK`` when ownership
  filings were touched) — **a quiet cycle with no new filing is still a
  success** (Phase 8);
* hand every newly-created ``event_id`` to the enrichment engine.

Nothing here busy-loops; cadence is the runner's job.
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
from talonx_ingest.intelligence.freshness import SourceFreshnessTracker
from talonx_ingest.intelligence.identity import event_id as make_event_id
from talonx_ingest.intelligence.service._ingest import ingest_symbol_filings
from talonx_ingest.intelligence.service._insider import ingest_form_ownership
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.observability import ServiceMetrics
from talonx_ingest.intelligence.service.retry import classify_error
from talonx_ingest.intelligence.service.scope import IngestionScope
from talonx_ingest.intelligence.service.stores import StoreBundle

logger = logging.getLogger("talonx_ingest.intelligence.service.poller")


@dataclass
class PollCycleResult:
    started_at_utc: datetime
    symbols_polled: int = 0
    symbols_failed: int = 0
    filings_seen: int = 0
    new_event_ids: list[str] = field(default_factory=list)
    new_form4_filings: int = 0
    submissions_freshness: str = FreshnessStatus.UNKNOWN.value
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def had_success(self) -> bool:
        return self.symbols_polled > 0 and self.symbols_polled > self.symbols_failed


class EdgarPoller:
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
        self.freshness = SourceFreshnessTracker(stores.events)
        self._rotation_cursor = 0

    # ------------------------------------------------------------------
    def _cycle_symbols(self, only: set[str] | None = None):
        resolved = [r for r in self.scope.resolved if only is None or r.symbol in only]
        n = self.config.poll_max_symbols_per_cycle
        if not n or n <= 0 or n >= len(resolved):
            return resolved
        start = self._rotation_cursor % len(resolved)
        picked = (resolved + resolved)[start : start + n]
        self._rotation_cursor = (start + n) % len(resolved)
        return picked

    # ------------------------------------------------------------------
    async def poll_once(
        self, *, now: datetime | None = None, symbols: list[str] | None = None
    ) -> PollCycleResult:
        now = now or datetime.now(timezone.utc)
        result = PollCycleResult(started_at_utc=now)
        t0 = time.monotonic()
        since = self.config.history_start(now)
        latest_event_ts: datetime | None = None
        touched_ownership = False
        ownership_ok = True
        form4_budget = self.config.poll_max_form4_per_cycle
        only = {s.upper() for s in symbols} if symbols else None

        for rs in self._cycle_symbols(only):
            call_t0 = time.monotonic()
            try:
                subs = await self.client.get_submissions(rs.cik)
            except Exception as exc:  # noqa: BLE001
                result.symbols_failed += 1
                result.errors.append(f"{rs.symbol}: {exc}")
                dec = classify_error(exc)
                self.metrics.record_poll(success=False, got_429=("429" in str(exc)))
                logger.warning("poll %s failed (%s): %s", rs.symbol, dec.cls.value, exc)
                continue
            latency_ms = (time.monotonic() - call_t0) * 1000.0
            self.metrics.record_poll(success=True, latency_ms=latency_ms)
            result.symbols_polled += 1

            si = ingest_symbol_filings(
                self.stores.events, subs,
                symbol=rs.symbol, forms=self.config.filing_forms,
                since_date=since, now=now,
            )
            result.filings_seen += si.filings_seen
            result.new_event_ids.extend(si.new_event_ids)
            self.metrics.events_discovered += si.events_built
            self.metrics.events_stored += si.events_new
            self.metrics.events_duplicate_suppressed += si.events_existing
            if si.latest_acceptance_utc and (
                latest_event_ts is None or si.latest_acceptance_utc > latest_event_ts
            ):
                latest_event_ts = si.latest_acceptance_utc

            # -- ownership filings (Form 4/3/5) ---------------------
            for nf in iter_normalized_filings(
                subs, symbol=rs.symbol, forms=self.config.effective_insider_forms()
            ):
                fdate = nf.filing_date or (
                    nf.acceptance_datetime.date() if nf.acceptance_datetime else None
                )
                if fdate is not None and fdate < since:
                    continue
                eid = make_event_id(
                    SourceType.SEC_EDGAR_SUBMISSIONS, nf.accession, EventType.INSIDER_TRANSACTION
                )
                if self.stores.events.has_event(eid):
                    continue
                if form4_budget is not None and form4_budget <= 0:
                    result.errors.append(
                        f"{rs.symbol}: form4 per-cycle budget exhausted — deferred to next cycle"
                    )
                    break
                if form4_budget is not None:
                    form4_budget -= 1
                touched_ownership = True
                outcome = await ingest_form_ownership(
                    self.client, self.stores.insider, self.stores.events,
                    cik=rs.cik, accession=nf.accession, symbol=rs.symbol,
                    form_type=nf.form, accepted_at_utc=nf.acceptance_datetime,
                    primary_document=nf.primary_document,
                    cache_dir=self.config.state_dir / "form_ownership_xml_cache",
                )
                if outcome.ok:
                    result.new_form4_filings += 1
                    self.metrics.insider_filings += 1
                    self.metrics.insider_transactions += outcome.transactions_total
                    if self.stores.events.has_event(eid):
                        result.new_event_ids.append(eid)
                else:
                    ownership_ok = False
                    self.metrics.insider_parse_failures += 1
                    result.errors.append(f"{rs.symbol} form4 {nf.accession}: {outcome.error}")

        # -- freshness bookkeeping (quiet != failure) -----------------
        snap = self.freshness.record_attempt(
            SourceType.SEC_EDGAR_SUBMISSIONS,
            success=result.had_success,
            latest_source_event_utc=latest_event_ts,
        )
        result.submissions_freshness = snap.status.value
        if touched_ownership:
            self.freshness.record_attempt(
                SourceType.SEC_FORM345_BULK, success=ownership_ok
            )

        # -- downstream enrichment for new events -------------------
        if self.enrichment is not None and result.new_event_ids:
            self.enrichment.source_status = snap.status.value
            for eid in list(dict.fromkeys(result.new_event_ids)):
                try:
                    await self.enrichment.process_event(eid, origin="poll", now=now)
                except Exception as exc:  # noqa: BLE001 - never let one event kill the cycle
                    result.errors.append(f"enrich {eid}: {exc}")
                    logger.exception("enrichment failed for %s", eid)

        result.duration_seconds = round(time.monotonic() - t0, 3)
        return result
