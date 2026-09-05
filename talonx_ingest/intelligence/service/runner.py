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
from datetime import datetime, timezone

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
from talonx_ingest.intelligence.service.singleton import write_heartbeat
from talonx_ingest.intelligence.service.stores import StoreBundle
from talonx_watchlist.config import WatchlistConfig
from talonx_watchlist.store import TickerWatchlistStore

logger = logging.getLogger("talonx_ingest.intelligence.service.runner")


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
        if self.poller is not None:
            self.poller.scope = self.scope
        if self.backfill is not None:
            self.backfill.scope = self.scope

    # ------------------------------------------------------------------
    async def poll_cycle(
        self, *, now: datetime | None = None, symbols: list[str] | None = None
    ) -> PollCycleResult:
        assert self.poller is not None
        res = await self.poller.poll_once(now=now, symbols=symbols)
        logger.info(
            "poll cycle: polled=%d failed=%d filings=%d new_events=%d form4=%d fresh=%s %.2fs",
            res.symbols_polled, res.symbols_failed, res.filings_seen,
            len(res.new_event_ids), res.new_form4_filings,
            res.submissions_freshness, res.duration_seconds,
        )
        return res

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
            await self.drain_retries(now=now)

            summary = {
                "at_utc": now.isoformat(),
                "symbols_polled": res.symbols_polled,
                "symbols_failed": res.symbols_failed,
                "filings_seen": res.filings_seen,
                "new_events": len(res.new_event_ids),
                "new_form4": res.new_form4_filings,
                "freshness": res.submissions_freshness,
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
