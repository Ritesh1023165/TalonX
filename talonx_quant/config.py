"""
talonx_quant.config
----------------------
All settings for the Technical & Quantitative Scanner, env-driven.

Deliberately self-contained at the CODE level (no import of talonx_ingest
Python objects) so this module can run as an independent process/service
consuming only the Redis wire contract -- matching the module boundary in
the project spec (its only real dependencies are redis.asyncio, pandas,
and pandas_ta).

It DOES share a .env FILE with the rest of the project, though -- every
module needs the same TALONX_REDIS_URL to actually talk to each other via
Redis, and maintaining a separate .env file per module with the same
values would just be a drift risk. Sharing a config file is not a code
dependency.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv


class VolatilityGateMode(str, Enum):
    """Task 45: which volatility ELIGIBILITY implementation is authoritative
    for candidate generation. Exactly two modes, no more -- see
    docs/research/TALONX_RESEARCH_LEDGER.md's Task 45 entry for why a third
    variant was deliberately not added.

    CURRENT_1M (the default, and the ONLY mode talonx_quant.consumer.
    QuantScanner -- live/paper-shadow -- will ever accept; it fails fast at
    construction otherwise) is byte-for-byte the pre-Task-45 behavior:
    talonx_quant.consumer._fails_min_volatility, unchanged.

    MULTITIMEFRAME_EXPERIMENTAL is research/backtest-only (talonx_backtest.
    BacktestEngine): the Task 41/42 Contract B evaluator
    (talonx_quant.indicators.evaluate_regime) becomes the active gate
    instead. Provisional research calibration thresholds -- see
    talonx_quant.indicators.PROVISIONAL_REGIME_15M_THRESHOLD_PCT/
    PROVISIONAL_REGIME_60M_THRESHOLD_PCT."""
    CURRENT_1M = "CURRENT_1M"
    MULTITIMEFRAME_EXPERIMENTAL = "MULTITIMEFRAME_EXPERIMENTAL"


class ConfluenceContract(str, Enum):
    """Task 51: which confluence/confirmation implementation is authoritative
    for candidate scoring. Exactly two modes, mirroring VolatilityGateMode's
    own LEGACY/EXPERIMENTAL split above.

    LEGACY (the default, and the ONLY mode talonx_quant.consumer.QuantScanner
    -- live/paper-shadow -- will ever accept; it fails fast at construction
    otherwise) is byte-for-byte the pre-Task-51 behavior: strategy.py's
    _confluence_score (Task 49's MACD-no-self-credit fix included), gated by
    confluence_score_min in consumer.py/talonx_backtest.engine.

    INDEPENDENT_CONFIRMATION_EXPERIMENTAL is research/backtest-only
    (talonx_backtest.BacktestEngine): strategy.py's
    evaluate_independent_confirmations becomes authoritative instead --
    TRIGGER + AT LEAST ONE independent, directionally-supportive
    confirmation, family-aware (see that function's own docstring).
    Eligibility becomes confirmation_count >= 1, not confluence_score_min."""
    LEGACY = "LEGACY"
    INDEPENDENT_CONFIRMATION_EXPERIMENTAL = "INDEPENDENT_CONFIRMATION_EXPERIMENTAL"


def _load_dotenv() -> None:
    """
    Loads the shared .env file at the repo root, if present. `override=False`:
    real environment variables always win over .env, same precedence rule
    as talonx_ingest.config.

    Resolved relative to this file's location (../.env from here), not the
    current working directory, so it's found reliably regardless of where
    you run `python -m talonx_quant.run` from.
    """
    shared_env = Path(__file__).resolve().parent.parent / ".env"
    if shared_env.is_file():
        load_dotenv(shared_env, override=False)


_load_dotenv()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class QuantConfig:
    # --- Redis ---
    redis_url: str = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")
    market_stream_channel: str = os.environ.get(
        "TALONX_REDIS_MARKET_CHANNEL", "talonx:market:stream"
    )
    signals_channel: str = os.environ.get(
        "TALONX_REDIS_SIGNALS_CHANNEL", "talonx:signals:quant"
    )
    # Rejection Trace Logging: one RejectedCandidateEvent per candidate a
    # gate drops (confluence, structural R:R, trend, ATR move/volatility,
    # blackout, cooldown, loss-lockout, throttle, pre-market liquidity/
    # news-catalyst) -- consumed by talonx_dispatch purely to keep a
    # durable, per-candidate audit trail (see talonx_dispatch/store.py's
    # rejected_candidates table), since a dropped candidate otherwise
    # never reaches that module at all. Same env var name talonx_dispatch
    # reads on its side of this boundary.
    rejected_candidates_channel: str = os.environ.get(
        "TALONX_REDIS_REJECTED_CANDIDATES_CHANNEL", "talonx:quant:rejected"
    )
    connect_timeout_seconds: float = _env_float("TALONX_REDIS_CONNECT_TIMEOUT", 5.0)
    socket_timeout_seconds: float = _env_float("TALONX_REDIS_SOCKET_TIMEOUT", 5.0)
    reconnect_backoff_base_seconds: float = _env_float("TALONX_QUANT_RECONNECT_BASE", 1.0)
    reconnect_backoff_max_seconds: float = _env_float("TALONX_QUANT_RECONNECT_MAX", 30.0)

    # --- Rolling buffer ---
    # How many bars to keep per symbol. Indicators need enough history to be
    # meaningful (MACD's slow EMA alone wants 26+ periods) but an unbounded
    # buffer would grow forever for a long-running process -- this caps
    # memory per symbol regardless of how long the process has been running.
    max_bars_per_symbol: int = _env_int("TALONX_QUANT_MAX_BARS", 200)

    # Bar-Level Ingestion Idempotency (2026-08-16 quant audit): a Redis
    # SETNX key (`processed_bar:{TICKER}:{tick_timestamp}`) per incoming
    # BAR tick, TTL'd for this long -- guards against a Pub/Sub reconnect
    # or upstream retry redelivering the EXACT same tick, which would
    # otherwise double-count that tick's volume in the still-forming
    # bucket's running accumulation (buffer.add_bar's own upsert-by-
    # timestamp only dedupes the FINAL row per bucket, not each tick
    # feeding it) or spuriously re-trigger Closed-Bar Evaluation. 600s
    # (10 min) comfortably covers any realistic reconnect-storm replay
    # window without the dedup set growing unbounded. See
    # consumer.py's _is_new_bar_tick for the in-memory fallback used
    # when Redis itself is unavailable.
    bar_dedup_ttl_seconds: float = _env_float("TALONX_QUANT_BAR_DEDUP_TTL_SECONDS", 600.0)

    # --- Indicator parameters ---
    rsi_period: int = _env_int("TALONX_QUANT_RSI_PERIOD", 14)
    macd_fast: int = _env_int("TALONX_QUANT_MACD_FAST", 12)
    macd_slow: int = _env_int("TALONX_QUANT_MACD_SLOW", 26)
    macd_signal: int = _env_int("TALONX_QUANT_MACD_SIGNAL", 9)
    ma_fast_period: int = _env_int("TALONX_QUANT_MA_FAST", 10)
    ma_slow_period: int = _env_int("TALONX_QUANT_MA_SLOW", 50)
    volume_avg_period: int = _env_int("TALONX_QUANT_VOLUME_AVG_PERIOD", 20)

    # Minimum bars required before ANY indicator is computed. Should be at
    # least macd_slow + macd_signal for a meaningful MACD reading, and at
    # least ma_slow_period + 1 for crossover detection (need a "previous"
    # value too). Left independently configurable rather than derived, so
    # it's explicit and can be tuned without doing the math each time.
    # 120 (not just macd_slow+macd_signal=35) per an investment-analyst
    # review of live paper trading results: an EMA is mathematically
    # defined from its first bar, but its value is still biased toward
    # its seed for a while after that -- 120 bars gives MACD's 26-period
    # EMA roughly 4-5x its own period to settle before this module trusts
    # a crossover, well under max_bars_per_symbol's 200-bar cap above.
    min_bars_required: int = _env_int("TALONX_QUANT_MIN_BARS", 120)

    # --- Signal trigger thresholds ---
    rsi_oversold: float = _env_float("TALONX_QUANT_RSI_OVERSOLD", 30.0)
    rsi_overbought: float = _env_float("TALONX_QUANT_RSI_OVERBOUGHT", 70.0)
    volume_surge_ratio_threshold: float = _env_float(
        "TALONX_QUANT_VOLUME_SURGE_RATIO", 2.0
    )

    # --- Noise filters ---
    # Per-ticker cooldown: once a signal fires for a ticker, a Redis key
    # `cooldown:{TICKER}` locks out ANY further signal for that ticker
    # (regardless of signal_type) until it expires. Default 20 minutes --
    # the middle of the requested 15-30 minute range. This is what stops
    # e.g. an RSI+volume setup at 15:01 and an unrelated MACD cross at
    # 15:12 on the same ticker from both alerting. Armed on actual
    # PUBLICATION (see consumer.py's _publish_signal), not merely on a
    # candidate surviving strategy.py's gates -- a candidate the batch
    # throttle later drops must not still burn the ticker's cooldown
    # slot (2026-08-16 quant audit: Post-Publication Cooldown Trigger).
    cooldown_seconds: float = _env_float("TALONX_QUANT_COOLDOWN_SECONDS", 1200.0)

    # Fail-closed risk gates (2026-08-16 quant audit): if Redis itself is
    # unreachable, _is_on_cooldown/_is_loss_locked_out can no longer
    # answer "is this ticker actually safe to trade" at all -- treating
    # that as "assume no" (the previous behavior) let candidates publish
    # during a genuine risk-state blackout. Default True: an exception
    # from either check is treated as "yes, blocked" (fail closed) rather
    # than "no, clear to trade" (fail open). Set False only as an
    # explicit, deliberate opt back into the old fail-open behavior.
    risk_check_fail_closed: bool = _env_bool("TALONX_QUANT_RISK_FAIL_CLOSED", True)

    # Minimum SMA fast/slow separation, as a fraction of price, required at
    # the crossover bar for a MA_GOLDEN_CROSS/MA_DEATH_CROSS to fire.
    # Filters out e.g. a $0.03 drift on a $500 stock (0.006%, far under the
    # 0.15% default) -- a real crossover event that's too small to matter.
    # Deliberately scoped to the SMA cross only, not MACD, per spec.
    min_ma_spread_pct: float = _env_float("TALONX_QUANT_MIN_MA_SPREAD_PCT", 0.0015)

    # Batch throttle: across ALL tickers, at most this many signals are
    # released per throttle_window_seconds, ranked by a weighted
    # Composite Opportunity Score (see consumer.py's _opportunity_score).
    # Candidates are buffered for the full window before any of them are
    # released -- see consumer.py's _flush_throttle_window -- so a signal
    # can be delayed by up to throttle_window_seconds, or dropped
    # entirely if it doesn't rank in the top throttle_max_signals that
    # window. 15s default (2026-08-16 quant audit: down from 60s) --
    # a candidate's entry price/R:R can drift materially over a full
    # minute of sitting in the buffer; a shorter window bounds that drift
    # before Dynamic R:R Revalidation (max_candidate_age_seconds below)
    # even has to reject anything for staleness.
    throttle_window_seconds: float = _env_float("TALONX_QUANT_THROTTLE_WINDOW_SECONDS", 15.0)
    throttle_max_signals: int = _env_int("TALONX_QUANT_THROTTLE_MAX_SIGNALS", 3)

    # Dynamic R:R Revalidation (2026-08-16 quant audit): a candidate
    # selected at throttle flush is re-evaluated against the LATEST
    # buffered close before it's actually published -- see
    # consumer.py's _revalidate_candidate. Older than this many seconds
    # (measured from QuantSignal.signal_generated_at) -> dropped as
    # EXPIRED_IN_THROTTLE_QUEUE regardless of price; still fresh enough
    # but its recalculated R:R (reward to the SAME pivot level / risk =
    # atr_stop_multiplier x the signal's own ATR) now sits below
    # min_risk_reward_ratio -> dropped as RR_DEGRADED_DURING_THROTTLE.
    # Deliberately double the throttle window (15s) rather than equal to
    # it -- a candidate generated right at the START of a window and
    # flushed at the END is already throttle_window_seconds old before
    # revalidation even runs.
    max_candidate_age_seconds: float = _env_float("TALONX_QUANT_MAX_CANDIDATE_AGE_SECONDS", 30.0)

    # Composite Opportunity Score weights (2026-08-16 quant audit, P1) --
    # replaces the old (confluence_score, volume_surge_ratio) tuple-sort,
    # whose raw-ratio tiebreaker systematically favored penny/meme-stock
    # pumps (huge surge ratios on a thin baseline volume) over a
    # higher-conviction, better-risk-reward setup on a liquid large-cap
    # with a smaller relative surge. Each factor is normalized to [0, 1]
    # before weighting (confluence_score/3, min(risk_reward_ratio/
    # opportunity_score_rr_cap, 1), min(volume_surge_ratio/
    # opportunity_score_volume_cap, 1), and 1.0/0.5/0.0 for
    # trend_aligned True/None/False) so no single unbounded input can
    # dominate the ranking on scale alone. Weights sum to 1.0 by default
    # but aren't required to -- only their RELATIVE size matters for
    # ranking.
    opportunity_score_confluence_weight: float = _env_float("TALONX_QUANT_OPPORTUNITY_CONFLUENCE_WEIGHT", 0.35)
    opportunity_score_rr_weight: float = _env_float("TALONX_QUANT_OPPORTUNITY_RR_WEIGHT", 0.30)
    opportunity_score_volume_weight: float = _env_float("TALONX_QUANT_OPPORTUNITY_VOLUME_WEIGHT", 0.20)
    opportunity_score_trend_weight: float = _env_float("TALONX_QUANT_OPPORTUNITY_TREND_WEIGHT", 0.15)
    # R:R of 5:1 and a 10x volume surge are both treated as "maxed out"
    # (normalized to 1.0) -- comfortably above what min_risk_reward_ratio
    # (1.5) and the surge thresholds (2.0x/3.0x) require, so a genuinely
    # exceptional setup doesn't need an even MORE extreme reading to rank
    # at the top of its factor.
    opportunity_score_rr_cap: float = _env_float("TALONX_QUANT_OPPORTUNITY_RR_CAP", 5.0)
    opportunity_score_volume_cap: float = _env_float("TALONX_QUANT_OPPORTUNITY_VOLUME_CAP", 10.0)

    # --- Analyst-review filters (added after a live paper-trading review
    # found a 0.33 profit factor and a 25% win rate, with 3 consecutive
    # SMCI losses accounting for 93% of session losses) ---

    # 14-period Average True Range, in the SAME units as price -- the
    # basis for both the movement-confirmation gate and the risk/reward
    # filter below.
    atr_period: int = _env_int("TALONX_QUANT_ATR_PERIOD", 14)

    # A candidate signal's own bar must move at least this many multiples
    # of ATR (true range: max(high-low, |high-prev_close|, |low-prev_close|))
    # to count as a real directional move rather than routine noise on a
    # high-beta name -- applied inside strategy.py's own edge-trigger
    # checks (an ADDITIONAL condition, alongside each check's existing
    # RSI/MACD/MA logic), not a separate downstream filter.
    atr_move_multiplier: float = _env_float("TALONX_QUANT_ATR_MOVE_MULTIPLIER", 1.0)

    # Confluence score: +1 each for a MACD cross firing this bar, +1 when
    # current RSI is in the direction-supporting extreme STATE (< rsi_
    # oversold for a bullish candidate, > rsi_overbought for a bearish
    # one), +1 for volume_surge_ratio > volume_surge_ratio_threshold --
    # computed fresh PER SIGNAL DIRECTION (not once per bar: two opposite-
    # direction signals on the same bar get their own scores) and attached
    # to every signal that fires. A signal below this score is suppressed
    # before it ever reaches the per-ticker cooldown lock or the global
    # throttle.
    #
    # RSI-curl self-exclusion (confirmed intentional, Task 28
    # RSI_CONFLUENCE_STATE_BASED_CONFIRMED, 2026-08-21): RSI_OVERSOLD_
    # VOLUME_SURGE / RSI_OVERBOUGHT_VOLUME_SURGE fire on the RECOVERY bar
    # (RSI has just exited the extreme zone), so the RSI component above
    # is intentionally zero on that same trigger bar -- the trigger and
    # the confluence leg check opposite, complementary conditions on
    # purpose. Such a candidate's score is therefore volume(1) alone
    # unless a same-bar MACD cross also coincides (-> 2, clearing this
    # gate). See results/task28_rsi_confluence_requirement/ and
    # tests/test_quant_strategy.py's "RSI-Curl / Confluence Contract"
    # section for the full requirements analysis and regression coverage.
    confluence_score_min: int = _env_int("TALONX_QUANT_CONFLUENCE_SCORE_MIN", 2)

    # Structural Risk/Reward filter (replaces the old constant-ATR-ratio
    # gate, which compared two fixed ATR multiples against each other and
    # was mathematically constant regardless of market data -- see git
    # history for the prior implementation). Reward is measured to the
    # nearest classic floor-trader PIVOT LEVEL (prior completed regular
    # session's R1/S1 -- see indicators.compute_daily_pivots), a genuine
    # market-derived target rather than another ATR multiple; risk is
    # atr_stop_multiplier x ATR (default 1.5x). A candidate whose
    # prior-session pivot data isn't available yet (cold start, or the
    # HTF buffer hasn't accumulated a full session) gets
    # risk_reward_ratio=None and is dropped by this gate -- same
    # "insufficient data -> no signal" fail-closed posture every other
    # warm-up-dependent check in this module already takes, rather than
    # silently falling back to a non-structural approximation.
    #
    # 2026-08-16 quant-audit fix: atr_stop_multiplier is now the SINGLE
    # source of truth for the risk distance, used identically by
    # _structural_risk_reward's denominator AND _stop_target_prices'
    # EXECUTED dollar stop (see strategy.py's own docstrings). This used
    # to be two separate config values (a `pivot_stop_atr_multiplier`
    # of 1.5x feeding only the gate, a `atr_stop_multiplier` of 1.0x
    # feeding only the executed stop) -- a real trade could pass the
    # gate at a nominal 2.0 R:R while its ACTUAL executed R:R (reward /
    # the tighter 1.0x-ATR stop that was really live) was 3.0, an
    # evaluated-vs-executed discrepancy an independent audit caught by
    # example. One multiplier, one risk distance, everywhere.
    atr_stop_multiplier: float = _env_float("TALONX_QUANT_ATR_STOP_MULTIPLIER", 1.5)
    # Fallback target multiple (see _stop_target_prices) -- only used
    # while a candidate's prior-session pivot data is still warming up;
    # once pivots are available, the target is the structural pivot
    # level instead, not this ATR multiple.
    atr_reward_multiplier: float = _env_float("TALONX_QUANT_ATR_REWARD_MULTIPLIER", 2.0)
    assumed_stop_loss_pct: float = _env_float("TALONX_QUANT_ASSUMED_STOP_LOSS_PCT", 0.005)
    min_risk_reward_ratio: float = _env_float("TALONX_QUANT_MIN_RISK_REWARD_RATIO", 1.5)

    # --- Minimum volatility gate (2026-08-14 session review: ADC, a
    # low-beta REIT, took up an intraday execution slot without enough
    # range to ever reach an ATR-scaled stop/target) -- ATR14/price, as a
    # percentage, must clear this before a bar's momentum indicators are
    # even evaluated. Distinct from atr_move_multiplier above: that gate
    # compares THIS bar's range to its own ATR (routine bar vs. genuine
    # move); this one is a per-symbol volatility floor independent of any
    # single bar. Missing ATR (warm-up) does NOT fail this gate closed --
    # every RSI/MACD/MA check already requires ATR via _clears_atr_move,
    # so an unwarmed symbol produces zero signals downstream regardless.
    min_atr_pct: float = _env_float("TALONX_QUANT_MIN_ATR_PCT", 0.25)

    # --- Task 45: volatility gate mode (research/backtest experimental
    # switch) --- default MUST stay CURRENT_1M; talonx_quant.consumer.
    # QuantScanner (live/paper-shadow) fails fast at construction if this
    # is ever anything else -- see that class's own __init__ guard. The
    # VolatilityGateMode(...) call below raises immediately (fail-closed,
    # not a silent fallback) if the env var holds anything other than one
    # of the two defined enum members.
    volatility_gate_mode: VolatilityGateMode = VolatilityGateMode(
        os.environ.get("TALONX_QUANT_VOLATILITY_GATE_MODE", VolatilityGateMode.CURRENT_1M.value)
    )

    # --- Task 51: confluence/confirmation contract (research/backtest
    # experimental switch) --- default MUST stay LEGACY; talonx_quant.
    # consumer.QuantScanner (live/paper-shadow) fails fast at construction
    # if this is ever anything else -- see that class's own __init__ guard,
    # same fail-closed posture as volatility_gate_mode above.
    confluence_contract: ConfluenceContract = ConfluenceContract(
        os.environ.get("TALONX_QUANT_CONFLUENCE_CONTRACT", ConfluenceContract.LEGACY.value)
    )

    # --- 15-minute 200 SMA higher-timeframe trend gate ---
    # A second, coarser RollingBarBuffer (see consumer.py's buffer_htf),
    # incrementally aggregated from the same 1-min BAR events that feed
    # the primary buffer -- only needs htf_sma_period+a few bars of
    # capacity (~210 rows), far cheaper than inflating the 1-min buffer
    # 15x to resample from scratch. Regular-session, BULLISH-only gate:
    # drops a bullish candidate whose price is at/below the 15m 200 SMA.
    htf_bar_interval_minutes: int = _env_int("TALONX_QUANT_HTF_BAR_INTERVAL_MINUTES", 15)
    htf_sma_period: int = _env_int("TALONX_QUANT_HTF_SMA_PERIOD", 200)
    htf_max_bars: int = _env_int("TALONX_QUANT_HTF_MAX_BARS", 210)
    trend_gate_enabled: bool = _env_bool("TALONX_QUANT_TREND_GATE_ENABLED", True)

    # --- Multi-timeframe volatility REGIME state (Task 40) ---
    # Observability-only 15m/60m ATR% readings, distinct from the 1-min
    # trigger-bar ATR gate above (min_atr_pct) which this does NOT
    # replace or feed into. The 15m leg reuses htf_bar_interval_minutes/
    # htf_max_bars/buffer_htf above unchanged (no separate config); this
    # section adds ONLY the new 60-minute leg's buffer sizing.
    # Deliberately continuous (no rth_only knob here, unlike
    # rth_only_htf_sma below) -- Task 39's design decision, not a
    # runtime-tunable choice.
    regime_60m_bar_interval_minutes: int = _env_int("TALONX_QUANT_REGIME_60M_BAR_INTERVAL_MINUTES", 60)
    regime_60m_max_bars: int = _env_int("TALONX_QUANT_REGIME_60M_MAX_BARS", 60)

    # --- Task 44: 60m regime bootstrap ---
    # Same yfinance 1-minute source (preseed.fetch_1m_history) the
    # existing 1m/15m preseed paths already use -- reused, not a second
    # data-loading system. "5d" was chosen empirically (not a strategy
    # threshold): it comfortably clears both the bare atr_period+1 (14)
    # bars needed for a first ATR reading AND the ~3-5x-period (42-70
    # bars) Wilder-smoothing convergence window the regime leg's own
    # existing atr_period already implies -- see
    # results/task44_60m_warmup_bootstrap/bootstrap_history_coverage.csv
    # for the measured bar counts this period actually returns.
    regime_60m_bootstrap_period: str = os.environ.get("TALONX_QUANT_REGIME_60M_BOOTSTRAP_PERIOD", "5d")

    # --- Pre-market session rules (04:00-09:30 America/New_York) ---
    # Stricter volume-surge bar than the regular-session default above,
    # plus a liquidity gate (dollar volume + bid-ask spread) and a news-
    # catalyst requirement -- pre-market liquidity is thin enough that the
    # regular-session thresholds alone aren't a meaningful filter. All
    # three pre-market-only checks are FAIL-CLOSED: if the data needed to
    # confirm a gate is missing (no recent quote, no news ever seen for
    # the ticker), the candidate is dropped rather than assumed to pass.
    premarket_volume_surge_ratio_threshold: float = _env_float(
        "TALONX_QUANT_PREMARKET_VOLUME_SURGE_RATIO", 3.0
    )
    premarket_min_dollar_volume_per_min: float = _env_float(
        "TALONX_QUANT_PREMARKET_MIN_DOLLAR_VOLUME_PER_MIN", 100_000.0
    )
    premarket_max_spread_pct: float = _env_float(
        "TALONX_QUANT_PREMARKET_MAX_SPREAD_PCT", 0.0012
    )
    # A QUOTE event older than this is treated as "no live quote" for the
    # spread gate -- pre-market quotes can go stale for illiquid names.
    premarket_quote_staleness_seconds: float = _env_float(
        "TALONX_QUANT_PREMARKET_QUOTE_STALENESS_SECONDS", 120.0
    )
    news_catalyst_lookback_hours: float = _env_float(
        "TALONX_QUANT_NEWS_CATALYST_LOOKBACK_HOURS", 4.0
    )
    # talonx_ingest.news.pipeline publishes one NewsArticleIngestedEvent
    # per newly-ingested article to this channel (mirrors filings_channel
    # above) -- this module only tracks the MOST RECENT timestamp per
    # ticker, not article content, for the 4h-lookback check.
    news_events_channel: str = os.environ.get(
        "TALONX_REDIS_NEWS_EVENTS_CHANNEL", "talonx:news:events"
    )

    # Post-loss lockout: talonx_paper's own trade-execution channel is
    # subscribed to (paper_trades_channel below) purely to detect a
    # losing SELL -- when one closes at realized_pnl_usd < 0, that ticker
    # is locked out for loss_lockout_seconds (75 min, the middle of the
    # analyst review's suggested 60-90 min range), on top of and longer
    # than the standard cooldown above, specifically to stop repeat
    # re-entries into a stock that just proved it was chopping/declining
    # (the exact pattern that drove 93% of session losses in the
    # reviewed run). Only ever engages for a ticker with paper trading
    # ENABLED -- one with it off never publishes a trade execution, so it
    # only ever sees the standard cooldown above, not this lockout.
    paper_trades_channel: str = os.environ.get(
        "TALONX_REDIS_PAPER_TRADES_CHANNEL", "talonx:paper:trades"
    )
    loss_lockout_seconds: float = _env_float("TALONX_QUANT_LOSS_LOCKOUT_SECONDS", 75 * 60.0)

    # --- Persistence (suppression counts, for the EOD report) ---
    # Cooldown/throttle suppression counts were in-memory-only counters
    # until this was added -- see store.py's QuantStateStore. Disable to
    # run pure in-memory, same escape hatch talonx_core's equivalent flag
    # provides.
    enable_persistence: bool = _env_bool("TALONX_QUANT_ENABLE_PERSISTENCE", True)
    db_path: str = os.environ.get(
        "TALONX_QUANT_DB_PATH", str(Path.home() / ".talonx" / "quant.db")
    )

    # --- Buffer persistence (survive a restart without a full re-warm-up) ---
    # How often to snapshot both RollingBarBuffers to quant.db (gated on
    # enable_persistence above, same as suppression counts). Also
    # snapshotted once on a graceful stop().
    buffer_checkpoint_interval_seconds: float = _env_float("TALONX_QUANT_BUFFER_CHECKPOINT_SECONDS", 60.0)
    # Only the 1-min buffer's reload is gap-gated by this: RSI/MACD/ATR
    # crossover detection compares consecutive bars, and a large gap
    # (e.g. an overnight shutdown) would make the first live bar after
    # reload look like one giant single-bar move, potentially firing a
    # signal purely off the overnight gap rather than a real intraday
    # move. If the most recent persisted 1-min bar for a symbol is older
    # than this, that symbol's 1-min buffer is discarded and re-warms up
    # normally instead of being reloaded stale.
    #
    # The 15-min HTF buffer (htf_sma_200, a slow trend-direction read,
    # never signal-triggering) has NO such gate -- it's deliberately
    # reloaded regardless of gap size, since surviving exactly this kind
    # of gap is the whole point: 200 bars needs ~50 continuous hours to
    # warm up from empty, which a daily restart can never accumulate on
    # its own.
    buffer_reload_max_gap_seconds: float = _env_float("TALONX_QUANT_BUFFER_RELOAD_MAX_GAP_SECONDS", 900.0)

    # --- Historical pre-seeding (Requirement 2: eliminate the ~24min/1m
    # and ~50-continuous-hour/15m cold-start warm-up above by backfilling
    # both buffers via yfinance the moment a ticker is first seen, or has
    # too little checkpointed history to reload -- see preseed.py and
    # consumer.py's _preseed_1m_if_needed/_preseed_htf_if_needed) ---
    historical_preseed_enabled: bool = _env_bool("TALONX_QUANT_PRESEED_ENABLED", True)
    preseed_1m_period: str = os.environ.get("TALONX_QUANT_PRESEED_1M_PERIOD", "1d")
    preseed_15m_period: str = os.environ.get("TALONX_QUANT_PRESEED_15M_PERIOD", "1mo")
    # Session-aware buffering (Requirement 3): restrict the 15m-200-SMA
    # trend gate's source buffer to Regular Trading Hours bars only --
    # pre-market 15m bars are simply never finalized into buffer_htf (see
    # consumer.py's _update_htf_buffer) rather than filtered out at SMA
    # compute time, so htf_max_bars' capacity is never spent on bars the
    # gate will never use.
    rth_only_htf_sma: bool = _env_bool("TALONX_QUANT_RTH_ONLY_HTF", True)
    # Requirement 4: the 15-min HTF buffer reloads unconditionally
    # (see buffer_reload_max_gap_seconds's own docstring for why), but a
    # gap this large since the newest checkpointed bar (default 24h --
    # e.g. a weekend) additionally triggers a yfinance backfill of
    # whatever's missing since then, on top of the unconditional reload.
    htf_backfill_gap_seconds: float = _env_float("TALONX_QUANT_HTF_BACKFILL_GAP_SECONDS", 86400.0)

    # --- Phase 2 LONG_TERM path: fundamental factor scoring ---
    # A sibling pipeline to everything above, not a second loop inside
    # QuantScanner -- see fundamental_consumer.FundamentalScanner. Own
    # channels, own thresholds, own (much longer) cooldown -- quarterly
    # cadence, so no batch throttle at all (signal volume here is
    # inherently low; throttling would be pointless complexity).
    fundamentals_events_channel: str = os.environ.get(
        "TALONX_REDIS_FUNDAMENTALS_CHANNEL", "talonx:fundamentals:events"
    )
    fundamental_signals_channel: str = os.environ.get(
        "TALONX_REDIS_FUNDAMENTAL_SIGNALS_CHANNEL", "talonx:signals:fundamental"
    )
    # Spec's example thresholds: ROIC >= 15% and F-Score >= 7.
    roic_threshold: float = _env_float("TALONX_QUANT_ROIC_THRESHOLD", 0.15)
    f_score_threshold: int = _env_int("TALONX_QUANT_F_SCORE_THRESHOLD", 7)
    # Deliberately its own key namespace (fundamental_cooldown:{TICKER}),
    # NOT the intraday cooldown:{TICKER} key -- sharing it would let a
    # same-day intraday signal suppress a quarterly fundamentals signal
    # for the same ticker, or vice versa, purely by key collision.
    # Default ~7 days: filings don't repeat within a quarter, this just
    # guards against re-publishing on a redundant/duplicate ingest event.
    fundamental_cooldown_seconds: float = _env_float(
        "TALONX_QUANT_FUNDAMENTAL_COOLDOWN_SECONDS", 7 * 86400.0
    )

    # --- Event-Driven Earnings Radar (Requirement 7 Stage 1) ---
    # FundamentalScanner ALSO subscribes to this channel (talonx_ingest's
    # filing-text ingestion trigger, same env var talonx_brain already
    # reads) purely to detect a fast-track-confirmed earnings filing
    # (NewFilingIngestedEvent.is_earnings_related=True) and republish a
    # FundamentalFactorSignal from persisted factors -- see
    # fundamental_consumer.py's own module docstring for the full flow.
    filings_channel: str = os.environ.get(
        "TALONX_REDIS_FILINGS_CHANNEL", "talonx:filings:events"
    )
    # Deliberately its OWN short-TTL cooldown namespace
    # (earnings_republish_cooldown:{TICKER}), NOT fundamental_cooldown_
    # seconds above -- a duplicate/amended 8-K shouldn't re-fire the
    # whole recalculation pipeline twice within the same hour, but this
    # must NOT be blocked by (or block) the unrelated 7-day standard
    # cooldown, which guards against a completely different scenario
    # (redundant routine re-ingests).
    earnings_republish_cooldown_seconds: float = _env_float(
        "TALONX_QUANT_EARNINGS_REPUBLISH_COOLDOWN_SECONDS", 3600.0
    )