"""
talonx_core.state
----------------------
In-memory per-ticker correlation state: the freshest QuantSignal and
freshest ResearchReport seen for each ticker, each timestamped by when
talonx_core RECEIVED it (not the payload's own internal timestamp), so
freshness is judged consistently regardless of clock skew between
producers or how long a message sat queued upstream.

State is process-local and NOT persisted -- a restart loses all
correlation history (see README "what's not built yet"). This is a
deliberate MVP scope choice: talonx_core is a correlation/decision layer
on top of two already-durable-enough upstream signals, not a system of
record itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from talonx_core.schemas import (
    AlertAction,
    FundamentalFactorSignal,
    LongTermResearchReport,
    MoatRating,
    QuantSignal,
    ResearchReport,
)


@dataclass
class TickerState:
    latest_signal: QuantSignal | None = None
    latest_signal_at: datetime | None = None

    latest_report: ResearchReport | None = None
    latest_report_at: datetime | None = None

    last_alert_at: datetime | None = None
    # The action and triggering-signal price of the last DISPATCHED alert
    # for this ticker -- decision.py's state-transition + price-delta gate
    # reads these to decide whether a same-action re-alert has moved
    # enough to be worth re-sending (see decision.py's evaluate()).
    last_alert_action: AlertAction | None = None
    last_alert_price: float | None = None


class TickerCorrelator:
    """Tracks one TickerState per ticker, in memory, for the life of the process."""

    def __init__(self) -> None:
        self._states: dict[str, TickerState] = {}

    def get_or_create(self, ticker: str) -> TickerState:
        ticker = ticker.upper()
        if ticker not in self._states:
            self._states[ticker] = TickerState()
        return self._states[ticker]

    def update_signal(self, signal: QuantSignal) -> TickerState:
        state = self.get_or_create(signal.ticker)
        state.latest_signal = signal
        state.latest_signal_at = datetime.now(timezone.utc)
        return state

    def update_report(self, report: ResearchReport) -> TickerState:
        state = self.get_or_create(report.ticker)
        state.latest_report = report
        state.latest_report_at = datetime.now(timezone.utc)
        return state

    def mark_alerted(
        self,
        ticker: str,
        action: AlertAction | None = None,
        price: float | None = None,
        when: datetime | None = None,
    ) -> None:
        state = self.get_or_create(ticker)
        state.last_alert_at = when or datetime.now(timezone.utc)
        if action is not None:
            state.last_alert_action = action
        if price is not None:
            state.last_alert_price = price

    def known_tickers(self) -> list[str]:
        return list(self._states.keys())


# ------------------------------------------------------------------
# Phase 2 LONG_TERM path -- a SEPARATE correlator/state pair, not a
# (ticker, horizon) tuple key threaded through the classes above. A
# DUAL_HORIZON ticker's intraday and long-term state must never collide
# -- see this module's docstring precedent (state is process-local,
# in-memory) and the plan's architecture-wide decision to use sibling
# objects rather than composite keys for exactly this reason.
# ------------------------------------------------------------------

@dataclass
class LongTermTickerState:
    fundamental_signal: FundamentalFactorSignal | None = None
    fundamental_signal_at: datetime | None = None

    longterm_report: LongTermResearchReport | None = None
    longterm_report_at: datetime | None = None

    last_alert_at: datetime | None = None
    last_alert_action: AlertAction | None = None
    last_alert_price: float | None = None

    # Fundamental-stop bookkeeping (decision.py's evaluate_long_term):
    # the spec's "ROIC below WACC for 2 consecutive quarters" -- adapted
    # to "2 consecutive annual observations," since this project's XBRL
    # extraction only pulls annual (10-K) facts, not quarterly ones (see
    # talonx_ingest.edgar.financials's own docstring). Incremented/reset
    # in update_signal(), read (never mutated) by decision.py.
    roic_below_wacc_streak: int = 0
    # The moat rating as of the PREVIOUS report (before the current one
    # in `longterm_report`) -- decision.py compares the two to detect a
    # downgrade. None until a second report has ever arrived.
    previous_moat_rating: MoatRating | None = None


class LongTermTickerCorrelator:
    """Tracks one LongTermTickerState per ticker, in memory, for the life
    of the process -- structurally identical to TickerCorrelator above,
    kept as a separate class rather than a shared generic one since its
    update_signal() also carries the ROIC-vs-WACC streak bookkeeping,
    which has no intraday equivalent."""

    def __init__(self) -> None:
        self._states: dict[str, LongTermTickerState] = {}

    def get_or_create(self, ticker: str) -> LongTermTickerState:
        ticker = ticker.upper()
        if ticker not in self._states:
            self._states[ticker] = LongTermTickerState()
        return self._states[ticker]

    def update_signal(self, signal: FundamentalFactorSignal, wacc: float) -> LongTermTickerState:
        state = self.get_or_create(signal.ticker)
        state.fundamental_signal = signal
        state.fundamental_signal_at = datetime.now(timezone.utc)
        if signal.roic is not None and signal.roic < wacc:
            state.roic_below_wacc_streak += 1
        else:
            state.roic_below_wacc_streak = 0
        return state

    def update_report(self, report: LongTermResearchReport) -> LongTermTickerState:
        state = self.get_or_create(report.ticker)
        # Capture the OUTGOING report's moat rating (if any) as the
        # baseline for the NEXT downgrade check, before overwriting it.
        if state.longterm_report is not None:
            state.previous_moat_rating = state.longterm_report.moat_rating
        state.longterm_report = report
        state.longterm_report_at = datetime.now(timezone.utc)
        return state

    def mark_alerted(
        self,
        ticker: str,
        action: AlertAction | None = None,
        price: float | None = None,
        when: datetime | None = None,
    ) -> None:
        state = self.get_or_create(ticker)
        state.last_alert_at = when or datetime.now(timezone.utc)
        if action is not None:
            state.last_alert_action = action
        if price is not None:
            state.last_alert_price = price

    def known_tickers(self) -> list[str]:
        return list(self._states.keys())
