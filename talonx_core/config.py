"""
talonx_core.config
-----------------------
All settings for the Core Event Bus & Decision Engine, env-driven.

Deliberately self-contained at the CODE level -- same reasoning as
talonx_quant (see its config.py): no import of talonx_ingest or
talonx_brain Python objects, so this module can run as an independent
process/service consuming only the Redis wire contracts of BOTH upstream
modules (talonx:signals:quant, talonx:reports:brain). Its only real
dependencies are redis.asyncio, pydantic, and asyncio, matching the module
spec. It DOES share the repo-root .env for TALONX_REDIS_URL, same
config-sharing-not-code-dependency pattern used everywhere else.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_dotenv() -> None:
    """
    Loads the shared .env file at the repo root, if present. `override=False`:
    real environment variables always win over .env, same precedence rule
    as talonx_ingest.config.

    Resolved relative to this file's location (../.env from here), not the
    current working directory, so it's found reliably regardless of where
    you run `python -m talonx_core.run` from.
    """
    shared_env = Path(__file__).resolve().parent.parent / ".env"
    if shared_env.is_file():
        load_dotenv(shared_env, override=False)


_load_dotenv()


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
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class CoreConfig:
    # --- Redis ---
    redis_url: str = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")
    # Same env vars talonx_quant / talonx_brain read -- all four modules
    # must agree on channel names to actually talk to each other.
    signals_channel: str = os.environ.get(
        "TALONX_REDIS_SIGNALS_CHANNEL", "talonx:signals:quant"
    )
    reports_channel: str = os.environ.get(
        "TALONX_REDIS_REPORTS_CHANNEL", "talonx:reports:brain"
    )
    alerts_channel: str = os.environ.get(
        "TALONX_REDIS_ALERTS_CHANNEL", "talonx:alerts:dispatch"
    )
    connect_timeout_seconds: float = _env_float("TALONX_REDIS_CONNECT_TIMEOUT", 5.0)
    socket_timeout_seconds: float = _env_float("TALONX_REDIS_SOCKET_TIMEOUT", 5.0)
    reconnect_backoff_base_seconds: float = _env_float("TALONX_CORE_RECONNECT_BASE", 1.0)
    reconnect_backoff_max_seconds: float = _env_float("TALONX_CORE_RECONNECT_MAX", 30.0)

    # --- Decision matrix ---
    # A CONFIRMED/CONTRADICTED verdict only reaches talonx:alerts:dispatch
    # if the research confidence backing it meets this bar -- below it,
    # the matrix treats the pair as UNCONFIRMED (no alert), same as a
    # neutral/insufficient_context verdict. This is the module's core
    # risk guardrail: don't dispatch on a low-confidence LLM call.
    min_confidence: float = _env_float("TALONX_CORE_MIN_CONFIDENCE", 0.5)

    # --- Correlation ---
    # How long a QuantSignal or ResearchReport stays "fresh" in a
    # ticker's state before it's too stale to correlate against a new
    # arrival on the other channel. Generous default (30 min) because
    # talonx_brain's Gemini calls are rate-limited (as low as 5/min on
    # the free tier -- see talonx_brain's README section) and can lag
    # their triggering signal by minutes under a backlog, not seconds.
    correlation_window_seconds: float = _env_float("TALONX_CORE_CORRELATION_WINDOW", 1800.0)

    # --- Guardrails ---
    # After dispatching an alert for a ticker, suppress further alerts
    # for that same ticker for this long, even if new correlated pairs
    # keep arriving -- prevents re-alerting on what is functionally the
    # same setup every time a new bar nudges an indicator.
    ticker_cooldown_seconds: float = _env_float("TALONX_CORE_TICKER_COOLDOWN", 300.0)

    # --- Persistence ---
    # TickerCorrelator state was in-memory only until this was added: a
    # restart mid-correlation (a QuantSignal received but its
    # ResearchReport hasn't landed yet -- routine given talonx_brain's
    # multi-minute Gemini lag) silently lost that half of the pair
    # forever. Persisting to a local SQLite file -- same "durable but
    # simple, stdlib, no new dependency" choice talonx_ingest.storage.ledger
    # makes -- closes that gap: store.py's TickerStateStore rehydrates the
    # correlator from disk at startup. Disable to always start clean.
    enable_persistence: bool = _env_bool("TALONX_CORE_ENABLE_PERSISTENCE", True)
    state_db_path: str = os.environ.get(
        "TALONX_CORE_STATE_DB", str(Path.home() / ".talonx" / "core_state.db")
    )
