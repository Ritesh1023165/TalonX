"""
talonx_watchlist.config
----------------------------
Settings for the ticker watchlist -- the shared control-plane store behind
the "which tickers is the pipeline tracking" question. Not a pipeline data
contract (no Redis channel involved), so it isn't owned by any of the 5
numbered modules; both `run_talonx.py` (reader) and `talonx_dispatch/app.py`
(reader+writer) depend on it directly, same as they already share the
repo-root .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_dotenv() -> None:
    """Loads the shared .env file at the repo root, if present -- same
    resolve-by-file-location, override=False pattern every other module's
    config.py uses."""
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
class WatchlistConfig:
    db_path: str = os.environ.get(
        "TALONX_WATCHLIST_DB", str(Path.home() / ".talonx" / "watchlist.db")
    )
    # Seeded once, only if the watchlist is completely empty (fresh install).
    default_symbol: str = os.environ.get("TALONX_WATCHLIST_DEFAULT_SYMBOL", "MSFT")
    default_name: str = os.environ.get(
        "TALONX_WATCHLIST_DEFAULT_NAME", "Microsoft Corporation"
    )
    default_exchange: str = os.environ.get("TALONX_WATCHLIST_DEFAULT_EXCHANGE", "NASDAQ")
    # How often run_talonx.py re-checks the store for add/remove changes.
    poll_interval_seconds: float = _env_float("TALONX_WATCHLIST_POLL_INTERVAL", 10.0)
