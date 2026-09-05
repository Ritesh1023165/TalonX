"""Frozen Task 62 opening-range participation breakout candidate.

This namespace is opt-in and is not imported by the existing TalonX candidate.
Research and shadow adapters share this completed-bar state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import math
from statistics import median
from typing import Mapping
from zoneinfo import ZoneInfo

from talonx_quant.session import get_entry_blackout, get_session


ORPB_V1_NAME = "OPENING_RANGE_PARTICIPATION_BREAKOUT_V1"
ORPB_V1_SHORT_NAME = "ORPB_V1"
ORPB_V1_UNIVERSE = (
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX",
    "ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON",
    "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU", "NFLX", "PANW", "PEP",
    "QCOM", "REGN", "SBUX", "TXN", "VRTX",
)
_ET = ZoneInfo("America/New_York")
_OPENING_RANGE_END = time(10, 0)


@dataclass(frozen=True)
class OrpbV1Config:
    opening_range_minutes: int = 30
    aggregate_minutes: int = 5
    opening_range_aggregate_bars: int = 6
    minimum_tick: float = 0.01
    per_side_cost_rate: float = 0.0005
    max_cost_r_5bps: float = 0.20
    cooldown_seconds: float = 20 * 60
    loss_lockout_seconds: float = 75 * 60
    release_capacity: int = 3

    def __post_init__(self) -> None:
        if (
            self.opening_range_minutes != 30
            or self.aggregate_minutes != 5
            or self.opening_range_aggregate_bars != 6
        ):
            raise ValueError("ORPB_V1 opening-range geometry is frozen at 30m / six 5m bars")
        if self.minimum_tick != 0.01 or self.per_side_cost_rate != 0.0005:
            raise ValueError("ORPB_V1 tick and 5bps-per-side cost are frozen")
        if self.max_cost_r_5bps != 0.20 or self.release_capacity != 3:
            raise ValueError("ORPB_V1 cost ceiling and capacity are frozen")
        if self.cooldown_seconds != 1200 or self.loss_lockout_seconds != 4500:
            raise ValueError("ORPB_V1 safety controls are frozen")


@dataclass(frozen=True)
class OrpbV1Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        values = (self.open, self.high, self.low, self.close, self.volume)
        if self.timestamp.tzinfo is None:
            raise ValueError("ORPB_V1 requires timezone-aware completed bars")
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("ORPB_V1 bar values must be finite")
        if self.volume < 0 or self.high < max(self.open, self.close, self.low):
            raise ValueError("Invalid ORPB_V1 OHLCV bar")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Invalid ORPB_V1 OHLCV bar")


@dataclass(frozen=True)
class OrpbV1Telemetry:
    """External diagnostics that are never read for eligibility."""

    rsi_14: float | None = None
    macd_12_26_9: float | None = None
    atr_15m_pct: float | None = None
    atr_60m_pct: float | None = None
    relative_volume: float | None = None
    extra: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class OrpbV1Candidate:
    ticker: str
    architecture: str
    confirmation_timestamp: datetime
    expected_entry_reference: float
    stop_price: float
    opening_range_high: float
    opening_range_low: float
    breakout_timestamp: datetime
    breakout_high: float
    breakout_low: float
    breakout_close: float
    breakout_volume: float
    opening_volume_median: float
    estimated_cost_r_5bps: float
    telemetry: OrpbV1Telemetry


@dataclass(frozen=True)
class OrpbV1Observation:
    ticker: str
    timestamp: datetime
    regular_session: bool
    phase: str
    opening_range_ready: bool
    opening_range_high: float | None
    opening_range_low: float | None
    opening_volume_median: float | None
    candidate: OrpbV1Candidate | None = None
    thesis_failure_exit: bool = False
    reset_reason: str | None = None
    rejection_reason: str | None = None
    telemetry: OrpbV1Telemetry = field(default_factory=OrpbV1Telemetry)


@dataclass
class _Aggregate:
    start: datetime
    last_timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def add(self, bar: OrpbV1Bar) -> None:
        self.last_timestamp = bar.timestamp
        self.high = max(self.high, bar.high)
        self.low = min(self.low, bar.low)
        self.close = bar.close
        self.volume += bar.volume


def estimated_cost_r_5bps(entry: float, stop: float) -> float:
    risk = abs(float(entry) - float(stop))
    if not all(math.isfinite(value) for value in (entry, stop, risk)) or risk <= 0:
        return math.inf
    return (float(entry) * 0.0005 + float(entry) * 0.0005) / risk


def actual_cost_r_5bps(entry: float, exit_price: float, stop: float) -> float:
    risk = abs(float(entry) - float(stop))
    if not all(math.isfinite(value) for value in (entry, exit_price, stop, risk)) or risk <= 0:
        return math.inf
    return (float(entry) * 0.0005 + float(exit_price) * 0.0005) / risk


def rank_orpb_v1_candidates(candidates: list[OrpbV1Candidate]) -> list[OrpbV1Candidate]:
    return sorted(
        candidates,
        key=lambda item: (
            item.estimated_cost_r_5bps,
            item.confirmation_timestamp,
            item.ticker,
        ),
    )


class OrpbV1StateMachine:
    """One-attempt-per-session, completed-bar ORPB_V1 signal semantics."""

    def __init__(self, ticker: str, config: OrpbV1Config | None = None):
        self.ticker = ticker.upper()
        self.config = config or OrpbV1Config()
        self._last_timestamp: datetime | None = None
        self._session_date: date | None = None
        self._aggregate_5m: _Aggregate | None = None
        self._opening_bars: list[_Aggregate] = []
        self._opening_high: float | None = None
        self._opening_low: float | None = None
        self._opening_volume_median: float | None = None
        self._attempted = False
        self._trigger: _Aggregate | None = None

    @property
    def phase(self) -> str:
        if self._trigger is not None:
            return "AWAITING_IMMEDIATE_CONFIRMATION"
        if self._attempted:
            return "EXHAUSTED"
        if self._opening_high is None:
            return "BUILDING_OPENING_RANGE"
        return "ARMED"

    @property
    def opening_range_ready(self) -> bool:
        return self._opening_high is not None

    def _reset_session(self, session_date: date) -> None:
        self._session_date = session_date
        self._aggregate_5m = None
        self._opening_bars = []
        self._opening_high = None
        self._opening_low = None
        self._opening_volume_median = None
        self._attempted = False
        self._trigger = None

    @staticmethod
    def _bucket_start(timestamp: datetime) -> datetime:
        local = timestamp.astimezone(_ET)
        return local.replace(minute=(local.minute // 5) * 5, second=0, microsecond=0)

    @staticmethod
    def _natural_bucket_close(timestamp: datetime) -> bool:
        return timestamp.astimezone(_ET).minute % 5 == 4

    def _update_aggregate(self, bar: OrpbV1Bar) -> list[_Aggregate]:
        completed: list[_Aggregate] = []
        start = self._bucket_start(bar.timestamp)
        if self._aggregate_5m is not None and self._aggregate_5m.start != start:
            completed.append(self._aggregate_5m)
            self._aggregate_5m = None
        if self._aggregate_5m is None:
            self._aggregate_5m = _Aggregate(
                start, bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume
            )
        else:
            self._aggregate_5m.add(bar)
        if self._natural_bucket_close(bar.timestamp):
            completed.append(self._aggregate_5m)
            self._aggregate_5m = None
        return completed

    def _record_opening_bars(self, completed: list[_Aggregate]) -> None:
        for item in completed:
            local_start = item.start.astimezone(_ET).time()
            if time(9, 30) <= local_start < _OPENING_RANGE_END:
                self._opening_bars.append(item)
        if len(self._opening_bars) == self.config.opening_range_aggregate_bars:
            self._opening_high = max(item.high for item in self._opening_bars)
            self._opening_low = min(item.low for item in self._opening_bars)
            self._opening_volume_median = float(median(item.volume for item in self._opening_bars))

    def on_completed_bar(
        self,
        bar: OrpbV1Bar,
        telemetry: OrpbV1Telemetry | None = None,
        *,
        state_only: bool = False,
    ) -> OrpbV1Observation:
        telemetry = telemetry or OrpbV1Telemetry()
        if self._last_timestamp is not None and bar.timestamp <= self._last_timestamp:
            raise ValueError("ORPB_V1 bars must be strictly chronological per ticker")
        self._last_timestamp = bar.timestamp
        if get_session(bar.timestamp) != "regular":
            self._trigger = None
            return OrpbV1Observation(
                self.ticker, bar.timestamp, False, self.phase, self.opening_range_ready,
                self._opening_high, self._opening_low, self._opening_volume_median,
                telemetry=telemetry,
            )

        local = bar.timestamp.astimezone(_ET)
        if local.date() != self._session_date:
            self._reset_session(local.date())
        completed = self._update_aggregate(bar)
        self._record_opening_bars(completed)
        candidate = None
        thesis_failure = False
        reset_reason = None
        rejection_reason = None

        if state_only:
            self._trigger = None
            self._attempted = False
            return OrpbV1Observation(
                self.ticker, bar.timestamp, True, self.phase, self.opening_range_ready,
                self._opening_high, self._opening_low, self._opening_volume_median,
                telemetry=telemetry,
            )

        if self.opening_range_ready:
            thesis_failure = any(
                item.start.astimezone(_ET).time() >= _OPENING_RANGE_END
                and item.close <= float(self._opening_high)
                for item in completed
            )

        if self._trigger is not None:
            immediate = bar.timestamp - self._trigger.last_timestamp == timedelta(minutes=1)
            passes = (
                immediate
                and get_entry_blackout(bar.timestamp) == "none"
                and bar.close > self._trigger.high
            )
            if passes:
                stop = self._trigger.low - self.config.minimum_tick
                cost = estimated_cost_r_5bps(bar.close, stop)
                if stop < bar.close and cost <= self.config.max_cost_r_5bps:
                    candidate = OrpbV1Candidate(
                        self.ticker, ORPB_V1_NAME, bar.timestamp, bar.close, stop,
                        float(self._opening_high), float(self._opening_low),
                        self._trigger.last_timestamp, self._trigger.high, self._trigger.low,
                        self._trigger.close, self._trigger.volume,
                        float(self._opening_volume_median), cost, telemetry,
                    )
                else:
                    rejection_reason = "ESTIMATED_COST_OR_GEOMETRY_INFEASIBLE"
            else:
                reset_reason = "IMMEDIATE_CONFIRMATION_FAILED"
            self._trigger = None

        if (
            candidate is None
            and not self._attempted
            and self.opening_range_ready
            and self._trigger is None
            and local.time() >= _OPENING_RANGE_END
        ):
            for item in completed:
                if (
                    item.start.astimezone(_ET).time() >= _OPENING_RANGE_END
                    and item.close > float(self._opening_high)
                ):
                    self._attempted = True
                    if get_entry_blackout(item.last_timestamp) != "none":
                        rejection_reason = "ENTRY_BLACKOUT"
                    elif item.volume > float(self._opening_volume_median):
                        self._trigger = item
                    else:
                        rejection_reason = "PARTICIPATION_INSUFFICIENT"
                    break

        return OrpbV1Observation(
            self.ticker, bar.timestamp, True, self.phase, self.opening_range_ready,
            self._opening_high, self._opening_low, self._opening_volume_median,
            candidate, thesis_failure, reset_reason, rejection_reason, telemetry,
        )


class OrpbV1ShadowNamespace:
    def __init__(self, config: OrpbV1Config | None = None):
        self.config = config or OrpbV1Config()
        self._machines: dict[str, OrpbV1StateMachine] = {}

    def machine(self, ticker: str) -> OrpbV1StateMachine:
        ticker = ticker.upper()
        if ticker not in self._machines:
            self._machines[ticker] = OrpbV1StateMachine(ticker, self.config)
        return self._machines[ticker]

    def observe(
        self,
        ticker: str,
        bar: OrpbV1Bar,
        telemetry: OrpbV1Telemetry | None = None,
        *,
        state_only: bool = False,
    ) -> OrpbV1Observation:
        return self.machine(ticker).on_completed_bar(bar, telemetry, state_only=state_only)
