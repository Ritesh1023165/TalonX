"""
talonx_quant.consumer
-------------------------
Async Redis Pub/Sub consumer: subscribes to talonx:market:stream, feeds
BAR events into the per-symbol rolling buffer, computes indicators, and
publishes any triggered QuantSignals to talonx:signals:quant. ALSO
subscribes to talonx:paper:trades (talonx_paper's execution feed) purely
to detect losing trades -- see the Post-Loss Lockout filter below.

Reconnects with backoff on connection loss -- a long-running listener
process should recover from a Redis restart/network blip on its own
rather than requiring a manual restart.

Filters sit between strategy.py's candidate signals and the actual
publish, on top of strategy.py's own edge-triggering/hysteresis/ATR-move
gate (the latter three all live IN strategy.py, upstream of everything
below):

  1. Post-Loss Lockout (Redis `loss_lockout:{TICKER}` key, TTL
     config.loss_lockout_seconds): a live paper-trading review found 3
     consecutive SMCI losses driving 93% of session losses -- the
     standard cooldown (below) reset in 20 minutes regardless of whether
     the closed trade won or lost, letting the engine repeatedly re-enter
     a stock that had just proven it was chopping/declining. This module
     subscribes to talonx_paper's own trade-execution channel and, on a
     SELL closing at a loss, locks that ticker out for LONGER than the
     standard cooldown -- 75 minutes by default. Only ever engages for a
     ticker with paper trading ENABLED (one with it off never publishes
     an execution, so it only ever sees the standard cooldown).
  2. Per-ticker cooldown (Redis `cooldown:{TICKER}` key, TTL
     config.cooldown_seconds): once ANY signal is accepted for a ticker,
     that ticker is locked out of producing further candidates -- of any
     signal_type -- until the cooldown expires. This is what stops e.g.
     an RSI+volume setup and a later, unrelated MACD cross on the same
     ticker from both alerting within a few minutes of each other.
  3. Confluence + risk/reward filters (strategy.py computes both,
     attached to every candidate signal): a candidate below
     config.confluence_score_min or config.min_risk_reward_ratio is
     dropped BEFORE the per-ticker cooldown is started -- a low-
     conviction candidate that never becomes a real signal must not
     still burn the ticker's cooldown slot and block a later, better one.
  4. Batch throttle (tumbling window, config.throttle_window_seconds):
     candidates that pass everything above are buffered, not published
     immediately. Every throttle_window_seconds, the buffer is ranked by
     (confluence_score, volume_surge_ratio) -- confluence first, volume
     surge as the tiebreaker -- and only the top config.throttle_max_signals
     are actually published; the rest are dropped. This means a signal
     can sit for up to throttle_window_seconds before it's published OR
     dropped -- a deliberate latency-for-quality tradeoff, not a bug.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from collections import Counter
from datetime import datetime, timezone

from pydantic import ValidationError

from talonx_quant.buffer import RollingBarBuffer
from talonx_quant.config import QuantConfig
from talonx_quant.indicators import compute_htf_trend, compute_indicators
from talonx_quant.schemas import (
    MarketTickEvent,
    NewsArticleIngestedEvent,
    PaperOrderType,
    PaperTradeExecution,
    QuantSignal,
    TickEventType,
)
from talonx_quant.store import QuantStateStore
from talonx_quant.strategy import evaluate_signals

logger = logging.getLogger("talonx_quant.consumer")

try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover - exercised only when dependency missing
    redis_asyncio = None


def _jittered_backoff(attempt: int, base: float, max_delay: float) -> float:
    raw = base * (2 ** (attempt - 1))
    capped = min(raw, max_delay)
    return capped * (0.5 + random.random())


def _partition(items: list, predicate) -> tuple[list, list]:
    """Splits `items` into (kept, dropped) by `predicate(item)`."""
    kept, dropped = [], []
    for item in items:
        (kept if predicate(item) else dropped).append(item)
    return kept, dropped


def _ensure_utc(dt: datetime) -> datetime:
    """Naive timestamps are assumed UTC, matching every wire timestamp
    convention elsewhere in this module -- avoids a naive/aware
    subtraction TypeError if an upstream event ever omits tzinfo."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def _incr_metric(client, stage: str, counter: str, amount: int = 1) -> None:
    """Stage-Gate Metric Funnel (Phase 2 requirement doc): atomic,
    per-UTC-day Redis counters at `metrics:{YYYY-MM-DD}:{stage}:{counter}`,
    read by talonx_dispatch's Daily Funnel dashboard tab. Each module
    re-declares this same small helper locally rather than sharing one --
    same "no internal library between modules" convention this project
    uses everywhere else (schemas are re-declared too). TTL is set once,
    on the write that actually creates the key each day (new_value ==
    amount is a cheap proxy for "just created" -- fine for telemetry,
    where an occasional race double-setting the TTL is harmless), so a
    day's counters expire on their own after ~32 days rather than
    accumulating forever. Never raises -- a metrics-write failure must
    not affect signal evaluation."""
    if client is None or amount <= 0:
        return
    key = f"metrics:{datetime.now(timezone.utc):%Y-%m-%d}:{stage}:{counter}"
    try:
        new_value = await client.incrby(key, amount)
        if new_value == amount:
            await client.expire(key, 2764800)  # 32 days
    except Exception as exc:  # noqa: BLE001 -- telemetry must never break the pipeline
        logger.debug("Metric increment failed for %s: %s", key, exc)


