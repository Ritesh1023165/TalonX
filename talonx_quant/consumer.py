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
     config.cooldown_seconds): once a signal is PUBLISHED for a ticker,
     that ticker is locked out of producing further candidates -- of any
     signal_type -- until the cooldown expires. This is what stops e.g.
     an RSI+volume setup and a later, unrelated MACD cross on the same
     ticker from both alerting within a few minutes of each other. Armed
     in _publish_signal, AFTER the batch throttle and revalidation below
     (2026-08-16 quant audit, Post-Publication Cooldown Trigger) -- a
     candidate the throttle later drops must not still burn the
     ticker's cooldown slot and block a later, better one.
  3. Confluence + risk/reward filters (strategy.py computes both,
     attached to every candidate signal): a candidate below
     config.confluence_score_min or config.min_risk_reward_ratio is
     dropped before it's even queued for the throttle window.
  4. Batch throttle (tumbling window, config.throttle_window_seconds,
     15s default) + Dynamic R:R Revalidation: candidates that pass
     everything above are buffered, not published immediately. Every
     throttle_window_seconds, the buffer is ranked by a weighted
     Composite Opportunity Score (see _opportunity_score -- confluence,
     structural R:R, volume surge, and trend alignment, each normalized
     to [0, 1] before weighting) and only the top config.throttle_max_signals
     are actually revalidated and published; the rest are dropped. This
     means a signal can sit for up to throttle_window_seconds before
     it's published OR dropped -- a deliberate latency-for-quality
     tradeoff, not a bug. (2026-08-16 quant audit, P1: replaced the
     original (confluence_score, volume_surge_ratio) tuple-sort, whose
     raw-ratio tiebreaker systematically favored penny/meme-stock pumps
     -- which can post enormous surge ratios on a thin baseline volume --
     over a higher-conviction, better-risk-reward setup on a liquid
     large-cap with a smaller relative surge.) Each of the top-ranked
     candidates is then re-checked against the LATEST buffered price
     before it actually publishes (see _revalidate_candidate) -- dropped
     if it's aged past config.max_candidate_age_seconds
     (EXPIRED_IN_THROTTLE_QUEUE) or its recalculated R:R has fallen
     below config.min_risk_reward_ratio (RR_DEGRADED_DURING_THROTTLE),
     rather than publishing a stale entry price/ratio.

Two further 2026-08-16 quant-audit fixes apply upstream of all of the
above:
  - Fail-Closed Risk Management: a Redis connection/timeout error inside
    the Post-Loss Lockout or per-ticker cooldown CHECK (not the SET --
    see _handle_risk_check_failure) is treated as "yes, blocked" by
    default (config.risk_check_fail_closed), not "no, clear to trade" --
    a genuine risk-state blackout must not silently degrade into
    publishing candidates as if nothing were wrong.
  - Bar-Level Ingestion Idempotency: every incoming BAR tick is checked
    against a dedup key (ticker + the tick's own precise timestamp,
    Redis SETNX with a TTL, in-memory fallback) BEFORE it's fed into the
    rolling buffer at all -- see _is_new_bar_tick -- so a stream replay
    or Pub/Sub reconnect redelivering the same tick can't double-count
    its volume in a still-forming bucket's running accumulation.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from collections import deque
from datetime import datetime, timezone

from pydantic import ValidationError

from talonx_quant import preseed
from talonx_quant.buffer import RollingBarBuffer
from talonx_quant.config import QuantConfig
from talonx_quant.indicators import compute_daily_pivots, compute_htf_trend, compute_indicators
from talonx_quant.schemas import (
    MarketTickEvent,
    NewsArticleIngestedEvent,
    PaperOrderType,
    PaperTradeExecution,
    QuantSignal,
    RejectedCandidateEvent,
    SignalDirection,
    TickEventType,
)
from talonx_quant.session import get_entry_blackout, get_session
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


def _fails_min_volatility(snapshot, config: QuantConfig) -> bool:
    """True if this bar's ATR14/price (as a percentage) is below
    config.min_atr_pct -- filters out low-beta/income names (e.g. a REIT)
    that can occupy an execution slot without enough range to ever reach
    an ATR-scaled stop/target. Deliberately does NOT fail closed on
    missing ATR (warm-up): every RSI/MACD/MA check in strategy.py already
    requires ATR via _clears_atr_move, so an unwarmed symbol produces zero
    signals downstream regardless of this gate's answer."""
    if snapshot.atr is None or not snapshot.price:
        return False
    atr_pct = (snapshot.atr / snapshot.price) * 100
    return atr_pct < config.min_atr_pct


