"""Task 65B live paper session runner.

Polls Alpaca's batched multi-symbol REST bars endpoint on a fixed interval,
feeds completed 1-minute bars into the reusable `SessionReadinessValidator`,
and -- only for symbols that reach READY at 10:00 ET -- drives the real
strategy/shadow decision path via `talonx_piv.decision_engine.DecisionEngine`
(which itself drives the real, unmodified `talonx_quant.consumer.QuantScanner`
-- see that module's docstring for why this is reuse, not reimplementation,
and why ORPB_V1 plays no part in it). Natural entries/exits become real PAPER
orders through `PaperLifecycle`.

If no natural STRATEGY-sourced order lifecycle occurs by the predeclared
cutoff (see talonx_piv.lifecycle_probe.PROBE_CUTOFF_ET), an isolated,
explicitly-operator-confirmed PIV_LIFECYCLE_PROBE exercises the full
submit -> ack -> fill -> position -> controlled exit -> reconciliation path
on its own, tagged separately and excluded from all strategy statistics.

Explicit feed pinning: the feed param is resolved once from
`config.feed_mode` (RESEARCH_SIP -> sip, IEX_PAPER_PIV -> iex) and reused for
every poll -- no retry on a different feed anywhere in this module.

No synthesized data: a symbol with any gap in its 09:30-09:59 minutes is
marked DATA_NOT_READY and is excluded from the decision engine entirely for
the rest of that session. Missing bars are never forward-filled or
interpolated.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from .config import FEED_MODE_PARAM, PivConfig
from .decision_engine import DecisionEngine
from .events import EventBus, PivEvent
from .lifecycle import PaperLifecycle
from .lifecycle_probe import close_piv_lifecycle_probe, run_piv_lifecycle_probe
from .readiness import READY_AT, SessionReadinessValidator

ET = ZoneInfo("America/New_York")
OPEN = time(9, 30)


def _parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


@dataclass(frozen=True)
class Bar:
    """Plain OHLCV value object -- independent of any strategy module."""
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
    decision_engine: DecisionEngine | None = None
    poll_interval_seconds: float = 60.0
    probe_enabled: bool = False

    _last_bar_ts: dict[str, datetime] = field(default_factory=dict, init=False)
    _last_seen_wall: dict[str, datetime] = field(default_factory=dict, init=False)
    _last_bar: dict[str, Bar] = field(default_factory=dict, init=False)
    _stale_flagged: set[str] = field(default_factory=set, init=False)
    _ready_symbols: set[str] | None = field(default=None, init=False)
    _session: date | None = field(default=None, init=False)
    _probe_attempted: bool = field(default=False, init=False)
    _probe_position_open: bool = field(default=False, init=False)

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

    async def process_tick(self, now: datetime) -> None:
        session = now.astimezone(ET).date()
        if self._session != session:
            self._session, self._ready_symbols = session, None
            self._last_bar_ts.clear(); self._last_seen_wall.clear(); self._stale_flagged.clear(); self._last_bar.clear()
            self._probe_attempted = self._probe_position_open = False

        fetched = self.fetch_bars_latest()
        new_bars: dict[str, Bar] = {}
        for symbol in self.config.universe:
            bar = fetched.get(symbol)
            if bar is None:
                continue
            last = self._last_bar_ts.get(symbol)
            if last is not None and bar.timestamp <= last:
                continue
            self._last_bar_ts[symbol] = bar.timestamp
            self._last_seen_wall[symbol] = now
            self._last_bar[symbol] = bar
            new_bars[symbol] = bar
            local_time = bar.timestamp.astimezone(ET).time()
            if OPEN <= local_time < READY_AT:
                self.validator.observe(symbol, session, bar.timestamp)

        if now.astimezone(ET).time() >= READY_AT and self._ready_symbols is None:
            self._finalize_readiness(session, now)

        if self.decision_engine is not None and self._ready_symbols:
            # A symbol must be BOTH session-readiness READY (opening-data
            # complete) AND warmup-ready (scanner has enough causal history
            # to compute indicators / HTF trend) before it ever reaches the
            # decision engine -- two independent fail-closed gates, neither
            # weakens the other.
            decision_eligible = self._ready_symbols & self.decision_engine.warmup_ready_symbols
            ready_bars = {s: b for s, b in new_bars.items() if s in decision_eligible}
            if ready_bars:
                await self.decision_engine.on_bars(ready_bars)

        if self.probe_enabled and not self._probe_attempted and now.astimezone(ET).time() >= _probe_cutoff():
            self._run_probe(now)
        elif self._probe_position_open:
            self._close_probe()

        self._check_stale(now)

    def _run_probe(self, now: datetime) -> None:
        self._probe_attempted = True
        result = run_piv_lifecycle_probe(
            self.config, self.events, self.lifecycle,
            explicit_confirmation=self.probe_enabled, now_et_time=now.astimezone(ET).time(),
        )
        if result.ran:
            self._probe_position_open = True

    def _write_warmup_report(self, warmup_checks: list) -> None:
        import json
        path = self.config.state_dir / "warmup_verification.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([c.to_dict() for c in warmup_checks], indent=2, sort_keys=True), encoding="utf-8")

    def _close_probe(self) -> None:
        closed = close_piv_lifecycle_probe(self.events, self.lifecycle)
        if closed is not None:
            self._probe_position_open = False

    async def run(
        self, *, stop_at: datetime | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if self.decision_engine is not None:
            warmup_checks = await self.decision_engine.start(list(self.config.universe))
            self._write_warmup_report(warmup_checks)
            if self.config.universe and not self.decision_engine.warmup_ready_symbols:
                self.events.emit(PivEvent.build(
                    "BROKER_ERROR", reason="WARMUP_CATASTROPHIC_FAILURE_ZERO_SYMBOLS_READY",
                    status="DECISION_PATH_CANNOT_SAFELY_PROCEED",
                ))
                await self.decision_engine.stop()
                return
        try:
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
                    try:
                        await self.process_tick(now)
                    except Exception as exc:  # noqa: BLE001 -- an isolated tick failure (e.g. a transient
                        # Alpaca REST timeout) must never kill an hours-long live session; the loop must
                        # survive it and keep polling, same "one bad cycle shouldn't take down a long-
                        # running process" posture already used elsewhere in this codebase (run_talonx.py's
                        # periodic loops). Confirmed live: an unhandled requests.exceptions.ReadTimeout from
                        # fetch_bars_latest() crashed the whole process ~34 minutes into today's session.
                        self.events.emit(PivEvent.build(
                            "BROKER_ERROR", reason=f"TICK_FAILED_{type(exc).__name__}: {exc}",
                            status="TICK_SKIPPED_LOOP_CONTINUES",
                        ))
                await sleep(self.poll_interval_seconds)
            if self._probe_position_open:
                self._close_probe()
            if self.decision_engine is not None:
                self.decision_engine.flatten_all(self._last_bar)
        finally:
            if self.decision_engine is not None:
                await self.decision_engine.stop()


def _probe_cutoff() -> time:
    from .lifecycle_probe import PROBE_CUTOFF_ET
    return PROBE_CUTOFF_ET
