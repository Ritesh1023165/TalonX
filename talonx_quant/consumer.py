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
     rather than publishing a stale entry price/ratio. Also re-checked
     against cooldown:{TICKER} immediately before proceeding (P1 fix,
     2026-08-16 quant audit) -- strategy.py can legitimately emit
     multiple independent candidates for the SAME ticker off one closed
     bar (e.g. a MACD cross AND an RSI/volume setup), and without this
     re-check the first one to publish would arm cooldown too late to
     stop a second same-ticker candidate already sitting in this SAME
     released batch from also publishing (COOLDOWN).

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

Round-3 quant audit (2026-08-16), three more correctness/integrity gaps:
  - Canonical Trade Geometry: _revalidate_candidate now recalculates
    stop_price/target_price alongside price/risk_reward_ratio, all via
    strategy.py's calculate_trade_geometry (the SAME function
    _build_signal uses) -- a prior version only recalculated the ratio,
    so a revalidated signal could publish with a stop/target still
    measured against its original, stale entry price.
  - Fail-Closed Lock Persistence: a Redis SET failure while ARMING the
    Post-Loss Lockout or per-ticker cooldown (as opposed to a failure
    CHECKING one, above) used to only log a warning -- the lock then
    silently never took effect. _start_loss_lockout/_start_cooldown now
    fall back to an in-memory, process-local lock for the same ticker
    and duration when the Redis SET fails (see _arm_fallback_lock /
    _in_memory_lock_active), enforced on every subsequent
    _is_loss_locked_out/_is_on_cooldown check until it expires or a
    later SET actually succeeds.
  - HTF-Unavailable Trend Gate: trend_aligned=None on a QuantSignal used
    to mean two different things -- "the trend gate doesn't apply to
    this candidate" (bearish/pre-market/disabled) AND "the gate applies
    but the 15m-200-SMA buffer hasn't warmed up yet" -- and both passed
    the old `trend_aligned is not False` filter identically. A
    regular-session bullish candidate with a genuinely cold HTF buffer
    is now rejected as HTF_DATA_UNAVAILABLE instead of silently
    publishing with zero trend confirmation -- see
    _trend_gate_applicable.

