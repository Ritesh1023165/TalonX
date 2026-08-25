"""Task 65B Part C -- restores the real strategy/shadow decision path.

Drives the REAL, unmodified talonx_quant.consumer.QuantScanner in-process:
feeds it Alpaca-sourced bars via its exact live entrypoint
(`_handle_market_tick`), forces its throttle window to resolve after each
poll tick (`_flush_throttle_window`), and observes whatever it actually
decided to publish via a real Redis subscription to its own
`config.signals_channel` -- the same channel talonx_core's DecisionEngine
consumes in production. This is reuse, not reimplementation: every gate
(confluence score, risk/reward, trend alignment, per-ticker cooldown,
loss-lockout, throttle-batch revalidation) is QuantScanner's own code,
running completely unmodified, with its own real Redis-backed state.

ORPB_V1 is not used here -- it is rejected/retired (see
docs/research/TALONX_RESEARCH_LEDGER.md Task 63P). QuantScanner is the
still-live "existing candidate" (strategy.py), unaffected by that
rejection.

LONG_ONLY: only BULLISH signals open a position -- talonx_quant's LONG_ONLY
lifecycle (Task 25A) means a BEARISH signal never opens a position anywhere
else in the system either; this is not a PIV-specific restriction, just
matching the one that already exists.

Sizing is a fixed, tiny, deterministic quantity (PIV_QUANTITY) -- this is an
operational-parity harness, not alpha-driven position sizing. Exit tracking
(stop/target monitoring against subsequent bars, forced EOD exit) is new
code in this module, since no reusable exit tracker exists for strategy.py
signals the way ORPB_V1's shadow controller had one built in.

Every event this module emits is tagged source="STRATEGY",
alpha_evidence=False -- today's traffic (natural or probe) is operational
PIV test traffic only and creates zero alpha evidence, regardless of
whether a signal fires or what it does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from talonx_quant.config import QuantConfig
from talonx_quant.consumer import QuantScanner
from talonx_quant.schemas import QuantSignal, RejectedCandidateEvent, SignalDirection

from .broker import PaperGuardError
from .events import EventBus, PivEvent
from .lifecycle import PaperLifecycle
from .warmup import WarmupCheck, preseed_and_verify

PIV_QUANTITY = 1.0
# QuantScanner is intraday-only today -- no MULTI_DAY strategy has been
# researched/frozen/validated (Task69Q PERMANENT PRODUCT TARGET #6). Do not
# widen this without a separately validated longer-horizon strategy family.
NATURAL_STRATEGY_HORIZON = "INTRADAY_SHORT"


@dataclass
class OpenDecisionPosition:
    symbol: str
    entry_signal_id: str
    stop_price: float | None
    target_price: float | None


@dataclass
class DecisionEngine:
    """Owns one QuantScanner instance + one Redis pubsub subscriber on its
    signals_channel. Async because QuantScanner's ingestion/publish path is
    async against a real Redis client -- see module docstring."""

    redis_client: Any
    events: EventBus
    lifecycle: PaperLifecycle
    config: QuantConfig = field(default_factory=QuantConfig)

    def __post_init__(self) -> None:
        self.scanner = QuantScanner(self.config)
        self.scanner._client = self.redis_client
        self._pubsub = self.redis_client.pubsub()
        self._subscribed = False
        self.positions: dict[str, OpenDecisionPosition] = {}
        self.natural_signal_count = 0
        self.warmup_checks: list[WarmupCheck] = []
        self.warmup_ready_symbols: set[str] = set()
        # Task 69Q Part 3 -- full quant decision funnel accounting, tapped
        # non-invasively off QuantScanner's own two publish channels (see
        # talonx_quant/consumer.py's _record_rejection/_publish_signal --
        # neither is touched). candidates := published + rejected + pending
        # + errored by construction (consumer.py's control flow guarantees
        # every candidate reaches exactly one of _record_rejection or
        # _publish_signal); "pending" has no meaning in this synchronous
        # per-tick poll model (always 0) and "errored" only counts messages
        # this subscriber received but failed to parse. unaccounted_
        # candidates therefore measures pub/sub delivery loss between
        # QuantScanner's publish and this subscriber's drain, not a deeper
        # internal accounting gap -- see quant_funnel_contract.json.
        self.published_count = 0
        self.rejected_count = 0
        self.errored_count = 0
        self.rejected_breakdown: dict[str, int] = {}
        self.evaluation_cycles = 0
        self.symbols_evaluated_total = 0

    async def start(self, universe: list[str] | None = None) -> list[WarmupCheck]:
        """Causal pre-market hydration, then subscribe to the scanner's own
        signal channel. universe=None skips warmup entirely (e.g. a test
        that doesn't need it) -- callers driving a real session must always
        pass the configured PIV universe. See warmup.py's module docstring
        for the causality argument and why this must run before any live
        bar is fed to the scanner."""
        if universe is not None:
            self.warmup_checks = await preseed_and_verify(self.scanner, universe, self.config.htf_sma_period)
            self.warmup_ready_symbols = {c.symbol for c in self.warmup_checks if c.ready}
        await self._pubsub.subscribe(self.config.signals_channel)
        await self._pubsub.subscribe(self.config.rejected_candidates_channel)
        self._subscribed = True
        return self.warmup_checks

    async def stop(self) -> None:
        if self._subscribed:
            await self._pubsub.unsubscribe(self.config.signals_channel)
            await self._pubsub.unsubscribe(self.config.rejected_candidates_channel)
            await self._pubsub.close()
            self._subscribed = False

    def funnel_summary(self) -> dict:
        """See module docstring above for the candidates/unaccounted_
        candidates definitions this reconciles."""
        candidates = self.published_count + self.rejected_count + self.errored_count
        return {
            "evaluation_cycles": self.evaluation_cycles,
            "symbols_evaluated_total": self.symbols_evaluated_total,
            "candidates": candidates,
            "published": self.published_count,
            "rejected": self.rejected_count,
            "pending": 0,
            "errored": self.errored_count,
            "unaccounted_candidates": candidates - (self.published_count + self.rejected_count + 0 + self.errored_count),
            "rejected_breakdown": dict(self.rejected_breakdown),
        }

    async def feed_bar(self, symbol: str, bar: Any) -> None:
        payload = {
            "event_type": "bar", "symbol": symbol, "source": "polling", "timestamp": bar.timestamp.isoformat(),
            "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close, "volume": bar.volume,
            "price": bar.close,
        }
        await self.scanner._handle_market_tick(payload)

    async def flush_and_collect(self) -> list[QuantSignal]:
        """Force the throttle window to resolve, then drain whatever the
        scanner actually published this cycle from its two real Redis
        channels -- signals_channel (published) and rejected_candidates_
        channel (rejected, tallied for the Part 3 funnel accounting) --
        never a direct/synthetic call, only what QuantScanner itself
        decided to publish after its own gating."""
        await self.scanner._flush_throttle_window()
        published: list[QuantSignal] = []
        while True:
            message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
            if message is None:
                break
            data = message.get("data")
            if not data:
                continue
            channel = message.get("channel")
            if isinstance(channel, (bytes, bytearray)):
                channel = channel.decode()
            if channel == self.config.rejected_candidates_channel:
                try:
                    rejected = RejectedCandidateEvent.model_validate_json(data)
                except Exception:
                    self.errored_count += 1
                    continue
                self.rejected_count += rejected.count
                self.rejected_breakdown[rejected.reason] = self.rejected_breakdown.get(rejected.reason, 0) + rejected.count
                continue
            try:
                published.append(QuantSignal.model_validate_json(data))
            except Exception:
                self.errored_count += 1
                continue
        return published

    def _handle_entry(self, signal: QuantSignal) -> None:
        self.natural_signal_count += 1
        self.published_count += 1
        symbol = signal.ticker.upper()
        self.events.emit(PivEvent.build(
            "SIGNAL", symbol=symbol, price=signal.price, status=signal.signal_type.value,
            source="STRATEGY", alpha_evidence=False,
        ))
        if signal.direction != SignalDirection.BULLISH:
            return  # LONG_ONLY lifecycle -- see module docstring; no order for a bearish signal
        if symbol in self.positions:
            return  # one PIV position per symbol at a time
        signal_id = f"strategy_entry_{symbol}_{signal.bar_timestamp.isoformat()}"
        try:
            result = self.lifecycle.order_intent(
                signal_id, symbol, "buy", PIV_QUANTITY, source="STRATEGY", alpha_evidence=False,
                reference_price=signal.price, stop_price=signal.stop_price,
                signal_timestamp=signal.bar_timestamp.isoformat(),
                strategy_id=signal.signal_type.value, horizon=NATURAL_STRATEGY_HORIZON,
            )
        except PaperGuardError as exc:
            self.events.emit(PivEvent.build("BROKER_ERROR", symbol=symbol, reason=str(exc), source="STRATEGY"))
            return
        self.positions[symbol] = OpenDecisionPosition(symbol, signal_id, signal.stop_price, signal.target_price)
        broker_id = result.get("id")
        if broker_id:
            self.lifecycle.poll_order_until_terminal(str(broker_id))

    def _check_exit(self, symbol: str, bar: Any, *, force_reason: str | None = None) -> None:
        position = self.positions.get(symbol)
        if position is None:
            return
        reason = force_reason
        if reason is None:
            if position.stop_price is not None and bar.low <= position.stop_price:
                reason = "STOP"
            elif position.target_price is not None and bar.high >= position.target_price:
                reason = "TARGET"
        if reason is None:
            return
        del self.positions[symbol]
        exit_event = "STOP_TRIGGERED" if reason == "STOP" else "EXIT_REQUESTED"
        self.events.emit(PivEvent.build(exit_event, symbol=symbol, reason=reason, price=bar.close, source="STRATEGY", alpha_evidence=False))
        signal_id = f"strategy_exit_{symbol}_{bar.timestamp.isoformat()}"
        exit_reference_price = {"STOP": position.stop_price, "TARGET": position.target_price}.get(reason)
        try:
            result = self.lifecycle.order_intent(
                signal_id, symbol, "sell", PIV_QUANTITY, source="STRATEGY", alpha_evidence=False,
                reference_price=exit_reference_price, signal_timestamp=bar.timestamp.isoformat(),
                horizon=NATURAL_STRATEGY_HORIZON,
            )
        except PaperGuardError as exc:
            self.events.emit(PivEvent.build("BROKER_ERROR", symbol=symbol, reason=str(exc), source="STRATEGY"))
            return
        broker_id = result.get("id")
        if broker_id:
            self.lifecycle.poll_order_until_terminal(str(broker_id))

    async def on_bars(self, bars: dict[str, Any]) -> None:
        """bars: {symbol: Bar} for this tick's newly-fetched, already-READY
        symbols only -- the caller (session_runner.py) applies readiness
        gating before calling this; a DATA_NOT_READY symbol's bar is never
        passed here at all."""
        self.evaluation_cycles += 1
        self.symbols_evaluated_total += len(bars)
        for symbol, bar in bars.items():
            await self.feed_bar(symbol, bar)
        for signal in await self.flush_and_collect():
            self._handle_entry(signal)
        for symbol, bar in bars.items():
            self._check_exit(symbol, bar)

    def flatten_all(self, bars: dict[str, Any]) -> None:
        for symbol in list(self.positions):
            bar = bars.get(symbol)
            if bar is not None:
                self._check_exit(symbol, bar, force_reason="END_OF_SESSION")
