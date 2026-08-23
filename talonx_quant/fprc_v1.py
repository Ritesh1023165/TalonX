"""Frozen Task 60 FPRC_V1 research/shadow candidate.

This module is deliberately namespaced and is not imported by the current
production candidate.  Both shadow observation and future research replay use
the state machine below so signal semantics cannot drift between adapters.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import math
from typing import Mapping
from zoneinfo import ZoneInfo

from talonx_quant.session import get_entry_blackout, get_session


FPRC_V1_NAME = "FAILED_PULLBACK_RECLAIM_CONTINUATION_V1"
FPRC_V1_SHORT_NAME = "FPRC_V1"
FPRC_V1_UNIVERSE = (
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AMD", "TSLA", "GOOGL", "PYPL", "STX",
    "ADBE", "ADI", "AMAT", "AVGO", "BKNG", "CMCSA", "COST", "CSCO", "GILD", "HON",
    "INTC", "INTU", "ISRG", "KLAC", "LRCX", "MDLZ", "MU", "NFLX", "PANW", "PEP",
    "QCOM", "REGN", "SBUX", "TXN", "VRTX",
)
# Recorded by telemetry adapters only; never read by FprcV1StateMachine.
FPRC_V1_ATR_15M_TELEMETRY_THRESHOLD_PCT = 0.329
FPRC_V1_ATR_60M_TELEMETRY_THRESHOLD_PCT = 0.839
_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class FprcV1Config:
    """Frozen architecture constants (test-only overrides remain explicit)."""

    sma_period: int = 200
    sma_slope_lookback: int = 4
    pullback_bars: int = 2
    minimum_tick: float = 0.01
    per_side_cost_rate: float = 0.0005
    max_cost_r_5bps: float = 0.20
    cooldown_seconds: float = 20 * 60
    loss_lockout_seconds: float = 75 * 60
    release_capacity: int = 3

    def __post_init__(self) -> None:
        if self.sma_period < 1 or self.sma_slope_lookback < 1:
            raise ValueError("SMA period and slope lookback must be positive")
        if self.pullback_bars != 2:
            raise ValueError("FPRC_V1 requires exactly two or more pullback bars")
        if self.minimum_tick <= 0 or self.per_side_cost_rate != 0.0005:
            raise ValueError("FPRC_V1 tick and 5bps-per-side cost are frozen")
        if self.max_cost_r_5bps != 0.20 or self.release_capacity != 3:
            raise ValueError("FPRC_V1 cost ceiling and capacity are frozen")


@dataclass(frozen=True)
class FprcV1Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        values = (self.open, self.high, self.low, self.close, self.volume)
        if self.timestamp.tzinfo is None:
            raise ValueError("FPRC_V1 requires timezone-aware completed bars")
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("FPRC_V1 bar values must be finite")
        if self.volume < 0 or self.high < max(self.open, self.close, self.low):
            raise ValueError("Invalid FPRC_V1 OHLCV bar")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Invalid FPRC_V1 OHLCV bar")


@dataclass(frozen=True)
class FprcV1Telemetry:
    """Observational values; the state machine never reads them for decisions."""

    rsi_14: float | None = None
    macd_12_26_9: float | None = None
    macd_signal_12_26_9: float | None = None
    sma_10: float | None = None
    sma_50: float | None = None
    relative_volume: float | None = None
    atr_15m_pct: float | None = None
    atr_60m_pct: float | None = None
    extra: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FprcV1Trend:
    ready: bool
    valid: bool
    latest_15m_close: float | None
    sma_200: float | None
    sma_200_four_bars_ago: float | None


@dataclass(frozen=True)
class FprcV1Candidate:
    ticker: str
    architecture: str
    confirmation_timestamp: datetime
    expected_entry_reference: float
    stop_price: float
    pullback_low: float
    reclaim_timestamp: datetime
    reclaim_high: float
    vwap: float
    estimated_cost_r_5bps: float
    trend: FprcV1Trend
    telemetry: FprcV1Telemetry


@dataclass(frozen=True)
class FprcV1Observation:
    ticker: str
    timestamp: datetime
    regular_session: bool
    vwap: float | None
    trend: FprcV1Trend
    phase: str
    below_vwap_count: int
    candidate: FprcV1Candidate | None = None
    thesis_failure_exit: bool = False
    reset_reason: str | None = None
    rejection_reason: str | None = None
    telemetry: FprcV1Telemetry = field(default_factory=FprcV1Telemetry)


@dataclass
class _Aggregate:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap_at_close: float

    def add(self, bar: FprcV1Bar, vwap: float) -> None:
        self.high = max(self.high, bar.high)
        self.low = min(self.low, bar.low)
        self.close = bar.close
        self.volume += bar.volume
        self.vwap_at_close = vwap


def estimated_cost_r_5bps(entry: float, stop: float) -> float:
    """Frozen two-sided 5bps feasibility calculation; invalid risk fails closed."""
    risk = abs(float(entry) - float(stop))
    if not all(math.isfinite(value) for value in (entry, stop, risk)) or risk <= 0:
        return math.inf
    return (float(entry) * 0.0005 + float(entry) * 0.0005) / risk


def actual_cost_r_5bps(entry: float, exit_price: float, stop: float) -> float:
    """Actual-fill reporting burden using entry and realized exit notionals."""
    risk = abs(float(entry) - float(stop))
    if not all(math.isfinite(value) for value in (entry, exit_price, stop, risk)) or risk <= 0:
        return math.inf
    return (float(entry) * 0.0005 + float(exit_price) * 0.0005) / risk


def rank_fprc_v1_candidates(candidates: list[FprcV1Candidate]) -> list[FprcV1Candidate]:
    """Frozen cost-first operational ordering; no composite score is consulted."""
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.estimated_cost_r_5bps,
            candidate.confirmation_timestamp,
            candidate.ticker,
        ),
    )


class FprcV1StateMachine:
    """Causal, completed-bar-only signal and thesis-failure state machine."""

    def __init__(self, ticker: str, config: FprcV1Config | None = None):
        self.ticker = ticker.upper()
        self.config = config or FprcV1Config()
        self._last_timestamp: datetime | None = None
        self._session_date: date | None = None
        self._cum_typical_volume = 0.0
        self._cum_volume = 0.0
        self._bars_15m: list[_Aggregate] = []
        self._aggregate_15m: _Aggregate | None = None
        self._aggregate_5m: _Aggregate | None = None
        self._previous_close: float | None = None
        self._previous_high: float | None = None
        self._previous_vwap: float | None = None
        self._previous_rth_timestamp: datetime | None = None
        self._below_count = 0
        self._pullback_low: float | None = None
        self._reclaim_timestamp: datetime | None = None
        self._reclaim_high: float | None = None
        self._reclaim_low: float | None = None

    @property
    def phase(self) -> str:
        if self._reclaim_timestamp is not None:
            return "AWAITING_IMMEDIATE_CONFIRMATION"
        if self._below_count:
            return "PULLBACK"
        return "IDLE"

    def reset_setup(self) -> None:
        self._below_count = 0
        self._pullback_low = None
        self._reclaim_timestamp = None
        self._reclaim_high = None
        self._reclaim_low = None

    @staticmethod
    def _bucket_start(timestamp: datetime, interval: int) -> datetime:
        local = timestamp.astimezone(_ET)
        return local.replace(minute=(local.minute // interval) * interval, second=0, microsecond=0)

    @staticmethod
    def _natural_bucket_close(timestamp: datetime, interval: int) -> bool:
        local = timestamp.astimezone(_ET)
        return local.minute % interval == interval - 1

    def _update_aggregate(self, current: _Aggregate | None, bar: FprcV1Bar, vwap: float, interval: int):
        completed: list[_Aggregate] = []
        start = self._bucket_start(bar.timestamp, interval)
        if current is not None and current.start != start:
            completed.append(current)
            current = None
        if current is None:
            current = _Aggregate(start, bar.open, bar.high, bar.low, bar.close, bar.volume, vwap)
        else:
            current.add(bar, vwap)
        if self._natural_bucket_close(bar.timestamp, interval):
            completed.append(current)
            current = None
        return current, completed

    def _trend(self, latest_price: float) -> FprcV1Trend:
        period = self.config.sma_period
        lookback = self.config.sma_slope_lookback
        if len(self._bars_15m) < period + lookback:
            return FprcV1Trend(False, False, None, None, None)
        closes = [bar.close for bar in self._bars_15m]
        sma = sum(closes[-period:]) / period
        prior = sum(closes[-period - lookback : -lookback]) / period
        latest = closes[-1]
        valid = latest_price > sma and latest > sma and sma >= prior
        return FprcV1Trend(True, valid, latest, sma, prior)

    def _remember_bar(self, bar: FprcV1Bar, vwap: float) -> None:
        self._previous_close = bar.close
        self._previous_high = bar.high
        self._previous_vwap = vwap
        self._previous_rth_timestamp = bar.timestamp

    def on_completed_bar(
        self,
        bar: FprcV1Bar,
        telemetry: FprcV1Telemetry | None = None,
        *,
        state_only: bool = False,
    ) -> FprcV1Observation:
        """Consume one completed 1m bar. ``state_only`` builds market readiness only."""
        telemetry = telemetry or FprcV1Telemetry()
        if self._last_timestamp is not None and bar.timestamp <= self._last_timestamp:
            raise ValueError("FPRC_V1 bars must be strictly chronological per ticker")
        self._last_timestamp = bar.timestamp
        empty_trend = self._trend(bar.close)
        if get_session(bar.timestamp) != "regular":
            self.reset_setup()
            return FprcV1Observation(self.ticker, bar.timestamp, False, None, empty_trend, self.phase, 0, telemetry=telemetry)

        local_date = bar.timestamp.astimezone(_ET).date()
        if local_date != self._session_date:
            self._session_date = local_date
            self._cum_typical_volume = 0.0
            self._cum_volume = 0.0
            # Never promote a partial prior-session HTF bucket to a completed
            # trend bar merely because the next session arrived.
            self._aggregate_15m = None
            self._aggregate_5m = None
            self._previous_close = self._previous_high = self._previous_vwap = None
            self._previous_rth_timestamp = None
            self.reset_setup()

        typical = (bar.high + bar.low + bar.close) / 3.0
        self._cum_typical_volume += typical * bar.volume
        self._cum_volume += bar.volume
        vwap = self._cum_typical_volume / self._cum_volume if self._cum_volume > 0 else math.nan

        self._aggregate_15m, completed_15m = self._update_aggregate(
            self._aggregate_15m, bar, vwap, 15
        )
        self._bars_15m.extend(completed_15m)
        retain = self.config.sma_period + self.config.sma_slope_lookback + 2
        self._bars_15m = self._bars_15m[-retain:]

        self._aggregate_5m, completed_5m = self._update_aggregate(
            self._aggregate_5m, bar, vwap, 5
        )
        thesis_failure = any(item.close < item.vwap_at_close for item in completed_5m)
        trend = self._trend(bar.close)
        reset_reason = rejection = None
        candidate = None

        if state_only:
            self.reset_setup()
            self._remember_bar(bar, vwap)
            return FprcV1Observation(
                self.ticker, bar.timestamp, True, vwap, trend, self.phase, 0,
                thesis_failure_exit=False, telemetry=telemetry,
            )

        blackout = get_entry_blackout(bar.timestamp)
        contiguous = self._previous_rth_timestamp is not None and (
            bar.timestamp - self._previous_rth_timestamp == timedelta(minutes=1)
        )

        # A reclaim owns exactly the immediately following bar.
        if self._reclaim_timestamp is not None:
            immediate = bar.timestamp - self._reclaim_timestamp == timedelta(minutes=1)
            passes = (
                immediate and trend.valid and blackout == "none" and math.isfinite(vwap)
                and bar.close > vwap and bar.close > float(self._reclaim_high)
            )
            if passes:
                pullback_low = min(float(self._pullback_low), float(self._reclaim_low))
                stop = pullback_low - self.config.minimum_tick
                cost = estimated_cost_r_5bps(bar.close, stop)
                if stop < bar.close and cost <= self.config.max_cost_r_5bps:
                    candidate = FprcV1Candidate(
                        self.ticker, FPRC_V1_NAME, bar.timestamp, bar.close, stop,
                        pullback_low, self._reclaim_timestamp, float(self._reclaim_high),
                        vwap, cost, trend, telemetry,
                    )
                else:
                    rejection = "ESTIMATED_COST_OR_GEOMETRY_INFEASIBLE"
            else:
                reset_reason = "IMMEDIATE_CONFIRMATION_FAILED"
            self.reset_setup()

        if blackout == "closing":
            if self.phase != "IDLE":
                reset_reason = "CLOSING_BLACKOUT"
            self.reset_setup()
        elif not trend.valid or not math.isfinite(vwap):
            if self.phase != "IDLE":
                reset_reason = "TREND_OR_VWAP_INVALID"
            self.reset_setup()
        elif candidate is None and blackout == "none":
            if not contiguous and self._below_count:
                self.reset_setup()
            if bar.close < vwap:
                self._below_count = self._below_count + 1 if contiguous else 1
                self._pullback_low = bar.low if self._pullback_low is None else min(self._pullback_low, bar.low)
            elif (
                self._below_count >= self.config.pullback_bars
                and self._previous_close is not None
                and self._previous_vwap is not None
                and self._previous_close <= self._previous_vwap
                and self._previous_high is not None
                and bar.close > vwap
                and bar.close > self._previous_high
            ):
                self._reclaim_timestamp = bar.timestamp
                self._reclaim_high = bar.high
                self._reclaim_low = bar.low
                self._pullback_low = min(float(self._pullback_low), bar.low)
                self._below_count = 0
            elif self._reclaim_timestamp is None:
                self.reset_setup()
        elif blackout == "opening":
            self.reset_setup()

        self._remember_bar(bar, vwap)
        return FprcV1Observation(
            self.ticker, bar.timestamp, True, vwap, trend, self.phase,
            self._below_count, candidate, thesis_failure, reset_reason, rejection, telemetry,
        )


class FprcV1ShadowNamespace:
    """Opt-in shadow namespace. Construction has no effect on current-candidate state."""

    def __init__(self, config: FprcV1Config | None = None):
        self.config = config or FprcV1Config()
        self._machines: dict[str, FprcV1StateMachine] = {}

    def machine(self, ticker: str) -> FprcV1StateMachine:
        ticker = ticker.upper()
        if ticker not in self._machines:
            self._machines[ticker] = FprcV1StateMachine(ticker, self.config)
        return self._machines[ticker]

    def observe(
        self,
        ticker: str,
        bar: FprcV1Bar,
        telemetry: FprcV1Telemetry | None = None,
        *,
        state_only: bool = False,
    ) -> FprcV1Observation:
        return self.machine(ticker).on_completed_bar(bar, telemetry, state_only=state_only)
