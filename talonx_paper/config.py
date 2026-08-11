"""
talonx_paper.config
------------------------
All settings for the Live Paper Trading Engine (Module 6), env-driven.

Deliberately self-contained at the CODE level, same convention as
talonx_quant/talonx_core: no import of their Python objects, only Redis
wire contracts (talonx:alerts:dispatch, talonx:market:stream) plus a
read/write dependency on talonx_watchlist's store for the per-ticker
"is paper trading enabled for this symbol" flag -- that's a shared
control-plane concern, not a pipeline data contract, same reasoning
run_talonx.py and talonx_dispatch/app.py already depend on
talonx_watchlist directly.

Shares the repo-root .env the same way every other module does.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_dotenv() -> None:
    shared_env = Path(__file__).resolve().parent.parent / ".env"
    if shared_env.is_file():
        load_dotenv(shared_env, override=False)


_load_dotenv()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class PaperConfig:
    # --- Redis ---
    redis_url: str = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")
    alerts_channel: str = os.environ.get("TALONX_REDIS_ALERTS_CHANNEL", "talonx:alerts:dispatch")
    market_channel: str = os.environ.get("TALONX_REDIS_MARKET_CHANNEL", "talonx:market:stream")
    # Own output contract -- talonx_dispatch subscribes to this too, to
    # push a short trade-execution notification independent of the
    # original alert push (see its own config.py).
    paper_trades_channel: str = os.environ.get(
        "TALONX_REDIS_PAPER_TRADES_CHANNEL", "talonx:paper:trades"
    )
    connect_timeout_seconds: float = _env_float("TALONX_REDIS_CONNECT_TIMEOUT", 5.0)
    socket_timeout_seconds: float = _env_float("TALONX_REDIS_SOCKET_TIMEOUT", 5.0)
    reconnect_backoff_base_seconds: float = _env_float("TALONX_PAPER_RECONNECT_BASE", 1.0)
    reconnect_backoff_max_seconds: float = _env_float("TALONX_PAPER_RECONNECT_MAX", 30.0)

    # --- Ledger ---
    db_path: str = os.environ.get(
        "TALONX_PAPER_DB", str(Path.home() / ".talonx" / "paper_trading.db")
    )

    # --- Fresh-install defaults only -- once the store has been
    # initialized (first ever run), the dashboard-set values in
    # portfolio_state take precedence over these; changing these env
    # vars later does NOT retroactively change an existing portfolio.
    # Use the dashboard's Reset Portfolio to actually apply a new value.
    default_initial_balance: float = _env_float("TALONX_PAPER_INITIAL_BALANCE", 10000.0)
    default_trade_allocation_usd: float = _env_float("TALONX_PAPER_TRADE_ALLOCATION", 2500.0)
