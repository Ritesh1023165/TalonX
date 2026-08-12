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
    # Phase 2 LONG_TERM path -- same env var names talonx_quant/talonx_brain
    # read on their sides of each boundary.
    fundamental_signals_channel: str = os.environ.get(
        "TALONX_REDIS_FUNDAMENTAL_SIGNALS_CHANNEL", "talonx:signals:fundamental"
    )
    reports_channel_long_term: str = os.environ.get(
        "TALONX_REDIS_REPORTS_LONG_TERM_CHANNEL", "talonx:reports:longterm"
    )
    alerts_channel_long_term: str = os.environ.get(
        "TALONX_REDIS_ALERTS_LONG_TERM_CHANNEL", "talonx:alerts:longterm"
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

    # A second, independent guardrail on top of the time cooldown above
    # (both must pass): once an alert has fired for a ticker, a REPEAT of
    # the exact same action (e.g. CONFIRMED_BULLISH -> CONFIRMED_BULLISH
    # again) is suppressed unless price has moved at least this fraction
    # since the price at that last alert. A genuine state TRANSITION
    # (e.g. CONFIRMED_BULLISH -> CONTRADICTED) always bypasses this check
    # -- it's only for "the same story repeating itself."
    price_delta_retrigger_pct: float = _env_float("TALONX_CORE_PRICE_DELTA_RETRIGGER_PCT", 0.01)

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

    # --- Phase 2 LONG_TERM decision matrix (decision.py's evaluate_long_term) ---
    # Spec's example thresholds, verbatim: Quality Score >= 7/10, Margin
    # of Safety >= 20% (price <= 0.8x fair value), overvaluation trim at
    # a 20% premium (price > 1.2x fair value).
    quality_score_min: int = _env_int("TALONX_CORE_LT_QUALITY_SCORE_MIN", 7)
    margin_of_safety_pct: float = _env_float("TALONX_CORE_LT_MARGIN_OF_SAFETY_PCT", 0.20)
    valuation_premium_pct: float = _env_float("TALONX_CORE_LT_VALUATION_PREMIUM_PCT", 0.20)
    # No beta/market-risk-premium data source exists anywhere in this
    # project to compute a real CAPM-based WACC -- used as a documented
    # assumed constant instead (roughly the long-run US equity market
    # average, a reasonable generic default).
    assumed_wacc: float = _env_float("TALONX_CORE_LT_ASSUMED_WACC", 0.09)
    max_debt_to_ebitda: float = _env_float("TALONX_CORE_LT_MAX_DEBT_TO_EBITDA", 4.0)
    # Roughly one fiscal year -- annual (10-K-only) facts mean a fresh
    # signal/report pair genuinely can't arrive more often than that; a
    # generous window avoids treating last year's still-relevant pair as
    # too stale to correlate against a slightly-lagged report.
    correlation_window_long_term_seconds: float = _env_float(
        "TALONX_CORE_LT_CORRELATION_WINDOW", 400 * 86400.0
    )
    # Long-term alerts intentionally repeat far less often than intraday
    # ones -- ~1 month, so a HOLD_QUALITY doesn't re-fire on every minor
    # daily-close price wobble once the state-transition gate below also
    # judges it unchanged.
    ticker_cooldown_long_term_seconds: float = _env_float(
        "TALONX_CORE_LT_TICKER_COOLDOWN", 30 * 86400.0
    )
    # Same "repeat of the same action needs a real price move" gate as
    # the intraday price_delta_retrigger_pct, just a wider default (5%
    # vs. 1%) since long-term valuation bands are inherently coarser.
    price_delta_retrigger_pct_long_term: float = _env_float(
        "TALONX_CORE_LT_PRICE_DELTA_RETRIGGER_PCT", 0.05
    )
