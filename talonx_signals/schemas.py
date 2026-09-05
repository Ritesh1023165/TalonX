"""Task 99A -- isolated domain types for the informational directional-alert
layer and the experimental lane. Pydantic frozen models; no dependency on
talonx_core / talonx_paper schemas (mirror-not-import convention, same as
every other module boundary in this repo).

Nothing here carries a profit/win probability or calibrated confidence. The
only numeric strength signal is `setup_score` (== the LEGACY
confluence_score, 0-3).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib

from pydantic import BaseModel, Field

PROFILE_CONTROL = "FROZEN_CONTROL"
PROFILE_EXPERIMENTAL = "EXPERIMENTAL_RELAXED_V1"


class AlertDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class MarketSession(str, Enum):
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    CLOSED = "closed"


class TradeGateStatus(str, Enum):
    """Whether the SAME underlying setup would clear the trade-execution gate
    of the relevant profile. Informational only -- a directional alert is
    emitted regardless of this value (S3.4)."""

    NOT_EVALUATED = "NOT_EVALUATED"          # informational-only path, gate not run
    WOULD_PASS = "WOULD_PASS"
    WOULD_REJECT = "WOULD_REJECT"


class WatchKind(str, Enum):
    RADAR = "RADAR"                          # upcoming earnings / scheduled catalyst
    GAP_UP = "GAP_UP"
    GAP_DOWN = "GAP_DOWN"
    ABNORMAL_VOLUME = "ABNORMAL_VOLUME"
    BULLISH_WATCH = "BULLISH_WATCH"
    BEARISH_WATCH = "BEARISH_WATCH"
    EVENT_CONTEXT = "EVENT_CONTEXT"          # overnight SEC / 96A material event


class SetupEvidence(BaseModel):
    """The technical inputs behind a directional alert -- carried verbatim from
    the QuantSignal that talonx_quant.strategy.evaluate_signals() produced.
    Any field may be None (warm-up)."""

    rsi: float | None = None
    macd: float | None = None
    macd_signal_line: float | None = None
    macd_cross: str | None = None           # "bullish" | "bearish" | None
    sma_fast: float | None = None
    sma_slow: float | None = None
    volume_surge_ratio: float | None = None
    atr: float | None = None
    atr_pct: float | None = None            # atr / price * 100
    trend_aligned: bool | None = None
    htf_sma_200: float | None = None
    price_vs_htf_sma_200_pct: float | None = None
    pivot_resistance: float | None = None
    pivot_support: float | None = None
    nearby_catalyst: str | None = None      # short label from 96A intelligence, if any


class DirectionalAlert(BaseModel):
    """Informational BULLISH / BEARISH setup. NOT an order and NOT a trade
    recommendation. Emitted independently of any trade-execution gate."""

    alert_id: str                           # deterministic, see make_alert_id
    symbol: str
    direction: AlertDirection
    profile: str = PROFILE_CONTROL          # which strategy profile produced it
    horizon: str = "INTRADAY_SHORT"
    setup_type: str                         # QuantSignal.signal_type value
    setup_score: int | None = None          # == LEGACY confluence_score (0-3). NOT a probability.
    setup_score_label: str = "setup_score"
    session: MarketSession
    price: float
    trade_gate_status: TradeGateStatus = TradeGateStatus.NOT_EVALUATED
    trade_gate_reject_reason: str | None = None
    risk_reward_ratio: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    geometry_path: str | None = None
    message: str = ""
    evidence: SetupEvidence = Field(default_factory=SetupEvidence)
    bar_timestamp: datetime
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Episode key the dedup logic grouped this alert under -- audit aid.
    episode_key: str = ""

    def to_redis_payload(self) -> str:
        return self.model_dump_json()


class PremarketWatch(BaseModel):
    """Pre-market observational item. Never an order, never alpha evidence
    (TALONX_PIV_RUNTIME_PRODUCT_TARGET.md sec 7)."""

    watch_id: str
    symbol: str
    kind: WatchKind
    session: MarketSession = MarketSession.PRE_MARKET
    reference_price: float | None = None
    prev_close: float | None = None
    gap_pct: float | None = None
    detail: str = ""
    reason_codes: tuple[str, ...] = ()
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()


class PremarketBundle(BaseModel):
    """Assembled pre-market surface for the dashboard + Telegram digest."""

    as_of: datetime
    watchlist_configured: int = 0
    watchlist_active: int = 0
    watchlist_covered: int = 0              # had a usable pre-market quote
    radar: list[PremarketWatch] = Field(default_factory=list)
    gap_up: list[PremarketWatch] = Field(default_factory=list)
    gap_down: list[PremarketWatch] = Field(default_factory=list)
    abnormal_volume: list[PremarketWatch] = Field(default_factory=list)
    bullish_watch: list[PremarketWatch] = Field(default_factory=list)
    bearish_watch: list[PremarketWatch] = Field(default_factory=list)
    event_context: list[PremarketWatch] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Deterministic identity
# ---------------------------------------------------------------------------

def make_alert_id(
    *, symbol: str, direction: str, setup_type: str, session: str, episode_ts: datetime,
) -> str:
    """Content-addressed. Two alerts for the same (symbol, direction, setup,
    session, trigger-episode minute) collapse to the same id -> the store
    de-duplicates them and Telegram never double-sends. `D` prefix
    distinguishes directional-alert ids from every other id space."""
    key = "|".join((
        symbol.upper(), str(direction), str(setup_type), str(session),
        episode_ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M"),
    ))
    return "D" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def make_watch_id(*, symbol: str, kind: str, day: datetime, bias: str | None = None) -> str:
    key = "|".join((
        symbol.upper(), str(kind), day.astimezone(timezone.utc).strftime("%Y-%m-%d"), str(bias or ""),
    ))
    return "W" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _hid(prefix: str, *parts: str) -> str:
    return prefix + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def make_trade_id(*, symbol: str, profile: str, side: str, opened_at: datetime, source_alert_id: str = "") -> str:
    """`X` prefix. A BUY and its later SELL share nothing -- each gets its own
    id from its own timestamp -- so a reply to either resolves independently."""
    return _hid("X", symbol.upper(), profile, side.upper(),
                opened_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), source_alert_id)


def make_radar_id(*, symbol: str, reporting_when: str, day: datetime) -> str:
    return _hid("R", symbol.upper(), reporting_when, day.astimezone(timezone.utc).strftime("%Y-%m-%d"))


def make_event_update_id(*, symbol: str, event_type: str, accepted_at: str) -> str:
    return _hid("E", symbol.upper(), event_type, accepted_at)
