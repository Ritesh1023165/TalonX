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
from .premarket_radar import PremarketRadarEngine, classify, is_premarket
from .readiness import READY_AT, ReadinessStateError, SessionReadinessValidator, load_readiness_state, save_readiness_state

ET = ZoneInfo("America/New_York")
OPEN = time(9, 30)
# Task 69Q Part 7C: if no NATURAL actionable signal has fired for this long
# during the regular session, send one compact "engine active" heartbeat --
# never more often than this, regardless of how many ticks run in between.
HEARTBEAT_INTERVAL_SECONDS = 1800.0


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
    # Task 69Q Part 8: a single mutable dict, owned by the caller (cli.py),
    # shared with the /ping listener -- see telegram_inbound.build_piv_info.
    # None is a fully supported no-op (e.g. tests that don't need /ping).
    piv_info: dict | None = None
    premarket_radar_enabled: bool = True

    _last_bar_ts: dict[str, datetime] = field(default_factory=dict, init=False)
    _last_seen_wall: dict[str, datetime] = field(default_factory=dict, init=False)
    _last_bar: dict[str, Bar] = field(default_factory=dict, init=False)
    _stale_flagged: set[str] = field(default_factory=set, init=False)
    _ready_symbols: set[str] | None = field(default=None, init=False)
    _session: date | None = field(default=None, init=False)
    _probe_attempted: bool = field(default=False, init=False)
    _probe_position_open: bool = field(default=False, init=False)
    _premarket_radar: PremarketRadarEngine = field(default_factory=PremarketRadarEngine, init=False)
    _last_heartbeat_wall: datetime | None = field(default=None, init=False)
    _last_natural_signal_wall: datetime | None = field(default=None, init=False)
    _last_natural_signal_count_seen: int = field(default=0, init=False)

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

    @property
    def _readiness_state_path(self):
        return self.config.state_dir / "session_readiness_state.json"

    def _restore_readiness(self, session: date) -> None:
        """Restore-safe by construction: a symbol's persisted READY/
        DATA_NOT_READY decision is honored as-is (the validator's own
        _final short-circuit already prevents any later re-evaluation or
        causal transition -- restoring into _final reproduces exactly the
        behavior a never-restarted process would have had). A symbol still
        PENDING at the time of a crash instead restores its raw pre-10:00
        observations, so live accumulation continues correctly from where
        it left off rather than restarting cold."""
        try:
            state = load_readiness_state(self._readiness_state_path)
        except ReadinessStateError as exc:
            self.events.emit(PivEvent.build("SESSION_READINESS_STATE_INVALID", reason=str(exc), status="MALFORMED_JSON"))
            return
        outcome = self.validator.restore_state(state, session)
        if outcome.missing:
            self.events.emit(PivEvent.build("SESSION_READINESS_STATE_MISSING", status="NO_PRIOR_STATE_FOUND"))
        elif outcome.invalid:
            self.events.emit(PivEvent.build("SESSION_READINESS_STATE_INVALID", status="MALFORMED_OR_UNSUPPORTED_SCHEMA"))
        elif outcome.stale:
            self.events.emit(PivEvent.build("SESSION_READINESS_STATE_STALE", status="PERSISTED_STATE_IS_FOR_A_DIFFERENT_SESSION_DATE"))
        else:
            self.events.emit(PivEvent.build(
                "SESSION_READINESS_STATE_RESTORED",
                status=f"restored={len(outcome.restored_symbols)} invalid_symbols={len(outcome.invalid_symbols)}",
                reason=",".join(outcome.invalid_symbols) or None,
            ))

    def _persist_readiness(self, session: date) -> None:
        save_readiness_state(self._readiness_state_path, self.validator.to_state(session))

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
        self._persist_readiness(session)
        if self.piv_info is not None:
            self.piv_info["session_ready_count"] = len(self._ready_symbols)
            if self.decision_engine is not None:
                self.piv_info["warmup_ready_count"] = len(self.decision_engine.warmup_ready_symbols)

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
        if self.piv_info is not None:
            self.piv_info["stale_count"] = len(self._stale_flagged)
            self.piv_info["feed_health"] = (
                f"DEGRADED ({len(self._stale_flagged)} stale)" if self._stale_flagged
                else "HEALTHY (PIV live feed active)"
            )

    async def process_tick(self, now: datetime) -> None:
        session = now.astimezone(ET).date()
        if self._session != session:
            self._session, self._ready_symbols = session, None
            self._last_bar_ts.clear(); self._last_seen_wall.clear(); self._stale_flagged.clear(); self._last_bar.clear()
            self._probe_attempted = self._probe_position_open = False
            # Restore before anything else this session: restored entries land in
            # the validator's own _final/_observed state, so the existing
            # finalize-trigger below (now >= READY_AT and _ready_symbols is None)
            # transparently reuses them via evaluate()'s short-circuit -- no
            # separate seeding needed, and no risk of double-finalizing.
            self._restore_readiness(session)

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
        if new_bars:
            self._persist_readiness(session)

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
        self._update_piv_info_after_tick(now)
        self._maybe_emit_heartbeat(now)

    def _update_piv_info_after_tick(self, now: datetime) -> None:
        """Task 69Q Part 8: keeps the shared /ping dict current every tick --
        cheap (small in-memory dicts/counters only, no I/O)."""
        if self.piv_info is None:
            return
        if self.decision_engine is not None:
            funnel = self.decision_engine.funnel_summary()
            self.piv_info["quant_evaluation_cycles"] = funnel["evaluation_cycles"]
            self.piv_info["quant_candidates"] = funnel["candidates"]
            self.piv_info["quant_published"] = funnel["published"]
            self.piv_info["quant_rejected"] = funnel["rejected"]
            self.piv_info["quant_unaccounted"] = funnel["unaccounted_candidates"]
            if funnel["published"] > self._last_natural_signal_count_seen:
                self._last_natural_signal_count_seen = funnel["published"]
                self._last_natural_signal_wall = now
        self.piv_info["radar_watch_count"] = self._premarket_radar.watch_count
        orders = self.lifecycle.state.orders.values()
        self.piv_info["natural_orders"] = sum(1 for o in orders if o.get("source") == "STRATEGY")
        self.piv_info["natural_fills"] = sum(1 for o in orders if o.get("source") == "STRATEGY" and o.get("status") == "filled")
        self.piv_info["probe_orders"] = sum(1 for o in orders if o.get("source") == "PIV_LIFECYCLE_PROBE")
        self.piv_info["probe_fills"] = sum(1 for o in orders if o.get("source") == "PIV_LIFECYCLE_PROBE" and o.get("status") == "filled")

    def _maybe_emit_heartbeat(self, now: datetime) -> None:
        """Task 69Q Part 7C: a compact, rate-limited 'engine active' status
        when no NATURAL actionable signal has published in a while --
        informational only, never sent more than once per
        HEARTBEAT_INTERVAL_SECONDS regardless of tick frequency."""
        if self.decision_engine is None:
            return
        if self._last_heartbeat_wall is None:
            self._last_heartbeat_wall = now  # baseline -- no heartbeat at the very first eligible tick
            return
        if (now - self._last_heartbeat_wall).total_seconds() < HEARTBEAT_INTERVAL_SECONDS:
            return
        if self._last_natural_signal_wall is not None and (now - self._last_natural_signal_wall).total_seconds() < HEARTBEAT_INTERVAL_SECONDS:
            self._last_heartbeat_wall = now
            return
        self._last_heartbeat_wall = now
        funnel = self.decision_engine.funnel_summary()
        top_reason = max(funnel["rejected_breakdown"], key=funnel["rejected_breakdown"].get) if funnel["rejected_breakdown"] else "NONE"
        self.events.emit(PivEvent.build(
            "STATUS_HEARTBEAT", status="NO_ACTIONABLE_TRADES_ENGINE_ACTIVE",
            reason=f"top_rejection={top_reason}",
        ))

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

    def _write_funnel_report(self) -> None:
        """Task 69Q Part 3: DecisionEngine only lives for the duration of the
        `start` command's live loop -- the separate `eod` CLI invocation
        cannot see its in-memory counters, so they're persisted here for
        `eod` to read and fold into the session report."""
        if self.decision_engine is None:
            return
        import json
        path = self.config.state_dir / "quant_funnel_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.decision_engine.funnel_summary(), indent=2, sort_keys=True), encoding="utf-8")

    def fetch_snapshots(self) -> dict[str, dict]:
        """Alpaca /v2/stocks/snapshots -- gives prevDailyBar.c (previous
        session close) and latestTrade/dailyBar for the pre-market radar's
        gap calculation. Reuses the exact transport/feed-param pattern
        fetch_bars_latest already uses; not called during the regular
        session (radar is pre-market-only, see process_premarket_tick)."""
        feed = FEED_MODE_PARAM[self.config.feed_mode]
        headers = {"APCA-API-KEY-ID": self.config.key_id, "APCA-API-SECRET-KEY": self.config.secret_key}
        response = self.transport.get(
            f"{self.config.data_endpoint}/v2/stocks/snapshots",
            headers=headers, params={"symbols": ",".join(self.config.universe), "feed": feed}, timeout=15,
        )
        if response.status_code != 200:
            return {}
        return (response.json() or {}).get("snapshots") or (response.json() or {})

    async def process_premarket_tick(self, now: datetime) -> None:
        """Observational only -- see premarket_radar.py's module docstring
        for why this can never place an order (no lifecycle/broker import
        anywhere in that module). Emits only on a bias TRANSITION, never
        every tick (Part 7C: avoid spam)."""
        if not self.premarket_radar_enabled:
            return
        try:
            snapshots = self.fetch_snapshots()
        except Exception as exc:  # noqa: BLE001 -- radar is best-effort, must never crash the session
            self.events.emit(PivEvent.build("BROKER_ERROR", reason=f"PREMARKET_RADAR_FETCH_FAILED_{type(exc).__name__}: {exc}", status="RADAR_TICK_SKIPPED"))
            return
        observations = []
        for symbol in self.config.universe:
            snap = snapshots.get(symbol) or {}
            prev_close = ((snap.get("prevDailyBar") or {}).get("c"))
            latest_price = ((snap.get("latestTrade") or {}).get("p")) or ((snap.get("dailyBar") or {}).get("c"))
            latest_volume = (snap.get("dailyBar") or {}).get("v")
            observations.append(classify(symbol, prev_close, latest_price, latest_volume))
        for transition in self._premarket_radar.evaluate(observations):
            reason_bits = list(transition.get("reason_codes", ()))
            if transition.get("gap_pct") is not None:
                reason_bits.append(f"gap_pct={transition['gap_pct']}")
            self.events.emit(PivEvent.build(
                transition["event"], symbol=transition["symbol"], source="PREMARKET_RADAR", alpha_evidence=False,
                status=transition.get("bias"), reason=",".join(reason_bits) or None,
            ))
        if self.piv_info is not None:
            self.piv_info["radar_watch_count"] = self._premarket_radar.watch_count

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
                elif is_premarket(now):
                    # Task 69Q Part 7A: observational-only radar, wholly
                    # separate from the regular-session decision path above --
                    # never touches lifecycle/broker (see premarket_radar.py).
                    try:
                        await self.process_premarket_tick(now)
                    except Exception as exc:  # noqa: BLE001 -- same posture as the regular-session tick above
                        self.events.emit(PivEvent.build(
                            "BROKER_ERROR", reason=f"PREMARKET_TICK_FAILED_{type(exc).__name__}: {exc}",
                            status="RADAR_TICK_SKIPPED_LOOP_CONTINUES",
                        ))
                await sleep(self.poll_interval_seconds)
            if self._probe_position_open:
                self._close_probe()
            if self.decision_engine is not None:
                self.decision_engine.flatten_all(self._last_bar)
                self._write_funnel_report()
        finally:
            if self.decision_engine is not None:
                await self.decision_engine.stop()


def _probe_cutoff() -> time:
    from .lifecycle_probe import PROBE_CUTOFF_ET
    return PROBE_CUTOFF_ET