def _opportunity_score(signal: QuantSignal, config: QuantConfig) -> float:
    """Composite Opportunity Score (2026-08-16 quant audit, P1): the
    throttle window's ranking key, replacing the old
    (confluence_score, volume_surge_ratio) tuple-sort -- whose raw-ratio
    tiebreaker systematically favored penny/meme-stock pumps (which can
    post enormous surge ratios on a thin baseline volume) over a
    higher-conviction, better-risk-reward setup on a liquid large-cap
    with a smaller relative surge. Each factor is normalized to [0, 1]
    before weighting, so no single unbounded input (R:R, volume surge)
    can dominate the ranking purely on scale."""
    confluence_norm = (signal.confluence_score or 0) / 3.0

    rr_norm = 0.0
    if signal.risk_reward_ratio is not None and config.opportunity_score_rr_cap > 0:
        rr_norm = min(signal.risk_reward_ratio / config.opportunity_score_rr_cap, 1.0)

    volume_norm = 0.0
    if signal.volume_surge_ratio is not None and config.opportunity_score_volume_cap > 0:
        volume_norm = min(signal.volume_surge_ratio / config.opportunity_score_volume_cap, 1.0)

    # trend_aligned is True (aligned), None (not applicable -- bearish,
    # pre-market, or the HTF buffer hasn't warmed up -- treated as
    # NEUTRAL, since "not applicable" isn't "misaligned"), or False
    # (should never actually reach the throttle window: the trend gate
    # already dropped a False candidate upstream in _handle_market_tick --
    # kept here only as a defensive, correctly-scored fallback).
    if signal.trend_aligned is True:
        trend_norm = 1.0
    elif signal.trend_aligned is False:
        trend_norm = 0.0
    else:
        trend_norm = 0.5

    return (
        config.opportunity_score_confluence_weight * confluence_norm
        + config.opportunity_score_rr_weight * rr_norm
        + config.opportunity_score_volume_weight * volume_norm
        + config.opportunity_score_trend_weight * trend_norm
    )


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


