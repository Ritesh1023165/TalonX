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
from datetime import datetime, timezone
from typing import Any

from talonx_quant.config import QuantConfig
from talonx_quant.consumer import QuantScanner
from talonx_quant.schemas import QuantSignal, RejectedCandidateEvent, SignalDirection

from .broker import PaperGuardError
from .config import PivConfig
from .decision_contract import DataReadiness, ExecutionStatus, MarketView, Recommendation, StrategyApprovalStatus, decide
from .decision_ledger import DecisionLedger
from .events import EventBus, PivEvent, trading_date_for
from .experimental_authorization import ExperimentalAuthorization
from .gemini_enrichment import GeminiEnrichmentOutbox
from .lifecycle import PaperLifecycle, stable_id
from .notification_outbox import NotificationOutbox, classify as classify_notification
from .shadow_ledger import ShadowLedger
from .warmup import WarmupCheck, preseed_and_verify

PIV_QUANTITY = 1.0
# QuantScanner is intraday-only today -- no MULTI_DAY strategy has been
# researched/frozen/validated (Task69Q PERMANENT PRODUCT TARGET #6). Do not
# widen this without a separately validated longer-horizon strategy family.
NATURAL_STRATEGY_HORIZON = "INTRADAY_SHORT"


def _natural_strategy_version() -> str:
    """Task 79E: QuantConfig has no strategy-version concept of its own --
    reuses talonx_backtest.reproducibility.get_strategy_version(), the
    SAME sha256[:12] fingerprint of the frozen strategy files
    (talonx_quant/{strategy,indicators,config,session}.py) the backtest
    reproducibility pipeline already computes and tests, rather than
    inventing a second, parallel, hand-maintained version tag. Computed
    fresh on every call (matches runtime_sha/config_hash's own
    "never cached, never assumed" identity philosophy) -- it changes the
    moment protected strategy source changes, forcing any
    ExperimentalAuthorization bound to the old fingerprint to fail closed.
    """
    from talonx_backtest.reproducibility import get_strategy_version
    return get_strategy_version()


@dataclass
class OpenDecisionPosition:
    symbol: str
    entry_signal_id: str
    stop_price: float | None
    target_price: float | None
    # Task 79E: True iff THIS position originated from an EXPERIMENTAL_BUY
    # decision -- carried so its protective exit/HOLD decisions stay
    # correctly labelled `experimental=True` regardless of whether the
    # entry permission that created it is still active (exits are never
    # gated on entry permission, matching paper_entry_enabled's own
    # exit-independence).
    experimental: bool = False
    experimental_id: str | None = None


