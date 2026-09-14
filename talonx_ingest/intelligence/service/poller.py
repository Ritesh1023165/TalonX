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
from collections.abc import Callable
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
from talonx_ingest.intelligence.service.state_machine import ProcessingStage
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
    @staticmethod
    def _report_progress(
        progress_cb: "Callable[[int, int, str], None] | None",
        symbols_done: int,
        symbols_total: int,
        last_symbol: str,
    ) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(symbols_done, symbols_total, last_symbol)
        except Exception:  # noqa: BLE001 - a progress observer must never break polling
            logger.debug("progress_cb raised; ignored", exc_info=True)

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
        self,
        *,
        now: datetime | None = None,
        symbols: list[str] | None = None,
        progress_cb: "Callable[[int, int, str], None] | None" = None,
        enrich_progress_cb: "Callable[[int, int, str], None] | None" = None,
    ) -> PollCycleResult:
        """``progress_cb(symbols_done, symbols_total, last_symbol)`` is invoked
        after every symbol is attempted (success or failure) -- a bounded,
        in-memory-only hook so a full first pass over a large scope (e.g. a
        broad-discovery expansion) can expose live progress without waiting
        for the whole cycle to finish.

        ``enrich_progress_cb(events_done, events_total, last_event_id)`` is
        invoked the same way, but for the SEPARATE downstream per-event
        significance/comparison enrichment pass below -- confirmed (Task 132
        section 2) to be the dominant cost of a large first cycle, not the
        per-symbol fetch loop: enrichment awaits ``process_event`` for every
        newly discovered event ONE AT A TIME, so a scope expansion that
        surfaces tens of thousands of new events can spend far longer here
        than fetching them. Both callbacks are optional; ``None`` for either
        is a byte-identical no-op for every existing caller/test."""
        now = now or datetime.now(timezone.utc)
        result = PollCycleResult(started_at_utc=now)
        t0 = time.monotonic()
        since = self.config.history_start(now)
        latest_event_ts: datetime | None = None
        touched_ownership = False
        ownership_ok = True
        form4_budget = self.config.poll_max_form4_per_cycle
        only = {s.upper() for s in symbols} if symbols else None

        cycle_symbols = self._cycle_symbols(only)
        symbols_total = len(cycle_symbols)
        for idx, rs in enumerate(cycle_symbols, start=1):
            call_t0 = time.monotonic()
            try:
                subs = await self.client.get_submissions(rs.cik)
            except Exception as exc:  # noqa: BLE001
                result.symbols_failed += 1
                result.errors.append(f"{rs.symbol}: {exc}")
                dec = classify_error(exc)
                self.metrics.record_poll(success=False, got_429=("429" in str(exc)))
                logger.warning("poll %s failed (%s): %s", rs.symbol, dec.cls.value, exc)
                self._report_progress(progress_cb, idx, symbols_total, rs.symbol)
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

            self._report_progress(progress_cb, idx, symbols_total, rs.symbol)

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
        # Task 133: bounded by count (enrich_max_events_per_cycle) and/or
        # wall-clock (enrich_time_budget_seconds) -- 0 means unbounded on
        # either axis, preserving the exact pre-Task-133 behaviour by
        # default. An event beyond the bound is NOT silently dropped: it
        # is durably registered (ps.ensure, cheap/local/no network) at
        # STORED so the SEPARATE, unbounded-scope recovery pass
        # (IntelligenceService.reconcile_and_enrich, which reuses the
        # SAME intel_event_processing table) picks it up on a later,
        # regular cadence instead of blocking THIS cycle's own delivery
        # opportunity. This is the fix for whole-cycle delivery
        # starvation on a large first pass -- not just progress logging.
        if self.enrichment is not None and result.new_event_ids:
            self.enrichment.source_status = snap.status.value
            unique_ids = list(dict.fromkeys(result.new_event_ids))
            enrich_total = len(unique_ids)
            max_events = self.config.enrich_max_events_per_cycle
            time_budget = self.config.enrich_time_budget_seconds
            enrich_t0 = time.monotonic()
            for enrich_done, eid in enumerate(unique_ids, start=1):
                over_count_budget = max_events and enrich_done > max_events
                over_time_budget = time_budget and (time.monotonic() - enrich_t0) > time_budget
                if over_count_budget or over_time_budget:
                    self._defer_to_recovery(eid)
                    continue
                try:
                    await self.enrichment.process_event(eid, origin="poll", now=now)
                except Exception as exc:  # noqa: BLE001 - never let one event kill the cycle
                    result.errors.append(f"enrich {eid}: {exc}")
                    logger.exception("enrichment failed for %s", eid)
                self._report_progress(enrich_progress_cb, enrich_done, enrich_total, eid)

        result.duration_seconds = round(time.monotonic() - t0, 3)
        return result

    def _defer_to_recovery(self, event_id: str) -> None:
        """Task 133: durably register a discovered-but-not-yet-enriched
        event at STORED (cheap, local, no network -- see ProcessingState
        Store.ensure's ON CONFLICT DO NOTHING) so it is picked up by the
        bounded recovery pass instead of being lost when this poll_once()
        call's own in-memory new_event_ids list goes out of scope."""
        try:
            ev = self.stores.events.get_event(event_id)
        except Exception:  # noqa: BLE001 -- deferral must never break the cycle
            logger.warning("_defer_to_recovery: could not load %s", event_id, exc_info=True)
            return
        if ev is None:
            return
        self.stores.processing.ensure(
            event_id,
            symbol=ev.symbol, event_type=ev.event_type.value,
            form_type=ev.form_type, accession=ev.accession,
            origin="poll", stage=ProcessingStage.STORED,
        )
