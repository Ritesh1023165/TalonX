"""
talonx_core.schemas
------------------------
Pydantic contracts for this module's Redis boundary.

QuantSignal and ResearchReport here mirror talonx_quant.schemas.QuantSignal
and talonx_brain.schemas.ResearchReport respectively -- deliberately
re-declared rather than imported, same reasoning as talonx_quant's own
re-declaration of MarketTickEvent: this module only knows the WIRE format
published to each channel, so producer and consumer stay independently
deployable/versionable.

ResearchReport here is a DELIBERATELY TRIMMED mirror -- it omits
`citations` (the full retrieved-chunk list with excerpt text), which the
decision matrix never looks at. Pydantic's default `extra="ignore"`
behavior means the omitted field is simply dropped on parse, not an
error, so this stays a strictly valid subset of the real wire shape.

ActionableAlert is this module's own output contract, published to
talonx:alerts:dispatch. It embeds the full triggering QuantSignal (not
just its ticker) plus the research summary/findings actually used in the
decision, so a downstream consumer has everything needed to act without a
separate lookup/join back into either upstream channel.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Input contracts
# ------------------------------------------------------------------

class SignalType(str, Enum):
    RSI_OVERSOLD_VOLUME_SURGE = "rsi_oversold_volume_surge"
    RSI_OVERBOUGHT_VOLUME_SURGE = "rsi_overbought_volume_surge"
    MACD_BULLISH_CROSS = "macd_bullish_cross"
    MACD_BEARISH_CROSS = "macd_bearish_cross"
    MA_GOLDEN_CROSS = "ma_golden_cross"
    MA_DEATH_CROSS = "ma_death_cross"


class SignalDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class QuantSignal(BaseModel):
    """Mirrors talonx_quant.schemas.QuantSignal -- consumed from talonx:signals:quant."""

    ticker: str
    signal_type: SignalType
    direction: SignalDirection
    message: str

    price: float
    rsi: float | None = None
    macd: float | None = None
    macd_signal_line: float | None = None
    sma_fast: float | None = None
    sma_slow: float | None = None
    volume: float | None = None
    volume_surge_ratio: float | None = None

    bar_timestamp: datetime
    published_at: datetime | None = None


class ResearchVerdict(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    INSUFFICIENT_CONTEXT = "insufficient_context"


class ResearchReport(BaseModel):
    """
    Trimmed mirror of talonx_brain.schemas.ResearchReport -- consumed from
    talonx:reports:brain. Omits `citations` deliberately (see module
    docstring).
    """

    ticker: str
    triggering_signal: QuantSignal
    verdict: ResearchVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    model_used: str

    # is_degraded=True is the ONE thing decision.py checks specially: it
    # means talonx_brain couldn't produce a real qualitative read (LLM
    # failed AND no cache existed) and this is a quant-only placeholder --
    # bypasses the normal confidence gate into a DEGRADED_QUANT_ALERT
    # rather than being silently suppressed like a normal low-confidence
    # report. is_stale/from_cache are informational only (not branched on
    # here), carried through from talonx_brain for dashboard/audit
    # visibility.
    is_stale: bool = False
    is_degraded: bool = False
    from_cache: bool = False

    generated_at: datetime
    published_at: datetime


# ------------------------------------------------------------------
# Output contract
# ------------------------------------------------------------------

class AlertAction(str, Enum):
    # Quant direction and research verdict agree.
    CONFIRMED_BULLISH = "confirmed_bullish"
    CONFIRMED_BEARISH = "confirmed_bearish"
    # Quant direction and research verdict disagree -- arguably the more
    # actionable of the two outcomes: the technical setup says one thing,
    # the fundamentals/news say another.
    CONTRADICTED = "contradicted"
    # talonx_brain couldn't produce a qualitative read at all (LLM outage,
    # no cache to fall back on) -- dispatched anyway, quant-only, so the
    # user knows a signal fired even without a research opinion backing it.
    DEGRADED_QUANT_ALERT = "degraded_quant_alert"

    # --- Phase 2 LONG_TERM decision matrix (see decision.py's
    # evaluate_long_term) -- disjoint from the intraday actions above,
    # never mixed on the same alert or the same Redis channel.
    HIGH_CONVICTION_BUY = "high_conviction_buy"
    HOLD_QUALITY = "hold_quality"
    TAKE_PROFIT_REBALANCE = "take_profit_rebalance"
    UNDER_PERFORM_REBALANCE = "under_perform_rebalance"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ActionableAlert(BaseModel):
    """Published to talonx:alerts:dispatch when a correlated pair clears the decision matrix."""

    ticker: str
    action: AlertAction
    severity: AlertSeverity
    rationale: str  # human-readable, combines the quant message + research summary

    quant_direction: SignalDirection
    research_verdict: ResearchVerdict
    research_confidence: float = Field(ge=0.0, le=1.0)

    triggering_signal: QuantSignal
    research_summary: str
    key_findings: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    model_used: str
    is_degraded: bool = False

    # When talonx_core itself received each half of the correlated pair --
    # useful for diagnosing how stale a pairing was, independent of the
    # bar_timestamp/generated_at already inside the upstream payloads.
    signal_received_at: datetime
    report_received_at: datetime

    correlated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()


# ------------------------------------------------------------------
# Phase 2 LONG_TERM path -- fundamentals/moat-DCF input contracts and
# this module's own long-term output contract
# ------------------------------------------------------------------

class FundamentalFactorSignal(BaseModel):
    """Mirrors talonx_quant.schemas.FundamentalFactorSignal -- consumed
    from talonx:signals:fundamental."""

    ticker: str
    fiscal_year: int
    roic: float | None = None
    piotroski_f_score: int | None = None
    fcf_yield: float | None = None
    altman_z_score: float | None = None
    debt_to_ebitda_proxy: float | None = None
    price: float
    message: str
    # Event-Driven Earnings Radar: True for an earnings-triggered
    # republish -- see talonx_quant.schemas.FundamentalFactorSignal's own
    # docstring. decision.py bypasses its own cooldown/no-state-change
    # gates when this is set on either the signal or the report below.
    is_earnings_related: bool = False
    computed_at: datetime


class MoatRating(str, Enum):
    WIDE = "wide"
    NARROW = "narrow"
    NONE = "none"


class LongTermResearchReport(BaseModel):
    """Trimmed mirror of talonx_brain.schemas.LongTermResearchReport --
    consumed from talonx:reports:longterm. Omits `citations`, same
    reasoning as the intraday ResearchReport mirror above: the decision
    matrix never looks at excerpt text."""

    ticker: str
    triggering_signal: FundamentalFactorSignal
    moat_rating: MoatRating
    capital_allocation_assessment: str
    dcf_fair_value_per_share: float
    quality_score: int = Field(ge=0, le=10)
    summary: str
    key_findings: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    model_used: str

    guidance_revision_notes: str | None = None
    revenue_eps_surprise: str | None = None
    is_earnings_related: bool = False

    is_stale: bool = False
    is_degraded: bool = False
    from_cache: bool = False

    generated_at: datetime
    published_at: datetime


class LongTermActionableAlert(BaseModel):
    """Published to talonx:alerts:longterm when a correlated fundamental-
    signal + long-term-report pair clears evaluate_long_term()'s matrix.
    A SIBLING schema to ActionableAlert, not a repurposing of it -- the
    fields genuinely differ (margin of safety / quality / moat instead of
    quant-direction / research-verdict / confidence)."""

    ticker: str
    action: AlertAction
    severity: AlertSeverity
    rationale: str
    # The LLM's own free-text summary (LongTermResearchReport.summary),
    # carried separately from `rationale` above -- rationale is the FULL
    # technical writeup (formula checks, quality/moat/price restated),
    # meant for format_telegram_long_term_details(); summary is a clean
    # one-or-two-sentence readout with no internal-threshold noise, meant
    # for the SHORT Telegram push (format_telegram_long_term_alert), which
    # needs something safe to truncate to ~120 chars without cutting off
    # mid-formula or mid-number.
    summary: str

    quality_score: int = Field(ge=0, le=10)
    moat_rating: MoatRating
    market_price: float
    intrinsic_fair_value: float
    margin_of_safety_pct: float  # (fair_value - price) / fair_value; negative means overvalued

    # Event-Driven Earnings Radar, Requirement 7/8: populated only for an
    # earnings-triggered alert (is_earnings_related=True) -- the PRE-
    # update fair-value/margin-of-safety, captured from the correlator's
    # state before update_report() overwrites it, same timing
    # previous_moat_rating already uses. None for a routine alert (no
    # "before" value to compare against, or not earnings-related at all).
    previous_fair_value: float | None = None
    previous_margin_of_safety_pct: float | None = None
    guidance_revision_notes: str | None = None
    revenue_eps_surprise: str | None = None
    is_earnings_related: bool = False

    triggering_signal: FundamentalFactorSignal
    capital_allocation_assessment: str
    key_findings: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    model_used: str
    is_degraded: bool = False

    signal_received_at: datetime
    report_received_at: datetime

    correlated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_redis_payload(self) -> str:
        return self.model_dump_json()
