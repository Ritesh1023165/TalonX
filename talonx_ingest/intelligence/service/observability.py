"""
talonx_ingest.intelligence.service.observability
================================================
Intelligence-only counters (``OBSERVABILITY`` Phase 30). Deliberately
separate from the quant / signal metrics — nothing here has a P&L, a
position, or a fill. In-memory counters plus an optional JSON snapshot to
``<state_dir>/service.metrics.json``.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ServiceMetrics:
    started_at_utc: str = field(default_factory=_now)

    # -- source / polling ---------------------------------------------
    edgar_polls: int = 0
    edgar_poll_success: int = 0
    edgar_poll_failure: int = 0
    edgar_429: int = 0
    edgar_retries: int = 0
    edgar_latency_ms_total: float = 0.0
    edgar_latency_samples: int = 0
    last_successful_poll_utc: str | None = None

    # -- backfill ---------------------------------------------------------
    backfill_units_total: int = 0
    backfill_units_complete: int = 0
    backfill_filings_fetched: int = 0
    backfill_filings_skipped: int = 0

    # -- events ----------------------------------------------------------
    events_discovered: int = 0
    events_stored: int = 0
    events_duplicate_suppressed: int = 0
    events_failed: int = 0

    # -- comparison (96C) --------------------------------------------
    comparison_attempted: int = 0
    comparison_passed: int = 0
    comparison_partial: int = 0
    comparison_failed: int = 0

    # -- insider (96D) --------------------------------------------------
    insider_filings: int = 0
    insider_transactions: int = 0
    insider_open_market_ps: int = 0
    insider_parse_failures: int = 0

    # -- significance (96E) ------------------------------------------
    significance_evaluated: int = 0
    significance_recomputed: int = 0
    band_counts: Counter = field(default_factory=Counter)

    # -- delivery (96F) — mirrors 96F counters, not a second engine ---
    delivery_enqueued: int = 0
    delivery_updates: int = 0
    delivery_suppressed: int = 0
    delivery_sent: int = 0
    delivery_dry_run: int = 0
    delivery_failed: int = 0
    claim_safety_rejections: int = 0

    # -- state machine -------------------------------------------------
    stage_terminal_failures: int = 0
    stage_retryable_failures: int = 0

    # ------------------------------------------------------------------
    def record_poll(self, *, success: bool, latency_ms: float | None = None,
                    got_429: bool = False, retries: int = 0) -> None:
        self.edgar_polls += 1
        if success:
            self.edgar_poll_success += 1
            self.last_successful_poll_utc = _now()
        else:
            self.edgar_poll_failure += 1
        if got_429:
            self.edgar_429 += 1
        self.edgar_retries += retries
        if latency_ms is not None:
            self.edgar_latency_ms_total += latency_ms
            self.edgar_latency_samples += 1

    def record_band(self, band: str | None) -> None:
        if band:
            self.band_counts[band] += 1

    @property
    def edgar_latency_ms_avg(self) -> float | None:
        if not self.edgar_latency_samples:
            return None
        return round(self.edgar_latency_ms_total / self.edgar_latency_samples, 1)

    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        return {
            "started_at_utc": self.started_at_utc,
            "as_of_utc": _now(),
            "source": {
                "edgar_polls": self.edgar_polls,
                "poll_success": self.edgar_poll_success,
                "poll_failure": self.edgar_poll_failure,
                "http_429": self.edgar_429,
                "retries": self.edgar_retries,
                "latency_ms_avg": self.edgar_latency_ms_avg,
                "last_successful_poll_utc": self.last_successful_poll_utc,
            },
            "backfill": {
                "units_total": self.backfill_units_total,
                "units_complete": self.backfill_units_complete,
                "units_pending": max(0, self.backfill_units_total - self.backfill_units_complete),
                "filings_fetched": self.backfill_filings_fetched,
                "filings_skipped": self.backfill_filings_skipped,
            },
            "events": {
                "discovered": self.events_discovered,
                "stored": self.events_stored,
                "duplicate_suppressed": self.events_duplicate_suppressed,
                "failed": self.events_failed,
            },
            "comparison": {
                "attempted": self.comparison_attempted,
                "passed": self.comparison_passed,
                "partial": self.comparison_partial,
                "failed": self.comparison_failed,
            },
            "insider": {
                "filings": self.insider_filings,
                "transactions": self.insider_transactions,
                "open_market_ps": self.insider_open_market_ps,
                "parse_failures": self.insider_parse_failures,
            },
            "significance": {
                "evaluated": self.significance_evaluated,
                "recomputed": self.significance_recomputed,
                "band_counts": dict(self.band_counts),
            },
            "delivery": {
                "enqueued": self.delivery_enqueued,
                "updates": self.delivery_updates,
                "suppressed": self.delivery_suppressed,
                "sent": self.delivery_sent,
                "dry_run": self.delivery_dry_run,
                "failed": self.delivery_failed,
                "claim_safety_rejections": self.claim_safety_rejections,
            },
            "state_machine": {
                "terminal_failures": self.stage_terminal_failures,
                "retryable_failures": self.stage_retryable_failures,
            },
        }

    def write(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")
        except OSError:
            pass