Round-4 quant audit (2026-08-16): deployment context for this section --
this process is NOT a 24x7 service. It's a host process (NOT
Dockerised -- see docker-compose.yaml, which runs only Redis, and
scripts/start_talonx.ps1/stop_talonx.ps1) started/stopped by a daily
Windows Scheduled Task, normally Mon-Fri ~08:00-22:00 UK local time (see
scripts/register_scheduled_tasks.ps1 -- Task Scheduler's own daily
trigger already handles BST/GMT transitions; this module adds no
UK-time-of-day logic of its own). Off-hours, both this process AND Redis
are expected to be stopped. Four fixes below, all scoped to that model:

  - GLOBAL_RISK_DEGRADED (process-wide, not per-ticker): round 3's
    per-ticker in-memory fallback lock (_arm_fallback_lock) is a real
    improvement over silently logging a warning, but it's still scoped
    to the one ticker whose write failed -- a Redis SET failing for
    AAPL's cooldown says nothing about whether Redis can be trusted for
    MSFT or NVDA; it says Redis itself is unreliable RIGHT NOW. Every
    mandatory-write failure (_arm_fallback_lock, called from both
    _start_loss_lockout and _start_cooldown) now ALSO calls
    _enter_risk_degraded, setting a single process-wide
    self._risk_degraded flag. Checked at two points: early and cheaply
    in _handle_market_tick (skips a ticker's candidates before running
    any of the gates below it) and AUTHORITATIVELY in _publish_signal
    (the single funnel every actual Redis publish goes through, for
    every ticker -- this is what makes the block truly process-wide, and
    also catches a candidate already queued in _pending_candidates from
    before degradation began). Cleared ONLY by _reconcile_risk_state
    confirming Redis can actually PERSIST a write (_verify_redis_persistence
    -- PING succeeding is deliberately not enough), run at the start of
    every _connect_and_listen call (a genuine process startup AND every
    reconnect after a dropped connection) and periodically by
    _checkpoint_loop while already degraded. GLOBAL_RISK_DEGRADED is
    NEVER written to Redis or otherwise persisted -- it's this process's
    own in-memory safety state; when the process stops (the normal
    ~22:00 shutdown), it simply disappears, and the next run/reconnect
    re-derives it fresh via _reconcile_risk_state. This is deliberately
    NOT a 24x7 recovery daemon -- both retry paths above piggyback on
    infrastructure (the reconnect-backoff loop, the buffer-checkpoint
    loop) that already only runs for the life of one connected session.
  - Per-ticker lock state needs no restart-time reconciliation of its
    own: _is_on_cooldown/_is_loss_locked_out always read
    `EXISTS cooldown:{TICKER}`/`loss_lockout:{TICKER}` LIVE from Redis,
    never from a process-local cache -- so a still-valid TTL'd lock from
    a PRIOR run (e.g. one active when Friday's process stopped) is
    honoured automatically the instant this process starts checking
    again, and an expired one is equally simple (Redis's own TTL already
    removed the key). There is no in-memory copy of that state to go
    stale, resurrect, or need reloading at startup -- see
    _reconcile_risk_state's own docstring.
  - Final Revalidation Data Availability: _revalidate_candidate
    previously published a candidate AS-GENERATED (its original,
    now-unverified geometry) when it couldn't obtain fresh
    price/ATR/pivot data at throttle-flush time. It now rejects that
    candidate outright as FINAL_REVALIDATION_DATA_UNAVAILABLE instead --
    final publication must be based on a VERIFIED current trade
    geometry, never an assumed-still-good stale one.
  - Race-condition analysis (Requirement 12, no code change): a
    theoretical check-then-act race exists between _is_on_cooldown's
    read and _start_cooldown's write for the SAME ticker, since
    _flush_throttle_window runs as a separate task from the main
    _handle_message loop. In practice this can't produce a duplicate
    publication: Closed-Bar Evaluation already caps a ticker to at most
    ONE candidate batch per closed 1-minute bar (structurally, via the
    bar-buffer bucket logic, not via this lock), so the earliest a
    SECOND batch for the same ticker could even be queued is the NEXT
    bar close, at least ~60s later -- while the entire
    revalidate-then-publish-then-arm-cooldown sequence for the first
    batch takes at most a few Redis round trips (milliseconds). A
    genuine collision would require the next bar-close event to arrive
    inside that multi-millisecond window, which the ~60s bar cadence
    makes structurally impossible. Bar-Level Ingestion Idempotency (see
    _is_new_bar_tick) is the actual exactly-once guarantee this module
    provides, and it's scoped to INPUT tick processing (a replayed/
    redelivered tick can't double-process), not to the downstream
    QuantSignal publish itself: Redis Pub/Sub has no delivery guarantee
    at all (not even at-least-once) for a published message a
    disconnected subscriber simply never receives -- this is a stated,
    accepted architectural limitation of Pub/Sub as a transport, not a
    gap this module can close without replacing Pub/Sub itself (an
    explicitly out-of-scope distributed-transaction-style change here).
    Downstream consumers of talonx:signals:quant are expected to treat
    delivery as best-effort, same as every other Pub/Sub channel in this
    project.

Round-5 quant audit (2026-08-16): "08:00-22:00 Monday-Friday is a
TRADING-SESSION rule, not an APPLICATION-STARTUP rule." TalonX may be
started at any time of day -- mid-session, before the window opens, on a
weekend, or after an unplanned crash/restart -- and must never assume it
was launched at exactly 08:00. session.py's is_operating_window_open
answers "is TalonX allowed to publish signals RIGHT NOW" from the
CURRENT UK-local (Europe/London, DST-aware) date/time on every call,
never from process uptime or launch time. Gated in two places, mirroring
GLOBAL_RISK_DEGRADED's own early/authoritative split above: early and
cheaply in _handle_market_tick (UK_SESSION_CLOSED, before the
ticker-specific gates below it), and AUTHORITATIVELY in
_revalidate_candidate -- a candidate generated just before the window
closes (e.g. 21:59:50) can still be sitting in the throttle buffer past
the close (22:00:00), so the early per-tick check alone isn't sufficient;
final revalidation re-checks the window immediately before publish. Both
Redis/risk health (GLOBAL_RISK_DEGRADED) AND the UK operating window must
be satisfied before a signal actually publishes -- neither check
substitutes for the other. Weekends are unconditionally closed via the
same function (Saturday/Sunday), no separate code path. No new
scheduler/daemon of any kind was added for this -- the check is a pure,
stateless function of the current instant, evaluated inline wherever
publication is about to happen, same "no 24x7 recovery service" posture
round 4 already established for GLOBAL_RISK_DEGRADED's own recovery
retries. At 22:00 (or any other window-closed instant), NOTHING is
deleted/reset/cleared -- Redis TTLs, per-ticker locks, and bar-dedup
state are completely untouched; only NEW publication is prevented.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from collections import deque
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from talonx_quant import preseed
from talonx_quant.aggregation import HtfBarAggregator
from talonx_quant.buffer import RollingBarBuffer
from talonx_quant.config import QuantConfig
from talonx_quant.indicators import (
    VolatilityRegimeSnapshot, classify_regime_shadow_disagreement, compute_daily_pivots, compute_htf_trend,
    compute_indicators, compute_volatility_regime, evaluate_regime,
)
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
from talonx_quant.session import get_entry_blackout, is_operating_window_open
from talonx_quant.store import QuantStateStore
from talonx_quant.strategy import calculate_trade_geometry, evaluate_signals

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


def _trend_gate_applicable(signal: QuantSignal, config: QuantConfig) -> bool:
    """True when the 15m-200-SMA trend gate is actually meant to evaluate
    this candidate -- config.trend_gate_enabled, BULLISH direction,
    regular session (mirrors strategy.py's own _trend_aligned
    applicability check). Used to distinguish "gate doesn't apply here"
    from "gate applies but htf_sma_200 wasn't available yet" -- both
    produce trend_aligned=None on the signal, but only the latter should
    be rejected as HTF_DATA_UNAVAILABLE (see _handle_market_tick)."""
    return (
        config.trend_gate_enabled
        and signal.direction == SignalDirection.BULLISH
        and signal.session == "regular"
    )


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
    "HTF_DATA_UNAVAILABLE": "trend_gate",
    "PREMARKET_LIQUIDITY": "premarket_liquidity_gate",
    "NEWS_CATALYST": "news_catalyst_gate",
    "THROTTLE": "throttle_gate",
    "EXPIRED_IN_THROTTLE_QUEUE": "throttle_revalidation_gate",
    "RR_DEGRADED_DURING_THROTTLE": "throttle_revalidation_gate",
    "RISK_STORE_UNAVAILABLE_FAIL_CLOSED": "risk_store_gate",
    "GLOBAL_RISK_DEGRADED": "risk_degraded_gate",
    "FINAL_REVALIDATION_DATA_UNAVAILABLE": "throttle_revalidation_gate",
    "UK_SESSION_CLOSED": "uk_session_gate",
    "US_MARKET_SESSION_CLOSED": "us_session_gate",
    "PREMARKET_PROVIDER_UNSUPPORTED": "premarket_provider_gate",
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
        # HTF bucketing itself (floor-bucket + finalize-on-next-bucket) is
        # factored into aggregation.HtfBarAggregator, shared unchanged
        # with talonx_backtest's historical replay engine -- see that
        # module's own docstring for why.
        self._htf_aggregator = HtfBarAggregator(
            self.config.htf_bar_interval_minutes, rth_only=self.config.rth_only_htf_sma,
        )
        # Task 40: multi-timeframe volatility REGIME state (observability
        # only -- see compute_volatility_regime's docstring). The 15m leg
        # reuses buffer_htf/_htf_aggregator above unchanged; this is ONLY
        # the new 60-minute leg, built from the exact same, already-proven
        # classes -- deliberately continuous (rth_only=False), per Task
        # 39's session-policy design, not a runtime-tunable knob.
        self.buffer_60m = RollingBarBuffer(self.config.regime_60m_max_bars)
        self._aggregator_60m = HtfBarAggregator(self.config.regime_60m_bar_interval_minutes, rth_only=False)
        # Latest snapshot per symbol -- observability only, never consulted
        # by any gate/eligibility decision.
        self._latest_regime_snapshot: dict[str, VolatilityRegimeSnapshot] = {}
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
        # Fail-Closed Lock Persistence (2026-08-16 quant audit, round 3):
        # in-memory fallback for the loss-lockout/cooldown locks
        # themselves (not just the CHECK, see _handle_risk_check_failure
        # above) -- if the Redis SET that's supposed to persist a lock
        # fails, the lock must still be enforced for its intended
        # duration rather than silently never taking effect. Same
        # "in-memory fallback when Redis is unavailable" convention as
        # _recent_bar_keys above; ticker -> the UTC instant the fallback
        # lock expires. See _start_loss_lockout/_start_cooldown and
        # _in_memory_lock_active.
        self._loss_lockout_fallback: dict[str, datetime] = {}
        self._cooldown_fallback: dict[str, datetime] = {}
        # GLOBAL_RISK_DEGRADED (2026-08-16 quant audit, round 4): process-
        # wide (not per-ticker) fail-closed state -- True whenever this
        # process can no longer TRUST that a mandatory risk-state write
        # (loss-lockout or cooldown) actually persisted to Redis. Blocks
        # ALL subsequent signal publication for EVERY ticker, not just the
        # one whose write failed (see _enter_risk_degraded's own
        # docstring for why a per-ticker response isn't sufficient here).
        # Defaults to False: a genuinely fresh, never-connected scanner
        # has no reason to assume Redis is broken -- the actual
        # startup-time verification runs in _connect_and_listen's
        # _reconcile_risk_state call, BEFORE the message loop (and so
        # before any tick can be processed or signal published) ever
        # starts, so production code is never at risk of publishing
        # ahead of that check. This flag is deliberately in-process only
        # (never written to Redis) -- see _enter_risk_degraded and
        # _reconcile_risk_state.
        self._risk_degraded: bool = False
        self._signals_suppressed_risk_degraded = 0
        self._signals_suppressed_uk_session_closed = 0
        self._signals_suppressed_us_session_closed = 0
        self._signals_suppressed_premarket_provider_unsupported = 0
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
        self._signals_suppressed_htf_unavailable = 0
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
    def signals_suppressed_htf_unavailable(self) -> int:
        return self._signals_suppressed_htf_unavailable

    @property
    def signals_suppressed_risk_degraded(self) -> int:
        return self._signals_suppressed_risk_degraded

    @property
    def signals_suppressed_uk_session_closed(self) -> int:
        return self._signals_suppressed_uk_session_closed

    @property
    def signals_suppressed_us_session_closed(self) -> int:
        return self._signals_suppressed_us_session_closed

    @property
    def signals_suppressed_premarket_provider_unsupported(self) -> int:
        return self._signals_suppressed_premarket_provider_unsupported

    @property
    def risk_degraded(self) -> bool:
        """GLOBAL_RISK_DEGRADED's public read -- see _enter_risk_degraded
        and _reconcile_risk_state. Exposed for dashboards/health checks;
        this process's own gates read self._risk_degraded directly."""
        return self._risk_degraded

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

        # Risk-State Reconciliation (2026-08-16 quant audit, round 4,
        # Requirements 3/8): runs BEFORE subscribe/the message loop below,
        # on EVERY connect AND every reconnect after a dropped connection
        # -- a PING succeeding is not sufficient to trust Redis for
        # mandatory risk-state persistence (see _verify_redis_persistence),
        # so GLOBAL_RISK_DEGRADED is set/cleared here based on a confirmed
        # write-verify BEFORE any tick can be processed or signal
        # published this connection.
        await self._reconcile_risk_state()

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
        could lose to at most buffer_checkpoint_interval_seconds.

        Also doubles as GLOBAL_RISK_DEGRADED's recovery-retry cadence
        (round 4 quant audit, Requirement 3): while degraded, each tick
        of this ALREADY-EXISTING periodic loop re-attempts
        _reconcile_risk_state. Deliberately reuses this loop rather than
        adding a new one -- the operating model is "no 24x7 daemon,"
        and this loop already only runs for the life of one connected
        session, exactly the scope recovery-retrying needs (a full
        connection drop is instead handled by _connect_and_listen's own
        reconciliation on reconnect, above)."""
        try:
            while True:
                await asyncio.sleep(self.config.buffer_checkpoint_interval_seconds)
                self._checkpoint_all_buffers()
                if self._risk_degraded:
                    await self._reconcile_risk_state()
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
        # Task 40: 60-minute regime leg -- same generic, buffer_type-keyed
        # checkpoint mechanism above, no store schema change needed.
        for symbol in self.buffer_60m.known_symbols():
            bars = self.buffer_60m.get_bars(symbol)
            if bars:
                self.store.checkpoint_buffer(symbol, "60m", bars)

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

        # Task 40: 60-minute regime leg -- minimal reload only (no gap
        # limit, mirroring the 15m block's own "no gap limit" reload
        # above). Deliberately does NOT add a yfinance historical-backfill
        # path analogous to _preseed_htf_if_needed -- that is a materially
        # larger, separate feature, explicitly out of scope for Task 40's
        # "smallest implementation possible" instruction. See
        # results/task40_volatility_state/warmup_state_requirements.md
        # for the exact remaining-gap classification. Until that future
        # task exists, a fresh process simply re-warms this leg from live
        # ticks over the following ~2 continuous days (>14 60-min bars),
        # same as any other cold-started buffer before its own checkpoint
        # mechanism existed.
        for symbol in self.store.buffered_symbols("60m"):
            bars = self.store.load_buffer(symbol, "60m")
            for bar in bars:
                self.buffer_60m.add_bar(
                    symbol=symbol, timestamp=datetime.fromisoformat(bar["timestamp"]),
                    open_=bar["open"], high=bar["high"], low=bar["low"],
                    close=bar["close"], volume=bar["volume"], session=bar.get("session"),
                )
            if bars:
                logger.info(
                    "Reloaded %d 60-min regime bar(s) for %s from checkpoint (no gap limit, no backfill)",
                    len(bars), symbol,
                )

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
        coarser bars (default 15-min). The actual bucketing (floor-bucket
        + finalize-on-next-bucket) lives in self._htf_aggregator
        (aggregation.HtfBarAggregator), shared unchanged with
        talonx_backtest's replay engine -- this method just feeds it and
        writes whatever it finalizes into buffer_htf.

        Session-aware buffering (Requirement 3): HtfBarAggregator itself
        drops a finalized bucket that falls OUTSIDE regular trading hours
        when constructed with rth_only=True (see __init__) -- the
        200-SMA trend gate this buffer exists for is RTH-only by
        definition, so a pre-market 15-min candle would only occupy a
        htf_max_bars slot the gate can never use."""
        symbol = event.symbol.upper()
        finalized = self._htf_aggregator.update(
            symbol=symbol, timestamp=event.timestamp,
            open_=event.open, high=event.high, low=event.low,
            close=event.close, volume=event.volume,
        )
        if finalized is not None:
            self.buffer_htf.add_bar(
                symbol=symbol, timestamp=finalized["timestamp"], open_=finalized["open"],
                high=finalized["high"], low=finalized["low"], close=finalized["close"],
                volume=finalized["volume"],
            )

    def _update_regime_buffer_60m(self, event: MarketTickEvent) -> None:
        """Task 40: the 60-minute regime leg's bucketing -- identical
        pattern to _update_htf_buffer above (same HtfBarAggregator/
        RollingBarBuffer classes, a different interval/rth_only), just
        for the new buffer_60m. Deliberately continuous (rth_only=False,
        set at construction) rather than RTH-only like the 15m trend
        buffer -- Task 39's session-policy design."""
        symbol = event.symbol.upper()
        finalized = self._aggregator_60m.update(
            symbol=symbol, timestamp=event.timestamp,
            open_=event.open, high=event.high, low=event.low,
            close=event.close, volume=event.volume,
        )
        if finalized is not None:
            self.buffer_60m.add_bar(
                symbol=symbol, timestamp=finalized["timestamp"], open_=finalized["open"],
                high=finalized["high"], low=finalized["low"], close=finalized["close"],
                volume=finalized["volume"],
            )

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
        self._update_regime_buffer_60m(event)
        self._bars_processed += 1

        if not bar_just_closed:
            return  # this bucket is still forming -- wait for the next bar's first tick to close it out

        df = closed_bar_df
        if df is None:
            return

        snapshot = compute_indicators(df, self.config)
        if snapshot is None:
            return  # not enough history yet for this symbol

        # Task 40: regime snapshot computed for EVERY closed bar,
        # unconditionally -- deliberately BEFORE the volatility gate below
        # so it is available regardless of that gate's outcome
        # (observability state, not an eligibility input; see
        # compute_volatility_regime's docstring). Reuses buffer_htf's
        # dataframe exactly as compute_htf_trend/compute_daily_pivots
        # already do below -- no new 15m read path.
        self._latest_regime_snapshot[event.symbol.upper()] = compute_volatility_regime(
            self.buffer_htf.get_dataframe(event.symbol), self.buffer_60m.get_dataframe(event.symbol),
            self.config.atr_period, snapshot.bar_timestamp,
        )

        fails_volatility = _fails_min_volatility(snapshot, self.config)

        # Task 42: shadow comparison, EXISTING decision (fails_volatility,
        # unchanged) vs. the new Contract B evaluator -- observability
        # only. Never consulted below; `fails_volatility` alone still
        # drives the reject-or-continue branch that follows. Recorded via
        # this project's existing per-stage Redis metric counters
        # (_incr_metric, already feeding talonx_dispatch's Daily Funnel
        # dashboard) plus a structured log line -- no Telegram/user-facing
        # surface touched, matching Task 42's observability-only scope.
        regime_result = evaluate_regime(self._latest_regime_snapshot[event.symbol.upper()])
        old_passes = not fails_volatility
        disagreement = classify_regime_shadow_disagreement(old_passes, regime_result)
        await _incr_metric(self._client, "quant", f"regime_shadow_{disagreement}", 1)
        logger.info(
            "regime_shadow symbol=%s current_pass=%s new_ready=%s new_eligible=%s reason=%s "
            "atr_pct_15m=%s atr_pct_60m=%s disagreement=%s",
            event.symbol, old_passes, regime_result.ready, regime_result.eligible, regime_result.reason,
            regime_result.atr_pct_15m, regime_result.atr_pct_60m, disagreement,
        )

        if fails_volatility:
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

        # GLOBAL_RISK_DEGRADED (2026-08-16 quant audit, round 4): checked
        # here, EARLY and per-ticker-uniformly, before any of the
        # ticker-specific gates below -- a mandatory Redis persistence
        # write failing for one ticker (see _enter_risk_degraded) means
        # this process can't trust risk-state integrity for ANY ticker,
        # so every candidate is suppressed here regardless of which
        # ticker triggered the degradation. This is a fast, cheap
        # early-exit; _publish_signal below has the AUTHORITATIVE final
        # gate, which also covers candidates already sitting in
        # _pending_candidates from before degradation began.
        if self._risk_degraded:
            self._signals_suppressed_risk_degraded += len(signals)
            await _incr_metric(self._client, "quant", "dropped_risk_degraded", len(signals))
            await self._record_rejection(
                event.symbol, "GLOBAL_RISK_DEGRADED", len(signals), datetime.now(timezone.utc), signals,
            )
            logger.info(
                "Suppressed %d candidate(s) for %s -- GLOBAL_RISK_DEGRADED "
                "(mandatory Redis risk-state persistence unavailable)",
                len(signals), event.symbol,
            )
            return

        # UK Operating Window (2026-08-16 quant audit, round 5): checked
        # against the CURRENT wall-clock instant (never the bar's own
        # timestamp, and never derived from when this process started --
        # see is_operating_window_open's own docstring), early and
        # per-ticker-uniformly, same posture as GLOBAL_RISK_DEGRADED
        # above. "08:00-22:00 Monday-Friday is a trading-session rule,
        # not an application-startup rule" -- TalonX may be started at
        # any time of day (mid-session, before the window opens, on a
        # weekend after an unplanned restart) and this check's answer
        # depends only on the CURRENT UK date/time. This is a fast,
        # cheap early-exit; _revalidate_candidate below has the
        # AUTHORITATIVE final check, since a candidate can be generated
        # just before 22:00 and not reach actual publication until after
        # it.
        if not is_operating_window_open():
            self._signals_suppressed_uk_session_closed += len(signals)
            await _incr_metric(self._client, "quant", "dropped_uk_session_closed", len(signals))
            await self._record_rejection(
                event.symbol, "UK_SESSION_CLOSED", len(signals), datetime.now(timezone.utc), signals,
            )
            logger.info(
                "Suppressed %d candidate(s) for %s -- outside TalonX's UK operating "
                "window (Mon-Fri 08:00-22:00 Europe/London)",
                len(signals), event.symbol,
            )
            return

        # US Market Closed Session Rejection (2026-08-18 correctness fix,
        # code-review finding #5): session=="closed" (outside 04:00-16:00
        # ET -- talonx_quant.session.get_session) previously had NO
        # dedicated gate below -- every check from here on is either
        # unconditional or specifically keyed on "pre_market", so a
        # closed-session candidate (e.g. from a still-polling yfinance
        # source overnight) could reach evaluation/scoring/publication on
        # the same footing as a genuine regular-session one. This is a
        # SEPARATE, orthogonal concept from the UK operating window check
        # above (is_operating_window_open): that gates WHEN TalonX itself
        # is allowed to publish (an operator schedule); this gates
        # WHETHER the US equities market is even open right now,
        # regardless of TalonX's own schedule. All signals from one
        # evaluate_signals() call share the same triggering bar and
        # therefore the same .session (see strategy.py/schemas.py).
        if signals and signals[0].session == "closed":
            self._signals_suppressed_us_session_closed += len(signals)
            await _incr_metric(self._client, "quant", "dropped_us_session_closed", len(signals))
            await self._record_rejection(
                event.symbol, "US_MARKET_SESSION_CLOSED", len(signals), datetime.now(timezone.utc), signals,
            )
            logger.info(
                "Suppressed %d candidate(s) for %s -- US equities market session is closed",
                len(signals), event.symbol,
            )
            return

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

        # Trend Alignment Gate, HTF-unavailable leg (2026-08-16 quant
        # audit, round 3): trend_aligned is None both when the gate
        # genuinely doesn't apply (bearish, pre-market, gate disabled)
        # AND when it DOES apply but the 15m-200-SMA buffer hasn't warmed
        # up yet (htf_sma_200 is None) -- the old `is not False` filter
        # below treated both cases identically, silently letting a
        # regular-session bullish candidate through with NO trend
        # confirmation at all whenever the HTF buffer was still cold.
        # Separated out here as its own gate/reason so a mandatory-gate
        # candidate with genuinely missing data is rejected and logged
        # distinctly from one that was actually evaluated and passed.
        survivors, dropped_for_missing_htf = _partition(
            survivors, lambda s: not (_trend_gate_applicable(s, self.config) and s.htf_sma_200 is None)
        )
        if dropped_for_missing_htf:
            await self._record_rejection(
                event.symbol, "HTF_DATA_UNAVAILABLE", len(dropped_for_missing_htf),
                datetime.now(timezone.utc), dropped_for_missing_htf,
            )
        self._signals_suppressed_htf_unavailable += len(dropped_for_missing_htf)
        await _incr_metric(self._client, "quant", "failed_htf_unavailable", len(dropped_for_missing_htf))
        if not survivors:
            logger.info(
                "Suppressed %d candidate(s) for %s -- 15m 200 SMA buffer still warming up",
                len(dropped_for_missing_htf), event.symbol,
            )
            return

        # Trend Alignment Gate, misaligned leg: drop a BULLISH,
        # regular-session candidate whose price is at/below the 15m 200
        # SMA. trend_aligned is None (not applicable, or already handled
        # by the HTF-unavailable leg above) for every candidate this
        # doesn't apply to, which passes through unfiltered here.
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
        #
        # 2026-08-18 correctness fix (code-review finding #2): a provider
        # that has NEVER delivered a genuine bid/ask QUOTE event for this
        # ticker (yfinance -- see talonx_ingest/market_data/yfinance_poll.py,
        # which only ever emits BAR events; only polygon_ws.py constructs
        # QUOTE events with bid/ask) is distinguished here from one that
        # HAS delivered a quote but it fails the freshness/spread/dollar-
        # volume check. Both outcomes still REJECT the candidate -- this
        # gate remains exactly as fail-closed as before, no pass/fail
        # behavior changes -- but the audit trail now says WHY:
        # PREMARKET_PROVIDER_UNSUPPORTED (no quote capability at all,
        # e.g. running on yfinance) vs PREMARKET_LIQUIDITY (a quote WAS
        # available and was genuinely too thin/stale/wide, or dollar
        # volume was too low).
        survivors, dropped_for_provider = _partition(
            survivors, lambda s: s.session != "pre_market" or self._latest_quotes.get(s.ticker.upper()) is not None
        )
        if dropped_for_provider:
            await self._record_rejection(
                event.symbol, "PREMARKET_PROVIDER_UNSUPPORTED", len(dropped_for_provider),
                datetime.now(timezone.utc), dropped_for_provider,
            )
        self._signals_suppressed_premarket_provider_unsupported += len(dropped_for_provider)
        await _incr_metric(self._client, "quant", "failed_premarket_provider_unsupported", len(dropped_for_provider))
        if not survivors:
            logger.info(
                "Suppressed %d candidate(s) for %s -- pre-market quote capability unavailable from current provider",
                len(dropped_for_provider), event.symbol,
            )
            return

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

    def _in_memory_lock_active(self, fallback: dict[str, datetime], ticker: str) -> bool:
        """Fail-Closed Lock Persistence: True if `ticker` has a still-live
        in-memory fallback lock (see _start_cooldown/_start_loss_lockout
        below) -- checked BEFORE the Redis read so a lock this process
        couldn't persist to Redis is still enforced for its intended
        duration, purely from local state. Expired entries are pruned on
        read rather than needing a separate sweep."""
        key = ticker.upper()
        expiry = fallback.get(key)
        if expiry is None:
            return False
        if datetime.now(timezone.utc) >= expiry:
            del fallback[key]
            return False
        return True

    async def _is_on_cooldown(self, ticker: str) -> bool:
        if self._in_memory_lock_active(self._cooldown_fallback, ticker):
            return True
        try:
            return bool(await self._client.exists(f"cooldown:{ticker.upper()}"))
        except Exception as exc:  # noqa: BLE001 -- see _handle_risk_check_failure for the fail-closed policy
            return await self._handle_risk_check_failure(ticker, "Cooldown", exc)

    async def _start_cooldown(self, ticker: str) -> None:
        try:
            await self._client.set(
                f"cooldown:{ticker.upper()}", "1", ex=int(self.config.cooldown_seconds)
            )
            self._cooldown_fallback.pop(ticker.upper(), None)
        except Exception as exc:  # noqa: BLE001 -- see the in-memory fallback lock below
            self._arm_fallback_lock(
                self._cooldown_fallback, ticker, self.config.cooldown_seconds, "Cooldown", exc,
            )

    async def _is_loss_locked_out(self, ticker: str) -> bool:
        if self._in_memory_lock_active(self._loss_lockout_fallback, ticker):
            return True
        try:
            return bool(await self._client.exists(f"loss_lockout:{ticker.upper()}"))
        except Exception as exc:  # noqa: BLE001 -- see _handle_risk_check_failure for the fail-closed policy
            return await self._handle_risk_check_failure(ticker, "Loss-lockout", exc)

    def _arm_fallback_lock(
        self, fallback: dict[str, datetime], ticker: str, duration_seconds: float,
        lock_name: str, exc: Exception,
    ) -> None:
        """Fail-Closed Lock Persistence (2026-08-16 quant audit, round 3):
        a Redis SET failure while ARMING a lock (as opposed to a Redis
        error while CHECKING one, see _handle_risk_check_failure) used to
        only log a warning and move on -- the lock then silently never
        took effect, so e.g. a losing trade's mandatory lockout, or a
        just-published signal's cooldown, could leave that ticker free to
        trade again immediately. Enforces the SAME lock, for the SAME
        duration, purely from process-local memory (see
        _in_memory_lock_active) until either it naturally expires or a
        LATER SET for this ticker succeeds and clears it (see the
        `.pop()` calls in _start_cooldown/_start_loss_lockout above).
        Logged at CRITICAL, matching _handle_risk_check_failure's
        severity -- this is a risk-control gap, not a routine hiccup."""
        key = ticker.upper()
        expiry = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        fallback[key] = expiry
        logger.critical(
            "%s lock persistence failed for %s (%s); enforcing in-memory fallback lock until %s",
            lock_name, ticker, exc, expiry.isoformat(),
        )
        self._enter_risk_degraded(f"{lock_name} persistence failed for {ticker}: {exc}")

    def _enter_risk_degraded(self, reason: str) -> None:
        """GLOBAL_RISK_DEGRADED (2026-08-16 quant audit, round 4): a
        mandatory risk-state persistence WRITE (loss-lockout or cooldown,
        via _arm_fallback_lock above) failed. The per-ticker in-memory
        fallback lock _arm_fallback_lock also arms remains an ADDITIONAL
        defense for the one ticker involved, but it must not be the ONLY
        response: a write failure on ANY ticker's mandatory lock means
        this process can no longer guarantee risk-state integrity FOR ANY
        TICKER -- this is a risk-control failure, not a ticker-specific
        market condition (e.g. AAPL's cooldown SET failing says nothing
        about whether MSFT or NVDA are actually safe to trade; it says
        Redis itself can't be trusted right now). ALL subsequent signal
        publication is blocked process-wide (see the gates in
        _handle_market_tick and _publish_signal) until
        _reconcile_risk_state confirms Redis can persist writes again --
        connectivity (PING) alone does not clear this, see
        _verify_redis_persistence."""
        was_degraded = self._risk_degraded
        self._risk_degraded = True
        if not was_degraded:
            logger.critical(
                "GLOBAL_RISK_DEGRADED entered (%s) -- blocking ALL signal publication "
                "process-wide until Redis persistence is reconciled.", reason,
            )

    async def _verify_redis_persistence(self) -> bool:
        """Round-4 quant audit, Requirement 8: PING succeeding is NOT
        sufficient to trust Redis for mandatory risk-state persistence --
        a reachable Redis can still fail to durably accept a write (mid
        failover, a read-only replica, disk full, quota/eviction
        rejecting the write, etc.), none of which PING alone would ever
        surface. Writes a short-TTL canary key and reads the exact value
        back; only a confirmed roundtrip counts as verified. Used both at
        connect/reconnect time and periodically while GLOBAL_RISK_DEGRADED
        (see _reconcile_risk_state)."""
        if self._client is None:
            return False
        key = "talonx:quant:risk_state_healthcheck"
        probe = str(datetime.now(timezone.utc).timestamp())
        try:
            await self._client.set(key, probe, ex=30)
            readback = await self._client.get(key)
            if isinstance(readback, bytes):
                readback = readback.decode()
            return readback == probe
        except Exception as exc:  # noqa: BLE001 -- any failure here means "not verified healthy"
            logger.warning("Redis persistence verification failed: %s", exc)
            return False

    async def _reconcile_risk_state(self) -> None:
        """Risk-State Reconciliation (2026-08-16 quant audit, round 4,
        Requirements 3/8/12): the single place GLOBAL_RISK_DEGRADED is
        cleared. Run once at the START of every _connect_and_listen call
        (BOTH a genuine process startup -- e.g. the Mon-Fri 08:00 UK
        Task-Scheduler-driven launch -- AND every reconnect after a
        dropped connection, which is exactly the boundary the existing
        reconnect-backoff loop already provides, so no separate 24x7
        monitoring process is needed for that case) and again on every
        _checkpoint_loop tick WHILE already degraded (covers a live
        connection that stays up but individual commands are failing).
        Clears the flag ONLY on a confirmed write-verify
        (_verify_redis_persistence) -- a bare successful PING is
        deliberately not enough (Requirement 8).

        Per-ticker cooldown/loss-lockout state itself needs NO separate
        reconciliation step: _is_on_cooldown/_is_loss_locked_out already
        read `EXISTS cooldown:{TICKER}`/`loss_lockout:{TICKER}` LIVE from
        Redis on every candidate, never from process-local memory, so a
        still-valid TTL'd lock from a PRIOR run (e.g. one still active
        when Friday's process stopped) is honoured automatically the
        moment this process starts checking again -- there is no
        in-memory copy of that state to go stale or need reloading. An
        expired lock is equally simple: Redis's own TTL has already
        removed the key, so EXISTS just returns false, same as any other
        key that was never set. GLOBAL_RISK_DEGRADED itself is NEVER
        persisted to Redis (see _enter_risk_degraded) -- it is this
        process's own in-memory safety state, and naturally disappears
        (acceptably -- see this module's own docstring) when the process
        stops; the NEXT run/reconnect re-derives it fresh, from scratch,
        via this method."""
        healthy = await self._verify_redis_persistence()
        was_degraded = self._risk_degraded
        self._risk_degraded = not healthy
        if healthy and was_degraded:
            logger.info(
                "GLOBAL_RISK_DEGRADED cleared -- Redis write persistence confirmed, "
                "resuming signal publication."
            )
        elif healthy:
            logger.info("Risk-state reconciliation: Redis write persistence confirmed.")
        elif was_degraded:
            logger.critical(
                "GLOBAL_RISK_DEGRADED: Redis write persistence still not confirmed -- "
                "remaining degraded, no signal publication."
            )
        else:
            logger.critical(
                "GLOBAL_RISK_DEGRADED: Redis write persistence could not be confirmed at "
                "connect -- blocking ALL signal publication until reconciled."
            )

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
            self._loss_lockout_fallback.pop(ticker.upper(), None)
        except Exception as exc:  # noqa: BLE001 -- see the in-memory fallback lock below
            self._arm_fallback_lock(
                self._loss_lockout_fallback, ticker, self.config.loss_lockout_seconds, "Loss-lockout", exc,
            )

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
        closed. Re-checks age and re-derives the FULL trade geometry
        (stop, target, risk, reward, ratio -- via strategy.py's
        calculate_trade_geometry, the same function _build_signal uses)
        against the LATEST buffered close before publishing, rather than
        trusting stale numbers.

        2026-08-16 quant audit (round 3): a prior version of this method
        only recalculated `price` and `risk_reward_ratio`, leaving
        stop_price/target_price pinned to the ORIGINAL entry price -- a
        published signal could show a ratio measured against the new
        price alongside a stop/target still measured against the old
        one, an internally inconsistent trade. Routing through
        calculate_trade_geometry means price/stop/target/ratio always
        move together. Risk stays atr_stop_multiplier x the signal's OWN
        atr (ATR itself doesn't meaningfully change over a 15-30s window,
        and re-running full indicator computation here would be wasted
        work). Returns None if the candidate should be dropped instead of
        published.

        2026-08-16 quant audit (round 5): also the AUTHORITATIVE final
        check of TalonX's UK operating window (see
        is_operating_window_open) -- the early per-tick check in
        _handle_market_tick only catches a candidate EVALUATED after the
        window closed; a candidate generated at 21:59:50 can still sit
        in the throttle buffer past 22:00:00 and reach THIS point after
        the window has closed. Checked first, before age/geometry, since
        a closed window makes every other check moot."""
        if not is_operating_window_open():
            logger.info(
                "Dropping %s %s -- TalonX's UK operating window closed before final "
                "revalidation (Mon-Fri 08:00-22:00 Europe/London)",
                signal.ticker, signal.signal_type.value,
            )
            await self._record_rejection(
                signal.ticker, "UK_SESSION_CLOSED", 1, now, [signal],
            )
            return None

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
            # Final Revalidation Data Availability (2026-08-16 quant
            # audit, round 4, Requirement 10): a PRIOR version of this
            # method published the candidate as-generated here (its
            # original, now-UNVERIFIED geometry) on the reasoning that
            # strategy.py's own gate had already confirmed a valid
            # geometry at generation time. That is no longer good enough
            # -- final publication must be based on a VERIFIED CURRENT
            # trade geometry, not an assumed-still-good stale one. If
            # fresh price/ATR/pivot data can't be obtained at this final
            # revalidation step, the candidate is rejected outright
            # rather than published on faith.
            logger.info(
                "Dropping %s %s -- fresh market data unavailable for final revalidation",
                signal.ticker, signal.signal_type.value,
            )
            await self._record_rejection(
                signal.ticker, "FINAL_REVALIDATION_DATA_UNAVAILABLE", 1, now, [signal],
            )
            return None

        geometry = calculate_trade_geometry(
            current_price, signal.atr, signal.direction,
            signal.pivot_resistance, signal.pivot_support, self.config,
        )
        if geometry is None or geometry.risk_reward_ratio is None:
            # The pivot level no longer sits on the tradeable side of the
            # new price (price has drifted through it), or risk resolved
            # to <= 0 -- can't confirm a valid geometry against the fresh
            # price, so this is a degraded candidate, not merely a stale
            # one.
            logger.info(
                "Dropping %s %s -- R:R could not be confirmed against current price %.2f during throttle wait",
                signal.ticker, signal.signal_type.value, current_price,
            )
            await self._record_rejection(
                signal.ticker, "RR_DEGRADED_DURING_THROTTLE", 1, now, [signal],
            )
            return None

        if geometry.risk_reward_ratio < self.config.min_risk_reward_ratio:
            logger.info(
                "Dropping %s %s -- R:R degraded to %.2f during throttle wait (was %.2f, needs >= %.2f)",
                signal.ticker, signal.signal_type.value, geometry.risk_reward_ratio,
                signal.risk_reward_ratio or 0.0, self.config.min_risk_reward_ratio,
            )
            await self._record_rejection(
                signal.ticker, "RR_DEGRADED_DURING_THROTTLE", 1, now, [signal],
            )
            return None

        return signal.model_copy(update={
            "price": current_price,
            "stop_price": geometry.stop_price,
            "target_price": geometry.target_price,
            "risk_reward_ratio": geometry.risk_reward_ratio,
            "signal_age_ms": signal_age_ms,
            # Task 35: the geometry re-derived above may have picked a
            # DIFFERENT path than the one recorded at signal generation
            # (e.g. price drifted through the structural level between
            # generation and this final pre-publish revalidation) -- these
            # must move together with stop_price/target_price/ratio, same
            # reasoning as the rest of this update dict.
            "geometry_path": geometry.geometry_path,
            "fallback_reason": geometry.fallback_reason,
            "structural_level": geometry.structural_level,
            "structural_level_type": geometry.structural_level_type,
        })

    async def _flush_throttle_window(self) -> None:
        if not self._pending_candidates:
            return

        candidates, self._pending_candidates = self._pending_candidates, []
        candidates.sort(key=lambda sig: _opportunity_score(sig, self.config), reverse=True)

        released, dropped = candidates[: self.config.throttle_max_signals], candidates[self.config.throttle_max_signals :]
        now = datetime.now(timezone.utc)
        for signal in released:
            # Intra-Flush Cooldown Re-Check (2026-08-16 quant audit, P1):
            # strategy.py can legitimately emit MULTIPLE independent
            # candidates for the SAME ticker off the same closed bar
            # (e.g. a MACD cross AND an RSI/volume setup), which can
            # both land in `released` together. Without this check, the
            # FIRST such candidate to publish arms cooldown:{TICKER} (see
            # _publish_signal's Post-Publication Cooldown Trigger) only
            # AFTER the second candidate had already been let past the
            # cooldown check it saw back when it first entered the queue
            # (_handle_market_tick, up to throttle_window_seconds
            # earlier) -- letting two signals for the same ticker publish
            # out of one flush, defeating the whole point of the
            # per-ticker cooldown. Re-checking HERE, immediately before
            # each candidate is allowed to proceed toward publication,
            # catches a cooldown armed by an EARLIER candidate in this
            # SAME loop (as well as one that already existed before this
            # flush even started, in which case revalidation/publish
            # work for this candidate is skipped entirely, not merely
            # its publish). Reuses _is_on_cooldown as-is -- same
            # fail-closed-on-Redis-error policy as every other cooldown
            # check in this module (see _handle_risk_check_failure), no
            # new fail-open path. Placed BEFORE _revalidate_candidate
            # (not just before _publish_signal) so a candidate that's
            # already doomed to a COOLDOWN rejection doesn't also pay
            # for a wasted current-price/geometry re-fetch.
            if await self._is_on_cooldown(signal.ticker):
                self._signals_suppressed_cooldown += 1
                logger.info(
                    "Dropping %s %s -- %s entered cooldown earlier in this "
                    "same throttle flush (or was already on cooldown)",
                    signal.ticker, signal.signal_type.value, signal.ticker,
                )
                await self._record_rejection(
                    signal.ticker, "COOLDOWN", 1, now, [signal],
                )
                continue

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
        # GLOBAL_RISK_DEGRADED (2026-08-16 quant audit, round 4): the
        # AUTHORITATIVE final gate -- every path to an actual Redis
        # publish funnels through this one method, for every ticker, so
        # this single check is what makes the degraded state truly
        # process-wide rather than per-ticker. Also covers a candidate
        # that was already sitting in _pending_candidates (queued for up
        # to throttle_window_seconds) BEFORE degradation began -- the
        # early per-tick gate in _handle_market_tick only catches
        # candidates evaluated AFTER degradation starts.
        if self._risk_degraded:
            logger.warning(
                "Dropping %s %s at publish time -- GLOBAL_RISK_DEGRADED", signal.ticker, signal.signal_type.value,
            )
            await self._record_rejection(
                signal.ticker, "GLOBAL_RISK_DEGRADED", 1, datetime.now(timezone.utc), [signal],
            )
            return
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
