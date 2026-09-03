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

    # -- backfill -------------------------------------------------------
    backfill_concurrency: int = 1
    backfill_max_form4_per_symbol: int = 400   # safety cap for a bounded proof
    backfill_max_filings_per_symbol: int = 600
    live_priority: bool = True

    # -- enrichment ---------------------------------------------------
    enable_xbrl: bool = True
    enrichment_max_retries: int = 4

    # -- delivery ---------------------------------------------------------
    # 96B qualification never sends externally unless this is explicitly
    # flipped AND Telegram is configured (Phase 13).
    dry_run_delivery: bool = True

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
            dry_run_delivery=_env_bool("TALONX_INTEL_DRY_RUN_DELIVERY", True),
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
