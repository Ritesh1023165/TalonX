"""
talonx_ingest.intelligence.service.runner
=========================================
``IntelligenceService`` — the supervised loop that ties scope + poller +
backfill + enrichment together (Phases 19–22, 30–33).

Design points:

* **Own process.** Never started by the trading engine; imports nothing
  from ``talonx_quant`` / ``talonx_core.decision`` / ``talonx_paper`` /
  ``talonx_piv`` / any order path.
* **Live priority.** In the combined loop the live poll cycle + retry drain
  always run to completion before backfill advances by a single symbol.
* **Quiet ≠ down.** Sleep cadence is driven by the freshness *status*
  (FRESH→base, STALE→recovery, DOWN→backoff), never by "did a filing
  arrive".
* **Restart-safe.** All progress lives in the ledger DB
  (checkpoint/state/outbox stores); a kill + restart resumes.
* **Dry-run delivery.** Enrichment only *enqueues* durable outbox rows; no
  external Telegram send happens here (Phase 13).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from talonx_ingest.edgar.client import EdgarClient
from talonx_ingest.intelligence.domain import FreshnessStatus, SourceType
from talonx_ingest.intelligence.freshness import SourceFreshnessTracker
from talonx_ingest.intelligence.service.backfill import Backfill, BackfillReport
from talonx_ingest.intelligence.service.cik_directory import CikDirectory
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.enrichment import EnrichmentEngine
from talonx_ingest.intelligence.service.observability import ServiceMetrics
from talonx_ingest.intelligence.service.poller import EdgarPoller, PollCycleResult
from talonx_ingest.intelligence.service.scope import IngestionScope, resolve_scope
from talonx_ingest.intelligence.service.state_machine import ProcessingStage
from talonx_ingest.intelligence.service.singleton import read_heartbeat, write_heartbeat
from talonx_ingest.intelligence.service.stores import StoreBundle
from talonx_watchlist.config import WatchlistConfig
from talonx_watchlist.store import TickerWatchlistStore

logger = logging.getLogger("talonx_ingest.intelligence.service.runner")


class _InertSender:
    """Placeholder passed to ``process_pending`` in ``mode="disabled"`` -- it is
    never called (disabled mode does not invoke a sender), it only satisfies the
    signature."""

    configured = False

    async def send(self, row):  # pragma: no cover - never reached in disabled mode
        raise RuntimeError("inert sender must not be called")


class IntelligenceService:
    def __init__(self, config: ServiceConfig | None = None):
        self.config = config or ServiceConfig.from_env()
        self.metrics = ServiceMetrics()
        self.stores: StoreBundle | None = None
        self.client: EdgarClient | None = None
        self.directory: CikDirectory | None = None
        self.scope: IngestionScope | None = None
        self.poller: EdgarPoller | None = None
        self.backfill: Backfill | None = None
        self.enrichment: EnrichmentEngine | None = None
        self._watchlist: TickerWatchlistStore | None = None
        self._owns_watchlist = False
        self._stop = asyncio.Event()
        # Task 131 Directive 4/5: per-symbol origin, for the dashboard's
        # broad-discovery panel to distinguish PRODUCT_WATCHLIST from
        # BROAD_DISCOVERY without a second scope/process/rate-limiter.
        self.scope_origin_by_symbol: dict[str, str] = {}

    # ------------------------------------------------------------------
    def request_stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    async def open(self, *, with_network: bool = True) -> "IntelligenceService":
        self.stores = StoreBundle.open(self.config.ledger())
        self._watchlist = TickerWatchlistStore(WatchlistConfig().db_path)
        self._owns_watchlist = True

        if with_network:
            self.client = EdgarClient()
            await self.client.__aenter__()
            self.directory = await CikDirectory.load(
                self.client,
                cache_path=self.config.company_tickers_cache_path(),
                max_age_days=self.config.company_tickers_max_age_days,
            )
        else:
            self.directory = self._directory_from_cache()

        self.scope = resolve_scope(
            config=self.config,
            watchlist_store=self._watchlist,
            directory=self.directory,
        )
        logger.info("scope: %s", self.scope.watchlist.summary_line())
        self._apply_broad_discovery()

        self.enrichment = EnrichmentEngine(
            self.stores, self.client, config=self.config, metrics=self.metrics,
            freshness=SourceFreshnessTracker(self.stores.events),
        )
        self.poller = EdgarPoller(
            self.stores, self.client, config=self.config, scope=self.scope,
            metrics=self.metrics, enrichment=self.enrichment,
        )
        self.backfill = Backfill(
            self.stores, self.client, config=self.config, scope=self.scope,
            metrics=self.metrics, enrichment=self.enrichment,
        )
        return self

    def _directory_from_cache(self) -> CikDirectory:
        import json

        p = self.config.company_tickers_cache_path()
        if p.is_file():
            try:
                return CikDirectory.from_company_tickers(
                    json.loads(p.read_text(encoding="utf-8")), from_cache=True
                )
            except (OSError, ValueError):
                pass
        return CikDirectory.from_company_tickers({}, from_cache=False)

    async def close(self) -> None:
        if self.client is not None:
            try:
                await self.client.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
            self.client = None
        if self.stores is not None:
            self.stores.close()
        if self._owns_watchlist and self._watchlist is not None:
            self._watchlist.close()

    async def __aenter__(self) -> "IntelligenceService":
        return await self.open()

    async def __aexit__(self, *exc) -> None:
        await self.close()

    # ------------------------------------------------------------------
    async def refresh_scope(self) -> None:
        assert self._watchlist is not None and self.directory is not None
        self.scope = resolve_scope(
            config=self.config, watchlist_store=self._watchlist, directory=self.directory
        )
        self._apply_broad_discovery()
        if self.poller is not None:
            self.poller.scope = self.scope
        if self.backfill is not None:
            self.backfill.scope = self.scope

    def _apply_broad_discovery(self) -> None:
        """Task 131 Directive 4: additive, opt-in (TALONX_INTEL_ENABLE_
        BROAD_DISCOVERY). Unions the 626-name Discovery Universe v1 into
        THIS SAME scope/process (so the shared SEC rate-limit budget is
        genuinely shared, not doubled by a second poller). A no-op,
        byte-identical to pre-Task-131 behaviour, unless explicitly
        enabled."""
        from talonx_ingest.intelligence.service.broad_discovery import (
            extend_scope_with_broad_discovery)
        assert self.scope is not None and self.directory is not None
        self.scope, self.scope_origin_by_symbol = extend_scope_with_broad_discovery(
            self.scope, self.directory)

    # ------------------------------------------------------------------
    async def poll_cycle(
        self, *, now: datetime | None = None, symbols: list[str] | None = None
    ) -> PollCycleResult:
        assert self.poller is not None
        cycle_started_at_utc = (now or datetime.now(timezone.utc)).isoformat()
        cycle_started_monotonic = time.monotonic()
        last_write_monotonic = 0.0
        known: dict = {}  # fields carried forward across writes (e.g. the
                           # symbol-phase totals still matter once enrichment starts)

        def _write(payload: dict, *, force: bool = False) -> None:
            nonlocal last_write_monotonic
            now_m = time.monotonic()
            if not force and (now_m - last_write_monotonic) < self.config.progress_write_min_interval_seconds:
                return
            last_write_monotonic = now_m
            known.update(payload)
            base = {
                "cycle_started_at_utc": cycle_started_at_utc,
                "elapsed_seconds": round(now_m - cycle_started_monotonic, 1),
                "cycle_complete": False,
            }
            base.update(known)
            write_heartbeat(self.config.progress_path(), base)

        def _on_symbol_progress(done: int, total: int, last_symbol: str) -> None:
            _write({
                "phase": "polling",
                "symbols_done": done, "symbols_total": total, "last_symbol": last_symbol,
            }, force=(done >= total))

        def _on_enrich_progress(done: int, total: int, last_event_id: str) -> None:
            _write({
                "phase": "enriching",
                "events_done": done, "events_total": total, "last_event_id": last_event_id,
            }, force=(done >= total))

        res = await self.poller.poll_once(
            now=now, symbols=symbols,
            progress_cb=_on_symbol_progress, enrich_progress_cb=_on_enrich_progress,
        )
        # one final, unthrottled write marking the whole poll_cycle() (fetch +
        # enrichment) truly complete -- distinct from either phase's own last
        # write, since enrichment can finish an instant after its own last
        # throttled/forced write above.
        _write({"phase": "done", "cycle_complete": True}, force=True)
        logger.info(
            "poll cycle: polled=%d failed=%d filings=%d new_events=%d form4=%d fresh=%s %.2fs",
            res.symbols_polled, res.symbols_failed, res.filings_seen,
            len(res.new_event_ids), res.new_form4_filings,
            res.submissions_freshness, res.duration_seconds,
        )
        return res

    async def deliver_cycle(self, *, now: datetime | None = None) -> dict | None:
        """One bounded intelligence-card delivery pass, inside the poll loop.

        Uses the EXISTING official transport (``talonx_dispatch.telegram_client``
        via ``TelegramSenderAdapter``) -- no second poller, no parallel loop.

        * ``deliver_intelligence_cards`` off (default) -> ``mode="disabled"``:
          eligible rows stay PENDING with ``held_reason``, nothing sent/mutated.
        * on + ``dry_run_delivery`` False + transport configured -> ``mode="enabled"``
          with the D5 age cutoff. IMMEDIATE first (route order), then DIGEST, so
          a DIGEST card is not sent as if it were IMMEDIATE.
        * a hard ``asyncio.wait_for`` timeout means a slow/backing-off transport
          never blocks source polling.
        """
        if self.stores is None:
            return None
        from talonx_ingest.intelligence.delivery.pipeline import (
            TelegramSenderAdapter, process_digest, process_pending,
        )

        # (1D) decision time = NOW, at drain, never the (possibly minutes-old)
        # poll-cycle timestamp -- the `now` arg is ignored on purpose except in
        # tests that pin it.
        now = now or datetime.now(timezone.utc)

        enabled = (
            bool(self.config.deliver_intelligence_cards)
            and not self.config.dry_run_delivery
        )
        mode = "enabled" if enabled else "disabled"
        sender = TelegramSenderAdapter() if enabled else _InertSender()

        def _event_time(event_id: str):
            try:
                ev = self.stores.events.get_event(event_id)
                return getattr(ev, "accepted_at_utc", None) if ev is not None else None
            except Exception:  # noqa: BLE001
                return None

        summary: dict = {"mode": mode, "at_utc": now.isoformat(), "ok": True}
        try:
            # IMMEDIATE -> individual sends; DIGEST -> aggregated on a schedule.
            imm = await asyncio.wait_for(
                process_pending(
                    self.stores.outbox, sender, mode=mode, route="IMMEDIATE",
                    limit=self.config.deliver_cards_per_cycle,
                    now=now,
                    enforce_age_cutoff=(
                        enabled and self.config.deliver_cards_enforce_age_cutoff),
                    event_time_lookup=_event_time,
                    expire_scan_limit=self.config.expire_scan_max_rows_per_cycle,
                ),
                timeout=self.config.deliver_cards_timeout_seconds,
            )
            dig = await asyncio.wait_for(
                process_digest(
                    self.stores.outbox, sender, mode=mode,
                    interval_seconds=self.config.deliver_digest_interval_seconds,
                    limit=self.config.deliver_cards_per_cycle,
                    now=now,
                    enforce_age_cutoff=(
                        enabled and self.config.deliver_cards_enforce_age_cutoff),
                    event_time_lookup=_event_time,
                    expire_scan_limit=self.config.expire_scan_max_rows_per_cycle,
                ),
                timeout=self.config.deliver_cards_timeout_seconds,
            )
            for route, res in (("IMMEDIATE", imm), ("DIGEST", dig)):
                summary[route] = {
                    "delivered": res.delivered, "held": res.held,
                    "simulated": res.simulated, "retried": res.retried,
                    "failed": res.failed, "ambiguous": res.ambiguous,
                    "expired": res.expired,
                    "held_reason": res.held_reason,
                    "message_ids": res.message_ids,
                    "row_errors": res.errors,
                    "skipped_not_configured": res.skipped_not_configured,
                }
                if res.errors:
                    summary["ok"] = False
        except asyncio.CancelledError:
            # shutdown -- propagate. process_pending has already marked any
            # in-flight row AMBIGUOUS.
            raise
        except asyncio.TimeoutError:
            logger.warning(
                "intelligence-card delivery drain timed out (%ss); poll loop continues",
                self.config.deliver_cards_timeout_seconds,
            )
            summary["timed_out"] = True
            summary["ok"] = False
        except Exception as exc:  # noqa: BLE001
            # (1E) an unexpected delivery error must be VISIBLE and must NOT
            # terminate source polling or be swallowed into a healthy state.
            logger.error("intelligence-card delivery cycle failed: %r -- poll loop continues", exc)
            summary["error"] = repr(exc)
            summary["ok"] = False
        if any(
            isinstance(v, dict) and (v.get("delivered") or v.get("failed") or v.get("ambiguous") or v.get("expired"))
            for v in summary.values()
        ):
            logger.info("intelligence-card delivery: %s", summary)
        return summary

    async def reconcile_and_enrich(self, *, now: datetime | None = None) -> dict:
        """Task 133: the bounded, backward-compatible recovery pass --
        called every poll-loop iteration, BETWEEN poll_cycle() and
        deliver_cycle(), so a large enrichment backlog can never again
        starve deliver_cycle() of a turn the way the old unbounded
        post-fetch loop inside poll_once() could.

        (1) RECONCILE: registers any ``text_events`` row with no
            ``intel_event_processing`` row yet -- a cheap, local, indexed
            anti-join (``find_undiscovered_events``), bounded by
            ``reconcile_max_events_per_cycle``. This is what makes an
            event persisted by an OLDER process version (or deferred by
            ``poll_once``'s own bounded enrichment via ``_defer_to_
            recovery``) discoverable again, independent of ingestion
            deduplication -- deduplication only ever prevents a SECOND
            ``text_events`` row for the same accession, it says nothing
            about whether that row has been enriched.
        (2) ENRICH: pulls a bounded batch (count and/or time budget --
            ``enrich_max_events_per_cycle`` / ``enrich_time_budget_
            seconds``, the SAME knobs ``poll_once``'s own inline
            enrichment bound uses) of ``next_for_processing`` -- every
            OPEN stage, honouring retry backoff -- and runs
            ``process_event`` on each, wall-clock-capped per event
            (``enrich_per_event_timeout_seconds``) so one bad/slow event
            cannot block the whole batch; a timeout is recorded as a
            bounded, backed-off retryable failure via ``record_error``,
            never a silent indefinite hang.

        Idempotent and duplicate-safe by construction: ``process_event``
        already re-derives its own stage from the row's current
        sub-states (Task 96C/E/F) rather than assuming a fresh start, so
        replaying a PARTIAL/interrupted row resumes rather than redoing
        completed steps, and card enqueue (``_enqueue_delivery``) itself
        is dedup-keyed on ``event_id`` -- neither reconciliation nor a
        retried enrichment pass can create a second card for one event.
        """
        assert self.stores is not None and self.enrichment is not None
        now = now or datetime.now(timezone.utc)
        ps = self.stores.processing

        # (1) reconcile -- make orphaned persisted events discoverable
        reconciled = 0
        for eid in ps.find_undiscovered_events(limit=self.config.reconcile_max_events_per_cycle):
            ev = self.stores.events.get_event(eid)
            if ev is None:
                continue
            ps.ensure(
                eid, symbol=ev.symbol, event_type=ev.event_type.value,
                form_type=ev.form_type, accession=ev.accession, origin="recovery",
                stage=ProcessingStage.STORED,
            )
            reconciled += 1

        # (2) bounded enrichment batch
        max_events = self.config.enrich_max_events_per_cycle or None
        time_budget = self.config.enrich_time_budget_seconds or None
        per_event_timeout = self.config.enrich_per_event_timeout_seconds or None
        rows = ps.next_for_processing(now=now, limit=max_events)
        enriched = timed_out = failed = 0
        t0 = time.monotonic()
        for row in rows:
            if time_budget and (time.monotonic() - t0) > time_budget:
                break
            try:
                coro = self.enrichment.process_event(row.event_id, origin=row.origin, now=now)
                if per_event_timeout:
                    await asyncio.wait_for(coro, timeout=per_event_timeout)
                else:
                    await coro
                enriched += 1
            except asyncio.TimeoutError:
                timed_out += 1
                logger.warning(
                    "recovery enrichment timed out for %s (>%ss)",
                    row.event_id, per_event_timeout,
                )
                ps.record_error(
                    row.event_id, error=f"enrichment timed out after {per_event_timeout}s",
                    retryable=True,
                    retry_after_utc=now + timedelta(seconds=self.config.poll_recovery_seconds),
                )
            except Exception as exc:  # noqa: BLE001 -- one bad event must not stop the batch
                failed += 1
                logger.warning("recovery enrichment failed for %s: %s", row.event_id, exc)

        summary = {
            "reconciled": reconciled, "enriched": enriched,
            "timed_out": timed_out, "failed": failed,
            "elapsed_seconds": round(time.monotonic() - t0, 2),
        }
        if reconciled or enriched or timed_out or failed:
            logger.info("recovery pass: %s", summary)
        return summary

    async def drain_retries(self, *, now: datetime | None = None, limit: int = 50) -> int:
        assert self.stores is not None and self.enrichment is not None
        now = now or datetime.now(timezone.utc)
        rows = self.stores.processing.due_for_retry(now=now, limit=limit)
        drained = 0
        for row in rows:
            try:
                await self.enrichment.process_event(row.event_id, origin=row.origin, now=now)
                drained += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("retry drain failed for %s: %s", row.event_id, exc)
        if drained:
            logger.info("retry drain: reprocessed %d event(s)", drained)
        return drained

    # ------------------------------------------------------------------
    def _sleep_seconds(self, freshness_status: str) -> float:
        if freshness_status == FreshnessStatus.DOWN.value:
            return self.config.poll_backoff_seconds
        if freshness_status == FreshnessStatus.STALE.value:
            return self.config.poll_recovery_seconds
        return self.config.poll_base_seconds

    def _heartbeat(self, *, mode: str, last_cycle: dict | None = None) -> None:
        payload = {
            "mode": mode,
            "scope": self.scope.watchlist.counts if self.scope else {},
            "effective_symbols": list(self.scope.symbols) if self.scope else [],
            "metrics": self.metrics.snapshot(),
        }
        if last_cycle is not None:
            payload["last_cycle"] = last_cycle
        write_heartbeat(self.config.heartbeat_path(), payload)
        self.metrics.write(self.config.metrics_path())

    # ------------------------------------------------------------------
    async def run_poll_loop(
        self,
        *,
        duration_seconds: float | None = None,
        max_cycles: int | None = None,
        with_backfill: bool = False,
    ) -> dict:
        assert self.poller is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + duration_seconds if duration_seconds else None
        cycles = 0
        cycle_summaries: list[dict] = []
        self._heartbeat(mode="poll:start")

        while not self._stop.is_set():
            now = datetime.now(timezone.utc)
            res = await self.poll_cycle(now=now)
            # Task 133: reconcile_and_enrich REPLACES the old drain_retries()
            # call here -- it is bounded (count and/or time budget) and also
            # covers due_for_retry's 3 stages PLUS every other open stage
            # (including a brand-new STORED row, e.g. from poll_cycle's own
            # bounded enrichment deferring work here, or a row recovered from
            # an event a prior process persisted but never enriched) -- so it
            # is a strict superset, not a narrower replacement. drain_retries
            # itself is kept, unchanged, for run_once()/other callers.
            recovery = await self.reconcile_and_enrich(now=now)
            # merge (not overwrite) into the progress file poll_cycle just
            # wrote, so an observer sees BOTH the fetch-phase snapshot and
            # this cycle's recovery-pass result together -- plus a cheap
            # (already-computed, no extra scan) remaining-backlog count.
            try:
                merged = read_heartbeat(self.config.progress_path()) or {}
                merged["recovery"] = recovery
                if self.stores is not None:
                    merged["backlog_by_stage"] = self.stores.processing.counts_by_stage()
                write_heartbeat(self.config.progress_path(), merged)
            except Exception:  # noqa: BLE001 -- progress reporting must never break the loop
                logger.debug("progress-file recovery merge failed", exc_info=True)
            # deliver_cycle computes its OWN drain-time `now`; never blocks the
            # loop (bounded) and never swallows an error into a healthy state.
            # Because reconcile_and_enrich is bounded (unlike the old
            # unbounded post-fetch enrichment loop), delivery gets a real,
            # regular turn on EVERY iteration, even with a large backlog.
            delivery = await self.deliver_cycle()

            summary = {
                "at_utc": now.isoformat(),
                "symbols_polled": res.symbols_polled,
                "symbols_failed": res.symbols_failed,
                "filings_seen": res.filings_seen,
                "new_events": len(res.new_event_ids),
                "new_form4": res.new_form4_filings,
                "freshness": res.submissions_freshness,
                "recovery": recovery,
                "delivery": delivery,
                "delivery_ok": (delivery or {}).get("ok", True),
                "errors": res.errors[:10],
            }
            cycle_summaries.append(summary)
            cycles += 1

            if with_backfill and self.backfill is not None:
                nxt = self._next_backfill_symbol()
                if nxt is not None:
                    logger.info("backfill (low priority): advancing %s", nxt)
                    await self.backfill.run(symbols=[nxt])

            self._heartbeat(mode="poll", last_cycle=summary)

            if max_cycles is not None and cycles >= max_cycles:
                break
            if deadline is not None and loop.time() >= deadline:
                break

            sleep_for = self._sleep_seconds(res.submissions_freshness)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                pass

        self._heartbeat(mode="poll:stopped")
        return {
            "cycles": cycles,
            "stopped": self._stop.is_set(),
            "cycle_summaries": cycle_summaries,
            "metrics": self.metrics.snapshot(),
        }

    def _next_backfill_symbol(self) -> str | None:
        assert self.stores is not None and self.scope is not None
        cp = self.stores.checkpoints
        forms = list(self.config.filing_forms) + [("edgar_form4_xml", "4")]
        for rs in self.scope.resolved:
            for f in self.config.filing_forms:
                c = cp.get(rs.symbol, "edgar_submissions", f)
                if c is None or not c.completed:
                    return rs.symbol
            c = cp.get(rs.symbol, "edgar_form4_xml", "4")
            if c is None or not c.completed:
                return rs.symbol
        return None

    # ------------------------------------------------------------------
    async def run_backfill(self, *, symbols: list[str] | None = None) -> BackfillReport:
        assert self.backfill is not None
        self._heartbeat(mode="backfill:start")
        report = await self.backfill.run(symbols=symbols)
        self._heartbeat(mode="backfill:done")
        return report

    async def run_once(self, *, symbols: list[str] | None = None, backfill: bool = True) -> dict:
        assert self.poller is not None
        out: dict = {}
        if backfill:
            out["backfill"] = (await self.run_backfill(symbols=symbols)).as_dict()
        res = await self.poll_cycle(symbols=symbols)
        await self.drain_retries()
        out["poll"] = {
            "symbols_polled": res.symbols_polled,
            "filings_seen": res.filings_seen,
            "new_events": len(res.new_event_ids),
            "new_form4": res.new_form4_filings,
            "freshness": res.submissions_freshness,
            "errors": res.errors[:20],
        }
        out["metrics"] = self.metrics.snapshot()
        self._heartbeat(mode="once:done", last_cycle=out["poll"])
        return out

    # ------------------------------------------------------------------
    def status(self) -> dict:
        assert self.stores is not None
        fr = SourceFreshnessTracker(self.stores.events)
        sources = {}
        for st in (SourceType.SEC_EDGAR_SUBMISSIONS, SourceType.SEC_XBRL,
                   SourceType.SEC_FORM345_BULK):
            snap = fr.snapshot(st)
            sources[st.value] = {
                "status": snap.status.value,
                "reason": snap.reason,
                "last_poll_success_utc": (
                    snap.last_poll_success_utc.isoformat()
                    if snap.last_poll_success_utc else None
                ),
                "consecutive_failures": snap.consecutive_failures,
                "age_seconds": snap.age_seconds,
            }
        cp = self.stores.checkpoints.summary()
        ps = self.stores.processing
        return {
            "as_of_utc": datetime.now(timezone.utc).isoformat(),
            "watchlist": self.scope.watchlist.counts if self.scope else {},
            "effective_symbols": list(self.scope.symbols) if self.scope else [],
            "directory_from_cache": self.directory.from_cache if self.directory else None,
            "source_freshness": sources,
            "backfill": cp,
            "processing_stages": ps.counts_by_stage(),
            "processing_substates": ps.counts_by_substate(),
            "processing_total": ps.total(),
            "store_counts": {
                "events": self.stores.events.count_events(),
                "filing_comparisons": self.stores.comparisons.count(),
                "insider_transactions": self.stores.insider.count_transactions(),
                "scored_events": self.stores.significance.count(),
            },
            "delivery_outbox": self.stores.outbox.counts_by_state(),
            "dry_run_delivery": self.config.dry_run_delivery,
            "metrics": self.metrics.snapshot(),
        }
