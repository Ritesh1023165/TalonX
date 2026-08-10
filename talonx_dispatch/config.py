"""
talonx_dispatch.config
---------------------------
All settings for the Notification Dispatcher & Streamlit Interface,
env-driven.

Deliberately self-contained at the CODE level -- same reasoning as
talonx_quant/talonx_core (see their config.py files): no import of
talonx_core/talonx_brain/talonx_ingest Python objects, so this module
runs as an independent process/service consuming only the Redis wire
contract (talonx:alerts:dispatch). Its dependencies match the module
spec: redis.asyncio, pydantic, python-telegram-bot, streamlit,
streamlit-autorefresh, pandas. It DOES share the repo-root .env for
TALONX_REDIS_URL, same config-sharing-not-code-dependency pattern used
everywhere else.
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
    you run `python -m talonx_dispatch.run` or
    `streamlit run talonx_dispatch/app.py` from.
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


@dataclass(frozen=True)
class DispatchConfig:
    # --- Redis ---
    redis_url: str = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")
    # Same env var talonx_core reads -- both sides of this boundary
    # (alert producer, alert consumer) must agree on the channel name.
    alerts_channel: str = os.environ.get(
        "TALONX_REDIS_ALERTS_CHANNEL", "talonx:alerts:dispatch"
    )
    connect_timeout_seconds: float = _env_float("TALONX_REDIS_CONNECT_TIMEOUT", 5.0)
    socket_timeout_seconds: float = _env_float("TALONX_REDIS_SOCKET_TIMEOUT", 5.0)
    reconnect_backoff_base_seconds: float = _env_float("TALONX_DISPATCH_RECONNECT_BASE", 1.0)
    reconnect_backoff_max_seconds: float = _env_float("TALONX_DISPATCH_RECONNECT_MAX", 30.0)

    # --- Telegram ---
    # Optional, same "additive, degrade gracefully" philosophy as
    # RedditConfig: if unset, the consumer still runs and still writes
    # every alert to the audit trail (store.py) -- it just skips the
    # mobile push. Get a token from @BotFather, and a chat_id by
    # messaging your bot once and hitting
    # https://api.telegram.org/bot<TOKEN>/getUpdates (see README §4).
    telegram_bot_token: str | None = os.environ.get("TELEGRAM_BOT_TOKEN") or None
    telegram_chat_id: str | None = os.environ.get("TELEGRAM_CHAT_ID") or None

    # Mobile push notifications get old fast -- only alerts at or above
    # this severity actually buzz your phone. The audit trail (and the
    # Streamlit feed) always show EVERYTHING regardless of this filter;
    # it only gates the Telegram push itself.
    telegram_min_severity: str = os.environ.get("TALONX_DISPATCH_MIN_SEVERITY", "warning")

    telegram_max_retries: int = _env_int("TALONX_DISPATCH_TELEGRAM_MAX_RETRIES", 3)
    telegram_backoff_base_seconds: float = _env_float("TALONX_DISPATCH_TELEGRAM_BACKOFF_BASE", 1.5)
    telegram_backoff_max_seconds: float = _env_float("TALONX_DISPATCH_TELEGRAM_BACKOFF_MAX", 30.0)

    # How long Bot.get_updates() long-polls per call before returning an
    # empty batch (telegram_listener.py) -- Telegram's own recommended
    # server-side long-poll pattern, not a client-side sleep loop.
    telegram_poll_timeout_seconds: float = _env_float("TALONX_DISPATCH_TELEGRAM_POLL_TIMEOUT", 30.0)

    # --- Audit trail (store.py) ---
    audit_db_path: str = os.environ.get(
        "TALONX_DISPATCH_AUDIT_DB", str(Path.home() / ".talonx" / "dispatch_audit.db")
    )
    # How long an alert stays in the audit trail (and therefore
    # look-up-able by ID via Telegram) before the retention sweep deletes
    # it -- keeps a long-running install from growing this file forever.
    retention_days: float = _env_float("TALONX_DISPATCH_RETENTION_DAYS", 5.0)
    retention_sweep_interval_hours: float = _env_float("TALONX_DISPATCH_RETENTION_SWEEP_HOURS", 24.0)

    # --- Streamlit dashboard (app.py) ---
    feed_limit: int = _env_int("TALONX_DISPATCH_FEED_LIMIT", 200)
    autorefresh_ms: int = _env_int("TALONX_DISPATCH_AUTOREFRESH_MS", 5000)
