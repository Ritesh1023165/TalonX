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


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class DispatchConfig:
    # --- Redis ---
    redis_url: str = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")
    # Same env var talonx_core reads -- both sides of this boundary
    # (alert producer, alert consumer) must agree on the channel name.
    alerts_channel: str = os.environ.get(
        "TALONX_REDIS_ALERTS_CHANNEL", "talonx:alerts:dispatch"
    )
    # Same env var talonx_paper reads -- published there after every
    # executed (non-ignored) paper trade; this module subscribes to it
    # too, to push a SEPARATE short Telegram notification (decoupled from
    # the original alert push -- see consumer.py).
    paper_trades_channel: str = os.environ.get(
        "TALONX_REDIS_PAPER_TRADES_CHANNEL", "talonx:paper:trades"
    )
    # Phase 2 LONG_TERM path -- same env var names talonx_core/talonx_paper
    # read on their sides of each boundary.
    alerts_channel_long_term: str = os.environ.get(
        "TALONX_REDIS_ALERTS_LONG_TERM_CHANNEL", "talonx:alerts:longterm"
    )
    paper_trades_channel_long_term: str = os.environ.get(
        "TALONX_REDIS_PAPER_TRADES_LONG_TERM_CHANNEL", "talonx:paper:trades:longterm"
    )
    # Event-Driven Earnings Radar's T-48h heads-up push (Requirement 5):
    # subscribed PURELY to keep a latest-signal/report-per-ticker cache for
    # that push's price/quality/moat/fair-value fields -- talonx_dispatch's
    # own long_term_alerts audit table isn't a safe source for this (it only
    # gets a row once a ticker clears the FULL decision matrix, which some
    # tracked tickers may never do). Same env var names talonx_core/
    # talonx_brain already read on their sides of each boundary.
    fundamental_signals_channel: str = os.environ.get(
        "TALONX_REDIS_FUNDAMENTAL_SIGNALS_CHANNEL", "talonx:signals:fundamental"
    )
    reports_channel_long_term: str = os.environ.get(
        "TALONX_REDIS_REPORTS_LONG_TERM_CHANNEL", "talonx:reports:longterm"
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

    # --- Event-Driven Earnings Radar, Requirement 5: T-48h heads-up push ---
    # How often to re-check talonx_watchlist's upcoming_earnings table for
    # tickers now within the heads-up window -- doesn't need to be
    # frequent (the window itself is 48 hours wide), matching the daily
    # cadence the requirement doc itself specifies.
    earnings_heads_up_check_interval_hours: float = _env_float(
        "TALONX_DISPATCH_EARNINGS_HEADS_UP_CHECK_HOURS", 24.0
    )
    earnings_heads_up_window_hours: float = _env_float(
        "TALONX_DISPATCH_EARNINGS_HEADS_UP_WINDOW_HOURS", 48.0
    )

    # --- Streamlit dashboard (app.py) ---
    feed_limit: int = _env_int("TALONX_DISPATCH_FEED_LIMIT", 200)
    # Was 5000 -- with st.tabs() rendering every tab's queries on every
    # tick (fixed separately by switching to a single-active-section
    # radio), 5s was an aggressive baseline load even for one section.
    # 10s keeps the feed responsive without re-querying twice as often
    # as needed.
    autorefresh_ms: int = _env_int("TALONX_DISPATCH_AUTOREFRESH_MS", 10000)

    # --- Smart Dispatch Filtering (mobile push volume reduction) ---
    # Every alert is ALWAYS recorded to the audit trail and shown on the
    # Streamlit dashboard regardless of these settings -- they only gate
    # whether a Telegram push actually goes out, same "durable write
    # first, filtered broadcast second" split telegram_min_severity
    # above already established. A live session (dispatch_audit.db) found
    # 86 pushes in 4.3 hours: 44.8% were non-actionable CONTRADICTED
    # alerts, and 40.2% were the same ticker re-alerting every ~20 min on
    # minor price noise.

    # Requirement 1: only actions representing a genuine trade decision
    # are push-eligible -- CONFIRMED_BULLISH/CONFIRMED_BEARISH intraday,
    # HIGH_CONVICTION_BUY/TAKE_PROFIT_REBALANCE/UNDER_PERFORM_REBALANCE
    # long-term (see consumer.py's _PUSH_ELIGIBLE_ACTIONS_*). Everything
    # else -- CONTRADICTED, DEGRADED_QUANT_ALERT, long-term HOLD_QUALITY
    # -- is a "no strong trade signal" state and gets muted the same way.
    mute_contradictions: bool = _env_bool("TALONX_DISPATCH_MUTE_CONTRADICTIONS", True)

    # Requirement 2: a SEPARATE, longer per-ticker lockout on the PUSH
    # itself (on top of, not instead of, whatever cooldown talonx_core
    # already applied before publishing the alert at all) -- stops the
    # same ticker's minor back-and-forth from re-buzzing a phone every
    # ~20 minutes. Tracked in-process (a plain dict keyed by ticker), not
    # Redis -- unlike talonx_quant's loss-lockout, no OTHER process needs
    # to see or set this state, so the extra Redis round-trip would be
    # pure overhead. Resets on restart, matching talonx_core's own
    # in-memory per-ticker cooldown (TickerCorrelator.last_alert_at).
    push_cooldown_minutes: float = _env_float("TALONX_DISPATCH_PUSH_COOLDOWN_MINUTES", 45.0)

    # Requirement 3: an early bypass of the cooldown above when price has
    # genuinely moved since the last push -- a ticker sitting flat for 45
    # minutes shouldn't push again, but one making a real move should.
    retrigger_price_delta_pct: float = _env_float("TALONX_DISPATCH_RETRIGGER_PRICE_DELTA_PCT", 1.0)

    # Requirement 4: suppress pushes for low-confidence research findings.
    # Intraday only -- ActionableAlert.research_confidence is a talonx_brain
    # output that has no long-term equivalent; LongTermActionableAlert's
    # own quality_score>=7 threshold is already enforced upstream in
    # talonx_core's decision matrix before a long-term alert is even
    # published, so a redundant proxy gate isn't added here.
    min_confidence: float = _env_float("TALONX_DISPATCH_MIN_CONFIDENCE", 0.75)
