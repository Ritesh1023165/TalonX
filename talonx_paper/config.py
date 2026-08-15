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


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


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

    # --- Risk management (engine.check_stop_take) ---
    # Percentage-based, off entry price. Static for now -- an ATR-based
    # dynamic version is a deliberately deferred follow-up (needs its own
    # rolling OHLC buffer + indicator calc); these defaults give a 1:2
    # risk-to-reward ratio, exceeding a 1:1.5 minimum.
    stop_loss_pct: float = _env_float("TALONX_PAPER_STOP_LOSS_PCT", 0.005)  # 0.50%
    take_profit_pct: float = _env_float("TALONX_PAPER_TAKE_PROFIT_PCT", 0.01)  # 1.00%

    # --- Friction simulation (engine.apply_spread) ---
    # Applied to every fill (BUY pays more, SELL receives less) so paper
    # PnL isn't unrealistically clean -- a flat commission is deliberately
    # NOT modeled, since most modern retail brokers are commission-free;
    # the bid-ask spread is the friction that actually always applies.
    simulated_spread_bps: float = _env_float("TALONX_PAPER_SIMULATED_SPREAD_BPS", 5.0)  # 0.05%

    # --- Entry conviction gate ---
    # A CONFIRMED_BULLISH alert below this severity is recorded as
    # ignored (BELOW_MIN_SEVERITY) rather than opening a position. Never
    # gates exits. "warning" is a starting point, not a backtested value
    # -- tune it using generate_eod_report.py's BELOW_MIN_SEVERITY counts
    # once there's a few real sessions of data (README §5o).
    min_entry_severity: str = os.environ.get("TALONX_PAPER_MIN_ENTRY_SEVERITY", "warning")

    # --- Phase 2 LONG_TERM path (DCA-aware ledger) ---
    alerts_channel_long_term: str = os.environ.get(
        "TALONX_REDIS_ALERTS_LONG_TERM_CHANNEL", "talonx:alerts:longterm"
    )
    paper_trades_channel_long_term: str = os.environ.get(
        "TALONX_REDIS_PAPER_TRADES_LONG_TERM_CHANNEL", "talonx:paper:trades:longterm"
    )
    # A SEPARATE starting balance/pool from the intraday portfolio above --
    # fresh-install default only, same "dashboard-set value wins after
    # first run" caveat as default_initial_balance.
    default_long_term_initial_balance: float = _env_float("TALONX_PAPER_LT_INITIAL_BALANCE", 20000.0)
    # The opening HIGH_CONVICTION_BUY's position size -- separate from
    # dca_contribution_usd below, which only ever adds to an ALREADY-open
    # position on a recurring schedule.
    long_term_initial_position_usd: float = _env_float("TALONX_PAPER_LT_INITIAL_POSITION", 2000.0)
    dca_contribution_usd: float = _env_float("TALONX_PAPER_DCA_CONTRIBUTION", 500.0)
    # Fixed-interval approximation of "monthly" -- not true calendar-month
    # scheduling (documented simplification, see the Phase 2 plan).
    dca_interval_days: float = _env_float("TALONX_PAPER_DCA_INTERVAL_DAYS", 30.0)
    # Fraction of the position trimmed on a TAKE_PROFIT_REBALANCE alert.
    rebalance_trim_pct: float = _env_float("TALONX_PAPER_REBALANCE_TRIM_PCT", 0.33)

    # --- Automated End-of-Day flattening (2026-08-14 session review: an
    # ADC position opened intraday and rode unclosed through market close,
    # with no automated liquidation routine to catch it) -- INTRADAY
    # ledger only (this engine's own `positions` table); the LONG_TERM
    # DCA-aware ledger above is explicitly out of scope, since a
    # multi-day/DCA position riding overnight is the intended behavior
    # there, not a bug. Time is expressed in America/New_York local time
    # (engine.seconds_until_next_eod_flatten converts via ZoneInfo), not a
    # fixed UTC offset, so the 15:50 ET target doesn't drift an hour off
    # across the spring/fall DST transition.
    eod_flatten_enabled: bool = _env_bool("TALONX_PAPER_EOD_FLATTEN_ENABLED", True)
    eod_flatten_hour_et: int = _env_int("TALONX_PAPER_EOD_FLATTEN_HOUR_ET", 15)
    eod_flatten_minute_et: int = _env_int("TALONX_PAPER_EOD_FLATTEN_MINUTE_ET", 50)
