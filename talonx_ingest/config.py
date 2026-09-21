"""
talonx_ingest.config
---------------------
Centralized, environment-driven configuration for the ingestion engine.

All tunables live here so client code never hardcodes magic numbers.

Loads a `.env` file (if present) via python-dotenv before reading any
environment variables, so local development doesn't require manually
exporting vars in every new shell. In production/CI, real environment
variables (set by the deployment platform) still take precedence --
see `_load_dotenv()` below for the exact precedence rule.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


def _load_dotenv() -> None:
    """
    Load variables from a .env file into os.environ.

    `override=False` (the default) means: if a variable is already set in
    the real environment (e.g. injected by Docker, CI, or `$env:VAR = ...`
    in PowerShell), that value wins and the .env value is ignored. This
    keeps .env strictly a local-development convenience, never a way to
    silently override a deployment's real config.

    Resolution order:
      1. .env at the repo root -- resolved relative to THIS file's
         location (../.env from here), not the current working directory.
         This means it's found reliably regardless of whether you run
         commands from the repo root or from inside talonx_ingest/, which
         is the layout every module's config.py shares (see each one's
         own _load_dotenv()).
      2. Fallback: find_dotenv(usecwd=True), which walks upward from the
         current working directory. Kept as a fallback for anyone who's
         set up a .env somewhere else on their own.
    """
    repo_root_env = Path(__file__).resolve().parent.parent / ".env"
    if repo_root_env.is_file():
        load_dotenv(repo_root_env, override=False)
        return

    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)


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


@dataclass(frozen=True)
class EdgarConfig:
    """
    SEC EDGAR access rules (see https://www.sec.gov/os/webmaster-faq#developers):
      - A descriptive User-Agent with a real contact (name/email or company) is
        REQUIRED. Requests without one, or with a generic UA, get 403'd or
        rate-limited more aggressively.
      - Hard cap: 10 requests/second across all SEC endpoints. We default
        conservatively under that to leave headroom for retries.
    """
    user_agent: str = os.environ.get(
        "TALONX_SEC_USER_AGENT",
        "TalonX Research Engine contact@example.com",  # MUST be overridden in prod
    )
    submissions_base: str = "https://data.sec.gov/submissions"
    company_facts_base: str = "https://data.sec.gov/api/xbrl/companyfacts"
    archives_base: str = "https://www.sec.gov/Archives/edgar/data"
    ticker_map_url: str = "https://www.sec.gov/files/company_tickers.json"

    max_requests_per_second: float = _env_float("TALONX_SEC_RPS", 8.0)
    max_concurrent_requests: int = _env_int("TALONX_SEC_CONCURRENCY", 4)

    max_retries: int = _env_int("TALONX_SEC_MAX_RETRIES", 5)
    backoff_base_seconds: float = _env_float("TALONX_SEC_BACKOFF_BASE", 1.5)
    backoff_max_seconds: float = _env_float("TALONX_SEC_BACKOFF_MAX", 60.0)
    request_timeout_seconds: float = _env_float("TALONX_SEC_TIMEOUT", 30.0)

    target_forms: tuple[str, ...] = ("10-K", "10-Q")
    lookback_filings_per_form: int = _env_int("TALONX_SEC_LOOKBACK", 4)


@dataclass(frozen=True)
class ChunkingConfig:
    # Financial filings run long and dense (Item 7 MD&A, Item 8 financial
    # statements). 1800/250 gives chunks that hold a full paragraph or table
    # fragment with enough overlap to preserve cross-sentence context.
    chunk_size: int = _env_int("TALONX_CHUNK_SIZE", 1800)
    chunk_overlap: int = _env_int("TALONX_CHUNK_OVERLAP", 250)
    min_chunk_chars: int = _env_int("TALONX_MIN_CHUNK_CHARS", 40)
    separators: tuple[str, ...] = ("\n\n", "\n", ". ", " ", "")


@dataclass(frozen=True)
class VectorStoreConfig:
    persist_directory: str = os.environ.get(
        "TALONX_CHROMA_DIR", str(Path.home() / ".talonx" / "chroma")
    )
    collection_name: str = os.environ.get("TALONX_CHROMA_COLLECTION", "sec_filings")
    embedding_model_name: str = os.environ.get(
        "TALONX_EMBEDDING_MODEL", "all-MiniLM-L6-v2"
    )
    upsert_batch_size: int = _env_int("TALONX_CHROMA_BATCH_SIZE", 128)


@dataclass(frozen=True)
class LedgerConfig:
    """Incremental-ingestion tracking: which filings are already fully processed."""
    path: str = os.environ.get(
        "TALONX_LEDGER_PATH", str(Path.home() / ".talonx" / "ingestion_ledger.db")
    )


@dataclass(frozen=True)
class RedisConfig:
    """Redis Pub/Sub broker settings for the event-producer contract."""
    url: str = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")
    market_stream_channel: str = os.environ.get(
        "TALONX_REDIS_MARKET_CHANNEL", "talonx:market:stream"
    )
    filings_events_channel: str = os.environ.get(
        "TALONX_REDIS_FILINGS_CHANNEL", "talonx:filings:events"
    )
    fundamentals_events_channel: str = os.environ.get(
        "TALONX_REDIS_FUNDAMENTALS_CHANNEL", "talonx:fundamentals:events"
    )
    # Pre-market news-catalyst gate's trigger (talonx_quant) -- published
    # once per newly-ingested article by news/pipeline.py, mirroring
    # filings_events_channel's role for the filing-ingestion side.
    news_events_channel: str = os.environ.get(
        "TALONX_REDIS_NEWS_EVENTS_CHANNEL", "talonx:news:events"
    )
    # /ping health-check's WebSocket status source (talonx_dispatch) -- a
    # short-TTL heartbeat key (not Pub/Sub) written by market_data on each
    # successful connect/tick, read directly via GET, not subscribed to.
    ws_heartbeat_key: str = os.environ.get(
        "TALONX_REDIS_WS_HEARTBEAT_KEY", "talonx:ingest:ws_heartbeat"
    )
    ws_heartbeat_ttl_seconds: int = _env_int("TALONX_REDIS_WS_HEARTBEAT_TTL_SECONDS", 120)
    # Task 87B FC_03: market-INDEPENDENT liveness beat (talonx_ingest.
    # liveness.LivenessBeacon). Written on a fixed timer regardless of
    # market activity so /ping can tell "process/redis down" from "market
    # legitimately quiet". TTL comfortably > the interval so a single
    # missed write never reads as DISCONNECTED.
    liveness_key: str = os.environ.get("TALONX_REDIS_LIVENESS_KEY", "talonx:ingest:liveness")
    liveness_interval_seconds: float = _env_float("TALONX_REDIS_LIVENESS_INTERVAL_SECONDS", 20.0)
    liveness_ttl_seconds: int = _env_int("TALONX_REDIS_LIVENESS_TTL_SECONDS", 90)
    connect_timeout_seconds: float = _env_float("TALONX_REDIS_CONNECT_TIMEOUT", 5.0)
    socket_timeout_seconds: float = _env_float("TALONX_REDIS_SOCKET_TIMEOUT", 5.0)
    # RedisEventPublisher's background reconnect loop (2026-08-18
    # correctness fix, code-review finding #3) -- same naming/default
    # convention as talonx_quant/talonx_brain/talonx_dispatch's own
    # reconnect_backoff_base_seconds/reconnect_backoff_max_seconds.
    reconnect_backoff_base_seconds: float = _env_float("TALONX_REDIS_RECONNECT_BASE", 1.0)
    reconnect_backoff_max_seconds: float = _env_float("TALONX_REDIS_RECONNECT_MAX", 30.0)


@dataclass(frozen=True)
class NewsConfig:
    """
    News/social feed ingestion settings.

    Primary source is NewsAPI.org (requires a free/paid API key). Fallback,
    used automatically when no key is configured, is Yahoo Finance's public
    per-ticker RSS feed -- no API key required, same failover philosophy as
    market_data (Polygon key -> WebSocket, else yfinance polling).
    """
    news_api_key: str | None = os.environ.get("NEWS_API_KEY") or None
    news_api_base_url: str = "https://newsapi.org/v2/everything"
    articles_per_ticker: int = _env_int("TALONX_NEWS_ARTICLES_PER_TICKER", 20)
    lookback_days: int = _env_int("TALONX_NEWS_LOOKBACK_DAYS", 7)

    rss_feed_url_template: str = os.environ.get(
        "TALONX_NEWS_RSS_TEMPLATE",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US",
    )

    max_retries: int = _env_int("TALONX_NEWS_MAX_RETRIES", 3)
    backoff_base_seconds: float = _env_float("TALONX_NEWS_BACKOFF_BASE", 1.5)
    backoff_max_seconds: float = _env_float("TALONX_NEWS_BACKOFF_MAX", 30.0)
    request_timeout_seconds: float = _env_float("TALONX_NEWS_TIMEOUT", 15.0)

    vector_collection_name: str = os.environ.get(
        "TALONX_NEWS_CHROMA_COLLECTION", "news_feed"
    )


@dataclass(frozen=True)
class RedditConfig:
    """
    Optional social-feed source, layered ON TOP of NewsConfig's
    NewsAPI/RSS pair -- not a fallback tier. NewsAPI/RSS already give a
    working "no signup at all" baseline (RSS) with an optional upgrade
    (NewsAPI key); Reddit is additive: if REDDIT_CLIENT_ID/
    REDDIT_CLIENT_SECRET aren't set, it's skipped entirely and the
    news pipeline behaves exactly as it did before this existed.

    Requires a free Reddit "script" app (register at
    reddit.com/prefs/apps -- no payment, no approval wait) for OAuth2
    client_credentials (app-only) auth -- no Reddit user account needed,
    just the app's own id/secret.

    Twitter/X was deliberately NOT built alongside this: as of the 2023+
    API pricing changes, reading/searching public posts requires a paid
    Basic tier ($100+/month) -- there is no usable free read path, unlike
    Reddit's genuinely free (if registration-gated) API. Building it
    would break this project's "works free out of the box, key optional
    for more" pattern every other source follows.
    """
    client_id: str | None = os.environ.get("REDDIT_CLIENT_ID") or None
    client_secret: str | None = os.environ.get("REDDIT_CLIENT_SECRET") or None
    # Reddit requires a descriptive, unique User-Agent identifying your
    # app -- same non-negotiable requirement SEC EDGAR has (see
    # EdgarConfig.user_agent above). Generic/missing UAs get throttled
    # hard or blocked outright.
    user_agent: str = os.environ.get(
        "REDDIT_USER_AGENT",
        "TalonX Research Engine by /u/change_me",  # MUST be overridden in prod
    )
    subreddits: tuple[str, ...] = tuple(
        s.strip()
        for s in os.environ.get(
            "TALONX_REDDIT_SUBREDDITS", "wallstreetbets,stocks,investing"
        ).split(",")
        if s.strip()
    )
    posts_per_ticker: int = _env_int("TALONX_REDDIT_POSTS_PER_TICKER", 15)
    lookback_days: int = _env_int("TALONX_REDDIT_LOOKBACK_DAYS", 7)

    # Reddit's free OAuth tier allows ~100 requests/minute; stay under
    # that with margin, same "self-throttle proactively" philosophy
    # talonx_brain uses for Gemini rather than reactively retrying 429s.
    max_requests_per_minute: float = _env_float("TALONX_REDDIT_RPM", 60.0)

    max_retries: int = _env_int("TALONX_REDDIT_MAX_RETRIES", 3)
    backoff_base_seconds: float = _env_float("TALONX_REDDIT_BACKOFF_BASE", 1.5)
    backoff_max_seconds: float = _env_float("TALONX_REDDIT_BACKOFF_MAX", 30.0)
    request_timeout_seconds: float = _env_float("TALONX_REDDIT_TIMEOUT", 15.0)


@dataclass(frozen=True)
class MarketDataConfig:
    """
    Real-time/near-real-time market data settings.

    Polygon.io WebSocket is the primary source when an API key is present.
    yfinance polling is the backup -- used both when no Polygon key is
    configured at all, and as an automatic failover if the WebSocket
    connection can't be established or keeps dropping after repeated
    reconnect attempts.
    """
    polygon_api_key: str | None = os.environ.get("POLYGON_API_KEY") or None
    polygon_ws_url: str = os.environ.get(
        "TALONX_POLYGON_WS_URL", "wss://socket.polygon.io/stocks"
    )
    # Channels to subscribe to per symbol: T=trades, Q=quotes, AM=minute aggregates.
    polygon_channels: tuple[str, ...] = ("T", "Q", "AM")

    ws_max_reconnect_attempts: int = _env_int("TALONX_WS_MAX_RECONNECT", 8)
    ws_backoff_base_seconds: float = _env_float("TALONX_WS_BACKOFF_BASE", 1.0)
    ws_backoff_max_seconds: float = _env_float("TALONX_WS_BACKOFF_MAX", 30.0)
    ws_auth_timeout_seconds: float = _env_float("TALONX_WS_AUTH_TIMEOUT", 10.0)
    ws_message_idle_timeout_seconds: float = _env_float("TALONX_WS_IDLE_TIMEOUT", 60.0)

    # yfinance has no true push/streaming API -- this is a polling interval.
    # Polygon's free/starter tiers also often exclude real-time data (15-min
    # delayed), so treat "WebSocket" as "lowest latency available to your
    # plan," not a guarantee of true real-time ticks.
    yfinance_poll_interval_seconds: float = _env_float("TALONX_YF_POLL_INTERVAL", 5.0)
    yfinance_max_retries: int = _env_int("TALONX_YF_MAX_RETRIES", 3)
    yfinance_backoff_base_seconds: float = _env_float("TALONX_YF_BACKOFF_BASE", 2.0)
    yfinance_backoff_max_seconds: float = _env_float("TALONX_YF_BACKOFF_MAX", 30.0)

    # A poll cycle where most/all symbols fail per-symbol (yfinance's
    # unofficial API occasionally gets a long-running process's cached
    # session/crumb into a stuck bad state -- e.g. a bare KeyError on
    # 'exchangeTimezoneName' when Yahoo returns a throttled/malformed
    # response) currently looks IDENTICAL to a healthy cycle to the outer
    # retry loop, since _fetch_snapshots catches every per-symbol
    # exception and just returns fewer events -- no backoff ever engages,
    # and the process needs a manual restart to recover. This threshold
    # (fraction of symbols that failed) is what promotes such a cycle
    # into a real, backed-off failure worth acting on.
    yfinance_degraded_cycle_failure_rate: float = _env_float("TALONX_YF_DEGRADED_FAILURE_RATE", 0.5)
    # After this many CONSECUTIVE degraded/failed cycles, proactively
    # reset yfinance's cached session/crumb (see YFinancePoller._reset_session)
    # rather than keep repeating the same doomed request pattern.
    yfinance_session_reset_after_failures: int = _env_int("TALONX_YF_SESSION_RESET_AFTER", 3)

    # Vectorized Multi-Quote Poller (talonx_ingest.poller.fetch_watchlist_quotes):
    # a full-watchlist pre-market refresh cycle logged at WARNING instead
    # of INFO once it takes longer than this -- the requirement's own
    # "50+ tickers refresh in under 30s" target, made visible as a log
    # signal rather than something that has to be timed externally.
    premarket_refresh_warn_seconds: float = _env_float("TALONX_PREMARKET_REFRESH_WARN_SECONDS", 30.0)


@dataclass(frozen=True)
class Settings:
    edgar: EdgarConfig = field(default_factory=EdgarConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    vector_store: VectorStoreConfig = field(default_factory=VectorStoreConfig)
    market_data: MarketDataConfig = field(default_factory=MarketDataConfig)
    ledger: LedgerConfig = field(default_factory=LedgerConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    news: NewsConfig = field(default_factory=NewsConfig)
    reddit: RedditConfig = field(default_factory=RedditConfig)
    raw_cache_dir: str = os.environ.get(
        "TALONX_RAW_CACHE_DIR", str(Path.home() / ".talonx" / "raw_filings")
    )


settings = Settings()