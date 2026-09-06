"""
talonx_v2.schemas -- V2 lane wire contracts (Phase 7, 9, 14)
===========================================================
Deliberately minimal.  V2 is a different phenomenon from V1 -- it does NOT
carry ATR / confluence / R:R.  It carries insider-cluster provenance.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class V2Direction(str, Enum):
    BULLISH = "BULLISH"        # informational positive opportunity
    BEARISH = "BEARISH"        # informational / anti-long only -- NEVER a short


class V2Action(str, Enum):
    BUY = "BUY"                # open an INSIDER_BUY_CLUSTER_V2 paper long
    SELL = "SELL"              # close an INSIDER_BUY_CLUSTER_V2 paper long only
    HOLD = "HOLD"              # informational, no order


class V2QuantSignal(BaseModel):
    """Quant-stage output for the V2 lane.  Published to talonx:v2:signal."""

    signal_id: str
    strategy_profile: str = "INSIDER_BUY_CLUSTER_V2"
    strategy_version: str = "INSIDER_BUY_CLUSTER_V2@1"
    source: str = "form4_insider_cluster"

    symbol: str
    issuer_cik: str
    direction: V2Direction = V2Direction.BULLISH
    horizon_trading_days: int = 10
    paper_eligible: bool = True

    episode_id: str
    distinct_owner_ciks: tuple[str, ...]
    n_distinct_owners: int
    aggregate_purchase_value: float | None = None
    any_officer: bool = False
    any_director: bool = False
    any_ten_percent: bool = False

    causal_event_ts: datetime          # when the 2nd distinct insider's filing became public
    eligible_entry_session: date       # first NYSE session strictly after causal_event_ts
    reason: str

    liquidity_ok: bool
    liquidity_median_dollar_volume: float | None = None
    liquidity_last_close: float | None = None

    bar_timestamp: datetime | None = None
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()


class V2Decision(BaseModel):
    """Brain-stage output.  Descriptive contextualisation only -- no V1
    gate is applied.  Published to talonx:v2:decision."""

    signal_id: str
    episode_id: str
    symbol: str
    strategy_profile: str = "INSIDER_BUY_CLUSTER_V2"
    strategy_version: str = "INSIDER_BUY_CLUSTER_V2@1"

    direction: V2Direction
    action: V2Action
    official_eligible: bool
    rationale: str
    context_notes: tuple[str, ...] = ()

    eligible_entry_session: date
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()


class V2Alert(BaseModel):
    """Official alert card content (Telegram / dashboard).  Published to
    talonx:v2:alert."""

    episode_id: str
    symbol: str
    action: V2Action
    direction: V2Direction
    strategy_version: str = "INSIDER_BUY_CLUSTER_V2@1"
    status: str = "PAPER_CANDIDATE"
    headline: str
    body: str
    entry_session: date | None = None
    target_exit_session: date | None = None
    paper_only: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()


class V2PaperTrade(BaseModel):
    """Paper ledger execution.  Published to talonx:v2:trade."""

    trade_id: int
    episode_id: str
    symbol: str
    action: V2Action
    strategy_profile: str = "INSIDER_BUY_CLUSTER_V2"
    strategy_version: str = "INSIDER_BUY_CLUSTER_V2@1"

    execution_price: float
    shares: float
    position_cost: float
    entry_session: date
    target_exit_session: date

    entry_price: float | None = None            # SELL only
    realized_pnl_usd: float | None = None        # SELL only
    realized_pnl_pct: float | None = None        # SELL only
    trading_days_held: int | None = None         # SELL only

    portfolio_cash_after: float
    paper_only: bool = True
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()