@dataclass
class DecisionEngine:
    """Owns one QuantScanner instance + one Redis pubsub subscriber on its
    signals_channel. Async because QuantScanner's ingestion/publish path is
    async against a real Redis client -- see module docstring."""

    redis_client: Any
    events: EventBus
    lifecycle: PaperLifecycle
    config: QuantConfig = field(default_factory=QuantConfig)
    # Task 70S: the OUTER PivConfig (Alpaca credentials/data_endpoint/feed_mode),
    # separate from `config` above (QuantScanner's own, unrelated QuantConfig).
    # None (the default -- every pre-Task-70S caller/test) means warmup.py's
    # Alpaca leg is skipped entirely; see preseed_and_verify's own docstring.
    piv_config: PivConfig | None = None
    # Task 77I: the three new durable ledgers -- all optional, defaulting to
    # an in-memory-only instance (never touches disk) in __post_init__ so
    # every pre-existing DecisionEngine test-construction site keeps working
    # unchanged (same fail-safe-default pattern Task 76S used for
    # PaperEntrySettings). Every REAL production caller (cli.py::runtime())
    # always supplies real, state_dir-backed instances.
    decision_ledger: DecisionLedger | None = None
    notification_outbox: NotificationOutbox | None = None
    shadow_ledger: ShadowLedger | None = None
    # Task 78I Stage 3: optional -- None means enrichment is not
    # configured at all (in-memory-only outbox constructed below), matching
    # every other optional-component pattern in this class.
    gemini_enrichment: GeminiEnrichmentOutbox | None = None
    runtime_sha: str | None = None
    config_hash: str | None = None
    # Task 79E: None (the default -- every pre-Task79E caller/test) means NO
    # experimental permission exists at all -- every eligible-but-UNVALIDATED
    # signal resolves exactly as before this task (NO_TRADE). Never
    # constructed here; always the caller's (cli.py's) explicit choice, and
    # never active unless an operator has populated the underlying,
    # inactive-by-default authorization file (see experimental_authorization.py).
    experimental_authorization: ExperimentalAuthorization | None = None
    # TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE. The ONLY way any decision this
    # engine makes can ever resolve to StrategyApprovalStatus.APPROVED --
    # `cli.py` never sets this (grep-provable), so no production code path
    # can reach it. Every real decision hardcodes UNVALIDATED, regardless of
    # any caller-supplied value elsewhere -- "do not trust a caller-supplied
    # 'approved' flag as production authority."
    strategy_approval_status_override: StrategyApprovalStatus | None = None

    def __post_init__(self) -> None:
        self.decision_ledger = self.decision_ledger or DecisionLedger(None)
        self.notification_outbox = self.notification_outbox or NotificationOutbox(None, None)
        self.shadow_ledger = self.shadow_ledger or ShadowLedger(None)
        self.gemini_enrichment = self.gemini_enrichment or GeminiEnrichmentOutbox(None)
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

    async def start(self, universe: list[str] | None = None, now: datetime | None = None) -> list[WarmupCheck]:
        """Causal pre-market hydration, then subscribe to the scanner's own
        signal channel. universe=None skips warmup entirely (e.g. a test
        that doesn't need it) -- callers driving a real session must always
        pass the configured PIV universe. See warmup.py's module docstring
        for the causality argument and why this must run before any live
        bar is fed to the scanner. `now` is test-only (fixes the causal
        cutoff); real sessions always use the default (current UTC time)."""
        if universe is not None:
            self.warmup_checks = await preseed_and_verify(
                self.scanner, universe, self.config.htf_sma_period,
                piv_config=self.piv_config, now=now,
            )
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

    def _strategy_approval_status(self) -> StrategyApprovalStatus:
        # See the field's own docstring above -- production callers never
        # supply strategy_approval_status_override, so this is always
        # UNVALIDATED outside a TEST_FIXTURE_ONLY construction site.
        return self.strategy_approval_status_override or StrategyApprovalStatus.UNVALIDATED

    def _record_decision(self, decision) -> None:
        """Task 77I: durable-record-before-dispatch, then two INDEPENDENT,
        individually-guarded branches -- a NotificationOutbox or
        ShadowLedger failure can never suppress the other, and neither can
        ever suppress or alter the real order_intent call that follows in
        the caller (which does not depend on either succeeding). If the
        durable record itself fails to write, that exception is NOT
        swallowed here -- it propagates to the caller, which must not then
        proceed to a BUY (see _handle_entry: the record() call happens
        before the recommendation==BUY branch, so a recording failure
        blocks the entry by construction, never silently continuing)."""
        self.decision_ledger.record(
            decision, event_id=decision.decision_id, evidence_category="natural",
            runtime_sha=self.runtime_sha, config_hash=self.config_hash,
        )
        try:
            self.notification_outbox.enqueue(decision)
        except Exception as exc:  # noqa: BLE001 -- a notification-outbox failure must never suppress
            # shadow tracking or the real order_intent call that follows -- see module docstring.
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=decision.ticker, reason=f"NOTIFICATION_ENQUEUE_FAILED_{type(exc).__name__}",
                source="STRATEGY",
            ))
        try:
            self.shadow_ledger.consider_entry(decision, source="STRATEGY")
        except Exception as exc:  # noqa: BLE001 -- a shadow-ledger failure must never suppress a
            # notification or the real order_intent call that follows -- see module docstring.
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=decision.ticker, reason=f"SHADOW_CONSIDER_ENTRY_FAILED_{type(exc).__name__}",
                source="STRATEGY",
            ))

    def _signal_is_fresh(self, signal: QuantSignal, now: datetime) -> bool:
        """Task 79E Stage 0: "do not assume every drained pub/sub message is
        current merely because some bars passed the runner's readiness
        gate" -- a message could, in principle, be delayed/foreign/replayed
        on the channel. Reuses the SAME stale-data threshold
        (config.stale_seconds) session_runner.py already applies to raw bar
        freshness, rather than inventing a second one."""
        bar_ts = signal.bar_timestamp
        if bar_ts.tzinfo is None:
            return False
        stale_seconds = getattr(self.piv_config, "stale_seconds", 120) if self.piv_config is not None else 120
        age = (now - bar_ts).total_seconds()
        return 0 <= age <= stale_seconds

    def _experimental_permissions(self, *, symbol: str, signal: QuantSignal, trading_date_et: str) -> tuple[bool, bool, str | None]:
        """Returns (experimental_buy_permitted, experimental_paper_permitted,
        experimental_id) -- both booleans default False/False if no
        authorization is configured at all, or if the signal itself is not
        fresh (see _signal_is_fresh), matching "signals admitted to the
        experimental path must correspond to eligible, fresh inputs"."""
        auth = self.experimental_authorization
        if auth is None:
            return False, False, None
        now = datetime.now(timezone.utc)
        if not self._signal_is_fresh(signal, now):
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=symbol, reason="EXPERIMENTAL_SIGNAL_NOT_FRESH", source="EXPERIMENTAL",
            ))
            return False, False, None
        buy_ok, buy_reason = auth.permits_entry(
            symbol=symbol, trading_date_et=trading_date_et, strategy_id=signal.signal_type.value,
            strategy_version=_natural_strategy_version(), runtime_sha=self.runtime_sha or "",
            config_hash=self.config_hash or "", now=now,
        )
        if not buy_ok:
            return False, False, None
        account_id = self.lifecycle.broker.identity.account_id if self.lifecycle.broker.identity is not None else ""
        paper_ok, _paper_reason = auth.permits_paper_execution(
            symbol=symbol, trading_date_et=trading_date_et, strategy_id=signal.signal_type.value,
            strategy_version=_natural_strategy_version(), runtime_sha=self.runtime_sha or "",
            config_hash=self.config_hash or "", now=now, account_id=account_id,
        )
        return True, paper_ok, auth.experiment_id

    def _handle_entry(self, signal: QuantSignal) -> None:
        self.natural_signal_count += 1
        self.published_count += 1
        symbol = signal.ticker.upper()
        self.events.emit(PivEvent.build(
            "SIGNAL", symbol=symbol, price=signal.price, status=signal.signal_type.value,
            source="STRATEGY", alpha_evidence=False,
        ))
        market_view = MarketView.BULLISH if signal.direction == SignalDirection.BULLISH else MarketView.BEARISH
        has_open_long = symbol in self.positions
        trading_date_et = trading_date_for(signal.bar_timestamp.isoformat())
        experimental_buy_permitted, experimental_paper_permitted, experimental_id = self._experimental_permissions(
            symbol=symbol, signal=signal, trading_date_et=trading_date_et,
        )
        decision_id = stable_id("decision", "entry", symbol, signal.bar_timestamp.isoformat())
        decision = decide(
            decision_id=decision_id, session_id=self.events.session_id or "",
            trading_date_et=trading_date_et, ticker=symbol,
            market_view=market_view, has_open_long=has_open_long,
            # A fresh incoming signal (bullish OR bearish) is never itself an
            # authorised exit condition -- see module docstring's LONG_ONLY
            # note and decision_contract's own hard invariant: SELL_TO_CLOSE
            # must never be reachable from market_view alone.
            approved_exit_condition=False,
            strategy_approval_status=self._strategy_approval_status(), data_readiness=DataReadiness.READY,
            paper_entry_enabled=self.lifecycle.paper_entry_settings.enabled_for(symbol),
            strategy_id=signal.signal_type.value, entry_price=signal.price, stop_price=signal.stop_price,
            target_price=signal.target_price, horizon=NATURAL_STRATEGY_HORIZON,
            experimental_buy_permitted=experimental_buy_permitted,
            experimental_paper_permitted=experimental_paper_permitted, experimental_id=experimental_id,
        )
        self._record_decision(decision)
        if classify_notification(decision) is not None:
            # Task 78I Stage 3: enrichment is REQUESTED for the same set of
            # decisions worth alerting on (actionable or WATCH) -- durable
            # bookkeeping only, never a chain.generate() call here (that
            # happens independently in dispatch_pending, see module
            # docstring's "initial deterministic alert does not wait for
            # Gemini"). A failure here must never suppress the alert/shadow/
            # execution branches that already happened above.
            try:
                self.gemini_enrichment.request(decision.decision_id, decision.ticker, signal)
            except Exception as exc:  # noqa: BLE001 -- optional component; never blocks the decision path.
                self.events.emit(PivEvent.build(
                    "BROKER_ERROR", symbol=symbol, reason=f"GEMINI_ENRICHMENT_REQUEST_FAILED_{type(exc).__name__}",
                    source="STRATEGY",
                ))
        if decision.recommendation not in (Recommendation.BUY, Recommendation.EXPERIMENTAL_BUY):
            return
        is_experimental = decision.recommendation == Recommendation.EXPERIMENTAL_BUY
        required_status = ExecutionStatus.ENTRY_ELIGIBLE_EXPERIMENTAL_PAPER if is_experimental else ExecutionStatus.ENTRY_ELIGIBLE
        if decision.execution_status != required_status:
            return  # recommendation preserved above (recorded); broker entry withheld (e.g. PAPER/experimental-PAPER not permitted)
        signal_id = f"strategy_entry_{symbol}_{signal.bar_timestamp.isoformat()}"
        order_source = "EXPERIMENTAL" if is_experimental else "STRATEGY"
        try:
            extra_kwargs: dict[str, Any] = {}
            if is_experimental:
                extra_kwargs = dict(
                    experimental_id=decision.experimental_id, experimental_trading_date_et=trading_date_et,
                    experimental_strategy_version=_natural_strategy_version(),
                )
            result = self.lifecycle.order_intent(
                signal_id, symbol, "buy", PIV_QUANTITY, source=order_source, alpha_evidence=False,
                reference_price=signal.price, stop_price=signal.stop_price,
                signal_timestamp=signal.bar_timestamp.isoformat(),
                strategy_id=signal.signal_type.value, horizon=NATURAL_STRATEGY_HORIZON,
                decision_id=decision.decision_id, **extra_kwargs,
            )
        except PaperGuardError as exc:
            self.events.emit(PivEvent.build("BROKER_ERROR", symbol=symbol, reason=str(exc), source=order_source))
            return
        self.positions[symbol] = OpenDecisionPosition(
            symbol, signal_id, signal.stop_price, signal.target_price,
            experimental=is_experimental, experimental_id=decision.experimental_id,
        )
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
        decision_id = stable_id("decision", "exit", symbol, bar.timestamp.isoformat())
        decision = decide(
            decision_id=decision_id, session_id=self.events.session_id or "",
            trading_date_et=trading_date_for(bar.timestamp.isoformat()), ticker=symbol,
            market_view=MarketView.NEUTRAL, has_open_long=True,
            approved_exit_condition=reason is not None,
            strategy_approval_status=self._strategy_approval_status(), data_readiness=DataReadiness.READY,
            paper_entry_enabled=self.lifecycle.paper_entry_settings.enabled_for(symbol),
            strategy_id=None, stop_price=position.stop_price, target_price=position.target_price,
            horizon=NATURAL_STRATEGY_HORIZON,
            # Task 79E: exits are NEVER gated on entry permission -- an
            # experimental position's protective exit stays correctly
            # labelled `experimental=True` regardless of whether the
            # authorization that created it has since expired or been
            # disabled (mirrors paper_entry_enabled's own pre-existing
            # exit-independence).
            is_experimental_position=position.experimental,
        )
        self._record_decision(decision)
        if reason is None:
            return
        del self.positions[symbol]
        exit_event = "STOP_TRIGGERED" if reason == "STOP" else "EXIT_REQUESTED"
        order_source = "EXPERIMENTAL" if position.experimental else "STRATEGY"
        self.events.emit(PivEvent.build(exit_event, symbol=symbol, reason=reason, price=bar.close, source=order_source, alpha_evidence=False))
        signal_id = f"strategy_exit_{symbol}_{bar.timestamp.isoformat()}"
        exit_reference_price = {"STOP": position.stop_price, "TARGET": position.target_price}.get(reason)
        try:
            result = self.lifecycle.order_intent(
                signal_id, symbol, "sell", PIV_QUANTITY, source=order_source, alpha_evidence=False,
                reference_price=exit_reference_price, signal_timestamp=bar.timestamp.isoformat(),
                horizon=NATURAL_STRATEGY_HORIZON, decision_id=decision.decision_id,
                experimental_id=position.experimental_id if position.experimental else None,
            )
        except PaperGuardError as exc:
            self.events.emit(PivEvent.build("BROKER_ERROR", symbol=symbol, reason=str(exc), source=order_source))
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
        for symbol, bar in bars.items():
            # Task 77I Stage 3: advances PENDING_FILL -> OPEN and checks
            # OPEN -> CLOSED for any shadow position on this symbol, using
            # the SAME bars the real decision path just saw -- completely
            # independent of whether a real order_intent call happened
            # above (a shadow entry only exists at all for an
            # approved-strategy BUY -- see shadow_ledger.py).
            try:
                self.shadow_ledger.on_bar(symbol, bar)
            except Exception as exc:  # noqa: BLE001 -- shadow tracking must never take down the real
                # decision/execution loop.
                self.events.emit(PivEvent.build(
                    "BROKER_ERROR", symbol=symbol, reason=f"SHADOW_ON_BAR_FAILED_{type(exc).__name__}", source="STRATEGY",
                ))

    def flatten_all(self, bars: dict[str, Any]) -> None:
        for symbol in list(self.positions):
            bar = bars.get(symbol)
            if bar is not None:
                self._check_exit(symbol, bar, force_reason="END_OF_SESSION")
        for symbol, bar in bars.items():
            try:
                self.shadow_ledger.force_close(symbol, bar.timestamp, bar.close, "END_OF_SESSION")
            except Exception as exc:  # noqa: BLE001 -- same posture as on_bars above.
                self.events.emit(PivEvent.build(
                    "BROKER_ERROR", symbol=symbol, reason=f"SHADOW_FORCE_CLOSE_FAILED_{type(exc).__name__}", source="STRATEGY",
                ))
