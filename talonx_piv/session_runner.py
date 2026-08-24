"""Task 65 live paper session runner.

Task 64 built the safety harness (preflight, order lifecycle, reconciliation,
Telegram) but nothing in the repository ever drove it from real market data --
`cli.py start` only flips a session-enabled flag. This module is the missing
plumbing: it polls Alpaca's batched multi-symbol REST bars endpoint on a
fixed interval and feeds completed 1-minute bars into the reusable
`SessionReadinessValidator`, exercising the whole live path -- feed ->
readiness -> telemetry -> Telegram -> reconciliation -- under real market
conditions.

No decision path is wired in today. ORPB_V1 is explicitly rejected/retired
(see docs/research/TALONX_RESEARCH_LEDGER.md Task 63P) -- driving it live
today, even framed as "just plumbing," would be an ORPB replay against live
data, which the operating rules for this task forbid outright. The actual
still-live "existing candidate" (talonx_quant/strategy.py via consumer.py's
QuantScanner) needs a 120-bar (~2h) warm-up buffer, a from-scratch entry/exit
tracker (no reusable one exists for it, unlike ORPB_V1's shadow controller),
and consumer.py's confluence/risk-reward/trend/cooldown publish-gating
faithfully reproduced rather than reimplemented from a cold read under time
pressure -- building that correctly for a LIVE paper broker in one session
was judged too much new, untested decision logic to introduce into a live
financial pipeline today. So this runner deterministically never generates a
SIGNAL/ORDER_INTENT: `process_tick` only ever calls the readiness validator,
never a strategy. Zero orders today is by construction, not by chance --
see results/task65_piv/task65_summary.md for the full rationale and the
follow-up task this defers to.

Explicit feed pinning: the feed param is resolved once from
`config.feed_mode` (RESEARCH_SIP -> sip, IEX_PAPER_PIV -> iex) and reused for
every poll. There is no retry-on-a-different-feed anywhere in this module.

No synthesized data: a symbol with any gap in its 09:30-09:59 minutes is
marked DATA_NOT_READY by the validator. Missing bars are never forward-filled
or interpolated; a poll that returns nothing for a symbol simply advances
that symbol's staleness clock (`_check_stale`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
import time as time_module
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import FEED_MODE_PARAM, PivConfig
from .events import EventBus, PivEvent
from .lifecycle import PaperLifecycle
from .readiness import READY_AT, SessionReadinessValidator

ET = ZoneInfo("America/New_York")
OPEN = time(9, 30)


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


@dataclass(frozen=True)
class Bar:
    """Plain OHLCV value object -- deliberately independent of any strategy
    module (see this file's module docstring for why no decision path,
    ORPB_V1 or otherwise, is imported here today)."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("session_runner requires timezone-aware bars")


@dataclass
class SessionRunner:
    config: PivConfig
    events: EventBus
    lifecycle: PaperLifecycle
    transport: Any
    validator: SessionReadinessValidator = field(default_factory=SessionReadinessValidator)
    poll_interval_seconds: float = 60.0

    _last_bar_ts: dict[str, datetime] = field(default_factory=dict, init=False)
    _last_seen_wall: dict[str, datetime] = field(default_factory=dict, init=False)
    _stale_flagged: set[str] = field(default_factory=set, init=False)
    _ready_symbols: set[str] | None = field(default=None, init=False)
    _session: date | None = field(default=None, init=False)

    @property
    def flatten_time(self) -> time:
        return _parse_hhmm(self.config.eod_flatten_et)

    def fetch_bars_latest(self) -> dict[str, Bar]:
        feed = FEED_MODE_PARAM[self.config.feed_mode]
        headers = {"APCA-API-KEY-ID": self.config.key_id, "APCA-API-SECRET-KEY": self.config.secret_key}
        response = self.transport.get(
            f"{self.config.data_endpoint}/v2/stocks/bars/latest",
            headers=headers, params={"symbols": ",".join(self.config.universe), "feed": feed}, timeout=15,
        )
        if response.status_code != 200:
            return {}
        bars = (response.json() or {}).get("bars") or {}
        result: dict[str, Bar] = {}
        for symbol, row in bars.items():
            if row is None or symbol not in self.config.universe:
                continue
            raw_ts = row.get("t")
            if not raw_ts:
                continue
            timestamp = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
            result[symbol] = Bar(
                timestamp, float(row["o"]), float(row["h"]), float(row["l"]), float(row["c"]), float(row["v"]),
            )
        return result

    def _finalize_readiness(self, session: date, now: datetime) -> None:
        self._ready_symbols = set()
        for symbol in self.config.universe:
            telemetry = self.validator.evaluate(symbol, session, now)
            if telemetry.status == "READY":
                self._ready_symbols.add(symbol)
                self.events.emit(PivEvent.build("MARKET_DATA_READY", symbol=symbol, reason=telemetry.reason))
            else:
                self.events.emit(PivEvent.build(
                    "DATA_NOT_READY", symbol=symbol, reason=telemetry.reason,
                    status=f"missing_minutes={len(telemetry.missing_minutes)}",
                ))

    def _check_stale(self, now: datetime) -> None:
        for symbol in self.config.universe:
            if self._ready_symbols is not None and symbol not in self._ready_symbols:
                continue
            last_seen = self._last_seen_wall.get(symbol)
            if last_seen is None:
                continue
            gap = (now - last_seen).total_seconds()
            if gap > self.config.stale_seconds and symbol not in self._stale_flagged:
                self._stale_flagged.add(symbol)
                self.events.emit(PivEvent.build("STALE_DATA", symbol=symbol, reason=f"no new bar for >{self.config.stale_seconds}s"))
            elif gap <= self.config.stale_seconds:
                self._stale_flagged.discard(symbol)

    def process_tick(self, now: datetime) -> None:
        session = now.astimezone(ET).date()
        if self._session != session:
            self._session, self._ready_symbols = session, None
            self._last_bar_ts.clear(); self._last_seen_wall.clear(); self._stale_flagged.clear()

        fetched = self.fetch_bars_latest()
        for symbol in self.config.universe:
            bar = fetched.get(symbol)
            if bar is None:
                continue
            last = self._last_bar_ts.get(symbol)
            if last is not None and bar.timestamp <= last:
                continue
            self._last_bar_ts[symbol] = bar.timestamp
            self._last_seen_wall[symbol] = now
            local_time = bar.timestamp.astimezone(ET).time()
            if OPEN <= local_time < READY_AT:
                self.validator.observe(symbol, session, bar.timestamp)

        if now.astimezone(ET).time() >= READY_AT and self._ready_symbols is None:
            self._finalize_readiness(session, now)

        # No decision path is called here -- see module docstring.
        # Signals/orders are zero today by construction, not by chance.

        self._check_stale(now)

    def run(
        self, *, stop_at: datetime | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], None] = time_module.sleep,
    ) -> None:
        self.events.emit(PivEvent.build("PAPER_SESSION_STARTED", status="LIVE_RUNNER_LOOP_STARTED"))
        while True:
            self.lifecycle.reload()
            if self.lifecycle.state.kill_switch:
                self.events.emit(PivEvent.build("KILL_SWITCH", reason="RUNNER_LOOP_OBSERVED_KILL_SWITCH", status="RUNNER_LOOP_STOPPED"))
                break
            now = clock()
            local = now.astimezone(ET)
            if (stop_at is not None and now >= stop_at) or local.time() >= self.flatten_time:
                break
            if local.time() >= OPEN:
                self.process_tick(now)
            sleep(self.poll_interval_seconds)
