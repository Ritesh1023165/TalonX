"""
talonx_backtest.engine
---------------------------
Historical replay engine. This is the one module in talonx_backtest that
actually drives talonx_quant's live strategy code end to end -- every
other module here only consumes what this one produces.

Architecture (Requirement 4 -- "reuse the same strategy.py, do not
duplicate formulas"):

    historical 1-min OHLCV (talonx_backtest.data)
        |
    RollingBarBuffer (talonx_quant.buffer)        <- SAME class live uses
    HtfBarAggregator (talonx_quant.aggregation)    <- SAME class live uses
        |
    compute_indicators / compute_htf_trend /
    compute_daily_pivots (talonx_quant.indicators) <- SAME functions
        |
    evaluate_signals (talonx_quant.strategy)       <- SAME function
        |
    gate pipeline (talonx_quant.consumer's own free functions:
    _fails_min_volatility, _trend_gate_applicable, _opportunity_score,
    _partition, _GATE_NAMES -- imported, not reimplemented)
        |
    TradeSimulator (talonx_backtest.execution)     <- backtest-only:
                                                       stop/target/slippage

Nothing in this module recomputes RSI/MACD/ATR/confluence/R:R/trend or
re-derives a threshold -- it only supplies historical bars where live
supplies live ticks, and replaces Redis-backed cooldown/loss-lockout
state with an in-memory dict keyed off the bar's own timestamp (backtest
has no wall clock; the historical timestamp IS the clock).

Look-ahead safety (Requirement 3): a historical 1-minute OHLCV row is,
by construction, already a CLOSED candle the instant it's read (unlike a
live tick stream, there is no partial-bar state for it to represent).
Evaluating strategy.py the moment a row is appended to the buffer is
therefore equivalent to live's "wait for the next tick to close this
bar" rule -- both evaluate using only the data available through that
bar's own close, never anything from a later bar. See tests/
test_backtest_lookahead.py for a fixture that proves this directly (a
signal's own reported price/indicators never depend on a bar with a
LATER timestamp than the signal itself).

Known, deliberate divergences from live (documented, not hidden -- see
the final report's "Known Limitations" section):
  - GLOBAL_RISK_DEGRADED and the UK 08:00-22:00 Mon-Fri operating window
    are Redis-health/deployment-schedule concerns, not strategy rules --
    neither is simulated here.
  - Pre-market liquidity/news-catalyst gates are fail-closed exactly as
    live is when no quote/news feed is available (see
    _clears_premarket_liquidity/_has_recent_news below) -- since this
    engine has no quote/news feed by default, EVERY pre-market candidate
    is dropped, matching live's own fail-closed posture under a
    permanently-missing-data condition, not a special backtest-only
    relaxation.
  - Throttle fidelity is LIMITED: 1-minute OHLCV cannot resolve
    sub-minute (15s) timing, so every candidate whose CLOSED bar shares
    one historical minute is treated as one throttle window and flushed
    immediately, rather than continuously every 15s. See
    BacktestConfig.throttle_fidelity.

Position lifecycle -- LONG_ONLY (Task 24/25A canonical requirement,
corrected 2026-08-20; previously this engine opened a genuine short on
every BEARISH signal, contradicting live/paper's own semantics -- see
results/task24_requirements_parity_audit/long_short_flow.md and
results/task25a_long_only_parity_fix/task25a_summary.md):
    FLAT   + qualifying BULLISH -> schedule a LONG entry (_pending_entry),
             filled at the next bar's open, same as before.
    LONG   + qualifying BULLISH -> no additional/overlapping position
             (unless allow_overlapping_trades) -- unchanged.
    FLAT   + qualifying BEARISH -> no position opened. Recorded as
             "NO_ACTIVE_POSITION", the same reason talonx_paper.
             decide_trade uses for the identical case -- never silently
             dropped.
    LONG   + qualifying BEARISH -> schedules an alert-driven exit
             (_pending_exit), filled at the next bar's open (same
             next-bar convention as an entry, to avoid lookahead on the
             exit price), exit_reason="SIGNAL_EXIT" -- distinct from
             STOP/TARGET/END_OF_SESSION/DATA_END. Mirrors talonx_paper's
             CONFIRMED_BEARISH/CONTRADICTED -> SELL.
This engine never opens a short; TradeSimulator.open_position raises if
ever handed a non-BULLISH signal, as a fail-closed invariant check.
"""
from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from talonx_quant.aggregation import HtfBarAggregator
from talonx_quant.buffer import RollingBarBuffer
from talonx_quant.config import QuantConfig
from talonx_quant.consumer import (
    _GATE_NAMES,
    _fails_min_volatility,
    _opportunity_score,
    _partition,
    _trend_gate_applicable,
)
from talonx_quant.indicators import (
    VolatilityRegimeSnapshot, compute_daily_pivots, compute_htf_trend, compute_indicators,
    compute_volatility_regime,
)
from talonx_quant.schemas import QuantSignal, SignalDirection
from talonx_quant.session import get_entry_blackout, get_session
from talonx_quant.strategy import calculate_trade_geometry, evaluate_signals

