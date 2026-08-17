"""
talonx_brain.config
------------------------
All settings for the Deep Research Agent & RAG Engine, env-driven.

Unlike talonx_quant, this module is NOT self-contained at the code level --
it imports talonx_ingest.storage.vector_store.VectorStore directly (see
retriever.py) because RAG retrieval must run through the exact embedding
function and persist path Module 1 used to write the store. Re-declaring a
"compatible" Chroma client here could silently point at a different
embedding model and return meaningless similarity scores, so that's a
correctness constraint, not a convenience. It still only talks to
talonx_quant via the Redis wire contract (talonx:signals:quant), same
boundary philosophy as everywhere else in the project.

Shares the repo-root .env (for TALONX_REDIS_URL, TALONX_CHROMA_*, etc.) the
same way talonx_quant does.
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
    you run `python -m talonx_brain.run` from.
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
class BrainConfig:
    # --- Redis ---
    redis_url: str = os.environ.get("TALONX_REDIS_URL", "redis://localhost:6379/0")
    # Same env var talonx_quant reads -- both sides of the trigger boundary
    # (signal producer, signal consumer) must agree on the channel name.
    signals_channel: str = os.environ.get(
        "TALONX_REDIS_SIGNALS_CHANNEL", "talonx:signals:quant"
    )
    reports_channel: str = os.environ.get(
        "TALONX_REDIS_REPORTS_CHANNEL", "talonx:reports:brain"
    )
    # Same channel talonx_ingest.pipeline already publishes
    # NewFilingIngestedEvent to after every successful filing ingestion --
    # subscribing here is what actually closes the cache-invalidation loop
    # (the publish side already existed before this cache was added).
    filings_channel: str = os.environ.get(
        "TALONX_REDIS_FILINGS_CHANNEL", "talonx:filings:events"
    )
    # Phase 2 LONG_TERM path -- same env var names talonx_quant/talonx_ingest
    # read on their sides of each boundary.
    fundamentals_events_channel: str = os.environ.get(
        "TALONX_REDIS_FUNDAMENTALS_CHANNEL", "talonx:fundamentals:events"
    )
    fundamental_signals_channel: str = os.environ.get(
        "TALONX_REDIS_FUNDAMENTAL_SIGNALS_CHANNEL", "talonx:signals:fundamental"
    )
    reports_channel_long_term: str = os.environ.get(
        "TALONX_REDIS_REPORTS_LONG_TERM_CHANNEL", "talonx:reports:longterm"
    )
    connect_timeout_seconds: float = _env_float("TALONX_REDIS_CONNECT_TIMEOUT", 5.0)
    socket_timeout_seconds: float = _env_float("TALONX_REDIS_SOCKET_TIMEOUT", 5.0)
    reconnect_backoff_base_seconds: float = _env_float("TALONX_BRAIN_RECONNECT_BASE", 1.0)
    reconnect_backoff_max_seconds: float = _env_float("TALONX_BRAIN_RECONNECT_MAX", 30.0)

    # --- Retrieval ---
    # Which ChromaDB collection/persist-dir/embedding-model to read is NOT
    # configured here -- retriever.py uses talonx_ingest's own VectorStore
    # defaults (TALONX_CHROMA_COLLECTION / TALONX_CHROMA_DIR /
    # TALONX_EMBEDDING_MODEL) so it can never drift out of sync with what
    # Module 1 actually wrote.
    retrieval_top_k: int = _env_int("TALONX_BRAIN_RETRIEVAL_TOP_K", 6)
    excerpt_max_chars: int = _env_int("TALONX_BRAIN_EXCERPT_MAX_CHARS", 600)
    # Same "inherit Module 1's settings, don't duplicate them" reasoning
    # applies to the news_feed collection too (see retriever.py) -- only
    # the on/off toggle and how many news chunks to pull live here.
    include_news_context: bool = _env_bool("TALONX_BRAIN_INCLUDE_NEWS", True)
    news_retrieval_top_k: int = _env_int("TALONX_BRAIN_NEWS_TOP_K", 3)

    # --- LLM provider selection ---
    # "gemini" (default, cloud -- fast, but free-tier quotas have proven
    # unreliable: retired models, zero-quota Pro, per-minute caps, and
    # per-DAY caps as low as 500 requests have all been hit building this
    # project) or "ollama" (local, no API key or quota, requires `ollama
    # serve` running with a pulled model -- see README §3.2 setup). Both
    # providers implement the same generate(signal, citations) ->
    # _LLMFindings interface (llm.py), so consumer.py never has to know
    # which one is active -- swap via env var, no code change.
    llm_provider: str = (os.environ.get("TALONX_BRAIN_LLM_PROVIDER", "gemini") or "gemini").strip().lower()

    # --- Gemini ---
    gemini_api_key: str | None = os.environ.get("GEMINI_API_KEY") or None
    # Pinned model names here have proven to be a moving target: both
    # gemini-1.5-pro and gemini-2.5-flash have already been retired/
    # restricted for this key over the course of building this module.
    # "gemini-flash-latest" is Google's own alias that always resolves to
    # the current recommended Flash model, so it survives that churn
    # without a code change. Flash (not Pro) by default because the
    # Gemini free tier grants ZERO quota for Pro models (billing-enabled
    # project required); override via env var if your project has Pro
    # access, e.g. "gemini-pro-latest".
    gemini_model: str = os.environ.get("TALONX_BRAIN_GEMINI_MODEL", "gemini-flash-latest")
    gemini_temperature: float = _env_float("TALONX_BRAIN_GEMINI_TEMPERATURE", 0.2)
    gemini_max_output_tokens: int = _env_int("TALONX_BRAIN_GEMINI_MAX_TOKENS", 2048)
    gemini_max_retries: int = _env_int("TALONX_BRAIN_GEMINI_MAX_RETRIES", 3)
    gemini_backoff_base_seconds: float = _env_float("TALONX_BRAIN_GEMINI_BACKOFF_BASE", 2.0)
    gemini_backoff_max_seconds: float = _env_float("TALONX_BRAIN_GEMINI_BACKOFF_MAX", 30.0)
    # Free-tier Gemini quotas are requests-PER-MINUTE and can be as low as 5
    # (observed on gemini-3.6-flash, what "gemini-flash-latest" currently
    # resolves to) -- with enough tickers under active surveillance, quant
    # signals can outpace that easily. Self-throttling to stay under quota
    # (see the _TokenBucket in llm.py) beats reactively retrying 429s,
    # which just queues up delay without bound under a sustained burst.
    # Lower this to match your actual plan/model if you still see 429s;
    # raise it if you're on a paid tier with a higher limit.
    gemini_max_requests_per_minute: float = _env_float("TALONX_BRAIN_GEMINI_RPM", 5.0)

    # --- Ollama (local) ---
    # No API key, no quota -- runs against a local `ollama serve`. Default
    # model is llama3.1 (8B): small enough for a typical dev machine's
    # CPU/GPU and supports the tool-calling method langchain-ollama uses
    # for with_structured_output(_LLMFindings). Swap via env var for a
    # larger/smaller local model.
    ollama_base_url: str = os.environ.get("TALONX_BRAIN_OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.environ.get("TALONX_BRAIN_OLLAMA_MODEL", "llama3.1")
    ollama_temperature: float = _env_float("TALONX_BRAIN_OLLAMA_TEMPERATURE", 0.2)
    ollama_max_retries: int = _env_int("TALONX_BRAIN_OLLAMA_MAX_RETRIES", 3)
    ollama_backoff_base_seconds: float = _env_float("TALONX_BRAIN_OLLAMA_BACKOFF_BASE", 2.0)
    ollama_backoff_max_seconds: float = _env_float("TALONX_BRAIN_OLLAMA_BACKOFF_MAX", 30.0)

    # --- Qualitative caching (see cache.py) ---
    # An escape hatch, not a tuning knob -- set false to always regenerate
    # (e.g. while actively debugging LLM prompt changes, where a stale
    # cache hit would be actively misleading).
    cache_enabled: bool = _env_bool("TALONX_BRAIN_CACHE_ENABLED", True)
    # Redis-level HARD TTL on a cache entry -- deliberately much longer
    # than the entry's own embedded logical expiry (next_expiry(), see
    # cache.py), so an entry survives PAST that logical expiry long enough
    # to still serve as an `is_stale=True` fallback if a live regeneration
    # attempt fails. This is just the outer safety net that stops a
    # forgotten/orphaned entry from living in Redis forever.
    cache_safety_ttl_seconds: float = _env_float("TALONX_BRAIN_CACHE_SAFETY_TTL", 21600.0)
    # Distributed lock (lock:brain:{ticker}) guarding cache population --
    # its own short TTL so a crashed worker can't hold it forever.
    cache_lock_ttl_seconds: float = _env_float("TALONX_BRAIN_CACHE_LOCK_TTL", 30.0)
    # How long a worker that LOST the lock race waits (polling the cache,
    # not the lock) for the winner to populate it before giving up and
    # generating its own report anyway -- bounded so a stuck/crashed lock
    # holder can't block everyone else indefinitely.
    cache_lock_wait_seconds: float = _env_float("TALONX_BRAIN_CACHE_LOCK_WAIT_SECONDS", 20.0)

    # --- Market-hours-aware cache expiry (Requirement 4D) ---
    # A cache entry's logical expiry is the SOONER of a base TTL or the
    # next of these two daily boundaries, so cached research doesn't
    # outlive the trading session it was generated for (e.g. overnight
    # earnings should force fresh analysis at the next open). zoneinfo
    # (stdlib) handles EST/EDT automatically -- these are plain exchange
    # local-time hours, not a fixed UTC offset. No holiday/weekend
    # calendar awareness -- see README's "what's not built yet".
    market_timezone: str = os.environ.get("TALONX_BRAIN_MARKET_TZ", "America/New_York")
    market_open_hour: int = _env_int("TALONX_BRAIN_MARKET_OPEN_HOUR", 9)
    market_close_hour: int = _env_int("TALONX_BRAIN_MARKET_CLOSE_HOUR", 16)
    # The "base TTL" side of the sooner-of comparison above -- caps how
    # long a cache entry can live even in the middle of a trading session
    # (e.g. generated at 10am shouldn't necessarily still be trusted at
    # 3:59pm). Default 2h.
    cache_base_ttl_seconds: float = _env_float("TALONX_BRAIN_CACHE_BASE_TTL", 7200.0)

    # --- Phase 2 LONG_TERM cache expiry -- flat cap, no market-hours
    # boundary math (a multi-year holding thesis has no "trading session"
    # to not outlive). 90 days per the spec's "90-day TTL or until the
    # next SEC filing" -- the "until next filing" half is satisfied by
    # invalidate() already being called on both NewFilingIngestedEvent
    # AND NewFundamentalsIngestedEvent for the long_term cache namespace,
    # not by any expiry-time logic.
    cache_base_ttl_long_term_seconds: float = _env_float(
        "TALONX_BRAIN_CACHE_BASE_TTL_LONG_TERM", 90 * 86400.0
    )

    # --- Persistence (report category counts, for the EOD report) ---
    # Cache-hit/degraded/LLM-call counts were only computable LIVE from
    # Redis messages (dashboard.py) until this was added -- see store.py's
    # BrainStatsStore. Disable to run pure in-memory.
    enable_persistence: bool = _env_bool("TALONX_BRAIN_ENABLE_PERSISTENCE", True)
    db_path: str = os.environ.get(
        "TALONX_BRAIN_DB_PATH", str(Path.home() / ".talonx" / "brain.db")
    )
