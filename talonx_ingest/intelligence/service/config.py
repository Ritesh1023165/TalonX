"""
talonx_ingest.intelligence.service.config
=========================================
``ServiceConfig`` — the one immutable knob-set for the continuous
intelligence ingestion service. Every field has a safe default; env vars
only *override*. Nothing here changes a quant threshold, a strategy
parameter, or an execution setting.

Defaults follow ``INGESTION_SCOPE_SPEC.md`` and ``EDGAR_POLLING_SPEC.md``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from talonx_ingest.config import settings

# The MVP filing set (MVP_SCOPE.md capability 1/2/3) + the insider form (4).
DEFAULT_FILING_FORMS: tuple[str, ...] = ("8-K", "10-Q", "10-K")
DEFAULT_INSIDER_FORMS: tuple[str, ...] = ("4",)
OPTIONAL_INSIDER_FORMS: tuple[str, ...] = ("3", "5")

# Known watchlist symbols that do NOT file 8-K/10-Q/10-K with the SEC.
# Surfaced as `unresolved` with this reason — never silently mapped.
KNOWN_NON_FILERS: dict[str, str] = {
    "SKHY": "Korean issuer (SK Hynix) - no SEC domestic filings",
    "SPCX": "SpaceX - private company, no SEC reporting",
    "BLSH": "Bullish - no domestic 8-K/10-Q/10-K filing history",
    "BABA": "foreign private issuer - files 20-F/6-K, not 8-K/10-Q/10-K",
    "ASML": "foreign private issuer - files 20-F/6-K, not 8-K/10-Q/10-K",
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_csv(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    return tuple(
        s.strip().upper() for s in raw.replace(";", ",").split(",") if s.strip()
    )


@dataclass(frozen=True)
class ServiceConfig:
    # -- scope -------------------------------------------------------------
    history_days: int = 900
    filing_forms: tuple[str, ...] = DEFAULT_FILING_FORMS
    insider_forms: tuple[str, ...] = DEFAULT_INSIDER_FORMS
    include_optional_insider_forms: bool = False
    explicit_exclusions: tuple[str, ...] = ()
    include_paused: bool = False

    # -- polling cadence (seconds) --------------------------------------
    poll_base_seconds: float = 180.0
    poll_backoff_seconds: float = 900.0
    poll_recovery_seconds: float = 300.0
    poll_max_symbols_per_cycle: int = 0        # 0 == every effective symbol
    poll_max_form4_per_cycle: int = 40         # bound ownership fetches per cycle
    progress_write_min_interval_seconds: float = 10.0  # throttle for the mid-cycle progress file

    # -- backfill -------------------------------------------------------
    backfill_concurrency: int = 1
    backfill_max_form4_per_symbol: int = 400   # safety cap for a bounded proof
    backfill_max_filings_per_symbol: int = 600
    live_priority: bool = True

    # -- enrichment ---------------------------------------------------
    enable_xbrl: bool = True
    enrichment_max_retries: int = 4
    # Task 133: bounds on the poll_once() post-fetch enrichment pass, so a
    # scope expansion that surfaces tens of thousands of new events cannot
    # block deliver_cycle()/heartbeat/shutdown for the whole first cycle.
    # UNLIKE poll_max_symbols_per_cycle's pre-existing "0 == unbounded"
    # convention, these two are BRAND NEW fields with no prior behaviour
    # to preserve, so they default to a real, always-on bound rather than
    # an opt-in one -- whole-cycle delivery starvation is a bug to fix by
    # default, not a footgun to leave loaded unless an operator remembers
    # to set an env var. 25 events / 60s mirrors the existing
    # deliver_cards_per_cycle=20 scale; any leftover work is durably
    # deferred to the SEPARATE, also-bounded reconcile_and_enrich pass
    # (runner.py) on the next cycle, never lost. 0 still means unbounded,
    # for a one-shot `once`/`backfill` CLI invocation that explicitly
    # wants to run a cycle to completion.
    enrich_max_events_per_cycle: int = 25
    enrich_time_budget_seconds: float = 60.0
    # Bounded per-event wall-clock cap around process_event() itself (each
    # underlying HTTP call already has EdgarClient's own request_timeout_
    # seconds; this is a belt-and-suspenders cap on the WHOLE per-event
    # unit of work -- comparison + XBRL + significance + delivery-enqueue
    # -- so one event's aggregate cost cannot indefinitely stall a batch).
    # 0 == no additional cap beyond the per-request one.
    enrich_per_event_timeout_seconds: float = 90.0
    # Task 133: bounded batch size for the backward-compatible recovery
    # sweep (persisted events with no processing row yet -- see
    # ProcessingStateStore.find_undiscovered_events). Always-on with a
    # modest default since it is a cheap, local, indexed anti-join, not a
    # new behaviour that needs an opt-in default.
    reconcile_max_events_per_cycle: int = 200

    # -- delivery ---------------------------------------------------------
    # 96B qualification never sends externally unless this is explicitly
    # flipped AND Telegram is configured (Phase 13).
    dry_run_delivery: bool = True
    # Task 117: the intelligence-card delivery drain wired into the poll loop.
    # ``deliver_intelligence_cards`` is the EXPLICIT enablement -- default off:
    # the drain still runs each cycle but in "disabled" mode (eligible rows stay
    # PENDING with a reason, nothing is sent, nothing is mutated). Set it True
    # AND ``dry_run_delivery=False`` AND have Telegram configured to actually
    # deliver. Per-cycle cap + a hard timeout keep it off the poll path.
    deliver_intelligence_cards: bool = False
    # Task 140: routine filing-inventory DIGEST delivery is a SEPARATE,
    # explicit opt-in from ``deliver_intelligence_cards`` -- default off.
    # IMMEDIATE (a qualified, substantive alert -- see notification_
    # policy.classify_disposition) is governed by ``deliver_intelligence_
    # cards`` alone, unaffected by this flag. When this is False, DIGEST-
    # route rows are drained in the EXISTING "disabled" mode (reuses
    # process_digest's own mode=MODE_DISABLED branch -- rows stay PENDING,
    # logged HELD/"delivery disabled", nothing sent, nothing lost); the
    # underlying event/enrichment/significance data stays fully persisted
    # and dashboard-queryable exactly as it always has been. Set True to
    # resume the periodic filing-activity digest as an explicit choice.
    deliver_digest_enabled: bool = False
    deliver_cards_per_cycle: int = 20
    deliver_cards_enforce_age_cutoff: bool = True
    deliver_cards_timeout_seconds: float = 20.0
    # Task 133 P0 fix: outbox.expire_stale() (called by BOTH process_pending
    # and process_digest) scans EVERY PENDING row, and -- when an
    # event_time_lookup is given, as deliver_cycle always does -- runs one
    # SYNCHRONOUS database read per row. At a large PENDING volume that
    # blocking loop can run for minutes with no `await` inside it, so
    # asyncio.wait_for's timeout above CANNOT preempt it (confirmed live:
    # the whole Intelligence process became unresponsive, holding its own
    # write lock). Bounding the scan (oldest-enqueued-first) is the fix --
    # None/unbounded is kept as expire_stale's own DEFAULT for any other
    # caller/test, but deliver_cycle always passes this bound.
    expire_scan_max_rows_per_cycle: int = 300
    # DIGEST route is AGGREGATED into one message per interval (default 6h),
    # not sent per-row. Restart-safe via a persisted time-bucket.
    deliver_digest_interval_seconds: float = 6 * 3600.0

    # -- paths ----------------------------------------------------------
    ledger_path: str | None = None
    state_dir: Path = field(
        default_factory=lambda: Path.home() / ".talonx" / "intelligence"
    )
    company_tickers_max_age_days: int = 7

    # ------------------------------------------------------------------
    def effective_insider_forms(self) -> tuple[str, ...]:
        if self.include_optional_insider_forms:
            return tuple(dict.fromkeys((*self.insider_forms, *OPTIONAL_INSIDER_FORMS)))
        return self.insider_forms

    def history_start(self, now: datetime | date | None = None) -> date:
        if now is None:
            now = datetime.now(timezone.utc)
        d = now.date() if isinstance(now, datetime) else now
        return d - timedelta(days=self.history_days)

    def ledger(self) -> str:
        return self.ledger_path or str(settings.ledger.path)

    def company_tickers_cache_path(self) -> Path:
        return self.state_dir / "company_tickers.json"

    def lock_path(self) -> Path:
        return self.state_dir / "service.lock"

    def heartbeat_path(self) -> Path:
        return self.state_dir / "service.heartbeat.json"

    def progress_path(self) -> Path:
        return self.state_dir / "service.progress.json"

    def metrics_path(self) -> Path:
        return self.state_dir / "service.metrics.json"

    def with_overrides(self, **kw) -> "ServiceConfig":
        return replace(self, **kw)

    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls) -> "ServiceConfig":
        return cls(
            history_days=_env_int("TALONX_INTEL_HISTORY_DAYS", 900),
            include_optional_insider_forms=_env_bool(
                "TALONX_INTEL_OPTIONAL_INSIDER_FORMS", False
            ),
            explicit_exclusions=_env_csv("TALONX_INTEL_EXCLUDE_SYMBOLS"),
            include_paused=_env_bool("TALONX_INTEL_INCLUDE_PAUSED", False),
            poll_base_seconds=_env_float("TALONX_INTEL_POLL_SECONDS", 180.0),
            poll_backoff_seconds=_env_float("TALONX_INTEL_POLL_BACKOFF_SECONDS", 900.0),
            poll_recovery_seconds=_env_float("TALONX_INTEL_POLL_RECOVERY_SECONDS", 300.0),
            poll_max_symbols_per_cycle=_env_int("TALONX_INTEL_POLL_MAX_SYMBOLS", 0),
            poll_max_form4_per_cycle=_env_int("TALONX_INTEL_POLL_MAX_FORM4", 40),
            backfill_concurrency=_env_int("TALONX_INTEL_BACKFILL_CONCURRENCY", 1),
            backfill_max_form4_per_symbol=_env_int(
                "TALONX_INTEL_BACKFILL_MAX_FORM4", 400
            ),
            backfill_max_filings_per_symbol=_env_int(
                "TALONX_INTEL_BACKFILL_MAX_FILINGS", 600
            ),
            live_priority=_env_bool("TALONX_INTEL_LIVE_PRIORITY", True),
            enable_xbrl=_env_bool("TALONX_INTEL_ENABLE_XBRL", True),
            enrich_max_events_per_cycle=_env_int("TALONX_INTEL_ENRICH_MAX_EVENTS", 25),
            enrich_time_budget_seconds=_env_float("TALONX_INTEL_ENRICH_TIME_BUDGET_SECONDS", 60.0),
            enrich_per_event_timeout_seconds=_env_float(
                "TALONX_INTEL_ENRICH_PER_EVENT_TIMEOUT_SECONDS", 90.0
            ),
            reconcile_max_events_per_cycle=_env_int(
                "TALONX_INTEL_RECONCILE_MAX_EVENTS", 200
            ),
            dry_run_delivery=_env_bool("TALONX_INTEL_DRY_RUN_DELIVERY", True),
            deliver_intelligence_cards=_env_bool("TALONX_INTEL_DELIVER_CARDS", False),
            deliver_digest_enabled=_env_bool("TALONX_INTEL_DELIVER_DIGEST_ENABLED", False),
            deliver_cards_per_cycle=_env_int("TALONX_INTEL_DELIVER_PER_CYCLE", 20),
            deliver_cards_enforce_age_cutoff=_env_bool(
                "TALONX_INTEL_DELIVER_AGE_CUTOFF", True
            ),
            deliver_cards_timeout_seconds=_env_float(
                "TALONX_INTEL_DELIVER_TIMEOUT_SECONDS", 20.0
            ),
            deliver_digest_interval_seconds=_env_float(
                "TALONX_INTEL_DELIVER_DIGEST_INTERVAL_SECONDS", 6 * 3600.0
            ),
            expire_scan_max_rows_per_cycle=_env_int(
                "TALONX_INTEL_EXPIRE_SCAN_MAX_ROWS", 300
            ),
            ledger_path=os.environ.get("TALONX_LEDGER_PATH") or None,
            state_dir=Path(
                os.environ.get(
                    "TALONX_INTEL_STATE_DIR",
                    str(Path.home() / ".talonx" / "intelligence"),
                )
            ),
            company_tickers_max_age_days=_env_int(
                "TALONX_INTEL_TICKERS_MAX_AGE_DAYS", 7
            ),
        )
