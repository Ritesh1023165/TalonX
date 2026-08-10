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

from talonx_core.schemas import AlertAction, QuantSignal, ResearchReport


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