from talonx_backtest.execution import ExecutionConfig, TradeSimulator
from talonx_backtest.portfolio import Trade

_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class BacktestConfig:
    quant_config: QuantConfig = field(default_factory=QuantConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    # EOD flatten (mirrors talonx_paper's real 15:50 ET daily sweep --
    # see talonx_paper/config.py's eod_flatten_hour_et/minute_et) -- an
    # open position is force-closed at this ET wall-clock time each
    # trading day, exit_reason=END_OF_SESSION, rather than being held
    # overnight. Disable to let trades run until stop/target/data end
    # only.
    eod_flatten_enabled: bool = True
    eod_flatten_hour_et: int = 15
    eod_flatten_minute_et: int = 50

    # One open simulated trade per symbol at a time by default (no
    # pyramiding) -- a signal published while that symbol already has an
    # open trade is still counted as PUBLISHED (cooldown is still armed,
    # matching live: talonx_quant has no concept of "position already
    # open", that's talonx_paper's job) but is not entered; see
    # SKIPPED_POSITION_OPEN in engine.RejectionRecord.
    allow_overlapping_trades: bool = False

    # Documentation-only field (spec section 16): NOT a behavior toggle.
    # 1-minute OHLCV cannot resolve config.quant_config.throttle_window_seconds
    # (15s default); every candidate sharing one historical bar-close
    # minute is ranked and flushed as a single throttle window instead of
    # continuously. Surfaced on BacktestResult/the report so this
    # limitation is never silently invisible to a reader of the results.
    throttle_fidelity: str = "LIMITED (flushed once per 1-minute bar-close, not continuously every throttle_window_seconds)"


@dataclass
class _PendingEntry:
    """A published signal awaiting execution at its symbol's next bar --
    carries the opportunity score it was ranked/published with alongside
    the signal itself (QuantSignal is a pydantic model with no such
    field of its own, and this is a backtest-only bookkeeping value, not
    part of the live wire contract)."""

    signal: QuantSignal
    opportunity_score: float


@dataclass
class _PendingExit:
    """A published BEARISH/CONTRADICTED signal awaiting execution at its
    symbol's next bar -- the LONG_ONLY-lifecycle counterpart of
    _PendingEntry (Task 25A). Carries only the triggering signal; unlike
    an entry, an alert-driven exit doesn't need an opportunity_score
    (it never competes for throttle ranking against other exits -- see
    _flush_throttle)."""

    signal: QuantSignal


@dataclass
class RejectionRecord:
    ticker: str
    reason: str
    count: int
    timestamp: pd.Timestamp


@dataclass
class BacktestResult:
    trades: list[Trade]
    rejections: list[RejectionRecord]
    signals_generated: int
    signals_published: int
    config: BacktestConfig
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    symbols: list[str]
    bars_processed: int = 0
    # Research telemetry (Task 10) -- always empty unless BacktestEngine
    # was constructed with research_telemetry=True; see that flag's own
    # docstring. Purely observational, never consulted by any gate/
    # decision, so a caller that ignores these two fields sees identical
    # behavior/artifacts to before this feature existed.
    volatility_telemetry: list[dict] = field(default_factory=list)
    candidate_telemetry: list[dict] = field(default_factory=list)


class BacktestEngine:
    """Single-pass, multi-symbol chronological replay. Construct once per
    backtest run (state is not reusable across runs -- create a new
    instance)."""

    def __init__(self, config: BacktestConfig | None = None, research_telemetry: bool = False):
        """`research_telemetry` (Task 10, default False): opt-in capture
        of two OBSERVATIONAL-ONLY lists (volatility_telemetry,
        candidate_telemetry -- see their append sites below) for
        research into per-symbol gate behavior. Purely additive: every
        value captured is read from an object the gate pipeline already
        computed (IndicatorSnapshot, QuantSignal, _fails_min_volatility's
        own return value) -- nothing is recalculated with different
        logic, no gate/threshold/ordering changes, and the existing
        signal_log/trades/rejections outputs are completely untouched by
        this flag. When False (the default), neither list is ever
        appended to, so behavior and cost are identical to before this
        flag existed -- see
        tests/test_backtest_research_telemetry.py's parity test."""
        self.config = config or BacktestConfig()
        self.research_telemetry = research_telemetry
        qc = self.config.quant_config

        self.buffer = RollingBarBuffer(qc.max_bars_per_symbol)
        self.buffer_htf = RollingBarBuffer(qc.htf_max_bars)
        self.htf_aggregator = HtfBarAggregator(qc.htf_bar_interval_minutes, rth_only=qc.rth_only_htf_sma)
        # Task 40: multi-timeframe volatility REGIME state (observability
        # only -- see compute_volatility_regime's own docstring). The 15m
        # leg reuses buffer_htf/htf_aggregator above unchanged; this is
        # ONLY the new 60-minute leg, built from the exact same, already-
        # proven RollingBarBuffer/HtfBarAggregator classes -- deliberately
        # continuous (rth_only=False) per Task 39's session-policy design,
        # not a runtime-tunable knob.
        self.buffer_60m = RollingBarBuffer(qc.regime_60m_max_bars)
        self.aggregator_60m = HtfBarAggregator(qc.regime_60m_bar_interval_minutes, rth_only=False)
        self.simulator = TradeSimulator(self.config.execution)

        self._cooldown_until: dict[str, pd.Timestamp] = {}
        self._loss_lockout_until: dict[str, pd.Timestamp] = {}
        self._pending_entry: dict[str, _PendingEntry] = {}
        self._pending_exit: dict[str, _PendingExit] = {}
        self._flattened_dates: set = set()

        self.trades: list[Trade] = []
        self.rejections: list[RejectionRecord] = []
        # Every raw candidate evaluate_signals() produces, BEFORE any
        # gate -- one dict per signal, in generation order. Exists
        # purely for tests (look-ahead-bias proof, live/backtest
        # regression fixture): a candidate's own reported price/RSI/R:R
        # here must never depend on a bar with a LATER timestamp than
        # the candidate itself. Not used by the engine's own control
        # flow. UNCONDITIONAL (pre-dates research_telemetry) --
        # tests/test_backtest_regression.py and test_backtest_lookahead.py
        # assert exact equality against this list's dict shape, so it
        # must never be extended/changed; candidate_telemetry below is a
        # deliberately separate list for Task 10's richer fields instead.
        self.signal_log: list[dict] = []
        # Task 10 research telemetry -- see research_telemetry docstring
        # above. One row per bar with a valid indicator snapshot
        # (volatility_telemetry) / one row per raw candidate signal
        # (candidate_telemetry), only when research_telemetry=True.
        self.volatility_telemetry: list[dict] = []
        self.candidate_telemetry: list[dict] = []
        # Task 40: latest multi-timeframe VolatilityRegimeSnapshot per
        # symbol (observability -- never consulted by any gate/decision).
        # regime_telemetry (one row per bar with a valid 1-min snapshot,
        # same population as volatility_telemetry) is captured ONLY when
        # research_telemetry=True, matching that flag's existing
        # observational-only convention.
        self.volatility_regime_snapshots: dict[str, VolatilityRegimeSnapshot] = {}
        self.regime_telemetry: list[dict] = []
        self.signals_generated = 0
        self.signals_published = 0
        self.bars_processed = 0
        # Task 35 fallback accounting -- counts the geometry_path actually
        # used at OPEN time (after fill-time reconciliation, the final,
        # definitive selection -- see _process_symbol_bar's pending-entry
        # branch), keyed by geometry_path, plus a fallback_reason
        # breakdown for the ATR_FALLBACK count. Descriptive counters only,
        # not a gate or a tuning metric.
        self.geometry_path_counts: dict[str, int] = {}
        self.fallback_reason_counts: dict[str, int] = {}
        self._last_close: dict[str, float] = {}
        self._last_timestamp: dict[str, pd.Timestamp] = {}

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    def run(
        self,
        df: pd.DataFrame,
        progress_callback: Callable[[int, int], None] | None = None,
        progress_interval_seconds: float = 2.0,
    ) -> BacktestResult:
        """`df`: normalized columns [timestamp, symbol, open, high, low,
        close, volume], tz-aware UTC (see talonx_backtest.data). Must
        already be sorted/deduped -- this engine does not repair data
        (see data.sort_and_dedupe); pass through check_dataset_quality
        first.

        `progress_callback`, if given, is called as `callback(bars_done,
        bars_total)` -- throttled to at most once every
        `progress_interval_seconds` of wall-clock time (compute_indicators
        recomputing indicators over the buffer on every bar makes a full
        run on months of data genuinely slow -- see docs/backtesting.md's
        "Where to get historical 1-minute OHLCV data" section -- so a
        run with no feedback at all is easy to mistake for hung). Always
        called at least once at completion (bars_done == bars_total),
        even for a run so fast the interval never elapses. A None
        callback (the default) costs nothing extra -- no timing calls,
        no branches taken in the hot per-bar loop beyond the None check."""
        if df.empty:
            return BacktestResult(
                trades=[], rejections=[], signals_generated=0, signals_published=0,
                config=self.config, start=None, end=None, symbols=[],
            )

        ordered = df.sort_values(["timestamp", "symbol"], kind="mergesort")
        symbols = sorted(ordered["symbol"].unique().tolist())
        total_bars = len(ordered)
        last_report = time.monotonic()

        for timestamp, group in ordered.groupby("timestamp", sort=True):
            candidates: list[QuantSignal] = []
            for _, row in group.iterrows():
                self._process_symbol_bar(row["symbol"], timestamp, row, candidates)
            if candidates:
                self._flush_throttle(candidates, timestamp)
            if self.config.eod_flatten_enabled:
                self._maybe_eod_flatten(timestamp)

            if progress_callback is not None:
                now = time.monotonic()
                if now - last_report >= progress_interval_seconds:
                    progress_callback(self.bars_processed, total_bars)
                    last_report = now

        self._finalize_at_data_end()

        if progress_callback is not None:
            progress_callback(self.bars_processed, total_bars)  # unconditional final report -- always reaches 100%

        return BacktestResult(
            trades=self.trades,
            rejections=self.rejections,
            signals_generated=self.signals_generated,
            signals_published=self.signals_published,
            config=self.config,
            start=ordered["timestamp"].iloc[0],
            end=ordered["timestamp"].iloc[-1],
            symbols=symbols,
            bars_processed=self.bars_processed,
            volatility_telemetry=self.volatility_telemetry,
            candidate_telemetry=self.candidate_telemetry,
        )

    # ------------------------------------------------------------------
    # Per-bar processing
    # ------------------------------------------------------------------

    def _process_symbol_bar(self, symbol: str, timestamp: pd.Timestamp, row, candidates: list[QuantSignal]) -> None:
        symbol = symbol.upper()
        self.bars_processed += 1

        # --- Trade lifecycle: entry / exit checks come BEFORE this bar's
        # data feeds indicator computation, matching "a signal published
        # off bar N enters at bar N+1's open, then bar N+1's own
        # high/low can immediately close it" (spec section 6). LONG_ONLY
        # lifecycle (Task 25A): a pending SIGNAL_EXIT (from a BEARISH/
        # CONTRADICTED candidate scheduled while long) is resolved
        # FIRST, at this bar's open, before any new entry -- an exit
        # frees the symbol up for a same-bar re-entry, never the reverse.
        pending_exit = self._pending_exit.pop(symbol, None)
        if pending_exit is not None and self.simulator.has_open(symbol):
            fill_price = float(row["open"])
            trade = self.simulator.close_on_signal_exit(symbol, timestamp, fill_price, pending_exit.signal)
            if trade is not None:
                self.trades.append(trade)
                self._maybe_arm_loss_lockout(symbol, trade, timestamp)
        elif pending_exit is not None:
            # Something else (EOD flatten, most commonly) already closed
            # this symbol between scheduling and fill time -- nothing to
            # exit. Never silently dropped, same reason talonx_paper
            # uses for the identical "no active position" case.
            self._reject(symbol, "NO_ACTIVE_POSITION", 1, timestamp)

        pending = self._pending_entry.pop(symbol, None)
        if pending is not None:
            local_date = timestamp.astimezone(_ET).date()
            if local_date in self._flattened_dates:
                # Task 24 finding: the once-per-day EOD-flatten guard
                # does not by itself prevent a NEW position from opening
                # after that day's flatten checkpoint has already run.
                # Task 25A closes that gap explicitly: no new entry may
                # open for a date once it has been flattened.
                self._reject(symbol, "POST_EOD_FLATTEN_NO_NEW_ENTRY", 1, timestamp)
            elif self.config.allow_overlapping_trades or not self.simulator.has_open(symbol):
                fill_price = float(row["open"])
                fill_signal = self._finalize_fill_geometry(pending.signal, fill_price, timestamp)
                if fill_signal is not None:
                    # Task 35 fallback accounting -- the geometry actually
                    # opened with, after fill-time reconciliation (the
                    # final, definitive selection for this trade).
                    if fill_signal.direction == SignalDirection.BULLISH and fill_signal.geometry_path:
                        self.geometry_path_counts[fill_signal.geometry_path] = (
                            self.geometry_path_counts.get(fill_signal.geometry_path, 0) + 1
                        )
                        if fill_signal.fallback_reason:
                            self.fallback_reason_counts[fill_signal.fallback_reason] = (
                                self.fallback_reason_counts.get(fill_signal.fallback_reason, 0) + 1
                            )
                    self.simulator.open_position(
                        fill_signal, timestamp, fill_price,
                        opportunity_score=pending.opportunity_score,
                    )
                    trade = self.simulator.check_exit(symbol, timestamp, float(row["high"]), float(row["low"]))
                    if trade is not None:
                        self.trades.append(trade)
                        self._maybe_arm_loss_lockout(symbol, trade, timestamp)
        elif self.simulator.has_open(symbol):
            trade = self.simulator.check_exit(symbol, timestamp, float(row["high"]), float(row["low"]))
            if trade is not None:
                self.trades.append(trade)
                self._maybe_arm_loss_lockout(symbol, trade, timestamp)

        # --- Feed the closed historical bar into the SAME buffers live uses.
        self.buffer.add_bar(
            symbol=symbol, timestamp=timestamp, open_=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]), volume=float(row["volume"]),
            session=get_session(timestamp),
        )
        finalized = self.htf_aggregator.update(
            symbol=symbol, timestamp=timestamp, open_=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]), volume=float(row["volume"]),
        )
        if finalized is not None:
            self.buffer_htf.add_bar(
                symbol=symbol, timestamp=finalized["timestamp"], open_=finalized["open"],
                high=finalized["high"], low=finalized["low"], close=finalized["close"],
                volume=finalized["volume"],
            )
        # Task 40: 60-minute regime leg -- identical pattern to the 15m
        # block immediately above, just a second HtfBarAggregator/
        # RollingBarBuffer pair at a different interval. No new bucketing
        # logic.
        finalized_60m = self.aggregator_60m.update(
            symbol=symbol, timestamp=timestamp, open_=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]), volume=float(row["volume"]),
        )
        if finalized_60m is not None:
            self.buffer_60m.add_bar(
                symbol=symbol, timestamp=finalized_60m["timestamp"], open_=finalized_60m["open"],
                high=finalized_60m["high"], low=finalized_60m["low"], close=finalized_60m["close"],
                volume=finalized_60m["volume"],
            )
        self._last_close[symbol] = float(row["close"])
        self._last_timestamp[symbol] = timestamp

        qc = self.config.quant_config
        df_1m = self.buffer.get_dataframe(symbol)
        snapshot = compute_indicators(df_1m, qc)
        if snapshot is None:
            return  # warm-up -- identical "insufficient data -> no signal" posture as live

        # Task 40: regime snapshot computed for EVERY post-warm-up bar,
        # unconditionally -- deliberately BEFORE the volatility gate below
        # so it is available regardless of that gate's outcome (this is
        # observability state, not an eligibility input; see
        # compute_volatility_regime's docstring). Reuses buffer_htf's
        # dataframe exactly as compute_htf_trend/compute_daily_pivots
        # already do -- no new 15m read path.
        regime_snapshot = compute_volatility_regime(
            self.buffer_htf.get_dataframe(symbol), self.buffer_60m.get_dataframe(symbol),
            qc.atr_period, timestamp,
        )
        self.volatility_regime_snapshots[symbol] = regime_snapshot
        if self.research_telemetry:
            self.regime_telemetry.append({
                "timestamp": timestamp, "symbol": symbol,
                "atr_15m": regime_snapshot.atr_15m, "atr_pct_15m": regime_snapshot.atr_pct_15m,
                "ready_15m": regime_snapshot.ready_15m,
                "atr_60m": regime_snapshot.atr_60m, "atr_pct_60m": regime_snapshot.atr_pct_60m,
                "ready_60m": regime_snapshot.ready_60m,
            })

        fails_volatility = _fails_min_volatility(snapshot, qc)
        if self.research_telemetry:
            # Same formula _fails_min_volatility itself uses internally
            # (talonx_quant/consumer.py) -- copied for DISPLAY only, not
            # a second implementation the gate could diverge from; the
            # actual gate decision below still comes from
            # fails_volatility, the one value both this telemetry row
            # and the reject-or-continue branch share.
            atr_pct = (snapshot.atr / snapshot.price * 100) if (snapshot.atr is not None and snapshot.price) else None
            self.volatility_telemetry.append({
                "timestamp": timestamp, "symbol": symbol, "price": snapshot.price,
                "atr": snapshot.atr, "atr_pct": atr_pct,
                "volatility_threshold": qc.min_atr_pct, "passes_volatility": not fails_volatility,
            })
        if fails_volatility:
            self._reject(symbol, "LOW_VOLATILITY", 1, timestamp)
            return

        df_htf = self.buffer_htf.get_dataframe(symbol)
        htf_sma_200 = compute_htf_trend(df_htf, qc.htf_sma_period)
        daily_pivots = compute_daily_pivots(df_htf, snapshot.bar_timestamp)
        signals = evaluate_signals(symbol, snapshot, qc, htf_sma_200=htf_sma_200, daily_pivots=daily_pivots)
        if not signals:
            return
        self.signals_generated += len(signals)
        for s in signals:
            self.signal_log.append({
                "timestamp": timestamp, "ticker": symbol, "signal_type": s.signal_type.value,
                "direction": s.direction.value, "price": s.price, "rsi": s.rsi,
                "confluence_score": s.confluence_score, "risk_reward_ratio": s.risk_reward_ratio,
            })
        if self.research_telemetry:
            # Every raw candidate, same point in the pipeline as
            # signal_log above (before ANY gate) -- so rejected AND
            # eventually-published candidates are both represented.
            # Every field is read directly off the QuantSignal `s`
            # strategy.py already built; confluence_score is the
            # AGGREGATE 0-3 int strategy.py computes (its own
            # RSI-zone/MACD-cross/volume-threshold sub-conditions are
            # local, unexposed values inside _confluence_score -- not
            # reconstructed here, see docs/backtesting.md's Task 10
            # note). trend_aligned is the one genuinely-exposed
            # per-signal gate boolean (None when the trend gate doesn't
            # apply to this signal, not "failed" -- same meaning as
            # everywhere else it's used).
            for s in signals:
                self.candidate_telemetry.append({
                    "timestamp": timestamp, "symbol": symbol, "direction": s.direction.value,
                    "signal_type": s.signal_type.value, "session": s.session, "price": s.price,
                    "rsi": s.rsi, "macd": s.macd, "macd_signal_line": s.macd_signal_line,
                    "volume_surge_ratio": s.volume_surge_ratio,
                    "confluence_score": s.confluence_score, "risk_reward_ratio": s.risk_reward_ratio,
                    "trend_component": s.trend_aligned,
                })

        # US Market Closed Session Rejection (Task 24 P1 / Task 25A parity
        # fix): live's consumer.py rejects a bar whose session tag is
        # "closed" before any other gate (matching the 2026-08-18
        # correctness fix there) -- this engine had no equivalent check
        # at all, so a dataset containing closed-session rows could sail
        # straight through every downstream gate. Same position in the
        # pipeline as live (right after evaluate_signals, before the
        # blackout gates); same "check signals[0], they all share one
        # session tag" shortcut live uses.
        if signals and signals[0].session == "closed":
            self._reject(symbol, "US_MARKET_SESSION_CLOSED", len(signals), timestamp)
            return

        blackout = get_entry_blackout(snapshot.bar_timestamp)
        if blackout == "opening":
            self._reject(symbol, "OPENING_BLACKOUT", len(signals), timestamp)
            return
        if blackout == "closing":
            signals, dropped = _partition(signals, lambda s: s.direction != SignalDirection.BULLISH)
            if dropped:
                self._reject(symbol, "CLOSING_BLACKOUT", len(dropped), timestamp)
            if not signals:
                return

        if self._is_loss_locked_out(symbol, timestamp):
            self._reject(symbol, "LOSS_LOCKOUT", len(signals), timestamp)
            return

        if self._is_on_cooldown(symbol, timestamp):
            self._reject(symbol, "COOLDOWN", len(signals), timestamp)
            return

        qualifying = [s for s in signals if (s.confluence_score or 0) >= qc.confluence_score_min]
        if not qualifying:
            self._reject(symbol, "LOW_CONFLUENCE", len(signals), timestamp)
            return

        survivors, dropped_rr = _partition(
            qualifying, lambda s: s.risk_reward_ratio is not None and s.risk_reward_ratio >= qc.min_risk_reward_ratio,
        )
        if dropped_rr:
            self._reject(symbol, "LOW_RISK_REWARD", len(dropped_rr), timestamp)
        if not survivors:
            return

        survivors, dropped_htf = _partition(
            survivors, lambda s: not (_trend_gate_applicable(s, qc) and s.htf_sma_200 is None)
        )
        if dropped_htf:
            self._reject(symbol, "HTF_DATA_UNAVAILABLE", len(dropped_htf), timestamp)
        if not survivors:
            return

        survivors, dropped_trend = _partition(survivors, lambda s: s.trend_aligned is not False)
        if dropped_trend:
            self._reject(symbol, "TREND_GATE", len(dropped_trend), timestamp)
        if not survivors:
            return

        # Pre-market liquidity / news-catalyst gates: fail-closed, same
        # as live when no quote/news feed exists (see module docstring)
        # -- this engine carries neither, so every pre-market candidate
        # is dropped here, not a backtest-only relaxation.
        survivors, dropped_premarket = _partition(survivors, lambda s: s.session != "pre_market")
        if dropped_premarket:
            self._reject(symbol, "PREMARKET_LIQUIDITY", len(dropped_premarket), timestamp)
        if not survivors:
            return

        candidates.extend(survivors)

    # ------------------------------------------------------------------
    # Cooldown / loss-lockout (virtual clock = bar timestamp, not wall time)
    # ------------------------------------------------------------------

    def _is_on_cooldown(self, symbol: str, now: pd.Timestamp) -> bool:
        expiry = self._cooldown_until.get(symbol)
        return expiry is not None and now < expiry

    def _arm_cooldown(self, symbol: str, now: pd.Timestamp) -> None:
        self._cooldown_until[symbol] = now + pd.Timedelta(seconds=self.config.quant_config.cooldown_seconds)

    def _is_loss_locked_out(self, symbol: str, now: pd.Timestamp) -> bool:
        expiry = self._loss_lockout_until.get(symbol)
        return expiry is not None and now < expiry

    def _arm_loss_lockout(self, symbol: str, now: pd.Timestamp) -> None:
        self._loss_lockout_until[symbol] = now + pd.Timedelta(seconds=self.config.quant_config.loss_lockout_seconds)

    # ------------------------------------------------------------------
    # Throttle (spec section 16 -- LIMITED fidelity, see class docstring)
    # ------------------------------------------------------------------

    def _flush_throttle(self, candidates: list[QuantSignal], timestamp: pd.Timestamp) -> None:
        qc = self.config.quant_config
        scored = [(s, _opportunity_score(s, qc)) for s in candidates]
        scored.sort(key=lambda pair: pair[1], reverse=True)

        released = scored[: qc.throttle_max_signals]
        dropped = scored[qc.throttle_max_signals :]

        for signal, score in released:
            symbol = signal.ticker.upper()
            if self._is_on_cooldown(symbol, timestamp):
                self._reject(symbol, "COOLDOWN", 1, timestamp)
                continue

            revalidated = self._revalidate(signal, timestamp)
            if revalidated is None:
                continue

            # Publication itself (and the cooldown it arms) happens
            # regardless of direction, matching live's _publish_signal --
            # talonx_quant has no concept of position state, so it
            # publishes a fully gate-checked BEARISH signal exactly the
            # same way it publishes a BULLISH one. What differs is what
            # a LONG_ONLY consumer does with it next (Task 24/25A): a
            # BULLISH signal always schedules an entry; a BEARISH one
            # only schedules an exit if a long is currently open, and is
            # otherwise recorded as NO_ACTIVE_POSITION -- never queued
            # as a new (short) position the way this engine used to.
            self.signals_published += 1
            self._arm_cooldown(symbol, timestamp)

            if revalidated.direction == SignalDirection.BULLISH:
                self._pending_entry[symbol] = _PendingEntry(signal=revalidated, opportunity_score=score)
            elif self.simulator.has_open(symbol):
                self._pending_exit[symbol] = _PendingExit(signal=revalidated)
            else:
                self._reject(symbol, "NO_ACTIVE_POSITION", 1, timestamp)

        if dropped:
            by_ticker: dict[str, int] = {}
            for signal, _ in dropped:
                by_ticker[signal.ticker.upper()] = by_ticker.get(signal.ticker.upper(), 0) + 1
            for ticker, count in by_ticker.items():
                self._reject(ticker, "THROTTLE", count, timestamp)

    def _revalidate(self, signal: QuantSignal, now: pd.Timestamp) -> QuantSignal | None:
        """Dynamic R:R Revalidation, reused conceptually from
        consumer._revalidate_candidate -- re-derives the FULL trade
        geometry via strategy.calculate_trade_geometry (the same
        function live revalidation uses) against the latest buffered
        close before the candidate is allowed to publish. Age is
        effectively 0 here (flush happens in the same historical minute
        the candidate was generated in -- see the throttle-fidelity
        note), so this mostly exercises the geometry re-check, not the
        staleness one; still run for parity and because a future,
        finer-resolution data source would make the age check meaningful
        again."""
        qc = self.config.quant_config
        symbol = signal.ticker.upper()

        age_seconds = 0.0  # see docstring -- flush is same-minute in this engine
        if age_seconds > qc.max_candidate_age_seconds:
            self._reject(symbol, "EXPIRED_IN_THROTTLE_QUEUE", 1, now)
            return None

        current_price = self._last_close.get(symbol)
        if current_price is None or signal.atr is None or signal.pivot_resistance is None or signal.pivot_support is None:
            self._reject(symbol, "FINAL_REVALIDATION_DATA_UNAVAILABLE", 1, now)
            return None

        geometry = calculate_trade_geometry(
            current_price, signal.atr, signal.direction, signal.pivot_resistance, signal.pivot_support, qc,
        )
        if geometry is None or geometry.risk_reward_ratio is None:
            self._reject(symbol, "RR_DEGRADED_DURING_THROTTLE", 1, now)
            return None
        if geometry.risk_reward_ratio < qc.min_risk_reward_ratio:
            self._reject(symbol, "RR_DEGRADED_DURING_THROTTLE", 1, now)
            return None

        return signal.model_copy(update={
            "price": current_price,
            "stop_price": geometry.stop_price,
            "target_price": geometry.target_price,
            "risk_reward_ratio": geometry.risk_reward_ratio,
            "signal_age_ms": age_seconds * 1000.0,
            # Task 35: keep geometry_path/fallback_reason/structural_level
            # in lockstep with the stop/target/ratio re-derived above.
            "geometry_path": geometry.geometry_path,
            "fallback_reason": geometry.fallback_reason,
            "structural_level": geometry.structural_level,
            "structural_level_type": geometry.structural_level_type,
        })

    def _finalize_fill_geometry(self, signal: QuantSignal, fill_price: float, now: pd.Timestamp) -> QuantSignal | None:
        """2026-08-19 correctness fix (Task 13 defect): _revalidate above
        re-derives stop_price/target_price against the bar-close price at
        THROTTLE-FLUSH time, but the actual fill happens a full bar later,
        at bar N+1's OPEN (see _process_symbol_bar's own docstring on the
        "signal at bar N -> entry at bar N+1's open" convention). Between
        those two prices, a real gap can leave the revalidated stop_price
        on the WRONG SIDE of the price the position actually fills at --
        execution.py's risk calc uses abs(entry_price_raw - stop_price),
        which silently tolerates this rather than rejecting it, so the
        resulting "STOP" exit was actually a favorable move mislabeled as
        a loss-side exit (always net_R=+1.0 exactly -- confirmed via Task
        13's audit against 6 real historical trades).

        Deliberately NARROW: only recomputes when the pre-existing
        geometry has ALREADY been invalidated by the fill price (fails the
        required stop < entry < target / target < entry < stop invariant).
        The far more common case -- fill price differs slightly from the
        revalidation price but stop/target still correctly bracket it --
        is left completely untouched, preserving the existing, intentional
        "execution_rr can legitimately diverge from screening_rr due to
        normal fill-price drift" behavior (see
        tests/test_backtest_execution.py::
        test_execution_rr_uses_the_real_fill_price_not_the_screening_reference_price).

        When recomputation IS needed, this reuses calculate_trade_geometry
        (the exact same function _revalidate already calls) anchored to the
        REAL fill price, and applies the SAME min_risk_reward_ratio gate a
        fresh candidate would have to clear -- rejecting (never silently
        keeping invalid geometry) if the gap is severe enough that even a
        freshly-anchored trade wouldn't qualify. screening_rr (signal.
        risk_reward_ratio) is deliberately NEVER overwritten here -- it is
        documented (execution.py) as the strategy's gate-time R:R, never
        recalculated against the fill; only the actual protective
        stop/target levels the position trades against are re-anchored.
        Returns None (and records a GEOMETRY_INVALIDATED_AT_FILL rejection)
        if no valid geometry exists even at the real fill price."""
        if signal.stop_price is None or signal.target_price is None:
            return signal  # nothing to validate against -- unchanged, pre-existing behavior (see test_execution_rr_is_none_when_stop_price_is_missing)

        if signal.direction == SignalDirection.BULLISH:
            geometry_valid = signal.stop_price < fill_price < signal.target_price
        else:
            geometry_valid = signal.target_price < fill_price < signal.stop_price
        if geometry_valid:
            return signal

        qc = self.config.quant_config
        geometry = calculate_trade_geometry(
            fill_price, signal.atr, signal.direction, signal.pivot_resistance, signal.pivot_support, qc,
        )
        if geometry is None or geometry.risk_reward_ratio is None or geometry.risk_reward_ratio < qc.min_risk_reward_ratio:
            self._reject(signal.ticker.upper(), "GEOMETRY_INVALIDATED_AT_FILL", 1, now)
            return None
        return signal.model_copy(update={
            "stop_price": geometry.stop_price, "target_price": geometry.target_price,
            # Task 35: this recompute path is the ACTUAL fill-anchored
            # geometry -- must overwrite the screening-time geometry_path/
            # fallback_reason too, since re-anchoring to the real fill
            # price can select a different path than screening did (e.g.
            # a gap that puts price below where structure was valid at
            # screening now makes it invalid, or vice versa).
            "geometry_path": geometry.geometry_path, "fallback_reason": geometry.fallback_reason,
            "structural_level": geometry.structural_level, "structural_level_type": geometry.structural_level_type,
        })

    # ------------------------------------------------------------------
    # EOD flatten / data-end finalization
    # ------------------------------------------------------------------

    def _maybe_eod_flatten(self, timestamp: pd.Timestamp) -> None:
        local = timestamp.astimezone(_ET)
        target = local.replace(
            hour=self.config.eod_flatten_hour_et, minute=self.config.eod_flatten_minute_et,
            second=0, microsecond=0,
        )
        if local < target:
            return
        date_key = local.date()
        if date_key in self._flattened_dates:
            return
        self._flattened_dates.add(date_key)

        for symbol in list(self.simulator.open_symbols()):
            price = self._last_close.get(symbol)
            if price is None:
                continue
            trade = self.simulator.force_close(symbol, timestamp, price, "END_OF_SESSION")
            if trade is not None:
                self.trades.append(trade)
                self._maybe_arm_loss_lockout(symbol, trade, timestamp)

    def _finalize_at_data_end(self) -> None:
        for symbol in list(self.simulator.open_symbols()):
            price = self._last_close.get(symbol)
            timestamp = self._last_timestamp.get(symbol)
            if price is None or timestamp is None:
                continue
            trade = self.simulator.force_close(symbol, timestamp, price, "DATA_END")
            if trade is not None:
                self.trades.append(trade)

    def _maybe_arm_loss_lockout(self, symbol: str, trade: Trade, now: pd.Timestamp) -> None:
        if trade.net_pnl is not None and trade.net_pnl < 0:
            self._arm_loss_lockout(symbol, now)

    # ------------------------------------------------------------------

    def _reject(self, ticker: str, reason: str, count: int, timestamp: pd.Timestamp) -> None:
        self.rejections.append(RejectionRecord(ticker=ticker.upper(), reason=reason, count=count, timestamp=timestamp))
