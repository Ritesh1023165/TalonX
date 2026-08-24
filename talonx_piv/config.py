"""Environment-only PIV configuration with immutable paper routing."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

PAPER_ENDPOINT = "https://paper-api.alpaca.markets"
DATA_ENDPOINT = "https://data.alpaca.markets"
DEFAULT_UNIVERSE = (
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX",
    "ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON",
    "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU", "NFLX", "PANW", "PEP",
    "QCOM", "REGN", "SBUX", "TXN", "VRTX",
)


def _truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


FEED_MODES = ("RESEARCH_SIP", "IEX_PAPER_PIV")
FEED_MODE_PARAM = {"RESEARCH_SIP": "sip", "IEX_PAPER_PIV": "iex"}
# IEX_PAPER_PIV is operational readiness evidence only; it can never stand in
# for SIP-based canonical alpha validation. See results/task65_piv/task65_summary.md.
CANONICAL_ALPHA_FEED_MODES = ("RESEARCH_SIP",)


def _feed_mode() -> str:
    return os.getenv("TALONX_PIV_FEED_MODE", "RESEARCH_SIP").strip().upper()


@dataclass(frozen=True)
class PivConfig:
    key_id: str = field(default_factory=lambda: os.getenv("APCA_API_KEY_ID", ""))
    secret_key: str = field(default_factory=lambda: os.getenv("APCA_API_SECRET_KEY", ""))
    paper_trading: bool = field(default_factory=lambda: _truthy("TALONX_PIV_PAPER_TRADING"))
    real_capital: bool = field(default_factory=lambda: _truthy("TALONX_PIV_REAL_CAPITAL"))
    broker_endpoint: str = field(default_factory=lambda: os.getenv("TALONX_PIV_BROKER_ENDPOINT", PAPER_ENDPOINT))
    data_endpoint: str = DATA_ENDPOINT
    approved_sha: str = field(default_factory=lambda: os.getenv("TALONX_PIV_APPROVED_SHA", ""))
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    state_dir: Path = field(default_factory=lambda: Path(os.getenv(
        "TALONX_PIV_STATE_DIR", "results/task64_paper_piv_readiness/runtime"
    )))
    stale_seconds: int = 120
    entry_cutoff_et: str = "15:45"
    eod_flatten_et: str = "15:50"
    universe: tuple[str, ...] = DEFAULT_UNIVERSE
    feed_mode: str = field(default_factory=_feed_mode)
    decision_path_enabled: bool = field(default_factory=lambda: _truthy("TALONX_PIV_DECISION_PATH", "true"))
    redis_url: str = field(default_factory=lambda: os.getenv("TALONX_REDIS_URL", "redis://localhost:6379"))