class QuantScanner:
    def __init__(self, config: QuantConfig | None = None, store: QuantStateStore | None = None):
        self.config = config or QuantConfig()
        self.store = store
        self.buffer = RollingBarBuffer(self.config.max_bars_per_symbol)
        # 15-min 200 SMA higher-timeframe trend gate: a second, coarser
        # buffer incrementally aggregated from the same 1-min BAR events
        # (see _update_htf_buffer) -- only needs htf_sma_period+a few bars
        # of capacity, far cheaper than resampling the 1-min buffer.
        self.buffer_htf = RollingBarBuffer(self.config.htf_max_bars)
        self._htf_accumulators: dict[str, dict] = {}
        # Pre-market liquidity gate: latest QUOTE event per symbol
        # (bid, ask, timestamp) -- QUOTE events carry spread info the BAR
        # buffer above never sees (buffer.py only stores BAR-type events).
        self._latest_quotes: dict[str, tuple[float, float, datetime]] = {}
        # Pre-market news-catalyst gate: most recent NewsArticleIngestedEvent
        # timestamp seen per symbol -- only the recency matters, not the
        # article content, for the 4h-lookback check.
        self._last_news_seen: dict[str, datetime] = {}
        self._client = None
        self._stop_event = asyncio.Event()
        self._signals_published = 0
        self._bars_processed = 0
        self._signals_suppressed_cooldown = 0
        self._signals_suppressed_throttle = 0
        self._signals_suppressed_loss_lockout = 0
        self._signals_suppressed_low_confluence = 0
        self._signals_suppressed_low_risk_reward = 0
        self._signals_suppressed_trend_gate = 0
        self._signals_suppressed_premarket_liquidity = 0
        self._signals_suppressed_news_catalyst = 0
        # Candidates that cleared strategy.py's own filters AND the
        # per-ticker cooldown, waiting for the next throttle window flush.
        self._pending_candidates: list[QuantSignal] = []

    def stop(self) -> None:
        self._stop_event.set()

    @property
    def signals_published(self) -> int:
        return self._signals_published

    @property
    def signals_suppressed_cooldown(self) -> int:
        return self._signals_suppressed_cooldown

    @property
    def signals_suppressed_throttle(self) -> int:
        return self._signals_suppressed_throttle

    @property
    def signals_suppressed_loss_lockout(self) -> int:
        return self._signals_suppressed_loss_lockout

    @property
    def signals_suppressed_low_confluence(self) -> int:
        return self._signals_suppressed_low_confluence

    @property
    def signals_suppressed_low_risk_reward(self) -> int:
        return self._signals_suppressed_low_risk_reward

    @property
    def signals_suppressed_trend_gate(self) -> int:
        return self._signals_suppressed_trend_gate

    @property
    def signals_suppressed_premarket_liquidity(self) -> int:
        return self._signals_suppressed_premarket_liquidity

    @property
    def signals_suppressed_news_catalyst(self) -> int:
        return self._signals_suppressed_news_catalyst

    async def run(self) -> None:
        if redis_asyncio is None:
            raise ImportError(
                "The 'redis' package is required. Install it with: pip install redis"
            )

        self._load_buffers_from_store()

        attempt = 0
        while not self._stop_event.is_set():
            try:
                await self._connect_and_listen()
                return  # clean stop() was called
            except Exception as exc:  # noqa: BLE001 -- any connection/listen failure retries
                attempt += 1
                wait = _jittered_backoff(
                    attempt, self.config.reconnect_backoff_base_seconds,
                    self.config.reconnect_backoff_max_seconds,
                )
                logger.warning(
                    "Redis connection/listen error (%s); reconnecting in %.1fs (attempt %d)",
                    exc, wait, attempt,
                )
                await asyncio.sleep(wait)

    async def _connect_and_listen(self) -> None:
        self._client = redis_asyncio.from_url(
            self.config.redis_url,
            socket_connect_timeout=self.config.connect_timeout_seconds,
            socket_timeout=self.config.socket_timeout_seconds,
        )
        await self._client.ping()
        logger.info("Connected to Redis at %s", self.config.redis_url)

        pubsub = self._client.pubsub()
        await pubsub.subscribe(
            self.config.market_stream_channel,
            self.config.paper_trades_channel,
            self.config.news_events_channel,
        )
        logger.info(
            "Subscribed to %s, %s, and %s",
            self.config.market_stream_channel, self.config.paper_trades_channel, self.config.news_events_channel,
        )

        throttle_task = asyncio.create_task(self._throttle_flush_loop(), name="throttle_flush")
        checkpoint_task = asyncio.create_task(self._checkpoint_loop(), name="buffer_checkpoint")

        try:
            while not self._stop_event.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    continue  # normal: no message within this poll window
                await self._handle_message(message)
        finally:
            throttle_task.cancel()
            checkpoint_task.cancel()
            try:
                await throttle_task
            except asyncio.CancelledError:
                pass
            try:
                await checkpoint_task
            except asyncio.CancelledError:
                pass
            # Flush whatever's pending rather than silently losing it on
            # every stop/reconnect -- see _flush_throttle_window's own
            # ranking logic; a partial window still gets ranked fairly.
            await self._flush_throttle_window()
            # Final snapshot on a graceful stop -- the periodic loop above
            # only checkpoints every buffer_checkpoint_interval_seconds,
            # so without this a clean shutdown could still lose up to that
            # interval's worth of the most recent bars.
            self._checkpoint_all_buffers()
            await pubsub.unsubscribe(
                self.config.market_stream_channel,
                self.config.paper_trades_channel,
                self.config.news_events_channel,
            )
            await pubsub.aclose()
            await self._client.aclose()

    async def _throttle_flush_loop(self) -> None:
        """Ranks and releases self._pending_candidates every throttle_window_seconds."""
        try:
            while True:
                await asyncio.sleep(self.config.throttle_window_seconds)
                await self._flush_throttle_window()
        except asyncio.CancelledError:
            pass

    async def _checkpoint_loop(self) -> None:
        """Periodically snapshots both RollingBarBuffers to quant.db (see
        _checkpoint_all_buffers) -- bounds how much of the most recent
        buffered history a crash (as opposed to a graceful stop(), which
        gets one final checkpoint in _connect_and_listen's finally block)
        could lose to at most buffer_checkpoint_interval_seconds."""
        try:
            while True:
                await asyncio.sleep(self.config.buffer_checkpoint_interval_seconds)
                self._checkpoint_all_buffers()
        except asyncio.CancelledError:
            pass

    def _checkpoint_all_buffers(self) -> None:
        if self.store is None:
            return
        for symbol in self.buffer.known_symbols():
            bars = self.buffer.get_bars(symbol)
            if bars:
                self.store.checkpoint_buffer(symbol, "1m", bars)
        for symbol in self.buffer_htf.known_symbols():
            bars = self.buffer_htf.get_bars(symbol)
            if bars:
                self.store.checkpoint_buffer(symbol, "15m", bars)

    def _load_buffers_from_store(self) -> None:
        """Reloads both RollingBarBuffers from their last checkpoint --
        called once at the start of run(), before the connect/listen
        retry loop, so a restart doesn't force every symbol through a
        full re-warm-up from empty (min_bars_required=120 for the 1-min
        buffer, htf_sma_period=200 -- ~50 continuous hours -- for the HTF
        one). See config.py's buffer_reload_max_gap_seconds docstring for
        why the 1-min buffer is gap-gated and the HTF buffer isn't."""
        if self.store is None:
            return

        now = datetime.now(timezone.utc)
        for symbol in self.store.buffered_symbols("1m"):
            bars = self.store.load_buffer(symbol, "1m")
            if not bars:
                continue
            last_bar_at = _ensure_utc(datetime.fromisoformat(bars[-1]["timestamp"]))
            gap_seconds = (now - last_bar_at).total_seconds()
            if gap_seconds > self.config.buffer_reload_max_gap_seconds:
                logger.info(
                    "Skipping stale 1-min buffer reload for %s (last bar %.0fs old, over the %.0fs limit)",
                    symbol, gap_seconds, self.config.buffer_reload_max_gap_seconds,
                )
                continue
            for bar in bars:
                self.buffer.add_bar(
                    symbol=symbol, timestamp=datetime.fromisoformat(bar["timestamp"]),
                    open_=bar["open"], high=bar["high"], low=bar["low"],
                    close=bar["close"], volume=bar["volume"],
                )
            logger.info("Reloaded %d 1-min bar(s) for %s from checkpoint", len(bars), symbol)

        for symbol in self.store.buffered_symbols("15m"):
            bars = self.store.load_buffer(symbol, "15m")
            for bar in bars:
                self.buffer_htf.add_bar(
                    symbol=symbol, timestamp=datetime.fromisoformat(bar["timestamp"]),
                    open_=bar["open"], high=bar["high"], low=bar["low"],
                    close=bar["close"], volume=bar["volume"],
                )
            if bars:
                logger.info(
                    "Reloaded %d 15-min HTF bar(s) for %s from checkpoint (no gap limit)", len(bars), symbol,
                )

    async def _handle_message(self, message: dict) -> None:
        raw = message.get("data")
        if raw is None:
            return

        channel = message.get("channel")
        if isinstance(channel, bytes):
            channel = channel.decode()

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Dropping unparseable message on %s: %s", channel, exc)
            return

        if channel == self.config.paper_trades_channel:
            await self._handle_paper_trade(payload)
        elif channel == self.config.market_stream_channel:
            await self._handle_market_tick(payload)
        elif channel == self.config.news_events_channel:
            self._handle_news_event(payload)
        else:
            logger.warning("Dropping message on unexpected channel %s", channel)

    def _handle_news_event(self, payload: dict) -> None:
        """Pre-market news-catalyst gate's trigger -- tracks only the MOST
        RECENT article timestamp per ticker, not content (see
        NewsArticleIngestedEvent's docstring)."""
        try:
            event = NewsArticleIngestedEvent.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping invalid news event: %s", exc)
            return
        symbol = event.ticker.upper()
        published_at = _ensure_utc(event.published_at)
        seen = self._last_news_seen.get(symbol)
        if seen is None or published_at > seen:
            self._last_news_seen[symbol] = published_at

    async def _handle_paper_trade(self, payload: dict) -> None:
        """Post-Loss Lockout's trigger -- see this module's own docstring.
        Only a closed (SELL) trade carries realized_pnl_usd at all; a BUY
        execution is ignored here entirely."""
        try:
            execution = PaperTradeExecution.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping invalid paper trade execution: %s", exc)
            return

        if execution.order_type != PaperOrderType.SELL:
            return
        if execution.realized_pnl_usd is None or execution.realized_pnl_usd >= 0:
            return  # no loss -- the standard cooldown already covers this ticker

        logger.info(
            "Post-loss lockout: %s closed at a loss ($%.2f) -- locking out for %.0f minutes",
            execution.ticker, execution.realized_pnl_usd, self.config.loss_lockout_seconds / 60.0,
        )
        await self._start_loss_lockout(execution.ticker)

    def _clears_premarket_liquidity(self, signal: QuantSignal) -> bool:
        """Dollar volume + bid-ask spread, both fail-closed. The signal's
        own `.price` doubles as the dollar-volume gate's price input --
        dollar volume itself isn't carried on QuantSignal (an internal
        gate input, not something downstream needs), so this re-derives
        it from the buffer's latest bar rather than threading a new field
        through strategy.py just for this one check."""
        df = self.buffer.get_dataframe(signal.ticker)
        if df is None or df.empty:
            return False
        window = df.tail(self.config.volume_avg_period)
        dollar_volume_avg = (window["volume"] * window["close"]).mean()
        if dollar_volume_avg is None or dollar_volume_avg < self.config.premarket_min_dollar_volume_per_min:
            return False

        quote = self._latest_quotes.get(signal.ticker.upper())
        if quote is None:
            return False
        bid, ask, quoted_at = quote
        age_seconds = (datetime.now(timezone.utc) - _ensure_utc(quoted_at)).total_seconds()
        if age_seconds > self.config.premarket_quote_staleness_seconds:
            return False
        mid = (bid + ask) / 2
        if mid <= 0:
            return False
        spread_pct = (ask - bid) / mid
        return spread_pct <= self.config.premarket_max_spread_pct

    def _has_recent_news(self, ticker: str) -> bool:
        seen = self._last_news_seen.get(ticker.upper())
        if seen is None:
            return False
        age_hours = (datetime.now(timezone.utc) - _ensure_utc(seen)).total_seconds() / 3600.0
        return age_hours <= self.config.news_catalyst_lookback_hours

    def _update_htf_buffer(self, event: MarketTickEvent) -> None:
        """Incrementally rolls up 1-min BAR events into buffer_htf's
        coarser bars (default 15-min), floor-bucketed by
        htf_bar_interval_minutes. Finalizes the previous bucket into
        buffer_htf only once a bar from the NEXT bucket arrives -- the
        currently-forming bucket is never pushed early/partial."""
        symbol = event.symbol.upper()
        interval = self.config.htf_bar_interval_minutes
        bucket_start = event.timestamp.replace(
            minute=(event.timestamp.minute // interval) * interval, second=0, microsecond=0
        )

        acc = self._htf_accumulators.get(symbol)
        if acc is not None and acc["bucket_start"] != bucket_start:
            self.buffer_htf.add_bar(
                symbol=symbol, timestamp=acc["bucket_start"], open_=acc["open"],
                high=acc["high"], low=acc["low"], close=acc["close"], volume=acc["volume"],
            )
            acc = None

        if acc is None:
            self._htf_accumulators[symbol] = {
                "bucket_start": bucket_start,
                "open": event.open, "high": event.high, "low": event.low,
                "close": event.close, "volume": event.volume or 0.0,
            }
        else:
            if event.high is not None:
                acc["high"] = event.high if acc["high"] is None else max(acc["high"], event.high)
            if event.low is not None:
                acc["low"] = event.low if acc["low"] is None else min(acc["low"], event.low)
            if event.close is not None:
                acc["close"] = event.close
            acc["volume"] = (acc["volume"] or 0.0) + (event.volume or 0.0)

    async def _handle_market_tick(self, payload: dict) -> None:
        try:
            event = MarketTickEvent.model_validate(payload)
        except ValidationError as exc:
            logger.warning("Dropping invalid market tick: %s", exc)
            return

        if event.event_type == TickEventType.QUOTE:
            # Pre-market liquidity gate's bid/ask source -- QUOTE events
            # never fed the OHLCV buffer (see buffer.py's own docstring),
            # but the spread they carry is exactly what that gate needs.
            # Latest-value cache only, not a buffer -- see __init__.
            if event.bid is not None and event.ask is not None:
                self._latest_quotes[event.symbol.upper()] = (event.bid, event.ask, event.timestamp)
            return

        if event.event_type != TickEventType.BAR:
            return  # only BAR/QUOTE events are handled; TRADE is a no-op here

        self.buffer.add_bar(
            symbol=event.symbol,
            timestamp=event.timestamp,
            open_=event.open,
            high=event.high,
            low=event.low,
            close=event.close,
            volume=event.volume,
        )
        self._update_htf_buffer(event)
        self._bars_processed += 1

        df = self.buffer.get_dataframe(event.symbol)
        if df is None:
            return

        snapshot = compute_indicators(df, self.config)
        if snapshot is None:
            return  # not enough history yet for this symbol

        htf_sma_200 = compute_htf_trend(
            self.buffer_htf.get_dataframe(event.symbol), self.config.htf_sma_period
        )
        signals = evaluate_signals(event.symbol, snapshot, self.config, htf_sma_200=htf_sma_200)
        if not signals:
            return
        await _incr_metric(self._client, "quant", "evaluated", len(signals))

        if await self._is_loss_locked_out(event.symbol):
            self._signals_suppressed_loss_lockout += len(signals)
            await _incr_metric(self._client, "quant", "failed_loss_lockout", len(signals))
            logger.info(
                "Suppressed %d signal(s) for %s -- in post-loss lockout",
                len(signals), event.symbol,
            )
            if self.store is not None:
                self.store.record_suppressed(
                    event.symbol, "LOSS_LOCKOUT", len(signals), datetime.now(timezone.utc)
                )
            return

        if await self._is_on_cooldown(event.symbol):
            self._signals_suppressed_cooldown += len(signals)
            logger.info(
                "Suppressed %d signal(s) for %s -- still in cooldown",
                len(signals), event.symbol,
            )
            if self.store is not None:
                self.store.record_suppressed(
                    event.symbol, "COOLDOWN", len(signals), datetime.now(timezone.utc)
                )
            return

        # Confluence + risk/reward filters run BEFORE the cooldown lock
        # below is started -- a low-conviction candidate that never
        # becomes a real signal must not still burn the ticker's cooldown
        # slot and block a later, better one.
        qualifying = [s for s in signals if (s.confluence_score or 0) >= self.config.confluence_score_min]
        if not qualifying:
            self._signals_suppressed_low_confluence += len(signals)
            await _incr_metric(self._client, "quant", "failed_confluence", len(signals))
            logger.info(
                "Suppressed %d candidate(s) for %s -- confluence score below %d",
                len(signals), event.symbol, self.config.confluence_score_min,
            )
            if self.store is not None:
                self.store.record_suppressed(
                    event.symbol, "LOW_CONFLUENCE", len(signals), datetime.now(timezone.utc)
                )
            return

        survivors = [
            s for s in qualifying
            if s.risk_reward_ratio is not None and s.risk_reward_ratio >= self.config.min_risk_reward_ratio
        ]
        dropped_for_rr = len(qualifying) - len(survivors)
        if dropped_for_rr and self.store is not None:
            self.store.record_suppressed(
                event.symbol, "LOW_RISK_REWARD", dropped_for_rr, datetime.now(timezone.utc)
            )
        self._signals_suppressed_low_risk_reward += dropped_for_rr
        await _incr_metric(self._client, "quant", "failed_rr_gate", dropped_for_rr)
        if not survivors:
            logger.info(
                "Suppressed %d candidate(s) for %s -- risk/reward below %.2f:1",
                len(qualifying), event.symbol, self.config.min_risk_reward_ratio,
            )
            return

        # Trend Alignment Gate: drop a BULLISH, regular-session candidate
        # whose price is at/below the 15m 200 SMA. trend_aligned is None
        # (not applicable -- bearish, pre-market, or HTF buffer still
        # warming up) for every candidate this doesn't apply to, which
        # passes through unfiltered here.
        survivors, dropped_for_trend = _partition(survivors, lambda s: s.trend_aligned is not False)
        if dropped_for_trend and self.store is not None:
            self.store.record_suppressed(
                event.symbol, "TREND_GATE", len(dropped_for_trend), datetime.now(timezone.utc)
            )
        self._signals_suppressed_trend_gate += len(dropped_for_trend)
        await _incr_metric(self._client, "quant", "failed_trend_gate", len(dropped_for_trend))
        if not survivors:
            logger.info(
                "Suppressed %d candidate(s) for %s -- below the 15m 200 SMA",
                len(dropped_for_trend), event.symbol,
            )
            return

        # Pre-market liquidity gate: dollar volume + bid-ask spread, both
        # fail-closed (missing/stale data = gate not cleared, not assumed
        # to pass). Regular-session/closed candidates are untouched.
        survivors, dropped_for_liquidity = _partition(
            survivors, lambda s: s.session != "pre_market" or self._clears_premarket_liquidity(s)
        )
        if dropped_for_liquidity and self.store is not None:
            self.store.record_suppressed(
                event.symbol, "PREMARKET_LIQUIDITY", len(dropped_for_liquidity), datetime.now(timezone.utc)
            )
        self._signals_suppressed_premarket_liquidity += len(dropped_for_liquidity)
        await _incr_metric(self._client, "quant", "failed_premarket_liquidity", len(dropped_for_liquidity))
        if not survivors:
            logger.info(
                "Suppressed %d candidate(s) for %s -- pre-market liquidity gate not cleared",
                len(dropped_for_liquidity), event.symbol,
            )
            return

        # Pre-market news-catalyst gate: requires a NewsArticleIngestedEvent
        # for this ticker within news_catalyst_lookback_hours. Fail-closed:
        # a ticker with no news ever seen never clears this.
        survivors, dropped_for_news = _partition(
            survivors, lambda s: s.session != "pre_market" or self._has_recent_news(event.symbol)
        )
        if dropped_for_news and self.store is not None:
            self.store.record_suppressed(
                event.symbol, "NEWS_CATALYST", len(dropped_for_news), datetime.now(timezone.utc)
            )
        self._signals_suppressed_news_catalyst += len(dropped_for_news)
        if not survivors:
            logger.info(
                "Suppressed %d candidate(s) for %s -- no news catalyst within %.0fh",
                len(dropped_for_news), event.symbol, self.config.news_catalyst_lookback_hours,
            )
            return

        # Lock the ticker out NOW, not at publish/flush time -- otherwise a
        # ticker firing twice before the next throttle flush would queue
        # two separate candidate batches into the same window, defeating
        # the point of the cooldown.
        await self._start_cooldown(event.symbol)
        self._pending_candidates.extend(survivors)

    async def _is_on_cooldown(self, ticker: str) -> bool:
        try:
            return bool(await self._client.exists(f"cooldown:{ticker.upper()}"))
        except Exception as exc:  # noqa: BLE001 -- Redis hiccup shouldn't block signal evaluation
            logger.warning("Cooldown check failed for %s (%s); treating as not on cooldown", ticker, exc)
            return False

    async def _start_cooldown(self, ticker: str) -> None:
        try:
            await self._client.set(
                f"cooldown:{ticker.upper()}", "1", ex=int(self.config.cooldown_seconds)
            )
        except Exception as exc:  # noqa: BLE001 -- a failed lock shouldn't drop the candidate
            logger.warning("Failed to set cooldown for %s (%s)", ticker, exc)

    async def _is_loss_locked_out(self, ticker: str) -> bool:
        try:
            return bool(await self._client.exists(f"loss_lockout:{ticker.upper()}"))
        except Exception as exc:  # noqa: BLE001 -- Redis hiccup shouldn't block signal evaluation
            logger.warning("Loss-lockout check failed for %s (%s); treating as not locked out", ticker, exc)
            return False

    async def _start_loss_lockout(self, ticker: str) -> None:
        try:
            await self._client.set(
                f"loss_lockout:{ticker.upper()}", "1", ex=int(self.config.loss_lockout_seconds)
            )
        except Exception as exc:  # noqa: BLE001 -- a failed lock shouldn't crash the handler
            logger.warning("Failed to set loss lockout for %s (%s)", ticker, exc)

    async def _flush_throttle_window(self) -> None:
        if not self._pending_candidates:
            return

        candidates, self._pending_candidates = self._pending_candidates, []
        candidates.sort(key=lambda sig: (sig.confluence_score or 0, sig.volume_surge_ratio or 0.0), reverse=True)

        released, dropped = candidates[: self.config.throttle_max_signals], candidates[self.config.throttle_max_signals :]
        for signal in released:
            await self._publish_signal(signal)

        if dropped:
            self._signals_suppressed_throttle += len(dropped)
            logger.info(
                "Throttle: released %d/%d candidate(s) this window (ranked by confluence "
                "score, then volume surge ratio), dropped %s",
                len(released), len(candidates),
                ", ".join(f"{s.ticker}/{s.signal_type.value}" for s in dropped),
            )
            if self.store is not None:
                now = datetime.now(timezone.utc)
                # dropped can span multiple tickers in one flush -- one
                # counter increment per ticker, not one blanket call.
                for ticker, count in Counter(s.ticker for s in dropped).items():
                    self.store.record_suppressed(ticker, "THROTTLE", count, now)

    async def _publish_signal(self, signal: QuantSignal) -> None:
        try:
            await self._client.publish(self.config.signals_channel, signal.to_redis_payload())
            self._signals_published += 1
            await _incr_metric(self._client, "quant", "published", 1)
            logger.info("Signal: %s %s -- %s", signal.ticker, signal.signal_type.value, signal.message)
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the scanner
            logger.warning("Failed to publish signal to Redis: %s", exc)
