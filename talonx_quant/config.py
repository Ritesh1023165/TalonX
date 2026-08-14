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
from pathlib import Path

from dotenv import load_dotenv


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
    # 15:12 on the same ticker from both alerting.
    cooldown_seconds: float = _env_float("TALONX_QUANT_COOLDOWN_SECONDS", 1200.0)

    # Minimum SMA fast/slow separation, as a fraction of price, required at
    # the crossover bar for a MA_GOLDEN_CROSS/MA_DEATH_CROSS to fire.
    # Filters out e.g. a $0.03 drift on a $500 stock (0.006%, far under the
    # 0.15% default) -- a real crossover event that's too small to matter.
    # Deliberately scoped to the SMA cross only, not MACD, per spec.
    min_ma_spread_pct: float = _env_float("TALONX_QUANT_MIN_MA_SPREAD_PCT", 0.0015)

    # Batch throttle: across ALL tickers, at most this many signals are
    # released per throttle_window_seconds, ranked by (confluence_score,
    # volume_surge_ratio) -- confluence first, volume surge as the
    # tiebreaker (a signal with no computed ratio sorts last within its
    # confluence tier). Candidates are buffered for the full window
    # before any of them are released -- see consumer.py's
    # _flush_throttle_window -- so a signal can be delayed by up to
    # throttle_window_seconds, or dropped entirely if it doesn't rank in
    # the top throttle_max_signals that window.
    throttle_window_seconds: float = _env_float("TALONX_QUANT_THROTTLE_WINDOW_SECONDS", 60.0)
    throttle_max_signals: int = _env_int("TALONX_QUANT_THROTTLE_MAX_SIGNALS", 3)

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

    # Confluence score: +1 each for a MACD cross firing this bar, RSI
    # currently in its extreme zone (< rsi_oversold or > rsi_overbought),
    # and volume_surge_ratio > volume_surge_ratio_threshold -- computed
    # once per bar (0-3) and attached to every signal that fires on it.
    # A signal below this score is suppressed before it ever reaches the
    # per-ticker cooldown lock or the global throttle.
    confluence_score_min: int = _env_int("TALONX_QUANT_CONFLUENCE_SCORE_MIN", 2)

    # Risk/reward filter. Reward side = atr_reward_multiplier * ATR (a
    # volatility-scaled profit target). Risk side is intentionally NOT
    # another ATR multiple -- 1.5x ATR / 0.75x ATR is a constant 2.0
    # regardless of any market data, which would make the filter a
    # permanent no-op. Instead the risk side mirrors talonx_paper's own
    # stop-loss distance (assumed_stop_loss_pct, default matching
    # TALONX_PAPER_STOP_LOSS_PCT's 0.5% -- talonx_quant stays
    # config-independent from talonx_paper by design, same "shadow
    # constant, documented as an approximation" pattern
    # talonx_dispatch/formatter.py's _VALUATION_EXIT_PREMIUM already
    # uses for a different cross-module display value), so the ratio
    # actually varies with each ticker's ATR-to-price relationship.
    # Phase 2 requirement doc default: reward = 2.0x ATR, stop = 1.0x ATR
    # (atr_stop_multiplier below) -- both explicit ATR multiples now, so
    # stop_price/target_price (see schemas.QuantSignal) are real, dollar-
    # denominated levels rather than just a ratio. min_risk_reward_ratio
    # stays a live gate (not a permanent no-op) because a signal can still
    # have atr=None (insufficient history) or the two multipliers can be
    # tuned independently via env vars.
    atr_reward_multiplier: float = _env_float("TALONX_QUANT_ATR_REWARD_MULTIPLIER", 2.0)
    atr_stop_multiplier: float = _env_float("TALONX_QUANT_ATR_STOP_MULTIPLIER", 1.0)
    assumed_stop_loss_pct: float = _env_float("TALONX_QUANT_ASSUMED_STOP_LOSS_PCT", 0.005)
    min_risk_reward_ratio: float = _env_float("TALONX_QUANT_MIN_RISK_REWARD_RATIO", 1.5)

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