# Rejection Trace Logging: stable, machine-readable gate identifiers for
# each suppress_reason string this module already produces -- published
# on RejectedCandidateEvent.gate so talonx_dispatch's audit trail can
# filter/group by gate without parsing the human-readable reason string.
# Acceptance criteria calls out "trend_gate, rr_gate, etc." by name --
# those two map 1:1 to TREND_GATE/LOW_RISK_REWARD below.
_GATE_NAMES = {
    "LOW_VOLATILITY": "volatility_gate",
    "OPENING_BLACKOUT": "opening_blackout_gate",
    "CLOSING_BLACKOUT": "closing_blackout_gate",
    "LOSS_LOCKOUT": "loss_lockout_gate",
    "COOLDOWN": "cooldown_gate",
    "LOW_CONFLUENCE": "confluence_gate",
    "LOW_RISK_REWARD": "rr_gate",
    "TREND_GATE": "trend_gate",
    "PREMARKET_LIQUIDITY": "premarket_liquidity_gate",
    "NEWS_CATALYST": "news_catalyst_gate",
    "THROTTLE": "throttle_gate",
    "EXPIRED_IN_THROTTLE_QUEUE": "throttle_revalidation_gate",
    "RR_DEGRADED_DURING_THROTTLE": "throttle_revalidation_gate",
    "RISK_STORE_UNAVAILABLE_FAIL_CLOSED": "risk_store_gate",
}


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
        # True Calendar-Aligned 1-Minute Candle Aggregation (Requirement 1):
        # raw poll-cycle BAR events (12s cadence by default) accumulate here,
        # floor-bucketed to the minute, and the running OHLCV is written
        # into self.buffer on EVERY tick (not just on bucket rollover) so
        # OTHER consumers (e.g. the pre-market liquidity gate) see the
        # latest partial minute -- see _update_1m_buffer. Indicator/signal
        # EVALUATION itself is a separate concern (Closed-Bar Evaluation,
        # see _handle_market_tick) and only ever runs once a bucket has
        # closed. A new row only appears once the wall clock actually
        # crosses into a new minute, so min_bars_required bars really do
        # span that many calendar minutes, not poll cycles.
        self._1m_accumulators: dict[str, dict] = {}
        # Historical pre-seeding (Requirement 2): each symbol is attempted
        # at most once per process lifetime -- a failed/rate-limited
        # attempt falls back to live accumulation rather than retrying
        # every tick (same "attempt once, periodic reconciler is the
        # safety net" posture run_talonx.py's WatchlistDrivenIngestion
        # already documents for its own reactive triggers).
        self._preseeded_1m: set[str] = set()
        self._preseeded_htf: set[str] = set()
        # Pre-market liquidity gate: latest QUOTE event per symbol
        # (bid, ask, timestamp) -- QUOTE events carry spread info the BAR
        # buffer above never sees (buffer.py only stores BAR-type events).
        self._latest_quotes: dict[str, tuple[float, float, datetime]] = {}
        # Pre-market news-catalyst gate: most recent NewsArticleIngestedEvent
        # timestamp seen per symbol -- only the recency matters, not the
        # article content, for the 4h-lookback check.
        self._last_news_seen: dict[str, datetime] = {}
        # Bar-Level Ingestion Idempotency: in-memory fallback dedup set,
        # used only when Redis itself is unavailable (see
        # _is_new_bar_tick) -- bounded to the last 200 dedup keys per
        # symbol, same "recent window, not unbounded history" posture as
        # every other in-process cache here.
        self._recent_bar_keys: dict[str, deque] = {}
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
        self._signals_suppressed_low_volatility = 0
        self._signals_suppressed_opening_blackout = 0
        self._signals_suppressed_closing_blackout = 0
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

    @property
    def signals_suppressed_low_volatility(self) -> int:
        return self._signals_suppressed_low_volatility

    @property
    def signals_suppressed_opening_blackout(self) -> int:
        return self._signals_suppressed_opening_blackout

    @property
    def signals_suppressed_closing_blackout(self) -> int:
        return self._signals_suppressed_closing_blackout

    async def run(self) -> None:
        if redis_asyncio is None:
            raise ImportError(
                "The 'redis' package is required. Install it with: pip install redis"
            )

        await self._load_buffers_from_store()

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

    async def _load_buffers_from_store(self) -> None:
        """Reloads both RollingBarBuffers from their last checkpoint --
        called once at the start of run(), before the connect/listen
        retry loop, so a restart doesn't force every symbol through a
        full re-warm-up from empty (min_bars_required=120 for the 1-min
        buffer, htf_sma_period=200 -- ~50 continuous hours -- for the HTF
        one). See config.py's buffer_reload_max_gap_seconds docstring for
        why the 1-min buffer is gap-gated and the HTF buffer isn't.

        Requirement 4 (Weekend & Overnight Gap Handling): a stale/short
        1-min reload and a 15-min reload that's still missing recent bars
        (gap > htf_backfill_gap_seconds, e.g. a weekend) both fall through
        to historical pre-seeding via yfinance (_preseed_1m_if_needed /
        _preseed_htf_if_needed) instead of leaving the symbol to re-warm
        up purely from live ticks."""
        if self.store is None:
            return

        now = datetime.now(timezone.utc)
        for symbol in self.store.buffered_symbols("1m"):
            bars = self.store.load_buffer(symbol, "1m")
            if bars:
                last_bar_at = _ensure_utc(datetime.fromisoformat(bars[-1]["timestamp"]))
                gap_seconds = (now - last_bar_at).total_seconds()
                if gap_seconds > self.config.buffer_reload_max_gap_seconds:
                    logger.info(
                        "Skipping stale 1-min buffer reload for %s (last bar %.0fs old, over the %.0fs limit)",
                        symbol, gap_seconds, self.config.buffer_reload_max_gap_seconds,
                    )
                else:
                    for bar in bars:
                        self.buffer.add_bar(
                            symbol=symbol, timestamp=datetime.fromisoformat(bar["timestamp"]),
                            open_=bar["open"], high=bar["high"], low=bar["low"],
                            close=bar["close"], volume=bar["volume"], session=bar.get("session"),
                        )
                    logger.info("Reloaded %d 1-min bar(s) for %s from checkpoint", len(bars), symbol)
            await self._preseed_1m_if_needed(symbol)

        for symbol in self.store.buffered_symbols("15m"):
            bars = self.store.load_buffer(symbol, "15m")
            for bar in bars:
                self.buffer_htf.add_bar(
                    symbol=symbol, timestamp=datetime.fromisoformat(bar["timestamp"]),
                    open_=bar["open"], high=bar["high"], low=bar["low"],
                    close=bar["close"], volume=bar["volume"], session=bar.get("session"),
                )
            gap_seconds = None
            if bars:
                last_bar_at = _ensure_utc(datetime.fromisoformat(bars[-1]["timestamp"]))
                gap_seconds = (now - last_bar_at).total_seconds()
                logger.info(
                    "Reloaded %d 15-min HTF bar(s) for %s from checkpoint (no gap limit)", len(bars), symbol,
                )
            force_backfill = gap_seconds is not None and gap_seconds > self.config.htf_backfill_gap_seconds
            if force_backfill:
                logger.info(
                    "15-min HTF checkpoint for %s is %.0fs old (over the %.0fs backfill threshold) -- "
                    "backfilling via yfinance", symbol, gap_seconds, self.config.htf_backfill_gap_seconds,
                )
            await self._preseed_htf_if_needed(symbol, force=force_backfill)

    async def preseed_symbols(self, symbols: list[str]) -> None:
        """Public entrypoint for run_talonx.py's watchlist-driven pre-seed
        reconciler (Requirement 2's "new ticker added to the watchlist"
        trigger). QuantScanner deliberately never imports talonx_watchlist
        itself (this module stays self-contained at the code level, same
        convention every other cross-module boundary here follows) -- the
        orchestrator owns the watchlist and calls this once at startup for
        the full watchlist, then again for just the symbol(s) that changed
        whenever it detects an addition/resume."""
        for symbol in symbols:
            symbol = symbol.upper()
            await self._preseed_1m_if_needed(symbol)
            await self._preseed_htf_if_needed(symbol)

    async def _preseed_1m_if_needed(self, symbol: str) -> None:
        if not self.config.historical_preseed_enabled:
            return
        symbol = symbol.upper()
        if symbol in self._preseeded_1m:
            return
        self._preseeded_1m.add(symbol)
        if self.buffer.bar_count(symbol) >= self.config.min_bars_required:
            return
        await self._run_1m_preseed(symbol)

    async def _run_1m_preseed(self, symbol: str) -> None:
        try:
            bars = await asyncio.to_thread(preseed.fetch_1m_history, symbol, self.config.preseed_1m_period)
        except Exception as exc:  # noqa: BLE001 -- pre-seeding is best-effort, never fatal
            logger.warning("1-min historical pre-seed failed for %s: %s", symbol, exc)
            return
        if not bars:
            logger.info(
                "1-min historical pre-seed returned no data for %s -- falling back to live accumulation", symbol,
            )
            return

        threshold = self.config.min_bars_required
        for bar in bars[-threshold:]:
            self.buffer.add_bar(
                symbol=symbol, timestamp=bar["timestamp"], open_=bar["open"], high=bar["high"],
                low=bar["low"], close=bar["close"], volume=bar["volume"], session=bar["session"],
            )
        logger.info(
            "1-min historical pre-seed: loaded %d bar(s) for %s (buffer now %d/%d)",
            len(bars[-threshold:]), symbol, self.buffer.bar_count(symbol), threshold,
        )
        if self.store is not None:
            self.store.checkpoint_buffer(symbol, "1m", self.buffer.get_bars(symbol))

    async def _preseed_htf_if_needed(self, symbol: str, force: bool = False) -> None:
        if not self.config.historical_preseed_enabled:
            return
        symbol = symbol.upper()
        if symbol in self._preseeded_htf:
            return
        self._preseeded_htf.add(symbol)
        if not force and self.buffer_htf.bar_count(symbol) >= self.config.htf_sma_period:
            return
        await self._run_htf_preseed(symbol)

    async def _run_htf_preseed(self, symbol: str) -> None:
        try:
            bars = await asyncio.to_thread(preseed.fetch_15m_history, symbol, self.config.preseed_15m_period)
        except Exception as exc:  # noqa: BLE001 -- pre-seeding is best-effort, never fatal
            logger.warning("15-min HTF historical pre-seed failed for %s: %s", symbol, exc)
            return
        if self.config.rth_only_htf_sma:
            bars = [b for b in bars if b["session"] == "regular"]
        if not bars:
            logger.info(
                "15-min HTF historical pre-seed returned no usable data for %s -- "
                "falling back to live accumulation", symbol,
            )
            return

        threshold = self.config.htf_sma_period
        for bar in bars[-threshold:]:
            self.buffer_htf.add_bar(
                symbol=symbol, timestamp=bar["timestamp"], open_=bar["open"], high=bar["high"],
                low=bar["low"], close=bar["close"], volume=bar["volume"], session=bar["session"],
            )
        logger.info(
            "15-min HTF historical pre-seed: loaded %d bar(s) for %s (buffer now %d/%d)",
            len(bars[-threshold:]), symbol, self.buffer_htf.bar_count(symbol), threshold,
        )
        if self.store is not None:
            self.store.checkpoint_buffer(symbol, "15m", self.buffer_htf.get_bars(symbol))

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
        currently-forming bucket is never pushed early/partial.

        Session-aware buffering (Requirement 3): when
        config.rth_only_htf_sma is set, a finalized bucket that falls
        OUTSIDE regular trading hours is simply never added to
        buffer_htf -- the 200-SMA trend gate this buffer exists for is
        RTH-only by definition, so a pre-market 15-min candle would only
        occupy a htf_max_bars slot the gate can never use."""
        symbol = event.symbol.upper()
        interval = self.config.htf_bar_interval_minutes
        bucket_start = event.timestamp.replace(
            minute=(event.timestamp.minute // interval) * interval, second=0, microsecond=0
        )

        acc = self._htf_accumulators.get(symbol)
        if acc is not None and acc["bucket_start"] != bucket_start:
            if not self.config.rth_only_htf_sma or get_session(acc["bucket_start"]) == "regular":
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

    def _update_1m_buffer(self, event: MarketTickEvent) -> None:
        """True Calendar-Aligned 1-Minute Candle Aggregation (Requirement
        1): floor-buckets incoming BAR events to the minute and builds a
        real OHLCV candle from each tick's own price (`event.close`) --
        open = first tick's price this minute, high/low = running max/min
        of every tick's price, close = latest tick's price, volume =
        accumulated. This is deliberately NOT the same as the raw
        open/high/low fields on the event itself (for the yfinance
        polling fallback those are the whole DAY's open/high/low --
        constant all session, useless for a 1-minute candle's shape).

        Unlike _update_htf_buffer, the still-forming bucket IS written
        into self.buffer on EVERY tick (not only once the bucket rolls
        over) -- OTHER consumers of the buffer (e.g. the pre-market
        liquidity gate's dollar-volume read) want the freshest
        partial-minute price, and buffer.py's session-tagged rows are
        also this module's restart-checkpoint source. A new ROW only
        appears once the wall clock actually crosses into a new minute
        (buffer.add_bar updates the existing row in place for the same
        bucket timestamp), so min_bars_required bars really do span that
        many calendar minutes, not raw poll cycles.

        Closed-Bar Evaluation (2026-08-16 quant audit): despite the
        buffer itself updating every tick, strategy.py's indicator/signal
        EVALUATION is deliberately NOT run against this still-forming
        row -- see _handle_market_tick's own bar_just_closed check, which
        captures the dataframe BEFORE this method is called on the tick
        that starts a new bucket, so evaluation always sees the bar that
        JUST closed, never a partial one. This function only aggregates;
        it does not decide when evaluation happens."""
        symbol = event.symbol.upper()
        if event.close is None:
            return
        bucket_start = event.timestamp.replace(second=0, microsecond=0)

        acc = self._1m_accumulators.get(symbol)
        if acc is None or acc["bucket_start"] != bucket_start:
            acc = {
                "bucket_start": bucket_start,
                "open": event.close, "high": event.close, "low": event.close,
                "close": event.close, "volume": event.volume or 0.0,
            }
        else:
            acc["high"] = max(acc["high"], event.close)
            acc["low"] = min(acc["low"], event.close)
            acc["close"] = event.close
            acc["volume"] = (acc["volume"] or 0.0) + (event.volume or 0.0)
        self._1m_accumulators[symbol] = acc

        self.buffer.add_bar(
            symbol=symbol, timestamp=acc["bucket_start"], open_=acc["open"],
            high=acc["high"], low=acc["low"], close=acc["close"], volume=acc["volume"],
        )

    async def _is_new_bar_tick(self, event: MarketTickEvent) -> bool:
        """Bar-Level Ingestion Idempotency (2026-08-16 quant audit): True
        if this exact tick (ticker + its own precise timestamp) hasn't
        been processed before. Redis SETNX (atomic, TTL'd
        bar_dedup_ttl_seconds) is the primary path -- it works across a
        process restart and across however many duplicate deliveries one
        reconnect storm produces, not just within this process's own
        memory. When Redis itself is unavailable, falls back to a
        bounded in-memory set of the last 200 dedup keys per symbol --
        best-effort, since idempotency is a data-quality concern here,
        not a trade-safety one (unlike the risk gates below, this does
        NOT need to fail closed -- a duplicate slipping through during a
        Redis outage costs at most one double-counted tick's worth of
        volume, not a bypassed risk control)."""
        symbol = event.symbol.upper()
        dedup_key = f"processed_bar:{symbol}:{event.timestamp.isoformat()}"

        if self._client is not None:
            try:
                is_new = await self._client.set(
                    dedup_key, "1", ex=int(self.config.bar_dedup_ttl_seconds), nx=True
                )
                return bool(is_new)
            except Exception as exc:  # noqa: BLE001 -- fall through to the in-memory fallback
                logger.warning(
                    "Bar dedup check failed for %s (%s); falling back to in-memory dedup", symbol, exc,
                )

        seen = self._recent_bar_keys.setdefault(symbol, deque(maxlen=200))
        if dedup_key in seen:
            return False
        seen.append(dedup_key)
        return True

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

        # Bar-Level Ingestion Idempotency (2026-08-16 quant audit): drop a
        # redelivered duplicate of a tick already processed -- a stream
        # replay or Pub/Sub reconnect resending the SAME tick would
        # otherwise double-count its volume in the still-forming bucket's
        # running accumulation below. Gated on the tick's own precise
        # timestamp (not the floor-bucketed minute), so legitimate
        # accumulation -- multiple distinct ticks landing in the same
        # forming minute -- is unaffected; only an exact repeat is caught.
        if not await self._is_new_bar_tick(event):
            await _incr_metric(self._client, "quant", "dropped_duplicate_bars", 1)
            logger.debug("Dropped duplicate bar tick for %s at %s", event.symbol, event.timestamp)
            return

        # Closed-Bar Evaluation (2026-08-16 quant audit, P0): indicators/
        # signals are evaluated ONLY on a just-CLOSED 1-min bar, never the
        # still-forming one. The buffer itself still updates the forming
        # bucket in place on every tick (unchanged -- other consumers, e.g.
        # the pre-market liquidity gate's dollar-volume read, want the
        # freshest partial-minute price), but evaluating strategy.py
        # against that partial candle let its OHLC keep moving mid-bar --
        # an RSI/MACD/MA crossing could flash true on an early, still-
        # forming tick and be false again by the bar's actual close (a
        # "phantom trigger"/repaint the audit flagged as a P0 correctness
        # flaw, not just noise). A bar is "closed" the instant the FIRST
        # tick of the NEXT bucket arrives -- capture the buffer's
        # dataframe BEFORE that tick's own bucket is written, so its last
        # row is the bar that just closed (no more ticks can land in it),
        # not the one just starting.
        symbol = event.symbol.upper()
        bucket_start = event.timestamp.replace(second=0, microsecond=0)
        prior_accumulator = self._1m_accumulators.get(symbol)
        bar_just_closed = prior_accumulator is not None and prior_accumulator["bucket_start"] != bucket_start
        closed_bar_df = self.buffer.get_dataframe(symbol) if bar_just_closed else None

        self._update_1m_buffer(event)
        self._update_htf_buffer(event)
        self._bars_processed += 1

        if not bar_just_closed:
            return  # this bucket is still forming -- wait for the next bar's first tick to close it out

        df = closed_bar_df
        if df is None:
            return

        snapshot = compute_indicators(df, self.config)
        if snapshot is None:
            return  # not enough history yet for this symbol

        if _fails_min_volatility(snapshot, self.config):
            self._signals_suppressed_low_volatility += 1
            await _incr_metric(self._client, "quant", "failed_min_volatility", 1)
            await self._record_rejection(event.symbol, "LOW_VOLATILITY", 1, datetime.now(timezone.utc))
            return  # ATR% below config.min_atr_pct -- low-beta name, skip momentum evaluation entirely

        df_htf = self.buffer_htf.get_dataframe(event.symbol)
        htf_sma_200 = compute_htf_trend(df_htf, self.config.htf_sma_period)
        daily_pivots = compute_daily_pivots(df_htf, snapshot.bar_timestamp)
        signals = evaluate_signals(
            event.symbol, snapshot, self.config, htf_sma_200=htf_sma_200, daily_pivots=daily_pivots,
        )
        if not signals:
            return
        await _incr_metric(self._client, "quant", "evaluated", len(signals))

        blackout = get_entry_blackout(snapshot.bar_timestamp)
        if blackout == "opening":
            # Opening Range Blackout (09:30-09:45 ET): ALL candidates
            # suppressed, both directions -- the first 15 minutes are
            # thin/volatile enough that even a bearish/exit read isn't
            # trustworthy yet.
            self._signals_suppressed_opening_blackout += len(signals)
            await _incr_metric(self._client, "quant", "dropped_opening_blackout", len(signals))
            await self._record_rejection(
                event.symbol, "OPENING_BLACKOUT", len(signals), datetime.now(timezone.utc), signals,
            )
            logger.info(
                "Suppressed %d candidate(s) for %s -- opening-range blackout (09:30-09:45 ET)",
                len(signals), event.symbol,
            )
            return
        if blackout == "closing":
            # Closing Entry Blackout (15:30-16:00 ET): only new BULLISH
            # entries are blocked -- prevents late-session whipsaws like
            # the PYPL #44 buy this gate was added for. A genuine bearish/
            # exit signal still fires, since an open position should be
            # allowed to exit before talonx_paper's EOD-flatten sweep
            # (15:50 ET) closes it out regardless.
            signals, dropped_for_closing = _partition(signals, lambda s: s.direction != SignalDirection.BULLISH)
            if dropped_for_closing:
                self._signals_suppressed_closing_blackout += len(dropped_for_closing)
                await _incr_metric(
                    self._client, "quant", "dropped_closing_blackout", len(dropped_for_closing)
                )
                await self._record_rejection(
                    event.symbol, "CLOSING_BLACKOUT", len(dropped_for_closing),
                    datetime.now(timezone.utc), dropped_for_closing,
                )
                logger.info(
                    "Suppressed %d BULLISH candidate(s) for %s -- closing-entry blackout (15:30-16:00 ET)",
                    len(dropped_for_closing), event.symbol,
                )
            if not signals:
                return

        if await self._is_loss_locked_out(event.symbol):
            self._signals_suppressed_loss_lockout += len(signals)
            await _incr_metric(self._client, "quant", "failed_loss_lockout", len(signals))
            logger.info(
                "Suppressed %d signal(s) for %s -- in post-loss lockout",
                len(signals), event.symbol,
            )
            await self._record_rejection(
                event.symbol, "LOSS_LOCKOUT", len(signals), datetime.now(timezone.utc), signals,
            )
            return

        if await self._is_on_cooldown(event.symbol):
            self._signals_suppressed_cooldown += len(signals)
            logger.info(
                "Suppressed %d signal(s) for %s -- still in cooldown",
                len(signals), event.symbol,
            )
            await self._record_rejection(
                event.symbol, "COOLDOWN", len(signals), datetime.now(timezone.utc), signals,
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
            await self._record_rejection(
                event.symbol, "LOW_CONFLUENCE", len(signals), datetime.now(timezone.utc), signals,
            )
            return

        survivors, dropped_for_rr = _partition(
            qualifying,
            lambda s: s.risk_reward_ratio is not None and s.risk_reward_ratio >= self.config.min_risk_reward_ratio,
        )
        if dropped_for_rr:
            await self._record_rejection(
                event.symbol, "LOW_RISK_REWARD", len(dropped_for_rr), datetime.now(timezone.utc), dropped_for_rr,
            )
        self._signals_suppressed_low_risk_reward += len(dropped_for_rr)
        await _incr_metric(self._client, "quant", "failed_rr_gate", len(dropped_for_rr))
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
        if dropped_for_trend:
            await self._record_rejection(
                event.symbol, "TREND_GATE", len(dropped_for_trend), datetime.now(timezone.utc), dropped_for_trend,
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
        if dropped_for_liquidity:
            await self._record_rejection(
                event.symbol, "PREMARKET_LIQUIDITY", len(dropped_for_liquidity),
                datetime.now(timezone.utc), dropped_for_liquidity,
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
        if dropped_for_news:
            await self._record_rejection(
                event.symbol, "NEWS_CATALYST", len(dropped_for_news), datetime.now(timezone.utc), dropped_for_news,
            )
        self._signals_suppressed_news_catalyst += len(dropped_for_news)
        if not survivors:
            logger.info(
                "Suppressed %d candidate(s) for %s -- no news catalyst within %.0fh",
                len(dropped_for_news), event.symbol, self.config.news_catalyst_lookback_hours,
            )
            return

        # Post-Publication Cooldown Trigger (2026-08-16 quant audit):
        # cooldown is NO LONGER armed here, at survival time -- it's
        # armed in _publish_signal, only once a candidate actually
        # clears the throttle window's ranking AND revalidation. Arming
        # it here (the original design) locked a ticker out for the full
        # 20-minute cooldown even when the batch throttle went on to drop
        # every one of its candidates that window -- a ticker that never
        # got a signal published was still penalized as if it had.
        # Closed-Bar Evaluation (see _handle_market_tick) already caps a
        # ticker to at most one candidate batch per closed bar
        # (structurally, not via this lock), so the original "prevent
        # two batches queuing in one window" race this comment used to
        # warn about can no longer happen regardless of when cooldown is
        # armed.
        self._pending_candidates.extend(survivors)

    async def _is_on_cooldown(self, ticker: str) -> bool:
        try:
            return bool(await self._client.exists(f"cooldown:{ticker.upper()}"))
        except Exception as exc:  # noqa: BLE001 -- see _handle_risk_check_failure for the fail-closed policy
            return await self._handle_risk_check_failure(ticker, "Cooldown", exc)

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
        except Exception as exc:  # noqa: BLE001 -- see _handle_risk_check_failure for the fail-closed policy
            return await self._handle_risk_check_failure(ticker, "Loss-lockout", exc)

    async def _handle_risk_check_failure(self, ticker: str, check_name: str, exc: Exception) -> bool:
        """Fail-Closed Risk Management (2026-08-16 quant audit): a Redis
        connection/timeout error inside _is_on_cooldown/_is_loss_locked_out
        means this process can no longer answer "is this ticker actually
        safe to trade right now" at all -- the PREVIOUS behavior (treat
        the exception as "not on cooldown"/"not locked out", i.e. return
        False) let candidates keep publishing during exactly the kind of
        risk-state blackout these two gates exist to prevent. Logged at
        CRITICAL (not WARNING) since this is a risk-control gap, not a
        routine hiccup -- an operator should notice immediately, not
        find it in a log review after the fact.

        config.risk_check_fail_closed (default True) is the enforced
        policy: return True (treat the ticker as BLOCKED) so the caller's
        `if await self._is_on_cooldown(...)` / `if await
        self._is_loss_locked_out(...)` check trips and the candidate is
        suppressed. Setting it False is an explicit, deliberate opt back
        into the old fail-open behavior -- not the default, and not
        silent (still logged CRITICAL either way)."""
        fail_closed = self.config.risk_check_fail_closed
        logger.critical(
            "%s check failed for %s (%s); %s", check_name, ticker, exc,
            "failing CLOSED (blocking trade)" if fail_closed
            else "failing OPEN (TALONX_QUANT_RISK_FAIL_CLOSED=false) -- NOT recommended",
        )
        if fail_closed:
            await self._record_rejection(
                ticker, "RISK_STORE_UNAVAILABLE_FAIL_CLOSED", 1, datetime.now(timezone.utc),
            )
        return fail_closed

    async def _start_loss_lockout(self, ticker: str) -> None:
        try:
            await self._client.set(
                f"loss_lockout:{ticker.upper()}", "1", ex=int(self.config.loss_lockout_seconds)
            )
        except Exception as exc:  # noqa: BLE001 -- a failed lock shouldn't crash the handler
            logger.warning("Failed to set loss lockout for %s (%s)", ticker, exc)

    def _latest_close(self, ticker: str) -> float | None:
        """Dynamic R:R Revalidation's current-price source -- the same
        buffer _handle_market_tick already keeps updated on every tick,
        just read directly rather than threaded through as an argument."""
        df = self.buffer.get_dataframe(ticker)
        if df is None or df.empty:
            return None
        return float(df["close"].iloc[-1])

    async def _revalidate_candidate(self, signal: QuantSignal, now: datetime) -> QuantSignal | None:
        """Dynamic R:R Revalidation (2026-08-16 quant audit): a candidate
        can sit in the throttle buffer for up to throttle_window_seconds
        before being ranked/released -- by the time it's actually about
        to publish, its entry price (and therefore its R:R) may have
        drifted from what strategy.py computed when the bar first
        closed. Re-checks age and re-derives reward/risk against the
        LATEST buffered close before publishing, rather than trusting
        stale numbers. Risk stays atr_stop_multiplier x the signal's OWN
        atr (ATR itself doesn't meaningfully change over a 15-30s
        window, and re-running full indicator computation here would be
        wasted work); only reward (which depends on the now-stale entry
        price) and the resulting ratio are recalculated. Returns None if
        the candidate should be dropped instead of published."""
        generated_at = _ensure_utc(signal.signal_generated_at)
        age_seconds = (now - generated_at).total_seconds()
        signal_age_ms = age_seconds * 1000.0

        if age_seconds > self.config.max_candidate_age_seconds:
            logger.info(
                "Dropping %s %s -- expired in throttle queue (%.0fms old, over %.0fms)",
                signal.ticker, signal.signal_type.value, signal_age_ms,
                self.config.max_candidate_age_seconds * 1000.0,
            )
            await self._record_rejection(
                signal.ticker, "EXPIRED_IN_THROTTLE_QUEUE", 1, now, [signal],
            )
            return None

        current_price = self._latest_close(signal.ticker)
        if (
            current_price is None or signal.atr is None
            or signal.pivot_resistance is None or signal.pivot_support is None
        ):
            # Can't recompute reward/risk without a fresh price and the
            # same ATR/pivot inputs the original R:R used -- publish
            # as-generated (with signal_age_ms filled in) rather than
            # dropping a candidate purely because fresher data isn't
            # available; strategy.py's own gate already confirmed a
            # valid R:R at generation time.
            return signal.model_copy(update={"signal_age_ms": signal_age_ms})

        risk = self.config.atr_stop_multiplier * signal.atr
        if risk <= 0:
            return signal.model_copy(update={"signal_age_ms": signal_age_ms})

        if signal.direction == SignalDirection.BULLISH:
            reward = signal.pivot_resistance - current_price
        else:
            reward = current_price - signal.pivot_support
        recalculated_rr = (reward / risk) if reward > 0 else 0.0

        if recalculated_rr < self.config.min_risk_reward_ratio:
            logger.info(
                "Dropping %s %s -- R:R degraded to %.2f during throttle wait (was %.2f, needs >= %.2f)",
                signal.ticker, signal.signal_type.value, recalculated_rr,
                signal.risk_reward_ratio or 0.0, self.config.min_risk_reward_ratio,
            )
            await self._record_rejection(
                signal.ticker, "RR_DEGRADED_DURING_THROTTLE", 1, now, [signal],
            )
            return None

        return signal.model_copy(update={
            "price": current_price,
            "risk_reward_ratio": recalculated_rr,
            "signal_age_ms": signal_age_ms,
        })

    async def _flush_throttle_window(self) -> None:
        if not self._pending_candidates:
            return

        candidates, self._pending_candidates = self._pending_candidates, []
        candidates.sort(key=lambda sig: _opportunity_score(sig, self.config), reverse=True)

        released, dropped = candidates[: self.config.throttle_max_signals], candidates[self.config.throttle_max_signals :]
        now = datetime.now(timezone.utc)
        for signal in released:
            revalidated = await self._revalidate_candidate(signal, now)
            if revalidated is None:
                continue
            await self._publish_signal(revalidated)

        if dropped:
            self._signals_suppressed_throttle += len(dropped)
            logger.info(
                "Throttle: released %d/%d candidate(s) this window (ranked by Composite "
                "Opportunity Score), dropped %s",
                len(released), len(candidates),
                ", ".join(f"{s.ticker}/{s.signal_type.value}" for s in dropped),
            )
            # dropped can span multiple tickers in one flush -- one
            # rejection record (count + per-candidate detail) per ticker,
            # not one blanket call.
            for ticker in {s.ticker for s in dropped}:
                ticker_signals = [s for s in dropped if s.ticker == ticker]
                await self._record_rejection(ticker, "THROTTLE", len(ticker_signals), now, ticker_signals)

    async def _record_rejection(
        self, ticker: str, reason: str, count: int, when: datetime,
        signals: list[QuantSignal] | None = None,
    ) -> None:
        """Rejection Trace Logging: single choke point for BOTH the
        existing local suppression-count persistence
        (self.store.record_suppressed, aggregated per UTC day, used by
        the EOD report) AND publishing one RejectedCandidateEvent PER
        CANDIDATE to talonx:quant:rejected, consumed by talonx_dispatch
        for a durable, per-candidate audit trail (its own AuditStore's
        rejected_candidates table) -- without this, a dropped candidate
        never reached talonx_dispatch at all, only published signals did.

        `signals` carries the actual QuantSignal candidates being
        dropped when available (most gates), giving each published
        RejectedCandidateEvent real signal_type/direction/confluence_score/
        risk_reward_ratio detail; some gates (e.g. LOW_VOLATILITY) run
        before any candidate signal is built at all, so `signals` is
        None there and `count` alone determines how many bare
        (ticker/reason only) events to publish -- every gate-drop site
        already had `count` for the store.record_suppressed call, so
        this doesn't require passing anything new for that case."""
        if self.store is not None:
            self.store.record_suppressed(ticker, reason, count, when)
        if self._client is None:
            return

        gate = _GATE_NAMES.get(reason, reason.lower())
        detail: list[QuantSignal | None] = list(signals) if signals is not None else [None] * count
        for signal in detail:
            event = RejectedCandidateEvent(
                ticker=ticker.upper(), gate=gate, reason=reason, rejected_at=when,
                signal_type=None if signal is None else signal.signal_type.value,
                direction=None if signal is None else signal.direction,
                price=None if signal is None else signal.price,
                confluence_score=None if signal is None else signal.confluence_score,
                risk_reward_ratio=None if signal is None else signal.risk_reward_ratio,
                session=None if signal is None else signal.session,
            )
            try:
                await self._client.publish(self.config.rejected_candidates_channel, event.to_redis_payload())
            except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the scanner
                logger.debug("Failed to publish rejection trace for %s (%s): %s", ticker, reason, exc)

    async def _publish_signal(self, signal: QuantSignal) -> None:
        try:
            await self._client.publish(self.config.signals_channel, signal.to_redis_payload())
            self._signals_published += 1
            await _incr_metric(self._client, "quant", "published", 1)
            logger.info("Signal: %s %s -- %s", signal.ticker, signal.signal_type.value, signal.message)
        except Exception as exc:  # noqa: BLE001 -- a publish failure shouldn't crash the scanner
            logger.warning("Failed to publish signal to Redis: %s", exc)
            return
        # Post-Publication Cooldown Trigger (2026-08-16 quant audit):
        # armed HERE, only once a candidate has actually cleared the
        # throttle window and successfully published -- not merely
        # survived strategy.py's gates. A candidate the throttle later
        # drops (or that fails revalidation/publish) must not burn the
        # ticker's cooldown slot and block a later, better one.
        await self._start_cooldown(signal.ticker)
