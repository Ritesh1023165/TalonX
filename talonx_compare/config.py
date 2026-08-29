"""Collector configuration -- an isolated namespace and storage layout.

Every path and channel here is either (a) an Original/PIV binding the
collector only ever *observes*, or (b) collector-owned storage under
``TALONX_COMPARE_STATE_DIR`` / ``TALONX_COMPARE_EVIDENCE_ROOT``. The
collector never writes anything under the Original or PIV state dirs and
never opens their lock files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

from talonx_piv.config import PivConfig

# The collector's own namespace. Used ONLY to name its own storage keys /
# files -- the collector never publishes, so this is not a Pub/Sub prefix.
COMPARE_NAMESPACE = "talonx:compare"

_DEFAULT_STATE_DIR = "results/task83_dashboard_comparison_qualification/collector_runtime"
_DEFAULT_EVIDENCE_ROOT = "results/task83_dashboard_comparison_qualification/daily_evidence"

# The Original pipeline's six-plus wire channels, mirrored from
# dashboard.py::CHANNELS (the single source of truth for the
# channel->schema mapping). Imported lazily in ``original_channels`` to
# avoid importing rich/redis at module import time.
_ORIGINAL_STAGE_MODULES = ("ingest", "quant", "brain", "core", "dispatch")


@dataclass(frozen=True)
class CompareConfig:
    # --- collector-owned storage (isolated) ---
    state_dir: Path = field(
        default_factory=lambda: Path(os.getenv("TALONX_COMPARE_STATE_DIR", _DEFAULT_STATE_DIR))
    )
    evidence_root: Path = field(
        default_factory=lambda: Path(os.getenv("TALONX_COMPARE_EVIDENCE_ROOT", _DEFAULT_EVIDENCE_ROOT))
    )
    namespace: str = COMPARE_NAMESPACE

    # --- Original bindings the collector only OBSERVES ---
    original_redis_url: str = field(
        default_factory=lambda: os.getenv("TALONX_REDIS_URL", "redis://localhost:6379/0")
    )

    # --- PIV bindings the collector only OBSERVES ---
    piv_redis_url: str = field(
        default_factory=lambda: os.getenv("TALONX_PIV_REDIS_URL", "redis://localhost:6379/1")
    )
    piv_state_dir: Path = field(default_factory=lambda: PivConfig().state_dir)

    # Freshness threshold (seconds): a source file / stream whose newest
    # record is older than this, while a run is otherwise corroborated, is
    # reported STALE -- never silently treated as "no activity".
    stale_seconds: int = 120

    @property
    def cursor_path(self) -> Path:
        return self.state_dir / "collector_cursors.json"

    @property
    def dedup_dir(self) -> Path:
        return self.state_dir / "dedup_index"

    @property
    def lock_path(self) -> Path:
        """Collector-owned single-instance lock. Deliberately under the
        collector state dir -- NEVER an Original/PIV lock path."""
        return self.state_dir / "collector.lock"

    def original_channels(self) -> dict[str, str]:
        """{key: channel} for every Original wire channel, from
        dashboard.CHANNELS (imported here, not at module load)."""
        from dashboard import CHANNELS

        return {w.key: w.channel for w in CHANNELS}

    def piv_channels(self) -> dict[str, str]:
        cfg = PivConfig()
        return {
            "market": cfg.market_stream_channel,
            "signals": cfg.signals_channel,
            "rejected": cfg.rejected_candidates_channel,
            "news": cfg.news_events_channel,
            "paper_trades": cfg.paper_trades_channel,
        }

    def original_stage_modules(self) -> tuple[str, ...]:
        return _ORIGINAL_STAGE_MODULES

    def observed_paths(self) -> list[Path]:
        """Every PIV file the collector reads (read-only)."""
        sd = self.piv_state_dir
        return [
            sd / "session_identity.json",
            sd / "piv_events.jsonl",
            sd / "session_readiness_state.json",
            sd / "decision_ledger.json",
            sd / "shadow_ledger.json",
            sd / "notification_outbox.json",
            sd / "lifecycle_state.json",
            sd / "freshness_report.json",
            sd / "latest_reconciliation.json",
            sd / "latest_session_report.json",
            sd / "eod_state.json",
            sd / "quant_funnel_report.json",
        ]
