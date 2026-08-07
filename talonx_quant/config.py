"""
talonx_quant.config
----------------------
All settings for the Technical & Quantitative Scanner, env-driven.

Deliberately self-contained at the CODE level (no import of talonx_ingest
Python objects) so this module can run as an independent process/service
consuming only the Redis wire contract -- matching the module boundary in
the project spec (its only real dependencies are redis.asyncio, pandas,
and pandas_ta).

It DOES share a .env FILE with talonx_ingest, though -- both modules need
the same TALONX_REDIS_URL to actually talk to each other via Redis, and
maintaining two separate .env files with the same values would just be a
drift risk. Sharing a config file is not a code dependency.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_dotenv() -> None:
    """
    Loads talonx_ingest/.env (the shared config file) if present.
    `override=False`: real environment variables always win over .env,
    same precedence rule as talonx_ingest.config.

    Resolved relative to this file's location (../talonx_ingest/.env from
    here), not the current working directory, so it's found reliably
    regardless of where you run `python -m talonx_quant.run` from.
    """
    shared_env = Path(__file__).resolve().parent.parent / "talonx_ingest" / ".env"
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
class QuantConfig:
    # --- Redis ---
    redis_url: str = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")
    market_stream_channel: str = os.environ.get(
        "TALONX_REDIS_MARKET_CHANNEL", "talonx:market:stream"
    )
    signals_channel: str = os.environ.get(
        "TALONX_REDIS_SIGNALS_CHANNEL", "talonx:signals:quant"
    )
    connect_timeout_seconds: float = _env_float("TALONX_REDIS_CONNECT_TIMEOUT", 5.0)
    socket_timeout_seconds: float = _env_float("TALONX_REDIS_SOCKET_TIMEOUT", 5.0)
    reconnect_backoff_base_seconds: float = _env_float("TALONX_QUANT_RECONNECT_BASE", 1.0)
    reconnect_backoff_max_seconds: float = _env_float("TALONX_QUANT_RECONNECT_MAX", 30.0)

    # --- Rolling buffer ---
    # How many bars to keep per symbol. Indicators need enough history to be
    # meaningful (MACD's slow EMA alone wants 26+ periods) but an unbounded
    # buffer would grow forever for a long-running process -- this caps
    # memory per symbol regardless of how long the process has been running.
    max_bars_per_symbol: int = _env_int("TALONX_QUANT_MAX_BARS", 200)

    # --- Indicator parameters ---
    rsi_period: int = _env_int("TALONX_QUANT_RSI_PERIOD", 14)
    macd_fast: int = _env_int("TALONX_QUANT_MACD_FAST", 12)
    macd_slow: int = _env_int("TALONX_QUANT_MACD_SLOW", 26)
    macd_signal: int = _env_int("TALONX_QUANT_MACD_SIGNAL", 9)
    ma_fast_period: int = _env_int("TALONX_QUANT_MA_FAST", 10)
    ma_slow_period: int = _env_int("TALONX_QUANT_MA_SLOW", 50)
    volume_avg_period: int = _env_int("TALONX_QUANT_VOLUME_AVG_PERIOD", 20)

    # Minimum bars required before ANY indicator is computed. Should be at
    # least macd_slow + macd_signal for a meaningful MACD reading, and at
    # least ma_slow_period + 1 for crossover detection (need a "previous"
    # value too). Left independently configurable rather than derived, so
    # it's explicit and can be tuned without doing the math each time.
    min_bars_required: int = _env_int("TALONX_QUANT_MIN_BARS", 60)

    # --- Signal trigger thresholds ---
    rsi_oversold: float = _env_float("TALONX_QUANT_RSI_OVERSOLD", 30.0)
    rsi_overbought: float = _env_float("TALONX_QUANT_RSI_OVERBOUGHT", 70.0)
    volume_surge_ratio_threshold: float = _env_float(
        "TALONX_QUANT_VOLUME_SURGE_RATIO", 2.0
    )