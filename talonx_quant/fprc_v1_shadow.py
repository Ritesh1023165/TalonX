"""Isolated no-capital shadow execution semantics for frozen FPRC_V1."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import math
from typing import Mapping
from zoneinfo import ZoneInfo

from talonx_quant.fprc_v1 import (
    FprcV1Bar,
    FprcV1Candidate,
    FprcV1Config,
    FprcV1ShadowNamespace,
    FprcV1Telemetry,
    actual_cost_r_5bps,
    estimated_cost_r_5bps,
    rank_fprc_v1_candidates,
)


_ET = ZoneInfo("America/New_York")
_FLATTEN = time(15, 50)


@dataclass
class FprcV1ShadowPosition:
    ticker: str
    candidate: FprcV1Candidate
    entry_timestamp: datetime
    entry_price: float
    stop_price: float
    risk: float
    mfe_price: float
    mae_price: float


@dataclass(frozen=True)
class FprcV1ShadowTrade:
    ticker: str
    confirmation_timestamp: datetime
    entry_timestamp: datetime
    entry_price: float
    stop_price: float
    exit_timestamp: datetime
    exit_price: float
    exit_reason: str
    gross_r: float
    cost_r_5bps: float
    net_r_5bps: float
    mfe_r: float
    mae_r: float


@dataclass(frozen=True)
class FprcV1ShadowRejection:
    ticker: str
    timestamp: datetime
    reason: str


class FprcV1ShadowController:
    """Paper-only controller shared by live shadow and future research adapters.

    It deliberately has no broker/publisher dependency and is not wired into the
    current candidate. Each call represents simultaneously completed 1m bars.
    """

    def __init__(self, config: FprcV1Config | None = None):
        self.config = config or FprcV1Config()
        self.signals = FprcV1ShadowNamespace(self.config)
        self.positions: dict[str, FprcV1ShadowPosition] = {}
        self.pending_entries: dict[str, FprcV1Candidate] = {}
        self.pending_thesis_exits: set[str] = set()
        self.cooldown_until: dict[str, datetime] = {}
        self.loss_lockout_until: dict[str, datetime] = {}
        self.flattened_dates: set[date] = set()
        self.published: list[FprcV1Candidate] = []
        self.trades: list[FprcV1ShadowTrade] = []
        self.rejections: list[FprcV1ShadowRejection] = []

    def _reject(self, ticker: str, timestamp: datetime, reason: str) -> None:
        self.rejections.append(FprcV1ShadowRejection(ticker, timestamp, reason))

    def _close(self, ticker: str, timestamp: datetime, price: float, reason: str) -> None:
        position = self.positions.pop(ticker)
        gross_r = (price - position.entry_price) / position.risk
        cost_r = actual_cost_r_5bps(position.entry_price, price, position.stop_price)
        trade = FprcV1ShadowTrade(
            ticker=ticker,
            confirmation_timestamp=position.candidate.confirmation_timestamp,
            entry_timestamp=position.entry_timestamp,
            entry_price=position.entry_price,
            stop_price=position.stop_price,
            exit_timestamp=timestamp,
            exit_price=price,
            exit_reason=reason,
            gross_r=gross_r,
            cost_r_5bps=cost_r,
            net_r_5bps=gross_r - cost_r,
            mfe_r=(position.mfe_price - position.entry_price) / position.risk,
            mae_r=(position.mae_price - position.entry_price) / position.risk,
        )
        self.trades.append(trade)
        if gross_r < 0:
            self.loss_lockout_until[ticker] = timestamp + timedelta(
                seconds=self.config.loss_lockout_seconds
            )

    def _fill_pending(self, ticker: str, bar: FprcV1Bar) -> None:
        candidate = self.pending_entries.pop(ticker, None)
        if candidate is None:
            return
        cost = estimated_cost_r_5bps(bar.open, candidate.stop_price)
        if (
            not math.isfinite(cost)
            or candidate.stop_price >= bar.open
            or cost > self.config.max_cost_r_5bps
        ):
            self._reject(ticker, bar.timestamp, "ACTUAL_FILL_COST_OR_GEOMETRY_INFEASIBLE")
            return
        risk = bar.open - candidate.stop_price
        self.positions[ticker] = FprcV1ShadowPosition(
            ticker, candidate, bar.timestamp, bar.open, candidate.stop_price,
            risk, bar.open, bar.open,
        )

    def _eligible(self, candidate: FprcV1Candidate) -> str | None:
        ticker = candidate.ticker
        now = candidate.confirmation_timestamp
        if ticker in self.positions or ticker in self.pending_entries:
            return "ONE_POSITION_PER_SYMBOL"
        if now < self.cooldown_until.get(ticker, now):
            return "COOLDOWN"
        if now < self.loss_lockout_until.get(ticker, now):
            return "POST_LOSS_LOCKOUT"
        if now.astimezone(_ET).date() in self.flattened_dates:
            return "SESSION_ALREADY_FLATTENED"
        return None

    def on_completed_bar_batch(
        self,
        bars: Mapping[str, FprcV1Bar],
        telemetry: Mapping[str, FprcV1Telemetry] | None = None,
        *,
        state_only: bool = False,
    ) -> list[FprcV1Candidate]:
        """Advance a timestamp batch and return candidates released this close."""
        telemetry = telemetry or {}
        normalized = {ticker.upper(): bar for ticker, bar in bars.items()}

        # Pending close/entry orders fill at this symbol's next available open.
        if not state_only:
            for ticker in sorted(normalized):
                bar = normalized[ticker]
                if ticker in self.pending_thesis_exits and ticker in self.positions:
                    self.pending_thesis_exits.discard(ticker)
                    self._close(ticker, bar.timestamp, bar.open, "THESIS_FAILURE")
                else:
                    self.pending_thesis_exits.discard(ticker)
                self._fill_pending(ticker, bar)

                position = self.positions.get(ticker)
                if position is not None:
                    position.mfe_price = max(position.mfe_price, bar.high)
                    position.mae_price = min(position.mae_price, bar.low)
                    if bar.low <= position.stop_price:
                        self._close(ticker, bar.timestamp, position.stop_price, "STOP")

        candidates: list[FprcV1Candidate] = []
        thesis_failures: set[str] = set()
        for ticker in sorted(normalized):
            observation = self.signals.observe(
                ticker,
                normalized[ticker],
                telemetry.get(ticker),
                state_only=state_only,
            )
            if observation.candidate is not None:
                candidates.append(observation.candidate)
            if observation.thesis_failure_exit:
                thesis_failures.add(ticker)
            if observation.rejection_reason:
                self._reject(ticker, observation.timestamp, observation.rejection_reason)

        if state_only:
            return []

        # Conservative stop-first handling precedes the 15:50 close.
        for ticker in sorted(normalized):
            bar = normalized[ticker]
            local = bar.timestamp.astimezone(_ET)
            if local.time() >= _FLATTEN and ticker in self.positions:
                self._close(ticker, bar.timestamp, bar.close, "END_OF_SESSION")
                self.pending_thesis_exits.discard(ticker)
                self.flattened_dates.add(local.date())
            elif ticker in thesis_failures and ticker in self.positions:
                self.pending_thesis_exits.add(ticker)

        eligible: list[FprcV1Candidate] = []
        for candidate in candidates:
            reason = self._eligible(candidate)
            if reason is None:
                eligible.append(candidate)
            else:
                self._reject(candidate.ticker, candidate.confirmation_timestamp, reason)

        available = max(
            0,
            self.config.release_capacity - len(self.positions) - len(self.pending_entries),
        )
        ranked = rank_fprc_v1_candidates(eligible)
        released = ranked[:available]
        for candidate in ranked[available:]:
            self._reject(candidate.ticker, candidate.confirmation_timestamp, "CAPACITY")
        for candidate in released:
            self.pending_entries[candidate.ticker] = candidate
            self.cooldown_until[candidate.ticker] = candidate.confirmation_timestamp + timedelta(
                seconds=self.config.cooldown_seconds
            )
            self.published.append(candidate)
        return released

    def close_data_end(self, bars: Mapping[str, FprcV1Bar]) -> None:
        """Research-only deterministic finalization; never an entry mechanism."""
        for ticker in sorted(list(self.positions)):
            bar = bars.get(ticker)
            if bar is not None:
                self._close(ticker, bar.timestamp, bar.close, "DATA_END")
