"""
talonx_ingest.shared_gateway.config
-----------------------------------------
Environment-driven configuration for the Shared Alpaca Gateway, following
the same `.env`-at-repo-root / real-env-wins convention every other
module's config.py already uses (see talonx_ingest.config._load_dotenv).

Deliberately reuses the SAME Alpaca credentials (APCA_API_KEY_ID/
APCA_API_SECRET_KEY) and the SAME data endpoint PIV already uses -- this
is the first non-PIV reader of those keys, and it is read-only market
data (bars/latest), never broker/order endpoints. See
results/task88_shared_gateway/architecture_before.md §16.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _load_dotenv() -> None:
    repo_root_env = Path(__file__).resolve().parent.parent.parent / ".env"
    if repo_root_env.is_file():
        load_dotenv(repo_root_env, override=False)


_load_dotenv()


def _truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


DATA_ENDPOINT = "https://data.alpaca.markets"
FEED_MODE_PARAM = {"RESEARCH_SIP": "sip", "IEX_PAPER_PIV": "iex"}


@dataclass(frozen=True)
class GatewayConfig:
    # repr=False: these must never appear in a log line, traceback, or
    # dataclass repr/print -- credentials are secrets, not debug output.
    key_id: str = field(default_factory=lambda: os.getenv("APCA_API_KEY_ID", ""), repr=False)
    secret_key: str = field(default_factory=lambda: os.getenv("APCA_API_SECRET_KEY", ""), repr=False)
    data_endpoint: str = DATA_ENDPOINT
    # Reuses PIV's own feed-mode env var -- the gateway polls the SAME feed
    # PIV already validated live (Task 87C), never a different one of its
    # own invention.
    feed_mode: str = field(default_factory=lambda: os.getenv("TALONX_PIV_FEED_MODE", "IEX_PAPER_PIV").strip().upper())

    # Task 88 gets its OWN Redis database (2) -- neither Original's (0) nor
    # PIV's (1) -- same isolation posture talonx_piv/isolation.py already
    # enforces between those two.
    redis_url: str = field(default_factory=lambda: os.getenv("TALONX_GATEWAY_REDIS_URL", "redis://localhost:6379/2"))

    poll_interval_seconds: float = field(default_factory=lambda: float(os.getenv("TALONX_GATEWAY_POLL_INTERVAL_SECONDS", "60.0")))
    liveness_interval_seconds: float = field(default_factory=lambda: float(os.getenv("TALONX_GATEWAY_LIVENESS_INTERVAL_SECONDS", "20.0")))

    connect_timeout_seconds: float = 5.0
    socket_timeout_seconds: float = 5.0
    reconnect_backoff_base_seconds: float = 1.0
    reconnect_backoff_max_seconds: float = 30.0
    http_timeout_seconds: float = 15.0

    # PIV's own hard-coded universe (talonx_piv.config.DEFAULT_UNIVERSE) --
    # imported lazily by universe.py to avoid a hard import-time coupling
    # from this config module into talonx_piv.
    original_watchlist_db_path: str = field(default_factory=lambda: os.getenv(
        "TALONX_WATCHLIST_DB_PATH", str(Path.home() / ".talonx" / "watchlist.db")
    ))

    # SHADOW_INGESTION_ONLY guard -- always True in this MVP; kept as an
    # explicit, inspectable flag (rather than an absence of code) so any
    # future change to this default is a single, auditable line, never an
    # accidental capability creep.
    shadow_only: bool = True
