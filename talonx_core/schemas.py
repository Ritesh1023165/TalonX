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
