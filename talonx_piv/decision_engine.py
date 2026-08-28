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
import math
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


def _is_finite_positive_number(value: Any) -> bool:
    """Task 79E-R2: strict validity check for a persisted quantity field --
    bool excluded explicitly (bool is an int subclass in Python), matching
    experimental_authorization.py's own strict-parsing posture."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and value > 0


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
    # Task 79E-R1: set once a STOP/TARGET/forced exit condition is first
    # observed for this position, and STAYS set (even across bars where the
    # triggering condition is no longer literally true, e.g. price recovers
    # mid-exit) until the position is CONFIRMED fully flat at the broker --
    # see _check_exit. This is what lets a partially-filled or
    # rejected/failed exit keep being retried on every subsequent bar for
    # whatever quantity is still actually held, instead of the plan being
    # silently dropped the instant the first sell attempt was made.
    exit_reason: str | None = None


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
    # Task 79E-R1: when set, takes priority over the static object above --
    # every permission check reloads fresh from disk (see
    # _current_experimental_authorization), so an operator deleting,
    # disabling, or editing the authorization file mid-session is observed
    # on the very next signal, not only after a process restart. cli.py's
    # real runtime() always sets this; `experimental_authorization=` (the
    # object) remains supported unchanged for every pre-existing test/
    # caller that constructs a fixed authorization directly.
    experimental_authorization_path: Any = None
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
        self._rehydrate_positions()

    def _rehydrate_positions(self) -> None:
        """Task 79E-R1/R2: rebuild self.positions from lifecycle.state.
        positions (persisted, restart-surviving truth) so a process
        restart does not silently lose an open position's exit plan (Task
        79E's own disclosed gap -- see remaining_issues.md item 1). Relies
        on order_intent's target_price persistence (alongside the
        pre-existing stop_price) to restore the full plan, and on
        lifecycle.mark_exit_triggered's own `triggered_exit_reason`
        persistence to restore a plan that had ALREADY fired before the
        restart -- Task 79E-R2 Requirement 3: "a triggered exit must
        remain actionable after restart even if price recovers." A
        rehydrated position is never causality-gated by skip_price_check
        (see on_bars/_check_exit) -- it was never opened by THIS process
        on THIS tick, so it carries no same-bar-as-entry risk in the first
        place; it IS still subject to the pending/uncertain-entry
        preservation _check_exit itself applies to every symbol.

        Task 79E-R2 Requirement 3: "missing required plan fields must
        produce explicit degraded/blocked recovery -- not
        'NO_ACTION_REQUIRED'":
        - No usable quantity information at all (neither `quantity` nor
          `remaining_quantity` is a genuine finite positive number) means
          exits could never be sized safely -- this method does NOT
          rehydrate a plan it cannot trust; the position is deliberately
          left untracked here so _flag_orphaned_positions's own visible
          MISSING_EXIT_PLAN_FOR_OPEN_POSITION catches it on the very next
          tick, rather than silently inventing a size or dropping it with
          no signal at all.
        - Both stop_price AND target_price missing means the position CAN
          be tracked (sized exits and forced EOD flatten still work) but
          has no NATURAL trigger at all -- flagged as degraded rather than
          claiming "no action required."
        """
        for position in self.lifecycle.state.positions.values():
            if position.get("status") != "OPEN":
                continue
            symbol = position.get("symbol")
            if not symbol or symbol in self.positions:
                continue
            self._try_rehydrate_one(symbol, position)

    def _try_rehydrate_one(self, symbol: str, position: dict) -> bool:
        """Shared by _rehydrate_positions (at construction) AND
        _flag_orphaned_positions (mid-session, e.g. for a position that
        only became OPEN AFTER a SUBMIT_FAILED_UNCERTAIN entry was later
        confirmed-adopted-and-filled by reconcile() -- _handle_entry's own
        self.positions[symbol] assignment is never reached for that case,
        since the raw exception propagates past it per the Task 78I
        contract; this is what closes that gap generally, rather than
        leaving it a permanently-orphaned, merely-visible-but-never-healed
        position for the rest of the session). Returns True iff a plan was
        (possibly degraded) rehydrated; False iff recovery was BLOCKED
        (see this method's own event reasons for which)."""
        quantity = position.get("quantity")
        remaining_quantity = position.get("remaining_quantity")
        if not _is_finite_positive_number(remaining_quantity) and not _is_finite_positive_number(quantity):
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=symbol, reason="EXIT_PLAN_RECOVERY_BLOCKED_MISSING_QUANTITY",
                status="DEGRADED_RECOVERY_ORPHAN_EXPECTED_NEXT_TICK",
            ))
            return False
        stop_price = position.get("stop_price")
        target_price = position.get("target_price")
        experimental_id = position.get("experimental_id")
        triggered_exit_reason = position.get("triggered_exit_reason")
        self.positions[symbol] = OpenDecisionPosition(
            symbol, f"rehydrated_{symbol}", stop_price, target_price,
            experimental=experimental_id is not None, experimental_id=experimental_id,
            exit_reason=triggered_exit_reason,
        )
        if triggered_exit_reason is not None:
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=symbol, reason="EXIT_PLAN_REHYDRATED_WITH_TRIGGERED_EXIT_PENDING",
                status=f"RESTART_RECOVERY_MUST_STILL_SELL_REASON_{triggered_exit_reason}",
            ))
        elif stop_price is None and target_price is None:
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=symbol, reason="EXIT_PLAN_RECOVERED_WITHOUT_PROTECTIVE_LEVELS",
                status="DEGRADED_RECOVERY_NO_NATURAL_STOP_OR_TARGET",
            ))
        else:
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=symbol, reason="EXIT_PLAN_REHYDRATED_FROM_PERSISTED_STATE",
                status="RESTART_RECOVERY_NO_ACTION_REQUIRED",
            ))
        return True

    def _flag_orphaned_positions(self, symbols: Any) -> None:
        """Task 79E-R1/R2: "missing plans must fail visibly, not be
        invented" -- an OPEN lifecycle position with no corresponding
        self.positions entry (e.g. rehydration missed it, state was
        mutated out of band, or a SUBMIT_FAILED_UNCERTAIN entry was only
        confirmed-adopted-and-filled by a LATER reconcile() call, after
        _handle_entry's own exception already propagated past its
        self.positions[symbol] assignment) is first given a chance to
        self-heal via the SAME rehydration logic a restart would use
        (_try_rehydrate_one) -- if that succeeds, this is no longer a gap
        at all. Only a GENUINE recovery failure (unsizeable quantity) is
        ever left as a visible MISSING_EXIT_PLAN_FOR_OPEN_POSITION
        (_try_rehydrate_one's own event already covers that case, so
        nothing further is invented here). Checked only for symbols this
        tick actually observed a bar for (cheap; every genuinely open
        position eventually appears here)."""
        for symbol in symbols:
            if symbol in self.positions:
                continue
            lifecycle_position = self.lifecycle._open_position_for(symbol)
            if lifecycle_position is None:
                continue
            if self._try_rehydrate_one(symbol, lifecycle_position):
                continue
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=symbol, reason="MISSING_EXIT_PLAN_FOR_OPEN_POSITION",
                status="ORPHANED_POSITION_NOT_MONITORED_FOR_STOP_TARGET",
            ))

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

    def _current_experimental_authorization(self) -> ExperimentalAuthorization | None:
        """Task 79E-R1: reload FRESH from disk on every call when a path is
        configured -- never a cached object -- so deletion, disablement, or
        an edited binding is observed on the very next signal. Falls back to
        the static `experimental_authorization` object for every
        pre-existing test/caller that constructs one directly."""
        if self.experimental_authorization_path is not None:
            from .experimental_authorization import load_experimental_authorization
            return load_experimental_authorization(self.experimental_authorization_path)
        return self.experimental_authorization

    def _live_session_scope(self) -> str:
        """Task 79E-R2 Requirement 5: "'REGULAR' is a category, not a
        session identity" -- Task 79E-R1 bound every experimental
        permission check to a fixed literal "REGULAR" string, which never
        actually distinguished one live session from another. This binds
        to the AUTHORITATIVE durable live-session identity instead:
        `self.events.session_id`, minted once per process by
        session_identity.build_session_identity and persisted to
        session_identity.json at `start`/`supervise` time. Binding to the
        real session id means a genuinely different process invocation
        (which always mints a fresh session_id -- see session_identity.py's
        own docstring) is correctly rejected as an unrelated session, while
        an in-process supervised restart
        (talonx_piv.supervisor.run_with_bounded_restart, which reconstructs
        SessionRunner/DecisionEngine but reuses the SAME EventBus/
        session_id across bounded restarts) is correctly recognised as THE
        SAME session recovering, never a new one -- permits same-session
        recovery while rejecting unrelated invocations."""
        return self.events.session_id or ""

    def _experimental_permissions(self, *, symbol: str, signal: QuantSignal, trading_date_et: str) -> tuple[bool, bool, str | None]:
        """Returns (experimental_buy_permitted, experimental_paper_permitted,
        experimental_id) -- both booleans default False/False if no
        authorization is configured at all, or if the signal itself is not
        fresh (see _signal_is_fresh), matching "signals admitted to the
        experimental path must correspond to eligible, fresh inputs"."""
        auth = self._current_experimental_authorization()
        if auth is None:
            return False, False, None
        now = datetime.now(timezone.utc)
        if not self._signal_is_fresh(signal, now):
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=symbol, reason="EXPERIMENTAL_SIGNAL_NOT_FRESH", source="EXPERIMENTAL",
            ))
            return False, False, None
        # Task 79E-R1: a fresh bar_timestamp alone only proves the MESSAGE is
        # recent -- not that the symbol itself is currently session-eligible
        # (has passed the SAME causal warmup gate the normal decision path
        # requires before it will ever act on a signal for that symbol; see
        # session_runner.py's own decision_eligible computation). Skipped
        # (never blocks) when warmup_ready_symbols is empty -- i.e. warmup
        # was never run for this engine instance at all (every isolated
        # unit/integration test that drives _handle_entry directly without
        # calling start() first) -- so this is purely an ADDITIONAL,
        # belt-and-suspenders check for a real, warmed-up live session, not
        # a new requirement on every construction site.
        if self.warmup_ready_symbols and symbol not in self.warmup_ready_symbols:
            self.events.emit(PivEvent.build(
                "BROKER_ERROR", symbol=symbol, reason="EXPERIMENTAL_SYMBOL_NOT_SESSION_ELIGIBLE", source="EXPERIMENTAL",
            ))
            return False, False, None
        buy_ok, buy_reason = auth.permits_entry(
            symbol=symbol, trading_date_et=trading_date_et, strategy_id=signal.signal_type.value,
            strategy_version=_natural_strategy_version(), runtime_sha=self.runtime_sha or "",
            config_hash=self.config_hash or "", now=now, session_scope=self._live_session_scope(),
        )
        if not buy_ok:
            return False, False, None
        account_id = self.lifecycle.broker.identity.account_id if self.lifecycle.broker.identity is not None else ""
        paper_ok, _paper_reason = auth.permits_paper_execution(
            symbol=symbol, trading_date_et=trading_date_et, strategy_id=signal.signal_type.value,
            strategy_version=_natural_strategy_version(), runtime_sha=self.runtime_sha or "",
            config_hash=self.config_hash or "", now=now, account_id=account_id,
            session_scope=self._live_session_scope(),
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
                    experimental_session_scope=self._live_session_scope(),
                )
            result = self.lifecycle.order_intent(
                signal_id, symbol, "buy", PIV_QUANTITY, source=order_source, alpha_evidence=False,
                reference_price=signal.price, stop_price=signal.stop_price, target_price=signal.target_price,
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

    def _check_exit(self, symbol: str, bar: Any, *, force_reason: str | None = None, skip_price_check: bool = False) -> None:
        position = self.positions.get(symbol)
        if position is None:
            return
        # Task 79E-R1: the lifecycle-side truth is authoritative for whether
        # this position is still actually open -- a PRIOR call's sell may
        # have since been confirmed fully filled (via poll_order_until_
        # terminal or a later reconcile()) without this engine ever having
        # re-observed it until now. Confirmed flat -> stop tracking; never
        # invent/guess a plan for a symbol lifecycle no longer shows OPEN.
        #
        # Task 79E-R2 Requirement 2: "do not delete exit tracking merely
        # because no OPEN position exists yet" -- a BUY can be legitimately
        # ACCEPTED-BUT-NOT-YET-FILLED (or its true outcome genuinely
        # uncertain) for one or more ticks after order_intent succeeded and
        # self.positions[symbol] was created in _handle_entry, BEFORE
        # lifecycle ever shows an OPEN position for it. Tracking is only
        # ever dropped here when lifecycle shows NEITHER an OPEN position
        # NOR any pending/uncertain entry outstanding -- i.e. the entry is
        # genuinely, conclusively gone (rejected, confirmed-not-submitted,
        # or the position was already fully sold and closed).
        if self.lifecycle._open_position_for(symbol) is None:
            if self.lifecycle.entry_still_pending_or_uncertain(symbol):
                return  # keep the plan; nothing confirmed-held yet to protect or sell
            del self.positions[symbol]
            return
        # Task 79E-R1/R2 entry/exit causality: `skip_price_check` is set
        # ONLY by on_bars() itself, computed as "was this symbol's
        # lifecycle position ALREADY confirmed OPEN before this tick's own
        # entries were processed" (see on_bars's own comment) -- true fill-
        # state, not merely "was this the same tick _handle_entry ran on."
        # This correctly protects BOTH a same-tick fill (the original R1
        # case: the entry bar's own low/high must never retroactively
        # trigger its own stop) AND a genuinely DELAYED fill (an order left
        # pending/accepted for one or more ticks before it actually fills
        # -- R1's narrower rule left that case's own first-eligible bar
        # unprotected). Deliberately NOT derived from wall-clock
        # timestamps (an earlier draft compared `bar.timestamp` against a
        # persisted entry timestamp with `>`, but two back-to-back
        # `datetime.now()` calls were observed to produce BIT-IDENTICAL
        # values on at least one real test-execution environment -- see
        # test_task65b_decision_engine.py's
        # test_stop_hit_triggers_controlled_exit, which caught this in the
        # full suite; clock-resolution-based ordering is not a safe
        # primitive here). A DIRECT _check_exit call (every test/caller
        # that does not go through on_bars) defaults to fully eligible --
        # only on_bars's own same-tick-vs-delayed-fill orchestration can
        # ever have the ambiguity this gate exists to resolve. A forced
        # exit (EOD flatten) is time-based, never price-based, and always
        # bypasses this gate too. Once a reason has already been latched
        # (position.exit_reason), it is never re-derived from price again
        # -- only confirmed-flat (above) clears it, so a delayed/partial
        # exit keeps being retried regardless of where price moves
        # afterward.
        causally_eligible = force_reason is not None or not skip_price_check
        reason = force_reason or position.exit_reason
        if reason is None and causally_eligible:
            if position.stop_price is not None and bar.low <= position.stop_price:
                reason = "STOP"
            elif position.target_price is not None and bar.high >= position.target_price:
                reason = "TARGET"
        if reason is not None and position.exit_reason is None:
            position.exit_reason = reason
            # Task 79E-R2 Requirement 3: persisted immediately, not only
            # held in memory -- "a triggered exit must remain actionable
            # after restart even if price recovers." A no-op (never
            # overwrites an already-recorded reason) if lifecycle already
            # has one for this symbol, e.g. from a prior process's own
            # trigger this rehydrated position already carried in.
            self.lifecycle.mark_exit_triggered(symbol, reason)
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
        # Task 79E-R1: sized to ACTUAL remaining holdings minus whatever a
        # prior attempt already has outstanding (pending/uncertain) -- never
        # the fixed PIV_QUANTITY constant, which is only ever correct for a
        # position's FIRST exit attempt with zero partial fills so far.
        # Zero/near-zero means an earlier attempt already covers everything
        # currently sellable -- do NOT submit a duplicate; keep monitoring
        # (position stays tracked) until lifecycle confirms fully flat.
        available = self.lifecycle.remaining_holdings(symbol)
        if available <= 1e-9:
            return
        exit_event = "STOP_TRIGGERED" if reason == "STOP" else "EXIT_REQUESTED"
        order_source = "EXPERIMENTAL" if position.experimental else "STRATEGY"
        self.events.emit(PivEvent.build(exit_event, symbol=symbol, reason=reason, price=bar.close, source=order_source, alpha_evidence=False))
        signal_id = f"strategy_exit_{symbol}_{bar.timestamp.isoformat()}"
        exit_reference_price = {"STOP": position.stop_price, "TARGET": position.target_price}.get(reason)
        try:
            result = self.lifecycle.order_intent(
                signal_id, symbol, "sell", available, source=order_source, alpha_evidence=False,
                reference_price=exit_reference_price, signal_timestamp=bar.timestamp.isoformat(),
                horizon=NATURAL_STRATEGY_HORIZON, decision_id=decision.decision_id,
                experimental_id=position.experimental_id if position.experimental else None,
                experimental_session_scope=self._live_session_scope() if position.experimental else None,
            )
        except PaperGuardError as exc:
            # Task 79E-R1: the position stays tracked (never deleted here) --
            # a rejected/failed exit attempt must keep being monitored and
            # retried on subsequent bars, not silently abandoned.
            self.events.emit(PivEvent.build("BROKER_ERROR", symbol=symbol, reason=str(exc), source=order_source))
            return
        broker_id = result.get("id")
        if broker_id:
            self.lifecycle.poll_order_until_terminal(str(broker_id))
        # Only now -- after this attempt (and any resulting fill observed by
        # the poll above) -- re-check whether the position is confirmed
        # fully flat; only then stop tracking it.
        if self.lifecycle._open_position_for(symbol) is None:
            del self.positions[symbol]

    async def on_bars(self, bars: dict[str, Any]) -> None:
        """bars: {symbol: Bar} for this tick's newly-fetched, already-READY
        symbols only -- the caller (session_runner.py) applies readiness
        gating before calling this; a DATA_NOT_READY symbol's bar is never
        passed here at all."""
        self.evaluation_cycles += 1
        self.symbols_evaluated_total += len(bars)
        self._flag_orphaned_positions(bars.keys())
        # Task 79E-R2 Requirement 4: captured BEFORE this tick's entries are
        # processed -- a symbol is only causality-ELIGIBLE for a NATURAL
        # price-based stop/target check if its lifecycle position was
        # ALREADY confirmed OPEN (i.e. genuinely filled) prior to this
        # tick, so price-based evaluation can never use price action from
        # at-or-before the fill -- regardless of whether the fill happened
        # synchronously during THIS tick's own _handle_entry (the original
        # same-tick-entry case) or was only confirmed later, on some
        # earlier tick, after a genuinely DELAYED fill (an order that stays
        # pending/accepted for one or more ticks before it fills) --
        # replacing Task 79E-R1's narrower "did _handle_entry just create
        # this position on THIS tick" rule, which only protected the
        # same-tick case and left a delayed fill's own first-eligible bar
        # unprotected. A rehydrated (restart-recovered) position is,
        # symmetrically, ALREADY open before the very first post-restart
        # tick, so it is correctly fully eligible from that first tick.
        already_filled_before_tick = {
            symbol for symbol in bars if self.lifecycle._open_position_for(symbol) is not None
        }
        for symbol, bar in bars.items():
            await self.feed_bar(symbol, bar)
        for signal in await self.flush_and_collect():
            self._handle_entry(signal)
        for symbol, bar in bars.items():
            self._check_exit(symbol, bar, skip_price_check=symbol not in already_filled_before_tick)
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
