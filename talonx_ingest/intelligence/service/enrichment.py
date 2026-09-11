"""
talonx_ingest.intelligence.service.enrichment
=============================================
Drive the deterministic downstream layers for one already-STORED
``TextEvent`` (Phases 9–13, 15–17).

    STORED event
      -> 96C filing comparison   (10-Q / 10-K only)
      -> 96D insider activity    (Form 4 parent events only)
      -> 96E information significance   (every event)
      -> 96F durable delivery outbox row   (enqueue only; no external send)

Failure isolation (Phase 16): each stage is independently wrapped. A
comparison / XBRL / ownership / significance / delivery failure never
deletes or rewrites the base event — it moves the processing row to
PARTIAL or FAILED_* with a quality flag, and only that stage is retried
(Phase 17). Significance still runs when the comparison is not ready
(deferred enrichment) and is recomputed by 96E's own fingerprint policy
when the comparison later lands.

No trading import. No forward returns. No new significance rule.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from talonx_ingest.intelligence.comparison.engine import run_comparison_for_event
from talonx_ingest.intelligence.comparison.retrieval import FilingArchiveCache
from talonx_ingest.intelligence.comparison.whatchanged import build_what_changed
from talonx_ingest.intelligence.delivery.claim_safety import PredictiveLanguageError
from talonx_ingest.intelligence.delivery.pipeline import enqueue_card
from talonx_ingest.intelligence.domain import EventType
from talonx_ingest.intelligence.pipeline import build_alert_card
from talonx_ingest.intelligence.service.config import ServiceConfig
from talonx_ingest.intelligence.service.observability import ServiceMetrics
from talonx_ingest.intelligence.service.retry import backoff_seconds, classify_error
from talonx_ingest.intelligence.service.state_machine import ProcessingStage
from talonx_ingest.intelligence.service.state_store import ProcessingStateStore
from talonx_ingest.intelligence.service.stores import StoreBundle
from talonx_ingest.intelligence.significance.alert_integration import apply_significance
from talonx_ingest.intelligence.significance.pipeline import evaluate_event

logger = logging.getLogger("talonx_ingest.intelligence.service.enrichment")

_PERIODIC = (EventType.QUARTERLY_FILING, EventType.ANNUAL_FILING)

# comparison quality flags that mean "retry the fetch later".
_COMPARISON_RETRY_FLAGS = {"current_document_unavailable", "prior_document_unavailable"}
# a flag that means the comparison itself is degraded (a whole document was
# missing). The many *expected* minor caveats a real filing carries
# (xbrl_concept_missing, section_not_found, ambiguous_section, parser_fallback,
# fiscal_period_mismatch, ...) are recorded on the FilingComparison's own
# data_quality_flags for the evidence trace and do NOT make the enrichment
# PARTIAL — the comparison is valid and persisted.
_COMPARISON_PARTIAL_FLAGS = {"low_quality_comparison"}


@dataclass
class EnrichmentOutcome:
    event_id: str
    symbol: str
    stage: ProcessingStage
    comparison_state: str
    insider_state: str
    significance_state: str
    delivery_state: str
    significance_band: str | None = None
    recompute_reason: str | None = None
    errors: list[str] = field(default_factory=list)


class EnrichmentEngine:
    def __init__(
        self,
        stores: StoreBundle,
        client,
        *,
        config: ServiceConfig,
        metrics: ServiceMetrics | None = None,
        cache: FilingArchiveCache | None = None,
        source_status: str | None = None,
        freshness=None,
    ):
        self.stores = stores
        self.client = client
        self.config = config
        self.metrics = metrics or ServiceMetrics()
        self.freshness = freshness
        self.cache = cache or (
            FilingArchiveCache(client, cache_dir=config.state_dir / "filing_comparison_cache")
            if client is not None
            else None
        )
        self.source_status = source_status

    # ------------------------------------------------------------------
    async def process_event(
        self,
        event_id: str,
        *,
        origin: str = "poll",
        allow_delivery: bool = True,
        now: datetime | None = None,
    ) -> EnrichmentOutcome:
        now = now or datetime.now(timezone.utc)
        ps = self.stores.processing
        ev = self.stores.events.get_event(event_id)
        if ev is None:
            # base event isn't in the 96A store — nothing to enrich.
            return EnrichmentOutcome(
                event_id, "", ProcessingStage.FAILED_TERMINAL,
                "NA", "NA", "NA", "NA", errors=["event not in EventStore"],
            )

        row = ps.ensure(
            event_id,
            symbol=ev.symbol,
            event_type=ev.event_type.value,
            form_type=ev.form_type,
            accession=ev.accession,
            origin=origin,
            stage=ProcessingStage.STORED,
            comparison_state=(
                ProcessingStateStore.PENDING if ev.event_type in _PERIODIC
                else ProcessingStateStore.NOT_APPLICABLE
            ),
            insider_state=(
                ProcessingStateStore.PENDING
                if ev.event_type is EventType.INSIDER_TRANSACTION
                else ProcessingStateStore.NOT_APPLICABLE
            ),
        )

        errors: list[str] = []
        comparison_ok = True
        what_changed: dict | None = None

        # -- 96C: filing comparison (deferred-safe) -------------------
        if ev.event_type in _PERIODIC and row.comparison_state != ProcessingStateStore.DONE:
            ps.set_stage(event_id, ProcessingStage.ENRICHMENT_PENDING, detail="96C comparison")
            what_changed, comparison_ok, cmp_err = await self._run_comparison(event_id, now)
            if cmp_err:
                errors.append(cmp_err)
        elif ev.event_type in _PERIODIC:
            # comparison already done on a prior pass — reload its facts so a
            # re-delivery keeps the "what changed" section.
            fc = self.stores.comparisons.get_comparison_for_current_event(event_id)
            if fc is not None:
                what_changed = build_what_changed(fc)

        # -- 96D: insider activity (parent event already stored by 96D) --
        if ev.event_type is EventType.INSIDER_TRANSACTION:
            ok, ins_err = self._confirm_insider(ev)
            ps.set_substate(
                event_id,
                insider_state=ProcessingStateStore.DONE if ok else ProcessingStateStore.PARTIAL,
                detail="96D insider activity" + ("" if ok else f" partial: {ins_err}"),
            )
            if ins_err:
                errors.append(ins_err)

        if comparison_ok:
            ps.set_stage(event_id, ProcessingStage.ENRICHED, detail="enrichment steps done/NA")

        # -- 96E: significance (always; recompute-safe) --------------
        sig_band, recompute_reason, sig_err = self._run_significance(ev, now)
        if sig_err:
            errors.append(sig_err)
            ps.set_substate(event_id, significance_state=ProcessingStateStore.FAILED,
                            detail=f"96E failed: {sig_err}")
        else:
            ps.set_substate(event_id, significance_state=ProcessingStateStore.DONE,
                            detail=f"96E band={sig_band} ({recompute_reason})")
            ps.set_stage(event_id, ProcessingStage.SIGNIFICANCE_EVALUATED)

        # -- 96F: durable delivery outbox (enqueue only) -------------
        delivery_state = ProcessingStateStore.PENDING
        if allow_delivery and sig_err is None:
            delivery_state, dlv_err = self._enqueue_delivery(ev, what_changed, row, now)
            if dlv_err:
                errors.append(dlv_err)
            ps.set_substate(event_id, delivery_state=delivery_state,
                            detail=f"96F {delivery_state}" + (f": {dlv_err}" if dlv_err else ""))

        # -- roll up final stage -----------------------------------
        final_row = ps.get(event_id)
        final_stage = self._rollup_stage(final_row, comparison_ok, sig_err, delivery_state,
                                         allow_delivery)
        ps.set_stage(event_id, final_stage, detail=f"rollup errors={len(errors)}")
        if errors and final_stage in (ProcessingStage.FAILED_RETRYABLE, ProcessingStage.PARTIAL):
            decision = classify_error(errors[-1])
            retry_after = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
            retry_after = retry_after + _td(backoff_seconds(final_row.attempts + 1))
            ps.record_error(
                event_id, error="; ".join(errors)[:480],
                retryable=decision.retryable, retry_after_utc=retry_after,
            )
            if decision.retryable:
                self.metrics.stage_retryable_failures += 1
            else:
                self.metrics.stage_terminal_failures += 1

        fr = ps.get(event_id)
        return EnrichmentOutcome(
            event_id=event_id,
            symbol=ev.symbol,
            stage=fr.stage,
            comparison_state=fr.comparison_state,
            insider_state=fr.insider_state,
            significance_state=fr.significance_state,
            delivery_state=fr.delivery_state,
            significance_band=sig_band,
            recompute_reason=recompute_reason,
            errors=errors,
        )

    # ------------------------------------------------------------------
    async def _run_comparison(self, event_id: str, now: datetime):
        ps = self.stores.processing
        self.metrics.comparison_attempted += 1
        try:
            fc = await run_comparison_for_event(
                self.stores.events, self.client, event_id,
                cache=self.cache, fetch_xbrl=self.config.enable_xbrl, now=now,
            )
        except Exception as exc:  # noqa: BLE001
            self.metrics.comparison_failed += 1
            ps.set_substate(event_id, comparison_state=ProcessingStateStore.FAILED,
                            detail=f"96C exception: {exc}")
            return None, False, f"comparison: {exc}"

        self.stores.comparisons.upsert_comparison(fc)
        flags = set(fc.data_quality_flags or ())
        what_changed = build_what_changed(fc)

        if self.freshness is not None and self.config.enable_xbrl:
            from talonx_ingest.intelligence.domain import SourceType as _ST

            self.freshness.record_attempt(
                _ST.SEC_XBRL, success="xbrl_unavailable" not in flags
            )

        if flags & _COMPARISON_RETRY_FLAGS:
            self.metrics.comparison_failed += 1
            ps.set_substate(event_id, comparison_state=ProcessingStateStore.FAILED,
                            detail=f"96C doc unavailable: {sorted(flags)}")
            return what_changed, False, f"comparison document unavailable: {sorted(flags & _COMPARISON_RETRY_FLAGS)}"

        if flags & _COMPARISON_PARTIAL_FLAGS:
            self.metrics.comparison_partial += 1
            ps.set_substate(event_id, comparison_state=ProcessingStateStore.PARTIAL,
                            detail=f"96C partial: {sorted(flags & _COMPARISON_PARTIAL_FLAGS)}")
            # partial is a legitimate persisted state — do NOT block the rest
            return what_changed, True, None

        self.metrics.comparison_passed += 1
        ps.set_substate(event_id, comparison_state=ProcessingStateStore.DONE,
                        detail=f"96C ok prior={fc.prior_accession or 'NONE'}")
        return what_changed, True, None

    # ------------------------------------------------------------------
    def _confirm_insider(self, ev):
        """The 96D pipeline stores the parent event + transactions at
        ingest time; here we only confirm an ``InsiderActivity`` can be
        built (it feeds 96E + 96F)."""
        try:
            from talonx_ingest.intelligence.insider.pipeline import build_insider_activity

            this_filing = self.stores.insider.query_transactions(accession=ev.accession)
            self.metrics.insider_open_market_ps += sum(
                1 for t in this_filing if t.is_open_market_discretionary
            )
            act = build_insider_activity(self.stores.insider, ev.symbol)
            if not act.transactions and not act.latest_filings:
                return False, "insider activity empty for symbol"
            return True, None
        except Exception as exc:  # noqa: BLE001
            self.metrics.insider_parse_failures += 1
            return False, f"insider: {exc}"

    # ------------------------------------------------------------------
    def _run_significance(self, ev, now: datetime):
        try:
            res = evaluate_event(
                ev,
                event_store=self.stores.events,
                comparison_store=self.stores.comparisons,
                insider_store=self.stores.insider,
                on_watchlist=True,
                source_status=self.source_status,
                now=now,
                store=self.stores.significance,
            )
        except Exception as exc:  # noqa: BLE001
            return None, None, f"significance: {exc}"
        self.metrics.significance_evaluated += 1
        if res.persisted:
            self.metrics.significance_recomputed += 1
        band = res.significance.band.value if res.significance else None
        self.metrics.record_band(band)
        return band, res.recompute_reason, None

    # ------------------------------------------------------------------
    def _enqueue_delivery(self, ev, what_changed, prior_row, now: datetime):
        sig = self.stores.significance.get_for_event(ev.event_id)
        card = build_alert_card(ev)
        if sig is not None:
            try:
                card = apply_significance(card, sig)
            except PredictiveLanguageError as exc:
                self.metrics.claim_safety_rejections += 1
                return ProcessingStateStore.FAILED, f"claim-safety: {exc}"

        insider_activity = None
        if ev.event_type is EventType.INSIDER_TRANSACTION:
            try:
                from talonx_ingest.intelligence.insider.pipeline import build_insider_activity

                insider_activity = build_insider_activity(self.stores.insider, ev.symbol)
            except Exception:  # noqa: BLE001
                insider_activity = None

        allow_update = prior_row.delivery_state == ProcessingStateStore.DONE
        try:
            result = enqueue_card(
                card,
                outbox=self.stores.outbox,
                what_changed=what_changed,
                insider_activity=insider_activity,
                allow_update=allow_update,
                now=now,
            )
        except PredictiveLanguageError as exc:
            self.metrics.claim_safety_rejections += 1
            return ProcessingStateStore.FAILED, f"claim-safety (render): {exc}"
        except Exception as exc:  # noqa: BLE001
            self.metrics.delivery_failed += 1
            return ProcessingStateStore.FAILED, f"delivery enqueue: {exc}"

        if result.disposition == "NEW":
            self.metrics.delivery_enqueued += 1
        elif result.disposition == "UPDATE":
            self.metrics.delivery_updates += 1
        else:
            self.metrics.delivery_suppressed += 1
        return ProcessingStateStore.DONE, None

    # ------------------------------------------------------------------
    @staticmethod
    def _rollup_stage(row, comparison_ok, sig_err, delivery_state, allow_delivery):
        if sig_err is not None:
            return ProcessingStage.FAILED_RETRYABLE
        if not comparison_ok:
            return ProcessingStage.PARTIAL
        if row.comparison_state == ProcessingStateStore.PARTIAL:
            base = ProcessingStage.PARTIAL
        else:
            base = ProcessingStage.COMPLETE
        if allow_delivery and delivery_state == ProcessingStateStore.FAILED:
            return ProcessingStage.PARTIAL
        if allow_delivery and delivery_state == ProcessingStateStore.DONE and base == ProcessingStage.COMPLETE:
            return ProcessingStage.COMPLETE
        if not allow_delivery and base == ProcessingStage.COMPLETE:
            return ProcessingStage.SIGNIFICANCE_EVALUATED
        return base


def _td(seconds: float):
    from datetime import timedelta

    return timedelta(seconds=seconds)
