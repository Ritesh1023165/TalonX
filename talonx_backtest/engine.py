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
"""
from __future__ import annotations

import itertools
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
from talonx_quant.indicators import compute_daily_pivots, compute_htf_trend, compute_indicators
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


class BacktestEngine:
    """Single-pass, multi-symbol chronological replay. Construct once per
    backtest run (state is not reusable across runs -- create a new
    instance)."""

    def __init__(self, config: BacktestConfig | None = None):
        self.config = config or BacktestConfig()
        qc = self.config.quant_config

        self.buffer = RollingBarBuffer(qc.max_bars_per_symbol)
        self.buffer_htf = RollingBarBuffer(qc.htf_max_bars)
        self.htf_aggregator = HtfBarAggregator(qc.htf_bar_interval_minutes, rth_only=qc.rth_only_htf_sma)
        self.simulator = TradeSimulator(self.config.execution)

        self._cooldown_until: dict[str, pd.Timestamp] = {}
        self._loss_lockout_until: dict[str, pd.Timestamp] = {}
        self._pending_entry: dict[str, _PendingEntry] = {}
        self._flattened_dates: set = set()

        self.trades: list[Trade] = []
        self.rejections: list[RejectionRecord] = []
        # Every raw candidate evaluate_signals() produces, BEFORE any
        # gate -- one dict per signal, in generation order. Exists
        # purely for tests (look-ahead-bias proof, live/backtest
        # regression fixture): a candidate's own reported price/RSI/R:R
        # here must never depend on a bar with a LATER timestamp than
        # the candidate itself. Not used by the engine's own control
        # flow.
        self.signal_log: list[dict] = []
        self.signals_generated = 0
        self.signals_published = 0
        self._last_close: dict[str, float] = {}
        self._last_timestamp: dict[str, pd.Timestamp] = {}

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """`df`: normalized columns [timestamp, symbol, open, high, low,
        close, volume], tz-aware UTC (see talonx_backtest.data). Must
        already be sorted/deduped -- this engine does not repair data
        (see data.sort_and_dedupe); pass through check_dataset_quality
        first."""
        if df.empty:
            return BacktestResult(
                trades=[], rejections=[], signals_generated=0, signals_published=0,
                config=self.config, start=None, end=None, symbols=[],
            )

        ordered = df.sort_values(["timestamp", "symbol"], kind="mergesort")
        symbols = sorted(ordered["symbol"].unique().tolist())

        for timestamp, group in ordered.groupby("timestamp", sort=True):
            candidates: list[QuantSignal] = []
            for _, row in group.iterrows():
                self._process_symbol_bar(row["symbol"], timestamp, row, candidates)
            if candidates:
                self._flush_throttle(candidates, timestamp)
            if self.config.eod_flatten_enabled:
                self._maybe_eod_flatten(timestamp)

        self._finalize_at_data_end()

        return BacktestResult(
            trades=self.trades,
            rejections=self.rejections,
            signals_generated=self.signals_generated,
            signals_published=self.signals_published,
            config=self.config,
            start=ordered["timestamp"].iloc[0],
            end=ordered["timestamp"].iloc[-1],
            symbols=symbols,
        )

    # ------------------------------------------------------------------
    # Per-bar processing
    # ------------------------------------------------------------------

    def _process_symbol_bar(self, symbol: str, timestamp: pd.Timestamp, row, candidates: list[QuantSignal]) -> None:
        symbol = symbol.upper()

        # --- Trade lifecycle: entry / exit checks come BEFORE this bar's
        # data feeds indicator computation, matching "a signal published
        # off bar N enters at bar N+1's open, then bar N+1's own
        # high/low can immediately close it" (spec section 6).
        pending = self._pending_entry.pop(symbol, None)
        if pending is not None and (self.config.allow_overlapping_trades or not self.simulator.has_open(symbol)):
            self.simulator.open_position(
                pending.signal, timestamp, float(row["open"]),
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
        self._last_close[symbol] = float(row["close"])
        self._last_timestamp[symbol] = timestamp

        qc = self.config.quant_config
        df_1m = self.buffer.get_dataframe(symbol)
        snapshot = compute_indicators(df_1m, qc)
        if snapshot is None:
            return  # warm-up -- identical "insufficient data -> no signal" posture as live

        if _fails_min_volatility(snapshot, qc):
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

            self.signals_published += 1
            self._arm_cooldown(symbol, timestamp)
            self._pending_entry[symbol] = _PendingEntry(signal=revalidated, opportunity_score=score)

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
