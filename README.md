# TalonX

**Project TalonX** is a quantitative & qualitative stock research
pipeline. This repo contains all five of its modules:

- **`talonx_ingest`** (Module 1) — Data Ingestion & Event Producer Engine.
  Pulls SEC filings, news/social content, and live market data into
  searchable/structured form, and publishes real-time events to Redis.
- **`talonx_quant`** (Module 2) — Technical & Quantitative Scanner.
  Listens to the market data Module 1 produces, computes technical
  indicators, and publishes trade-setup signals.
- **`talonx_brain`** (Module 3) — Deep Research Agent & RAG Engine.
  Listens to the trade-setup signals Module 2 produces, retrieves relevant
  SEC filing and news context from Module 1's ChromaDB store, and asks
  Gemini to ground or challenge each technical signal against that
  context, publishing a structured research report.
- **`talonx_core`** (Module 4) — Core Event Bus & Decision Engine.
  Correlates Module 2's technical signals with Module 3's research
  reports per ticker, runs a Decision Matrix against them (do they agree,
  or contradict?), and publishes an actionable alert when one clears the
  confidence bar and isn't in cooldown.
- **`talonx_dispatch`** (Module 5) — Notification Dispatcher & Streamlit
  Interface. Listens for Module 4's actionable alerts, pushes them to
  Telegram as mobile notifications, records every one to a durable audit
  trail, and serves a live Streamlit dashboard over that trail for
  monitoring and trade audit review.

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.11 or 3.12** | Get it from [python.org/downloads](https://www.python.org/downloads/) — not the Microsoft Store version. Check "Add python.exe to PATH" during install. **Avoid Python 3.13+** for now: `numba` (a `pandas_ta` dependency) doesn't yet support it. |
| **Visual C++ Build Tools** (Windows only) | Needed if `pip install` fails compiling `chromadb`/`hnswlib`. Get the "Desktop development with C++" workload from the [VC++ Build Tools installer](https://visualstudio.microsoft.com/visual-cpp-build-tools/). |
| **An editor** | VS Code (Python extension) or Visual Studio 2022 (Python Development workload). |
| **~2GB free disk** | `sentence-transformers` pulls in PyTorch on first install. |
| **Redis** | Required for Module 2 and Module 3, and for event publishing in Module 1 (Module 1 still works without it — publishing just degrades gracefully). `docker compose up -d` from the repo root starts it (see `docker-compose.yaml` — pinned `redis:7.0.15`, healthchecked, named `talonx-redis`); `docker compose down` to stop it. |
| **An LLM for Module 3** (`talonx_brain`) | Two options, switchable via `TALONX_BRAIN_LLM_PROVIDER` — see §3.3 and §9.4. **Gemini** (default): free-tier cloud, needs a `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/apikey), but its free-tier quotas (per-minute AND per-day) are easy to exhaust under active testing. **Ollama** (local): no API key, no quota, runs entirely on your machine — needs [Ollama](https://ollama.com/download) installed with a model pulled (`ollama pull llama3.1`). |

---

## 2. Project layout

```
C:\workspace\TalonX\              <- open THIS folder as your project root
├── .env                            <- your local secrets/config (create from .env.example), shared by every module
├── .env.example
├── .gitignore
├── inspect_store.py               <- CLI to spot-check what's in ChromaDB
├── run_talonx.py                   <- runs Module 1 + 2 + 3 + 4 + 5 + 6 together, one process (Streamlit dashboard always separate)
├── send_test_signal.py             <- publishes synthetic bars to test the quant scanner
├── dashboard.py                    <- live terminal dashboard: counts + per-ticker + per-category breakdown across all 6 Redis channels
├── dashboard_web.py                 <- same data, served as a local browser UI with charts (imports dashboard.py)
├── dashboard_web_static\
│   └── index.html                    <- self-contained HTML/CSS/JS -- no CDN, sparkline + bar charts, WebSocket client
├── requirements-dashboard.txt      <- rich + redis + aiohttp, for running either dashboard tool standalone
├── pyproject.toml                  <- pytest config
├── requirements-dev.txt            <- pytest + pytest-asyncio, for running tests
├── tests\
│   ├── conftest.py                   <- shared fixtures
│   ├── test_cleaner.py
│   ├── test_chunker.py
│   ├── test_ledger.py
│   ├── test_events_schemas.py
│   ├── test_pipeline_ledger_integration.py
│   ├── test_reddit_client.py
│   ├── test_quant_strategy.py        <- signal logic incl. edge-triggering + hysteresis (§3.2, §9.5)
│   ├── test_quant_consumer.py        <- per-ticker cooldown + batch throttle orchestration (§3.2, §9.5)
│   ├── test_brain_schemas.py
│   ├── test_brain_retriever.py
│   ├── test_brain_consumer.py
│   ├── test_brain_llm.py             <- provider-switch (Gemini/Ollama) + retry/backoff (§3.3, §9.4)
│   ├── test_core_schemas.py
│   ├── test_core_decision.py
│   ├── test_core_store.py
│   ├── test_core_consumer.py
│   ├── test_dispatch_schemas.py
│   ├── test_dispatch_formatter.py
│   ├── test_dispatch_store.py
│   └── test_dispatch_consumer.py
├── talonx_ingest\
│   ├── config.py                   <- all settings, env-driven
│   ├── pipeline.py                 <- SEC filing ingestion entrypoint
│   ├── check_connectivity.py       <- network diagnostic script
│   ├── common\
│   │   └── backoff.py               <- shared retry/backoff helper
│   ├── edgar\
│   │   ├── client.py                <- async SEC EDGAR client (rate-limited, retrying)
│   │   └── models.py                <- filing data structures
│   ├── events\
│   │   ├── schemas.py                <- Pydantic contracts: MarketTickEvent, NewFilingIngestedEvent
│   │   └── publisher.py              <- async Redis Pub/Sub publisher (graceful if Redis down)
│   ├── news\
│   │   ├── client.py                 <- NewsAPI primary, Yahoo Finance RSS fallback
│   │   ├── reddit_client.py          <- optional additional source: Reddit OAuth2 search
│   │   ├── models.py                 <- NewsArticle (shared shape: NewsAPI, RSS, and Reddit all normalize into this)
│   │   └── pipeline.py               <- fetch (news + Reddit) -> chunk -> embed into ChromaDB
│   ├── processing\
│   │   ├── cleaner.py                <- HTML -> plain text
│   │   └── chunker.py                <- text -> embeddable chunks (shared by filings + news)
│   ├── storage\
│   │   ├── vector_store.py           <- ChromaDB wrapper (supports multiple collections)
│   │   └── ledger.py                 <- SQLite: tracks what's already ingested (filings + news)
│   └── market_data\
│       ├── manager.py                <- WebSocket-first, polling-fallback orchestration
│       ├── polygon_ws.py             <- Polygon.io WebSocket client
│       ├── yfinance_poll.py          <- yfinance polling fallback
│       ├── models.py                 <- normalized market event type
│       └── run.py                    <- market data entrypoint; also publishes to Redis
├── talonx_quant\                    <- Module 2: Technical & Quantitative Scanner
│   ├── config.py                     <- all settings, env-driven
│   ├── schemas.py                    <- MarketTickEvent (input, mirrors talonx_ingest's wire format), QuantSignal (output)
│   ├── buffer.py                     <- per-ticker rolling OHLCV buffer (in-memory, bounded)
│   ├── indicators.py                 <- RSI/MACD/SMA/volume-surge via pandas_ta
│   ├── strategy.py                   <- indicator snapshot -> QuantSignal trigger logic, edge-triggered + hysteresis-gated (§3.2)
│   ├── consumer.py                   <- async Redis subscriber; per-ticker cooldown + batch throttle (§3.2)
│   └── run.py                        <- entrypoint: listens talonx:market:stream, publishes talonx:signals:quant
├── talonx_brain\                    <- Module 3: Deep Research Agent & RAG Engine
│   ├── config.py                     <- all settings, env-driven (LLM provider + Gemini + Ollama, retrieval, Redis)
│   ├── schemas.py                    <- QuantSignal (input, mirrors talonx_quant's wire format), ResearchReport/Citation (output)
│   ├── retriever.py                  <- ChromaDB RAG retrieval (imports talonx_ingest's VectorStore directly)
│   ├── llm.py                        <- structured-output chain: GeminiResearchChain (langchain-google-genai) or OllamaResearchChain (langchain-ollama), picked by build_research_chain()
│   ├── consumer.py                   <- async Redis subscriber: retrieve -> generate -> publish
│   └── run.py                        <- entrypoint: listens talonx:signals:quant, publishes talonx:reports:brain
├── talonx_core\                     <- Module 4: Core Event Bus & Decision Engine
│   ├── config.py                     <- all settings, env-driven (correlation window, confidence gate, cooldown, persistence, Redis)
│   ├── schemas.py                    <- QuantSignal + trimmed ResearchReport (inputs, mirror talonx_quant/talonx_brain wire formats), ActionableAlert (output)
│   ├── state.py                      <- TickerState / TickerCorrelator -- per-ticker, in memory for the life of the process
│   ├── store.py                      <- TickerStateStore -- SQLite-backed persistence, rehydrates the correlator across restarts
│   ├── decision.py                   <- the Decision Matrix (pure function, no I/O)
│   ├── consumer.py                   <- async Redis subscriber on TWO channels: correlate -> decide -> publish (write-through to the store)
│   └── run.py                        <- entrypoint: listens talonx:signals:quant + talonx:reports:brain, publishes talonx:alerts:dispatch
└── talonx_dispatch\                 <- Module 5: Notification Dispatcher & Streamlit Interface
    ├── config.py                     <- all settings, env-driven (Telegram, audit DB, Streamlit refresh, Redis)
    ├── schemas.py                    <- trimmed ActionableAlert mirror (input, mirrors talonx_core's wire format)
    ├── store.py                      <- AuditStore -- SQLite audit trail; consumer.py writes, app.py reads (two separate processes)
    ├── formatter.py                  <- pure ActionableAlert -> Telegram Markdown text
    ├── telegram_client.py            <- thin async wrapper over python-telegram-bot, retry/backoff
    ├── consumer.py                   <- async Redis subscriber: record to audit trail -> maybe push Telegram
    ├── run.py                        <- entrypoint: listens talonx:alerts:dispatch (consumer half only)
    └── app.py                        <- Streamlit dashboard: `streamlit run talonx_dispatch/app.py` (ALWAYS standalone)
```

**Important:** `.env` lives at the repo root — every module resolves it by
path relative to its own package location (`../.env` from inside each
package, not by searching the current working directory), so it's found
reliably no matter which folder you run commands from. `talonx_ingest`,
`talonx_quant`, `talonx_brain`, `talonx_core`, and `talonx_dispatch` all
read the SAME file (they share `TALONX_REDIS_URL` and other Redis
settings; `talonx_brain` also needs `GEMINI_API_KEY` and `talonx_dispatch`
needs `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` from it) rather than needing
their own copies. `inspect_store.py` and `pytest` still need to be run
from the repo root (`C:\workspace\TalonX`), since that's how Python
resolves `talonx_ingest.*` / `talonx_quant.*` / `talonx_brain.*` /
`talonx_core.*` / `talonx_dispatch.*` imports.

---

## 3. What each module does, in depth

### 3.1 `talonx_ingest` — Module 1: Data Ingestion & Event Producer

Four independent pipelines, sharing common infrastructure underneath.

#### SEC filing ingestion (`talonx_ingest.pipeline`)

```
tickers → resolve ticker→CIK via SEC's official mapping
        → pull each company's filing history, filter to recent 10-K/10-Q
        → [ledger check: skip filings already fully ingested]
        → fetch raw HTML → clean → chunk → embed
        → upsert into ChromaDB ("sec_filings" collection)
        → publish NewFilingIngestedEvent to Redis (talonx:filings:events)
```

- **`edgar/client.py`** — async SEC EDGAR client. Rate-limited to a safe
  margin under SEC's 10 req/sec cap via a token-bucket limiter, with
  jittered exponential backoff on 429/5xx responses. 403/404 are treated
  as non-retryable (usually means the User-Agent header is missing/bad).
- **`processing/cleaner.py`** — strips HTML/XBRL noise (scripts, styles,
  hidden tags) from raw filing HTML, flattens tables into readable
  pipe-delimited text so numeric structure survives without dragging
  along markup, and collapses excess whitespace.
- **`processing/chunker.py`** — splits cleaned text into ~1800-character
  overlapping chunks (configurable), each tagged with metadata (ticker,
  form type, filing date, accession number, chunk index). Chunk IDs are
  deterministic (hash of source ID + chunk index), which makes
  re-embedding the same filing idempotent in ChromaDB.
- **`storage/ledger.py`** — a local SQLite file tracking which filings
  have been *fully* ingested. Since SEC filings are immutable once filed
  (amendments get a new accession number, not a mutation), "already
  ingested" is a safe, permanent skip — no staleness logic needed. A
  filing is only marked complete **after** all its chunks are
  successfully written, so a crash mid-run leaves it eligible for a
  clean retry rather than silently marked done.
- **`storage/vector_store.py`** — a ChromaDB wrapper. Supports multiple
  named collections (filings and news use separate ones) sharing one
  embedding model (`all-MiniLM-L6-v2`, local, no API key needed).

#### News/social feed ingestion (`talonx_ingest.news`)

Same shape as filing ingestion, different source(s) and destination
collection:

```
tickers → fetch articles (NewsAPI.org if NEWS_API_KEY set,
                           else Yahoo Finance RSS — no key needed)
        → ALSO fetch Reddit posts (if REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET
                                    set -- additive, not a fallback; skipped
                                    entirely, no error, if unset)
        → [ledger check: skip articles/posts already ingested]
        → chunk (title + summary/selftext) → embed
        → upsert into ChromaDB ("news_feed" collection, separate from filings)
```

Articles/posts are deduped by a hash of their URL (there's no universal
article ID the way filings have an accession number — a Reddit permalink
serves the same role). Same incremental ledger philosophy, same
partial-upsert safety, tracked in a second table in the same SQLite file.

- **`reddit_client.py`** — searches a configurable set of subreddits
  (default `wallstreetbets, stocks, investing` — `TALONX_REDDIT_SUBREDDITS`)
  for recent posts mentioning a ticker, via Reddit's OAuth2
  `client_credentials` grant (app-only auth — no Reddit user account
  needed, just a free registered app's id/secret). Normalizes results
  into the exact same `NewsArticle` shape NewsAPI/RSS produce, so nothing
  downstream (chunker, ledger, vector store) needed to change to accept
  it. Self-throttles via a token bucket (`TALONX_REDDIT_RPM`, default
  60/min, under Reddit's free-tier ~100/min) — same proactive-pacing
  philosophy `talonx_brain` uses for Gemini, rather than reactively
  retrying 429s.
- **Additive, not a fallback tier.** NewsAPI/RSS already guarantee a
  working "no signup at all" baseline (RSS); Reddit requires registering
  a free app first (see §4), so it's layered on top rather than inserted
  into that fallback chain — if unconfigured, `RedditClient.fetch_for_ticker()`
  returns `[]` immediately with no network call and no warning, and the
  rest of the pipeline behaves exactly as it did before Reddit existed.
- **Twitter/X was deliberately not built.** As of the 2023+ API pricing
  changes, reading/searching public posts requires a paid Basic tier
  ($100+/month) — there's no usable free read path, unlike Reddit's
  genuinely free (if registration-gated) API. Building it would break
  this project's "works free out of the box, key optional for more"
  pattern every other source follows. Revisit if that changes.
- **⏳ Live end-to-end validation is PENDING** (code complete, unit
  tested, not yet exercised against the real Reddit API) — app creation
  at reddit.com/prefs/apps hit an issue that wasn't resolved yet. Once
  `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` are in `.env`, validate with:
  ```powershell
  python -m talonx_ingest.news.pipeline AAPL
  ```
  and confirm a `Found N Reddit post(s)` log line, then spot-check with
  `inspect_store.py --query "..." --ticker AAPL` for a `reddit:r/...`
  source in the results.

#### Live market data (`talonx_ingest.market_data`)

```
tickers → Polygon.io WebSocket (if POLYGON_API_KEY set)
            ├─ auth → subscribe (trades, quotes, minute bars)
            └─ on repeated reconnect failure → automatic failover to:
        → yfinance polling (every 5s, delayed data, no key required)
        → normalize both sources into one MarketEvent shape
        → publish MarketTickEvent to Redis (talonx:market:stream)
```

- **`polygon_ws.py`** — handles the connect/auth/subscribe/parse cycle,
  reconnects with jittered backoff on drops, and raises a distinct
  exception when the reconnect budget is exhausted (vs. an auth
  rejection) so the manager knows whether retrying differently would
  help or whether to fail over immediately.
- **`yfinance_poll.py`** — wraps the synchronous `yfinance` library in
  `asyncio.to_thread` so it doesn't block the event loop; batches all
  symbols into one call per poll cycle rather than one request each.
- **`manager.py`** — the single entrypoint downstream code talks to. It
  never exposes which source is active; consumers only see normalized
  `MarketEvent` objects with a `source` field for observability.

#### Redis event publishing (`talonx_ingest.events`)

The formal output contract, independent of ChromaDB. Two Pydantic
schemas (`MarketTickEvent`, `NewFilingIngestedEvent`) define exactly
what's published and where. If Redis is unreachable, publishing is
disabled for that run (logged once as a warning) — it never crashes
ingestion, since ChromaDB writes are the source of truth and Pub/Sub is
a real-time notification layer on top.

### 3.2 `talonx_quant` — Module 2: Technical & Quantitative Scanner

```
talonx:market:stream (Redis)
    → parse + validate each message as MarketTickEvent
    → only BAR-type events matter (trades/quotes are ignored --
      indicators need OHLCV, not tick-level data)
    → append to a per-ticker rolling buffer (bounded, oldest bars drop off)
    → once enough history exists (60 bars by default):
        → compute RSI, MACD, SMA fast/slow, volume-surge ratio via pandas_ta
        → evaluate against configured thresholds, EDGE-TRIGGERED (fires
          only on the bar the condition first becomes true, not every
          subsequent bar it remains true):
            - RSI crosses under 30 AND volume > 2x average → bullish (oversold + surge)
            - RSI crosses over 70 AND volume > 2x average  → bearish (overbought + surge)
            - MACD line crosses its signal line             → bullish/bearish cross
            - fast MA crosses slow MA, spread >= 0.15% of price → golden/death cross
    → candidate signal(s) for a ticker are DROPPED if that ticker is still
      within its post-signal cooldown (default 20 min); otherwise the
      ticker's cooldown starts now and the candidate(s) are buffered
    → every 60s (default), the buffer is ranked by volume_surge_ratio and
      only the top 3 (default) are published to Redis
      (talonx:signals:quant) -- the rest are dropped
```

**Noise filters (added after live testing surfaced alert chatter — see
§9.5 for the full before/after):**
- **Edge-triggering** (`strategy.py`) — every signal type, including the
  RSI+volume setup, fires only on the transition bar. Previously the
  RSI+volume check was a pure level check that would re-fire on every bar
  RSI stayed under 30/over 70; MACD and MA crossovers were already
  edge-triggered via their existing was-below/now-above comparison.
- **Hysteresis / minimum spread** (`strategy.py`, `TALONX_QUANT_MIN_MA_SPREAD_PCT`,
  default 0.15%) — a MA crossover only counts if the resulting fast/slow
  spread is at least this fraction of price. Filters a technically-real
  but economically-meaningless crossover, e.g. a $0.03 drift on a $500
  stock (~0.006%, far under 0.15%). Deliberately scoped to the MA cross
  only, not MACD.
- **Per-ticker cooldown** (`consumer.py`, `TALONX_QUANT_COOLDOWN_SECONDS`,
  default 1200 = 20 min) — a Redis key `cooldown:{TICKER}` locks a ticker
  out of producing ANY further candidate (regardless of signal_type) once
  one is accepted, until the cooldown expires. This is what stops e.g. an
  RSI+volume setup at 15:01 and an unrelated MACD cross at 15:12 on the
  same ticker from both alerting.
- **Batch throttle** (`consumer.py`, `TALONX_QUANT_THROTTLE_WINDOW_SECONDS`
  default 60 / `TALONX_QUANT_THROTTLE_MAX_SIGNALS` default 3) — candidates
  that clear cooldown are buffered, not published immediately. Every
  window, the buffer is ranked by `volume_surge_ratio` (a signal with no
  computed ratio sorts last) and only the top N are actually published.
  **This is a deliberate latency-for-quality tradeoff**: a signal can sit
  for up to the full window before it's published or dropped — there is
  no way to guarantee "top N of the window" without waiting for the
  window to close first. A final partial-window flush happens on
  `Ctrl+C`/reconnect so nothing buffered is silently lost.

- **`buffer.py`** — the rolling OHLCV window is deliberately deduped by
  timestamp: yfinance polling re-sends a snapshot of the *current* bar
  every 5 seconds (it's not a discrete new-bar push like a WebSocket
  aggregate), so without this the buffer would fill with dozens of
  near-identical rows for what is, price-action-wise, one bar.
- **`indicators.py`** — computes both the *current* and *previous*
  values for RSI, MACD, and moving averages, not just the latest, since
  edge-triggering/crossover detection needs to know the relationship
  flipped between two consecutive bars, not just where it stands now.
- **`strategy.py`** — a single bar update can trigger multiple
  independent signals at once (e.g. an RSI+volume setup and a MACD cross
  on the same bar) — each is evaluated separately rather than collapsed
  into one. All of them still pass through the SAME per-ticker cooldown
  in `consumer.py`, though, since that gate is ticker-scoped, not
  signal_type-scoped.
- This module is deliberately self-contained at the code level: it
  re-declares the `MarketTickEvent` shape locally rather than importing
  `talonx_ingest` Python objects, so the two modules could run as
  separate services/processes without refactoring. It does share the
  same `.env` file (both need the same `TALONX_REDIS_URL`), which is a
  config-sharing decision, not a code dependency.

### 3.3 `talonx_brain` — Module 3: Deep Research Agent & RAG Engine

```
talonx:signals:quant (Redis)
    → parse + validate each message as QuantSignal
    → cache-first: brain_cache:{ticker} in Redis has a FRESH entry?
        yes → skip retrieval AND the LLM call entirely, republish it
              (from_cache=True) -- this is the actual LLM-spend reduction
        no  → acquire lock:brain:{ticker} (distributed lock -- guards
              against a cache stampede if this ever runs as more than one
              process); lost the race? wait briefly for the winner's
              cache write, else generate anyway rather than block forever
    → retrieve top-K relevant chunks from ChromaDB's "sec_filings"
      collection, scoped to the signal's ticker (same store, same
      embedding model Module 1 wrote it with)
    → ALSO retrieve top-K relevant chunks from the "news_feed" collection,
      same ticker scope (optional -- TALONX_BRAIN_INCLUDE_NEWS, on by
      default; see retriever.py)
    → zero chunks retrieved at all (cold start)? bypass the LLM entirely,
      publish an INSUFFICIENT_CONTEXT report immediately
    → otherwise, build a structured RAG prompt (technical trigger + filing
      excerpts + news excerpts) and run it through the configured LLM
      provider (TALONX_BRAIN_LLM_PROVIDER, "gemini" by default or "ollama"
      for a local model -- see below) with a structured-output schema
      (verdict / confidence / summary / key findings / risk factors)
        LLM call fails? → stale (expired) brain_cache entry exists?
                            yes → republish it, flagged is_stale=True
                            no  → publish a DEGRADED report instead
                                  (verdict=neutral, confidence=0.0,
                                  is_degraded=True)
    → assemble a ResearchReport (LLM findings + the original QuantSignal +
      citation objects for every retrieved chunk, filing or news)
    → cache the result (brain_cache:{ticker}, unless it's degraded or
      itself a stale republish) and publish to Redis (talonx:reports:brain)

talonx:filings:events (Redis, published by talonx_ingest.pipeline)
    → NewFilingIngestedEvent for ticker X → DELETE brain_cache:X outright
      (not just marked stale -- a new filing genuinely invalidates old
      analysis, so it shouldn't be resurrected as a stale fallback either)
```

- **`retriever.py`** — unlike `talonx_quant`, this module is NOT
  self-contained at the code level: it imports
  `talonx_ingest.storage.vector_store.VectorStore` directly rather than
  re-declaring a Chroma client, because retrieval must run through the
  exact embedding function and persist directory Module 1 used to write
  each store — a mismatch there would silently return meaningless
  similarity scores, not just an error. It only inherits Module 1's
  `TALONX_CHROMA_*` / `TALONX_NEWS_CHROMA_COLLECTION` settings; there's no
  separate copy to drift out of sync. Queries `sec_filings` and
  `news_feed` independently (`ContextRetriever`, `TALONX_BRAIN_RETRIEVAL_TOP_K`
  and `TALONX_BRAIN_NEWS_TOP_K` respectively) and concatenates the
  results — filings first, then news — rather than re-ranking across
  collections by distance, since cosine distance is only comparable
  within one collection (same embedding model, same query), and filing
  text vs. news text have very different length/style profiles. Set
  `TALONX_BRAIN_INCLUDE_NEWS=false` to disable the news half and fall
  back to filings-only.
- **`llm.py`** — asks the LLM for a deliberately narrow structured output
  (verdict, confidence, summary, key findings, risk factors) rather than
  the full `ResearchReport` — ticker, the triggering signal, citation
  objects, model name, and timestamps are all assembled by Python code
  that already has them exactly right, instead of asking the model to
  echo data it could get wrong. Two provider implementations share one
  retry/backoff loop (`_BaseResearchChain.generate()`) and the same
  `generate(signal, citations) -> _LLMFindings` interface, so
  `consumer.py` never has to know which one is active:
  - **`GeminiResearchChain`** (default, `TALONX_BRAIN_LLM_PROVIDER=gemini`
    or unset) — cloud, via `langchain-google-genai`. Self-throttles with a
    token-bucket rate limiter (`TALONX_BRAIN_GEMINI_RPM`, default 5/min --
    match it to your actual quota) so a burst of signals paces itself
    under the free tier's per-MINUTE quota instead of retrying into
    repeated 429s. There's also a separate, unrelated free-tier quota this
    doesn't protect against — see §9.2's "and one more wall" and §9.4.
  - **`OllamaResearchChain`** (`TALONX_BRAIN_LLM_PROVIDER=ollama`) — local,
    via `langchain-ollama`, talking to a locally-running `ollama serve`.
    No API key, no rate limiter (nothing to throttle against — see §9.4
    for full setup and tradeoffs).
- **`consumer.py`** — same reconnect-with-backoff Redis listener shape as
  `talonx_quant.consumer`, subscribed to BOTH `talonx:signals:quant`
  (research trigger) and `talonx:filings:events` (cache invalidation --
  the publish side already existed in `talonx_ingest.pipeline`, this
  module just added the subscriber). Per-signal orchestration is
  cache-first → retrieve → generate → publish (see `cache.py` above), with
  an LLM failure falling back to a stale cache entry, then a degraded
  report, rather than just dropping the signal -- see the diagram. A
  failure that isn't otherwise handled (a genuinely broken payload, etc.)
  is logged and skipped rather than killing the listener.
- Publishes a `verdict` of `"insufficient_context"` (distinct from
  `"neutral"`) when retrieval comes back empty -- **bypassing the LLM
  call entirely** rather than spending a call asking the model to notice
  it has nothing to work with.
- **`cache.py`** — `BrainCache`, the Redis-backed qualitative cache
  (`brain_cache:{ticker}`) behind the cache-first flow in the diagram
  above. The one non-obvious design point: an "expired" entry still needs
  to be usable as a fallback (see below), but Redis's own `EX` TTL just
  DELETES a key once it elapses -- so every entry embeds its OWN logical
  `expires_at` inside the JSON payload and is written under a much longer
  Redis-level safety-net TTL (`TALONX_BRAIN_CACHE_SAFETY_TTL`, default
  6h); reads compare `now` against the embedded timestamp, not Redis's
  remaining TTL. `expires_at` at write time is the SOONER of a base TTL
  (`TALONX_BRAIN_CACHE_BASE_TTL`, default 2h) or the next daily
  market-open/close boundary (`TALONX_BRAIN_MARKET_TZ`, default
  `America/New_York`, via `zoneinfo` so EST/EDT is handled automatically;
  `TALONX_BRAIN_MARKET_OPEN_HOUR`/`_CLOSE_HOUR`, default 9/16) -- so
  cached research never outlives the trading session it was generated
  for. No holiday/weekend trading-calendar awareness -- see §8. The
  distributed lock (`lock:brain:{ticker}`, `TALONX_BRAIN_CACHE_LOCK_TTL`)
  and its bounded wait (`TALONX_BRAIN_CACHE_LOCK_WAIT_SECONDS`, default
  20s) only matter if `talonx_brain.run` is ever scaled to more than one
  process -- today's single-process consumer always acquires it
  immediately. `TALONX_BRAIN_CACHE_ENABLED=false` disables caching
  entirely (an escape hatch for debugging prompt changes, where a stale
  hit would be actively misleading).
- Wired into `run_talonx.py` as a third continuous task (see §3.5) --
  but OPTIONALLY: on the `gemini` provider, if `GEMINI_API_KEY` isn't set,
  the orchestrator logs a warning and runs Modules 1+2 without it rather
  than crashing (this check doesn't apply to the `ollama` provider, which
  has no API key to check). Run it standalone instead (§5h) if you want it
  decoupled from the other two.

### 3.4 `talonx_core` — Module 4: Core Event Bus & Decision Engine

```
talonx:signals:quant (Redis)  ──┐
                                 ├──► talonx_core: update per-ticker state
talonx:reports:brain (Redis)  ──┘     (TickerCorrelator -- freshest
                                        QuantSignal + freshest
                                        ResearchReport seen for that
                                        ticker, each timestamped by
                                        RECEIPT time)
                                       │
                                       ▼
                          re-run the Decision Matrix for that ticker
                          (decision.py -- pure function, no I/O):
                            1. both halves present? both still fresh
                               (within TALONX_CORE_CORRELATION_WINDOW)?
                            2. ticker not in cooldown
                               (TALONX_CORE_TICKER_COOLDOWN)?
                            3. report.is_degraded?
                               yes → action = DEGRADED_QUANT_ALERT
                                     (skips step 4 entirely)
                               no  → research confidence >=
                                     TALONX_CORE_MIN_CONFIDENCE, and verdict
                                     is directional (not neutral/
                                     insufficient)?
                          → any "no" at steps 1-2, or failing step 4 = no
                            alert, silently
                                       │
                                       ▼
                    (skipped for a degraded report) quant direction ==
                    research verdict?
                      yes → CONFIRMED_BULLISH / CONFIRMED_BEARISH
                      no  → CONTRADICTED (quant and research disagree)
                                       │
                                       ▼
                          5. state-transition + price-delta gate: is this
                             action the SAME as the last alert actually
                             dispatched for this ticker? If so, has price
                             moved >= TALONX_CORE_PRICE_DELTA_RETRIGGER_PCT
                             (default 1.0%) since that alert? A genuine
                             transition (or a first-ever alert) always
                             passes; a repeat of the same action without
                             enough price movement is suppressed -- runs
                             IN ADDITION to the cooldown at step 2, not
                             instead of it.
                                       │
                                       ▼
                     publish ActionableAlert to Redis
                     (talonx:alerts:dispatch), record that ticker's new
                     cooldown/action/price
```

- **`state.py`** — `TickerCorrelator` holds one `TickerState` per ticker,
  in memory, for the life of the process. Freshness is judged from when
  *talonx_core itself* received each half of the pair, not the payload's
  own internal timestamp -- this stays correct regardless of clock skew
  between producers or how long a message sat queued upstream (which, for
  `talonx_brain`, can be minutes under its Gemini rate limit -- see its
  README section).
- **`store.py`** — `TickerStateStore`, SQLite-backed (stdlib, same choice
  `talonx_ingest.storage.ledger` makes), one row per ticker, upserted on
  every update -- now including `last_alert_action`/`last_alert_price` for
  the re-trigger gate above, added via the same idempotent
  `PRAGMA table_info` + `ALTER TABLE` migration pattern used by
  `talonx_watchlist/store.py`, so a pre-existing `core_state.db` upgrades
  in place rather than erroring. Fixes a real gap: without it, a restart
  mid-correlation (a `QuantSignal` received but its `ResearchReport`
  hasn't landed yet -- routine given `talonx_brain`'s multi-minute lag)
  would silently lose that half of the pair forever. `consumer.py`
  rehydrates the correlator from it at startup and writes through on
  every update; `run.py`
  constructs it (`TALONX_CORE_ENABLE_PERSISTENCE`, default on;
  `TALONX_CORE_STATE_DB`, default `~/.talonx/core_state.db`) and degrades
  gracefully (logs a warning, continues in-memory-only) if the file can't
  be opened, same philosophy as Redis publishing elsewhere in this
  project. Calls are made synchronously, NOT via `asyncio.to_thread` --
  `sqlite3`'s default `check_same_thread=True` would break under a
  different worker thread, same reasoning `IngestionLedger` documents for
  its own connection.
- **`decision.py`** — the Decision Matrix itself: a pure function over a
  `TickerState` snapshot, no I/O, so it's trivial to unit test in
  isolation from Redis/asyncio (see `tests/test_core_decision.py`).
  Deliberately narrow: only `CONFIRMED_BULLISH`, `CONFIRMED_BEARISH`,
  `CONTRADICTED`, and `DEGRADED_QUANT_ALERT` ever reach the alerts
  channel -- a neutral/insufficient-context verdict, or one below the
  confidence gate, is UNCONFIRMED and produces no alert at all, keeping
  `talonx:alerts:dispatch` purely actionable rather than a firehose.
  `CONTRADICTED` is treated as at least as noteworthy as agreement (its
  severity floor is WARNING, never INFO) -- a technical signal and the
  research disagreeing is arguably the more actionable outcome of the
  two, not a "nothing to report" case.
- **State-transition + price-delta re-trigger gate** — a second guardrail
  on top of the time-based cooldown (both must pass, neither replaces the
  other): `TickerState` now also tracks the `action` and `triggering
  signal price` of the last alert actually dispatched for a ticker. A new
  evaluation that would produce the SAME action as that last alert is
  suppressed unless price has moved at least `TALONX_CORE_PRICE_DELTA_RETRIGGER_PCT`
  (default 1.0%) since then; a genuine transition (including the very
  first alert for a ticker) always passes regardless of price. Persisted
  the same way as everything else in `store.py` (see below).
- **`report.is_degraded` bypass** — `talonx_brain` publishes a
  specially-flagged `ResearchReport` (verdict `neutral`, confidence 0.0,
  `is_degraded=True`) when its LLM call fails AND it has no cached report
  to fall back on (see §3.3's caching section). `decision.py` recognizes
  this flag and skips the confidence/verdict matrix entirely, always
  producing `DEGRADED_QUANT_ALERT` (severity WARNING, regardless of the
  0.0 confidence) instead of silently suppressing it the way a normal
  low-confidence report would be -- the point is the user should still
  learn a technical signal fired even with zero qualitative backing.
  `DEGRADED_QUANT_ALERT` participates in the state-transition gate above
  as its own pseudo-state, so a sustained LLM outage doesn't re-alert on
  every single signal for the same ticker.
- **`consumer.py`** — subscribes to BOTH `talonx:signals:quant` and
  `talonx:reports:brain` on one Redis connection (`pubsub.subscribe`
  called with two channel names), routes each incoming message to the
  correlator by channel, and re-runs the decision matrix after every
  single update -- so a decision can be triggered by either half of the
  pair arriving second, not just by report arrival. Same reconnect-with-
  backoff shape as `talonx_quant.consumer` / `talonx_brain.consumer`; a
  bad message on either channel is logged and dropped rather than killing
  the listener.
- **Deliberately self-contained at the code level**, same as
  `talonx_quant`: re-declares the `QuantSignal` and `ResearchReport` wire
  shapes locally rather than importing `talonx_quant`/`talonx_brain`
  Python objects (its `ResearchReport` mirror is trimmed -- it omits
  `citations`, which the decision matrix never uses; Pydantic's default
  `extra="ignore"` behavior means parsing the real, fuller wire payload
  still works fine). Its only real dependencies are `redis.asyncio`,
  `pydantic`, and `asyncio`, matching the module spec.
- **Risk guardrails implemented**: a confidence gate (`TALONX_CORE_MIN_CONFIDENCE`),
  a per-ticker time cooldown (`TALONX_CORE_TICKER_COOLDOWN`), and the
  state-transition + price-delta re-trigger gate
  (`TALONX_CORE_PRICE_DELTA_RETRIGGER_PCT`) above. **Not implemented**: a
  global cross-ticker rate limiter -- see §8.
- Wired into `run_talonx.py` as a fourth continuous task (see §3.6),
  unconditionally (unlike Module 3, it has no optional external
  dependency -- no API key, nothing that can plausibly be missing beyond
  what Modules 2/3 already require). `--skip-core` leaves it out on
  purpose. Run it standalone instead (§5i) if you want it decoupled.

### 3.5 `talonx_dispatch` — Module 5: Notification Dispatcher & Streamlit Interface

```
talonx:alerts:dispatch (Redis)
    → parse + validate each message as ActionableAlert
    → record it to the audit trail FIRST, unconditionally (store.py --
      SQLite, durable; this is now the ONLY durable historical record of
      alerts anywhere in the pipeline, since Redis Pub/Sub itself isn't one)
    → if Telegram is configured AND severity >= TALONX_DISPATCH_MIN_SEVERITY:
        → format a SHORT summary (ticker/action/price/confidence/one-line
          quant trigger + this alert's ID -- formatter.format_telegram_summary)
        → send via python-telegram-bot, with retry/backoff (telegram_client.py)
        → record delivery success/failure back onto that alert's audit row

(concurrently, in the SAME process -- DispatchAgent.run() is 3 tasks, not 1:)
Telegram (incoming messages, telegram_listener.py's TelegramReplyListener)
    → long-polls Bot.get_updates() -- Telegram's own server-side long-poll,
      not a busy loop
    → someone replies to a push with its ID (or "/details 47", "/id 47")
    → look it up (store.get_by_id) → reply with the FULL writeup
      (formatter.format_telegram_details); not found (or purged by
      retention) → a "not found" reply; anything else → a usage hint
    → only ever responds to the configured TELEGRAM_CHAT_ID -- a personal,
      single-user bot, not multi-tenant

(also concurrently:) retention sweep -- purge_older_than(), once at
startup then every TALONX_DISPATCH_RETENTION_SWEEP_HOURS (default 24h),
deleting audit rows older than TALONX_DISPATCH_RETENTION_DAYS (default 5)
so a long-running install doesn't grow dispatch_audit.db forever (and so
an alert ID stops being answerable via Telegram once it's aged out)

(independently, as a SEPARATE process:)
Streamlit (`streamlit run talonx_dispatch/app.py`)
    → reads the SAME audit trail SQLite file
    → renders live metrics, a derived per-ticker watchlist, a live alert
      feed, and a filterable audit trail table
    → auto-refreshes on a timer (streamlit-autorefresh) for a "live" feel
```

- **Two cooperating processes, not one -- a deliberate architecture
  decision, not what the module spec's file list literally implies.**
  Streamlit reruns its entire script top-to-bottom on every
  interaction/refresh, which is fundamentally incompatible with holding
  a persistent asyncio Redis Pub/Sub subscription open. So `consumer.py`
  (the async Redis subscriber + Telegram dispatcher) and `app.py` (the
  Streamlit dashboard) are separate, independently-run processes that
  communicate through `store.py`'s SQLite file rather than sharing
  in-process state -- same "async producer writes to durable local
  SQLite, something else reads it" shape as `talonx_core.store`. Both
  need to be running for the dashboard to show anything (§5m/§5n).
- **`store.py`** — the audit trail itself, and the first durable
  historical record of alerts in the whole pipeline (talonx_core's own
  `TickerStateStore` persists correlator *state*, not a log of *published
  alerts*). SQLite, same pattern as `talonx_ingest.storage.ledger` /
  `talonx_core.store`, with one deliberate deviation: `check_same_thread`
  defaults to `True` (matching the others) for `consumer.py`'s single-
  process, single-thread connection, but `app.py` explicitly passes
  `check_same_thread=False` for its own connection, since Streamlit's
  execution model can run a cached session object on a different thread
  than the one that created it -- a real constraint the ledger/core_state
  precedent didn't have to deal with. WAL journal mode is enabled for
  smoother concurrent read-while-write between the two processes. Every
  public method holds an internal `threading.Lock`, added after a real
  concurrency bug: two Streamlit reruns sharing the cached, `check_same_
  thread=False` connection on different threads could interleave and hit
  an "impossible" state. `get_by_id()` backs the Telegram reply lookup;
  `purge_older_than()` backs the retention sweep
  (`TALONX_DISPATCH_RETENTION_DAYS`, default 5) -- both new.
- **`formatter.py`** — TWO pure formatting functions now, no I/O, trivially
  unit-testable without a bot token. `format_telegram_summary(alert,
  alert_id)` is the actual push: short enough to read at a glance during
  a live session (ticker/action/price/confidence/one-line quant trigger +
  the ID), which replaced a much longer message that used to carry the
  full research writeup on every single push. `format_telegram_details(row)`
  is that full writeup (rationale, key findings, risks, model/timestamp
  footer) -- sent back on demand when someone replies with the ID. It
  takes an audit ROW DICT (`AuditStore.get_by_id()`'s shape), not a live
  `ActionableAlert` -- by reply time, possibly minutes or days later, the
  original in-memory object is long gone, but every field it needs is
  already a stored column. Both use Telegram's LEGACY "Markdown" parse
  mode rather than "MarkdownV2" -- MarkdownV2 requires escaping a long
  list of characters that routinely show up in Gemini-generated research
  text (`_*[]()~`>#+-=|{}.!`), which would be a much larger surface for a
  garbled message than this is worth. Legacy mode only needs 4 characters
  escaped (`_*\`[`), handled for any upstream-generated text (ticker/enum
  values are from our own schemas and never need escaping).
- **`telegram_client.py`** — the SEND side. `is_configured` gates
  everything, same "additive, degrade gracefully" pattern `RedditClient`
  established: if `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` aren't set,
  `send()` is a silent no-op and the audit trail (and Streamlit
  dashboard) work normally without it. Retries transient failures with
  jittered backoff; respects Telegram's own `RetryAfter` hint exactly
  when it's given one rather than guessing a backoff; fails fast (no
  retry) on a bad token/forbidden chat, since retrying a config problem
  just burns the retry budget for nothing.
- **`telegram_listener.py`** — the RECEIVE side (`TelegramReplyListener`),
  new: long-polls `Bot.get_updates()` for incoming messages and answers
  "reply with an alert's ID" requests by looking it up in the audit trail
  and sending back `format_telegram_details`. Drains any backlog on
  startup (one throwaway `get_updates()` call with no offset) so a
  restart doesn't replay old commands. Only started (as a third task
  under `DispatchAgent.run()`) if Telegram is configured -- no token,
  nothing to poll. **Only one process may poll a given bot token's
  `get_updates()` at a time** -- running two `DispatchAgent`s against the
  same `TELEGRAM_BOT_TOKEN` makes the second one's polling fail with HTTP
  409 Conflict.
- **Mobile push notifications are severity-gated**
  (`TALONX_DISPATCH_MIN_SEVERITY`, default `warning`) -- an `INFO`-level
  alert still gets recorded to the audit trail and shows in the Streamlit
  feed, it just doesn't buzz your phone. This is a product judgment call
  (mobile notification fatigue is real), not a technical constraint;
  lower it to `info` in `.env` if you want everything pushed.
- **Deliberately self-contained at the code level**, same as
  `talonx_quant`/`talonx_core`: re-declares a TRIMMED `ActionableAlert`
  mirror rather than importing `talonx_core` Python objects -- the
  embedded triggering-signal reference drops the numeric indicator
  fields (rsi/macd/sma/volume) this module only ever displays, never
  recomputes. Pydantic's default `extra="ignore"` behavior means parsing
  the real, fuller wire payload still works fine. Dependencies match the
  module spec exactly: `redis.asyncio`, `pydantic`,
  `python-telegram-bot`, `streamlit`, `streamlit-autorefresh`, `pandas`.
- **This finally closes the gap flagged since Module 4 was built**
  (§8 used to say "no ACTIONABLE downstream consumer of
  `talonx:alerts:dispatch` is built" -- `dashboard.py`/`dashboard_web.py`
  gave visibility, but did nothing with an alert). Telegram push is the
  action; the audit trail + Streamlit dashboard is the review surface.
- **`consumer.py` is wired into `run_talonx.py`** (§3.7) -- no required API
  key, same "safe to always include" reasoning as Module 4. `app.py`
  (Streamlit) is NOT, and never will be: Streamlit's own dev server is not
  an `asyncio.gather()`-compatible task (see the "Two cooperating
  processes" note above) -- always run it separately, alongside
  `run_talonx.py`, in its own terminal (§5n).

### 3.6 `talonx_paper` — Module 6: Live Paper Trading Engine

```
Redis: talonx:alerts:dispatch ──┐
                                 ├──► talonx_paper.consumer
Redis: talonx:market:stream ────┘         │
                                           ├─ ticker has paper trading enabled?
                                           │  (talonx_watchlist -- see below) no -> skip
                                           │
                                           ├─ market tick (BAR)? -> update_latest_price
                                           │  (mark-to-market source for the dashboard,
                                           │  a SEPARATE process with no access to this
                                           │  one's in-memory state)
                                           │
                                           └─ alert -> engine.decide_trade (pure):
                                                CONFIRMED_BULLISH + flat        -> BUY
                                                CONFIRMED_BEARISH/CONTRADICTED
                                                  + long                       -> SELL
                                                repeat signal, same state       -> ignored
                                                                                    (logged only)
                                                DEGRADED_QUANT_ALERT            -> no action
                                                          │
                                                          ▼
                                        PaperTradingStore.execute_buy/execute_sell
                                        (SQLite -- positions, trade_history,
                                        portfolio_state all updated atomically)
                                                          │
                                                          ▼
                                        Redis: talonx:paper:trades (PaperTradeExecution)
                                                          │
                                                          ▼
                                        talonx_dispatch.consumer -- its OWN short
                                        Telegram push (§3.5), decoupled from the
                                        triggering alert's push
```

- **Not what the original requirement doc specified, and why**: the doc
  asked for a PostgreSQL ledger and one combined Telegram message (alert +
  execution card together) -- both deliberately NOT built that way here.
  SQLite matches every other store in this project (no new database
  technology, no new docker service) and two DECOUPLED short pushes
  preserve the alert-shortening work from the session before this one,
  rather than reintroducing a long combined message. Position sizing is a
  FIXED dollar amount per trade (default $2,500, `TALONX_PAPER_TRADE_ALLOCATION`)
  rather than "100% of cash" -- since the one-position-per-TICKER limit is
  per-ticker, not portfolio-wide, "100% of cash" would let the first BUY
  signal claim the entire balance and starve every other tracked ticker.
- **Trigger mapping**: the doc's own action names (`BUY_SIGNAL`,
  `BEARISH`, `VALUE_TRAP_WARNING`) don't exist in the real `AlertAction`
  enum -- mapped onto the real one in `engine.py`: BUY on
  `CONFIRMED_BULLISH`, SELL on `CONFIRMED_BEARISH` **or** `CONTRADICTED`
  (the doc's own Telegram example shows `CONTRADICTED` triggering a
  SELL), no action at all on `DEGRADED_QUANT_ALERT` (no research backing,
  not worth trading on).
- **`engine.py`** -- pure functions, no I/O, same testability philosophy
  as `talonx_core.decision`: `decide_trade` (the state machine above),
  `calculate_buy` (spends `min(allocation, cash)`, so a low balance
  partially fills rather than erroring), `calculate_sell_pnl` (exact
  formulas from the requirement doc, verified against its own worked
  example in `tests/test_paper_engine.py`).
- **`store.py`** -- `PaperTradingStore`, SQLite (WAL, `threading.Lock`,
  same convention every store built this session uses). Four tables:
  `portfolio_state` (single row -- cash, allocation, cumulative PnL,
  win/loss counts; percentages are DERIVED on read, never stored, so they
  can't drift), `positions` (one row per OPEN position -- a ticker's
  ABSENCE from this table IS "flat," no separate status column),
  `trade_history` (append-only, powers the dashboard's trade table, CSV
  export, and equity curve), `latest_prices` (updated on every market
  tick -- exists because the Streamlit dashboard is a separate process
  with no access to the engine's in-memory price cache). `execute_buy`/
  `execute_sell` are OPERATION-shaped, not raw CRUD -- each updates
  positions + portfolio_state + trade_history atomically (one lock, one
  commit) so `consumer.py` never hand-coordinates a multi-table write.
- **Per-ticker enable/disable lives in `talonx_watchlist`, not a second
  ticker list** -- `paper_trading_enabled` is a new column on the SAME
  `tickers` table §5n's dashboard already manages (same idempotent
  migration pattern as `exchange`/`status` before it), toggled via a
  multiselect in the dashboard's new "💰 Paper Trading" section. This is
  the "configure which ticker can be used" control surface.
- Wired into `run_talonx.py` as a sixth continuous task (see §3.7) --
  `--skip-paper-trading` leaves it out on purpose; a ledger-open failure
  degrades the same way Module 5's audit DB failure does (warns, doesn't
  crash the rest of the pipeline). Run it standalone with
  `python -m talonx_paper.run` if you want it decoupled.

### 3.7 `run_talonx.py` — orchestrator

Runs Module 1's periodic ingestion (filings + news, immediately then on
a repeating interval) and Module 1 + 2 + 3 + 4 + 5 + 6's six continuous
streams (market data, quant scanner, research agent, decision engine,
dispatch agent, paper trading engine) together as concurrent tasks in one
process. A failure in one periodic ingestion cycle is logged and the loop
continues to the next scheduled run; the continuous streams are
unaffected by ingestion cycle failures entirely, since they're
independent tasks. Module 3 is optional here -- `--skip-brain` leaves it
out on purpose, and it's left out automatically (with a warning, not a
crash) if its configured LLM provider isn't ready (§3.3). Modules 5 and 6
degrade the same way if their respective SQLite ledgers can't be opened
(rare). Modules 2 and 4 are always included unless explicitly skipped.
**The Streamlit dashboard is never included** (see §3.5 -- run it
alongside this file, in its own terminal, §5n).

**Every continuous component can be pulled out individually**
(`--skip-market-data`, `--skip-quant`, `--skip-brain`, `--skip-core`,
`--skip-dispatch`, `--skip-paper-trading`) -- useful while actively
iterating on one piece: run the others here and the one you're changing
in its own terminal, so you don't have to restart this whole process on
every edit. If every component ends up skipped (including
`--skip-ingestion`), it logs an error and exits immediately rather than
hanging on an empty task list.

### 3.8 End-to-end data flow

```
SEC EDGAR ──┐
            ├──► talonx_ingest ──► ChromaDB (sec_filings, news_feed)
News/RSS ───┘         │                          ▲
                       └──► Redis: talonx:filings:events
                                                   │ (retrieval, scoped by ticker)
Polygon/yfinance ──► talonx_ingest.market_data ──► Redis: talonx:market:stream
                                                          │
                                                          ▼
                                              talonx_quant (buffer, indicators, strategy)
                                                          │
                                                          ▼
                                              Redis: talonx:signals:quant ──────┐
                                                          │                     │
                                                          ▼                     │
                                    talonx_brain (retriever, Gemini structured  │
                                                  chain)                        │
                                                          │                     │
                                                          ▼                     │
                                              Redis: talonx:reports:brain ──┐   │
                                                                            │   │
                                                                            ▼   ▼
                                                    talonx_core (TickerCorrelator, Decision Matrix)
                                                                            │
                                                                            ▼
                                                     Redis: talonx:alerts:dispatch ──────┐
                                                                            │            │
                                                                            ▼            ▼
                                                    talonx_dispatch.consumer      talonx_paper.consumer
                                                    (audit + short Telegram push)  (BUY/SELL simulation,
                                                                            │       ticker gated by
                                                            ┌───────────────┤       talonx_watchlist)
                                                            ▼               ▼            │
                                                   SQLite: dispatch_audit.db  Telegram    ▼
                                                            ▲                    Redis: talonx:paper:trades
                                                            │ (read-only,               │
                                                            │  separate process)         ▼
                                                   talonx_dispatch.app ◄── SQLite: paper_trading.db
                                                   (Streamlit dashboard:           │
                                                    alerts + watchlist +           ▼
                                                    paper trading)          talonx_dispatch.consumer's
                                                                             OWN short Telegram push
                                                                             (decoupled from the alert's)
```

---

### 3.9 Phase 2 — Multi-Horizon Architecture (`LONG_TERM` alongside `INTRADAY`)

TalonX started as a purely intraday momentum scanner (minutes-to-hours
holding period). Phase 2 adds a SECOND, fully independent horizon --
fundamentals-driven quality/value investing (6-months-to-multi-year
holding) -- running alongside the first, without touching how the
intraday engine behaves. Both horizons share the same watchlist, the
same Redis connection, and (for `talonx_paper`) the same SQLite file,
but every other piece of state is a SIBLING, not a shared/merged one --
that segregation is the core design decision behind everything below.

**Tagging a ticker's horizon.** `talonx_watchlist`'s "🎯 Tracked
tickers" table (§5n) gained a Horizon selector per row (and on the
add-ticker form): `INTRADAY` (default, Phase 1 behavior, unchanged),
`LONG_TERM` (fundamentals path only -- bypasses minute-bar technical
scanning entirely), or `DUAL_HORIZON` (both paths run independently for
the same ticker). A `DUAL_HORIZON` ticker's intraday and long-term
state, positions, and alerts never collide -- see "Why sibling objects,
not composite keys" below.

**Why sibling objects, not composite keys.** Threading a `(ticker,
horizon)` tuple through the EXISTING intraday structures
(`TickerCorrelator`, `TickerStateStore.ticker_state`,
`PaperTradingStore.positions`) would have meant a `DUAL_HORIZON`
ticker's two evaluations silently colliding in the same slot. Instead,
every Phase 2 addition is a separate class/table/schema: a second
`LongTermTickerCorrelator` alongside `TickerCorrelator`, a second
`ticker_state_long_term` table alongside `ticker_state`, a second set of
`long_term_*` tables in the SAME `paper_trading.db` file (sharing only
the `latest_prices` mark-to-market cache -- a price is a price
regardless of horizon), and a second `long_term_alerts` table alongside
`alerts` in the audit trail. This also matches the project's existing
convention of each module re-declaring its own trimmed wire schemas
rather than sharing Python objects across module boundaries.

**Per-module additions:**

- **`talonx_ingest`** -- a new structured-financials path, entirely
  separate from the existing filing-TEXT ingestion (which still runs
  too; moat/DCF research needs the qualitative 10-K text as well as the
  numbers). `edgar/financials.py` parses up to 10 years of annual facts
  from SEC's XBRL "company facts" API (`EdgarClient.get_company_facts`),
  with a fallback chain per financial-statement field since XBRL tag
  naming varies by company/era. `ingest_long_term_financials()`
  publishes a `NewFundamentalsIngestedEvent` (embedding the parsed
  numbers directly, not just metadata) on `talonx:fundamentals:events`
  whenever a fiscal year newer than the ledger's last-known one is
  found.
- **`talonx_quant`** -- `fundamentals.py` computes ROIC, the Piotroski
  F-Score (0-9; 2 of the spec's 9 checks are substituted with
  revenue-growth and FCF-positivity, since this codebase has no prior
  Days-Sales-Outstanding/gross-margin data to compare against), FCF
  Yield, and a documented Altman Z-Score variant (Working Capital and
  Total Liabilities components substituted with Cash/Total Assets and a
  Total Debt proxy -- returns `None` for a debt-free company, since the
  debt-based proxy is undefined for one). `fundamental_consumer.py`'s
  `FundamentalScanner` is a SIBLING to `QuantScanner`, not a second loop
  inside it -- a quarterly-cadence signal has no use for a 20-minute
  intraday cooldown, and batch-throttling a handful of quarterly signals
  would be pointless complexity. Publishes a `FundamentalFactorSignal`
  to `talonx:signals:fundamental` whenever ROIC and F-Score both clear
  their configured thresholds (`TALONX_QUANT_ROIC_THRESHOLD` /
  `TALONX_QUANT_F_SCORE_THRESHOLD`, defaults 15% / 7).
- **`talonx_brain`** -- a long-term research chain
  (`build_long_term_research_chain`) producing moat rating
  (WIDE/NARROW/NONE), a capital-allocation assessment, a DCF fair value
  per share, and a 0-10 quality score, using the SAME Gemini/Ollama
  provider already configured for the intraday chain (§3.3, §9.4). The
  qualitative-research cache (§3.3) gained a `horizon` parameter --
  intraday keys are byte-identical to before (no invalidation of
  existing cache entries), long-term keys use a flat 90-day TTL cap (no
  market-hours-boundary math -- a multi-year thesis has no "trading
  session" to outlive) and are ALSO invalidated the moment a fresh
  filing OR fresh structured financials arrive for that ticker.
- **`talonx_core`** -- `evaluate_long_term()` implements the spec's
  4-rule decision matrix verbatim: `HIGH_CONVICTION_BUY` (quality ≥ 7/10,
  a real moat, price ≤ 0.8× fair value), `HOLD_QUALITY` (quality ≥ 7/10,
  price within the 0.8×-1.2× band), `TAKE_PROFIT_REBALANCE` (price >
  1.2× fair value), `UNDER_PERFORM_REBALANCE` (ROIC below WACC for 2
  consecutive quarters, OR Debt/EBITDA above `TALONX_CORE_LT_MAX_DEBT_TO_EBITDA`,
  OR the moat rating was downgraded since the last evaluation). WACC has
  no real data source anywhere in this project (no beta/market-risk-
  premium feed) -- it's a documented assumed constant
  (`TALONX_CORE_LT_ASSUMED_WACC`, default 9%), and EBITDA is proxied by
  operating income (no separate D&A line exists in the parsed XBRL
  facts) -- both intentionally conservative-direction simplifications,
  not real financial-model outputs.
- **`talonx_paper`** -- a DCA-aware ledger in the SAME `paper_trading.db`
  file, with its OWN cash pool (`TALONX_PAPER_LT_INITIAL_BALANCE`,
  default $20,000, entirely separate from the intraday portfolio's
  balance). `HIGH_CONVICTION_BUY` opens a position only when flat
  (`TALONX_PAPER_LT_INITIAL_POSITION`); ongoing conviction is then
  expressed through a recurring DCA contribution
  (`TALONX_PAPER_DCA_CONTRIBUTION`, every `TALONX_PAPER_DCA_INTERVAL_DAYS`
  -- a fixed-interval approximation of "monthly," not true calendar-month
  scheduling) into every currently-open long-term position, not by
  repeating the BUY alert itself. `TAKE_PROFIT_REBALANCE` trims a
  configurable fraction (`TALONX_PAPER_REBALANCE_TRIM_PCT`, default
  33%); `UNDER_PERFORM_REBALANCE` is a full exit. As with the intraday
  engine, entry (BUY-type) triggers are gated by conviction; exit
  (SELL-type / fundamental-stop) triggers are NEVER gated.
- **`talonx_dispatch`** -- a separate `long_term_alerts` audit table and
  its own Telegram push format (price vs. fair value, margin of safety,
  quality/moat, the take-profit exit target, expected holding horizon).
  Because `alerts` and `long_term_alerts` are two independently-
  auto-incrementing tables, long-term Telegram IDs are prefixed --
  `#LT12` in the push, reply `LT12` (case-insensitive) for full detail,
  disambiguated from a bare intraday `#12`.
- **Dashboard (`talonx_dispatch/app.py`)** -- restructured into 3 tabs:
  **📈 Intraday Monitor** (everything Phase 1 already had), **💎
  Long-Term Radar** (a Valuation & Margin of Safety table, the
  moat/capital-allocation/DCF writeup behind each ticker, and the
  long-term portfolio's cash/positions/DCA-contributed/equity curve),
  and **⚙️ Watchlist & Settings** (the ticker watchlist with its horizon
  selector, both portfolios' settings, and a horizon-filterable unified
  audit trail).
- **`generate_eod_report.py`** -- gained a Valuation & Margin of Safety
  Radar section (latest known price/fair-value/quality/moat snapshot per
  ticker -- NOT limited to the report's own calendar day, since
  fundamentals evaluations happen on the order of quarters, not daily)
  and a Long-Term Portfolio summary section (cash, total DCA
  contributed, unrealized + realized PnL), both from `AuditStore`/
  `PaperTradingStore`'s existing Phase 2 tables.
- **Structured JSON logging** -- `talonx_ingest/common/structured_logging.py`'s
  `log_structured()` helper (one JSON line per key event:
  `FACTOR_CALCULATED`, `MOAT_EVALUATED`, `VALUATION_DERIVED`,
  `TRADE_EXECUTED`, `FUNDAMENTAL_STOP_TRIGGERED`) is applied to every NEW
  long-term code path. It's routed through a dedicated
  `<module>.structured` CHILD logger rather than the module's own
  logger, specifically because `talonx_brain.consumer` /
  `talonx_core.consumer` / `talonx_paper.consumer` each handle BOTH
  horizons in the same class -- this keeps the new JSON lines fully
  isolated from that module's pre-existing plain-text intraday log
  lines, in either direction. Retrofitting those existing ~15 intraday
  log call sites to the same format is a deliberate, separate follow-up
  (§8).

**Not built this pass** (see §8 for the reasoning behind each): DRIP /
dividend reinvestment, a separate End-of-Quarter report, a full
structured-logging retrofit of the pre-existing intraday log lines, true
calendar-month DCA scheduling, and a real CAPM-based WACC.

---

## 4. First-time setup

Open a terminal (VS Code integrated terminal, or Visual Studio's Terminal
pane) **in `C:\workspace\TalonX`** — the parent folder, not `talonx_ingest`.

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# Your prompt should now show (.venv) at the start of the line.

# 2. Install dependencies
pip install -r talonx_ingest\requirements.txt
```

This installs `aiohttp`, `chromadb`, `sentence-transformers` (pulls in
PyTorch — the slow part), `websockets`, `yfinance`, and a few smaller
libraries. Expect this step to take several minutes on first run.

```powershell
# 3. Set up your .env file (repo root, shared by every module)
copy .env.example .env
```

Edit `.env` and set at minimum:
```
TALONX_SEC_USER_AGENT="Your Name Your Company your.email@example.com"
```
SEC EDGAR requires a real, descriptive User-Agent — without one you'll get
403 errors. Everything else in `.env.example` is optional and has sane
defaults (commented out).

If you want live market data via Polygon.io (optional — yfinance polling
works with no key at all), also set:
```
POLYGON_API_KEY=your_polygon_io_api_key
```

If you want to run Module 3 (`talonx_brain`), pick ONE of the two LLM
providers below (§9.4 has the full tradeoff writeup):

**Option A — Gemini (default, cloud)**, required — there's no fallback
path without it:
```
GEMINI_API_KEY=your_gemini_api_key
```

**Option B — Ollama (local, no API key/quota)** — install
[Ollama](https://ollama.com/download), run `ollama pull llama3.1` once,
then set:
```
TALONX_BRAIN_LLM_PROVIDER=ollama
```
`ollama serve` must be running (the installer sets it up as a background
service on Windows, so this is usually already true — check with
`ollama list`). No `GEMINI_API_KEY` needed for this path.

If you want Reddit as an additional news/social source (optional —
NewsAPI/RSS already work with no signup at all; Reddit adds ON TOP of
that, it's not required for anything else to function):
1. Log into Reddit, go to https://www.reddit.com/prefs/apps
2. Click "create another app...", choose **script**, fill in any
   name/description, redirect URI can be `http://localhost:8080`
   (unused, but the form requires something)
3. After creating it, the client ID is the string under the app name;
   the client secret is labeled "secret"
4. Set in `.env`:
```
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USER_AGENT="TalonX Research Engine by /u/your_reddit_username"
```
Reddit requires a real, descriptive User-Agent identifying an actual
account (same non-negotiable rule SEC EDGAR has for
`TALONX_SEC_USER_AGENT`) — a generic or missing one gets throttled hard
or blocked.

If you want Telegram push notifications from Module 5
(`talonx_dispatch`), optional — without it, alerts are still recorded to
the audit trail and shown in the Streamlit dashboard, you just don't get
a mobile push:
1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts
   (name, username ending in `bot`). It replies with a token that looks
   like `123456789:AAH...` — that's your `TELEGRAM_BOT_TOKEN`.
2. Send your new bot ANY message first (bots can't message you until you
   message them first) — search for its username and send e.g. `hi`.
3. Get your chat ID: open
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
   (substitute your real token), and find `"chat":{"id":...}` in the
   response — that number is your `TELEGRAM_CHAT_ID`.
4. Set in `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Each push is now a short summary ending in an ID (`#47`) — **reply to
that message with the number** (`47`, `#47`, `/details 47`, or `/id 47`
all work) to get the full research writeup back from the bot. Only
replies from the `TELEGRAM_CHAT_ID` above are answered. An ID stops
working once its alert ages out of the audit trail
(`TALONX_DISPATCH_RETENTION_DAYS`, default 5 days) — the bot replies
"not found" rather than erroring.

---

## 5. Running things

All commands below assume: `.venv` is activated, and your terminal's
current directory is `C:\workspace\TalonX`.

### 5a. Run everything together (recommended)

```powershell
python run_talonx.py
```
Single process, single terminal, single Ctrl+C to stop. This starts:
- SEC filing + news ingestion, immediately, then again every 6 hours (`--interval-hours` to change)
- Live market data streaming, continuously
- The quant scanner, continuously
- The research agent (Module 3), continuously -- *if* its LLM provider is
  ready (`GEMINI_API_KEY` set for the default `gemini` provider, or
  `ollama serve` running for `TALONX_BRAIN_LLM_PROVIDER=ollama`) and
  `talonx_brain\requirements.txt` is installed; otherwise it's skipped
  with a one-time warning, everything else still runs
- The decision engine (Module 4), continuously -- always, no optional
  dependency to be missing
- The dispatch agent (Module 5), continuously -- *if* its audit database
  can open (essentially always; the only failure mode is a bad path/
  permissions issue). Records every alert to the audit trail and pushes to
  Telegram if configured.
- The paper trading engine (Module 6), continuously -- *if* its ledger
  database can open (same failure mode as Module 5). Simulates BUY/SELL
  execution for tickers with paper trading enabled (§3.6) and pushes its
  own short Telegram notification per executed trade.
- **Phase 2 (§3.9)**, automatically for any ticker tagged `LONG_TERM` or
  `DUAL_HORIZON` in the watchlist -- structured financials ingestion, the
  fundamental factor scanner, a slow daily-close price poll for
  `LONG_TERM`-only tickers (a `DUAL_HORIZON` ticker already gets prices
  from the regular stream above), and the DCA-aware long-term paper
  engine. Modules 3/4/5 (`talonx_brain`/`talonx_core`/`talonx_dispatch`)
  already handle both horizons internally within the same task started
  above -- no separate flag needed for those three. A fresh install with
  no `LONG_TERM`-tagged tickers simply has nothing for any of this to do.

**The Streamlit dashboard is separate** -- run
`streamlit run talonx_dispatch\app.py` (§5n) in its own terminal
alongside this one if you want to view it live (alerts, the ticker
watchlist, AND the paper trading portfolio all live there).

Custom tickers:
```powershell
python run_talonx.py AAPL MSFT NVDA TSLA
```
Skip the periodic ingestion and only run the continuous streams (e.g.
if you already have filings/news ingested and just want live monitoring):
```powershell
python run_talonx.py --skip-ingestion
```
Leave out the research agent even if it's configured (e.g. to avoid Gemini
API usage while just testing Modules 1+2):
```powershell
python run_talonx.py --skip-brain
```
Leave out the decision engine (e.g. while debugging Modules 1-3 in
isolation and don't want alerts firing):
```powershell
python run_talonx.py --skip-core
```
Leave out market data streaming or the quant scanner individually
(e.g. you're actively iterating on `talonx_quant` and want to run just
that one yourself, restarting it freely, without restarting everything
else on every change):
```powershell
python run_talonx.py --skip-market-data
python run_talonx.py --skip-quant
```
Leave out paper trading (e.g. you don't want simulated trades while just
testing alert delivery):
```powershell
python run_talonx.py --skip-paper-trading
```
Leave out just the Phase 2 long-term paper engine (e.g. you want the
intraday paper engine but not DCA contributions while testing):
```powershell
python run_talonx.py --skip-long-term-paper
```

The sections below describe each component separately -- useful for
debugging one piece in isolation, or if you want independent control over
each rather than running them as one process.

### 5b. Ingest SEC filings (standalone)

```powershell
python -m talonx_ingest.pipeline
```
Default watchlist is `AAPL MSFT NVDA`. To specify your own tickers:
```powershell
python -m talonx_ingest.pipeline TSLA AMZN GOOGL
```

**First run** will pause once to download the embedding model (~90MB,
one-time, cached afterward). Full run for 3 tickers typically takes
1–3 minutes: ~15–45s for SEC fetches (rate-limited to a safe margin under
SEC's 10 req/sec cap), the rest for cleaning/chunking/embedding.

You'll see progressive logs like:
```
Resolved 8 target filings for AAPL (0000320193)
Chunked AAPL 10-K (...) into 187 chunks
Upserted batch of 128 chunks (128/620)
Ingested AAPL: 620 new chunks written to ChromaDB
Ingestion summary (new chunks written this run): {'AAPL': 620, 'MSFT': 583, 'NVDA': 601}
```

**Incremental ingestion**: filings already fully processed in a previous
run are automatically skipped (tracked via a local SQLite ledger, not
re-fetched or re-embedded). Running the same command again shortly after
will show `Up to date` for each ticker and complete almost instantly.
To force a full reprocess anyway (e.g. after changing chunk size):
```powershell
python -m talonx_ingest.pipeline --force-refresh
```

Data lands at:
```
C:\Users\<you>\.talonx\chroma\                  <- the vector store
C:\Users\<you>\.talonx\ingestion_ledger.db        <- what's already been ingested
```

### 5c. Inspect what's in the vector store

```powershell
# Overall stats: total chunks, breakdown by ticker and form type
python inspect_store.py --summary

# Semantic search
python inspect_store.py --query "supply chain risk" --ticker NVDA

# More results, full text instead of a preview
python inspect_store.py --query "share buybacks" --ticker AAPL --form 10-K -n 10 --full
```

### 5d. Stream market data (standalone)

```powershell
python -m talonx_ingest.market_data.run AAPL MSFT NVDA
```
Uses Polygon WebSocket if `POLYGON_API_KEY` is set in `.env`, otherwise
automatically falls back to yfinance polling (every 5s, delayed data).
**This runs continuously — it does not exit on its own.** Stop it with
`Ctrl+C`. If the WebSocket keeps failing to reconnect, it automatically
switches to polling for the rest of that run rather than giving up
entirely.

### 5e. Ingest news/social feeds (standalone)

```powershell
python -m talonx_ingest.news.pipeline AAPL MSFT NVDA
```
Uses NewsAPI.org if `NEWS_API_KEY` is set in `.env`, otherwise automatically
falls back to Yahoo Finance's public per-ticker RSS feed (no key needed).
ALSO searches Reddit (`wallstreetbets`, `stocks`, `investing` by default)
if `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` are set (§4) — additive on
top of NewsAPI/RSS, silently skipped (no error, no warning) if unset.
Embeds into a separate ChromaDB collection (`news_feed` by default) so
filing text and news text stay independently queryable. Same incremental
ledger behavior as filings — re-running skips articles/posts already
ingested; `--force-refresh` bypasses that.

### 5f. Redis event publishing

Both `talonx_ingest.pipeline` and `talonx_ingest.market_data.run` publish
events to Redis Pub/Sub as their formal output contract, in addition to
writing to ChromaDB / printing to console:

| Channel | Event | Published when |
|---|---|---|
| `talonx:filings:events` | `NewFilingIngestedEvent` | A filing's chunks are fully written to ChromaDB |
| `talonx:market:stream` | `MarketTickEvent` | Every trade/quote/bar tick |

No setup is required to run the pipeline without Redis — if it's not
reachable at `TALONX_REDIS_URL` (default `redis://localhost:6379/0`),
publishing is disabled for that run (logged once as a warning) and
everything else continues normally. To actually see events flowing, make
sure Redis is running (`docker compose up -d`) and subscribe from another
terminal:
```powershell
docker exec talonx-redis redis-cli subscribe talonx:filings:events
```

### 5g. Run the quant scanner (standalone)

```powershell
pip install -r talonx_quant\requirements.txt
python -m talonx_quant.run
```
Listens to `talonx:market:stream`, maintains a rolling OHLCV buffer per
ticker from BAR events, and publishes `QuantSignal` events to
`talonx:signals:quant` when RSI+volume, MACD crossover, or MA crossover
conditions trigger. Runs continuously — `Ctrl+C` to stop. Needs bars to
accumulate before signals can fire (`TALONX_QUANT_MIN_BARS`, default 60),
so pair it with `market_data.run` streaming the same tickers, and expect
a warm-up period before the first signal.

**Known compatibility caveat**: `pandas_ta` references `numpy.NaN`, which
was removed in NumPy 2.0. If `pip install pandas_ta` or its import fails
with `AttributeError: module 'numpy' has no attribute 'NaN'`, pin
`numpy<2` in your environment (`pip install "numpy<2"`) until upstream
releases a fix.

To watch signals arrive, subscribe in another terminal:
```powershell
docker exec talonx-redis redis-cli subscribe talonx:signals:quant
```

To fire a guaranteed test signal without waiting on real market
conditions, see `send_test_signal.py` at the project root.

### 5h. Run the research agent (talonx_brain, standalone)

`run_talonx.py` (§5a) already starts this automatically when its LLM
provider is configured -- run it standalone instead if you want it
decoupled from Modules 1+2 (e.g. running on a different machine/schedule),
or you're just iterating on `talonx_brain` itself.

```powershell
pip install -r talonx_brain\requirements.txt
python -m talonx_brain.run
```
Listens to `talonx:signals:quant`, and for each `QuantSignal` retrieves
relevant SEC filing context for that ticker from ChromaDB, asks the
configured LLM (Gemini by default, or a local Ollama model -- see §3.3 and
§9.4) to assess it against the technical trigger, and publishes a
`ResearchReport` to `talonx:reports:brain`. Requires either `GEMINI_API_KEY`
in `.env` (default `gemini` provider) or `ollama serve` running locally
(`TALONX_BRAIN_LLM_PROVIDER=ollama`), and at least some filings already
ingested for the tickers you're scanning (see §5b) — with no filing context, reports still publish, just with
`verdict: "insufficient_context"` instead of a guess. Runs continuously —
`Ctrl+C` to stop. Pair it with `market_data.run` + `talonx_quant.run` (or
just `send_test_signal.py`) so signals actually arrive on the input
channel.

To watch reports arrive, subscribe in another terminal:
```powershell
docker exec talonx-redis redis-cli subscribe talonx:reports:brain
```

### 5i. Run the decision engine (talonx_core, standalone)

`run_talonx.py` (§5a) already starts this automatically -- run it
standalone instead if you want it decoupled from the other three modules,
or you're just iterating on `talonx_core` itself.

```powershell
pip install -r talonx_core\requirements.txt
python -m talonx_core.run
```
Listens to BOTH `talonx:signals:quant` and `talonx:reports:brain`,
correlates them per ticker, runs the Decision Matrix, and publishes an
`ActionableAlert` to `talonx:alerts:dispatch` when a pair is CONFIRMED or
CONTRADICTED (see §3.4). No API key or extra setup required -- it needs
only Redis, same as `talonx_quant`. Pair it with `talonx_quant.run` +
`talonx_brain.run` (or `send_test_signal.py` for a synthetic trigger) so
there's actually something to correlate. Runs continuously — `Ctrl+C` to
stop.

Correlator state persists to `C:\Users\<you>\.talonx\core_state.db`
(SQLite, `TALONX_CORE_STATE_DB` to change it) — stopping and restarting
this process picks up right where it left off rather than losing
whichever half of an in-flight pair had already arrived. Set
`TALONX_CORE_ENABLE_PERSISTENCE=false` to always start clean instead.

To watch alerts arrive, subscribe in another terminal:
```powershell
docker exec talonx-redis redis-cli subscribe talonx:alerts:dispatch
```

### 5j. Run the test suite

```powershell
pip install -r requirements-dev.txt
pytest
```
Covers the cleaner, chunker (both the filing path and the generic path
news reuses), the incremental ledger (filings and news, including
persistence across reopens), the Redis event schemas, the
ledger/upsert safety logic in `pipeline.ingest_ticker` (partial upserts
never falsely mark a filing complete), and the Reddit client's parsing
logic (post-to-`NewsArticle` mapping, lookback-window filtering, the
"not configured -> `[]`, no network call" short-circuit -- consistent
with this project's existing choice not to mock-test the OTHER network
clients' full request/retry flow either, e.g. `EdgarClient`). Also covers
`talonx_brain`'s
schemas, its ChromaDB-result-to-`Citation` transform, and its
retrieve/generate/publish orchestration; and `talonx_core`'s schemas
(including that its trimmed `ResearchReport` mirror correctly parses the
full wire payload), its Decision Matrix (every suppression check and
outcome, as a pure function), its `TickerStateStore` (real SQLite,
including that state survives a simulated restart -- close and reopen a
fresh connection against the same file), and its dual-channel
correlate/decide/publish orchestration with write-through persistence;
and `talonx_dispatch`'s schemas (including that its trimmed
`ActionableAlert` mirror parses the full wire payload), its Markdown
formatter (all three actions, all three severities, the 4-character
escaping, truncation), its `AuditStore` (real SQLite, including the
`id`-tiebreaker ordering fix and persistence across a simulated restart),
and its record-then-maybe-push consumer orchestration (severity
filtering, Telegram failures recorded not raised). Redis, ChromaDB,
Gemini, and Telegram are all mocked; SQLite is exercised for real
throughout, same choice `test_ledger.py` makes for `talonx_ingest`'s own
store. Network-dependent code (EDGAR client, market data sources, Gemini,
Telegram) is exercised via mocks, not live calls -- this is a fast,
offline-safe suite you can run on every change. `requirements-dev.txt`
now pulls in every module's own `requirements.txt`, so a fresh checkout
running just `pip install -r requirements-dev.txt && pytest` collects
and runs the ENTIRE suite, not only `talonx_ingest`'s tests.

### 5k. Diagnose a hang or connectivity issue

If any command above seems to hang with no log output:
```powershell
python talonx_ingest\check_connectivity.py
```
Tests each external endpoint (SEC ticker map, SEC submissions API, SEC
archives, Hugging Face) with an 8-second timeout each, so you know in
under a minute which one (if any) is blocked — rather than waiting
indefinitely on a full pipeline run.

If you're behind a corporate proxy, set it first:
```powershell
$env:HTTPS_PROXY = "http://your-proxy:port"
python talonx_ingest\check_connectivity.py
```
(The pipeline and market data client both automatically honor
`HTTP_PROXY`/`HTTPS_PROXY` if set, via `trust_env=True`.)

### 5l. Watch the live pipeline dashboard

```powershell
pip install -r requirements-dashboard.txt
python dashboard.py
```
A read-only, live-refreshing terminal view across ALL SIX Redis channels
at once (`talonx:filings:events`, `talonx:market:stream`,
`talonx:signals:quant`, `talonx:reports:brain`, `talonx:alerts:dispatch`,
`talonx:paper:trades`) -- total messages, throughput (msgs/min), a
per-ticker breakdown, and a per-CATEGORY breakdown for each, so you can
see at a glance how much data has moved through Modules 1-6 and where
the activity actually is, without digging through six different terminal
logs. The category breakdowns are the answer to "how many LLM calls is
this actually making" and similar questions -- derived entirely from
fields already present in each message (no other module needed to
change for this): `talonx:reports:brain` splits into **LLM call / cache
hit (no LLM) / stale fallback (no LLM) / cold start (no LLM) / degraded
(LLM failed)** (Module 3's caching, §3.3), `talonx:signals:quant` splits
by signal type, `talonx:alerts:dispatch` splits by action, and
`talonx:paper:trades` splits by BUY/SELL plus a running realized-PnL
total. **What this can't show**: anything that gets SUPPRESSED before
publishing -- a talonx_quant signal dropped by cooldown/throttle, a
failed Telegram send, an ignored paper trade -- never becomes a message,
so a pure Redis observer has nothing to count; that would need each
module to explicitly publish its own internal counters somewhere, which
none of them do today. Run it alongside `run_talonx.py` (or any
combination of standalone module processes) — it only subscribes, it
never publishes, so it can't affect the pipeline it's watching.

```powershell
python dashboard.py --top-n 8       # show more tickers per channel (default: 5)
python dashboard.py --refresh 0.5   # redraw faster (default: 1.0s)
```

In-memory only — counts reset if you restart it; this is a live view of
"what's happening right now," not a historical record (see
`talonx_ingest.storage.ledger` / `talonx_core.store` for this project's
actual durable stores). `Ctrl+C` to stop; prints a final summary of
totals per channel on exit.

**Prefer a browser UI with charts?** Same underlying data, served as a
local web page instead of a terminal table:
```powershell
pip install -r requirements-dashboard.txt
python dashboard_web.py
```
Then open **http://localhost:8787** in your browser. Runs entirely on
your machine — a small `aiohttp` server (already a dependency, no new
framework) pushes live JSON snapshots over a WebSocket to a
self-contained HTML/JS page (no CDN, works offline). Each channel gets
its own card: a live sparkline of recent throughput, and a bar chart of
its top tickers, color-coded per module. Auto-reconnects with backoff if
the connection drops (same "reconnect, don't crash" pattern this project
uses everywhere else).

Deliberately NOT a published Claude Artifact — Artifacts enforce a strict
CSP that blocks `fetch`/`WebSocket` calls to any host outside the
artifact's own origin, which would block reaching this project's local,
Redis-backed data entirely. `dashboard_web.py` sidesteps that by running
the whole thing locally, same "everything on your machine" philosophy as
Redis/ChromaDB/SQLite elsewhere in this project.
```powershell
python dashboard_web.py --port 9000     # if 8787 is taken
```
Reuses `dashboard.py`'s channel-watching logic directly (imports it) so
the two tools can never drift out of sync on which channel maps to which
ticker field — pick whichever one fits the moment; there's no need to run
both.

### 5m. Run the notification dispatcher (talonx_dispatch, standalone)

`run_talonx.py` (§5a) already starts this automatically — run it
standalone instead if you want it decoupled from the other four modules
(e.g. running on a different machine/schedule), or you're just iterating
on `talonx_dispatch` itself.

```powershell
pip install -r talonx_dispatch\requirements.txt
python -m talonx_dispatch.run
```
Listens to `talonx:alerts:dispatch`, records every `ActionableAlert` to
the audit trail (`~\.talonx\dispatch_audit.db` by default —
`TALONX_DISPATCH_AUDIT_DB` to change it), and pushes a Telegram message
for anything at or above `TALONX_DISPATCH_MIN_SEVERITY` (default
`warning`) if `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are set (§4) —
otherwise it logs one warning at startup and keeps recording to the
audit trail without pushing. **The Streamlit dashboard (§5n) is never
started this way, or by `run_talonx.py`** — see §3.5 for why; always run
it as its own separate process. Runs continuously — `Ctrl+C` to stop;
prints a summary of alerts processed / Telegram sent / failed on exit.

### 5n. Run the Streamlit dashboard — live alerts + ticker watchlist

```powershell
streamlit run talonx_dispatch\app.py
```
Opens in your browser automatically (Streamlit's default behavior).
Reads the SAME audit trail `talonx_dispatch.run` (§5m) writes to for its
alert-related sections — **both need to be running** for those to show
anything; that half is a pure read-only view over the SQLite file. The
**"🎯 Tracked tickers"** section at the top is different: it's a live
control surface over the ticker watchlist (`talonx_watchlist/store.py`)
— add, remove, or pause/resume a ticker there and `run_talonx.py`'s market
data streaming (and periodic filing/news ingestion) picks it up within one
poll interval, no restart needed. Pausing stops streaming/ingestion for
that ticker but keeps its row (name, exchange, added date) — unlike
removing, resuming it later doesn't lose that. A newly added ticker starts
**paused** — resume it once you're ready to start tracking it (the
auto-seeded fresh-install default and any CLI-seeded tickers still start
active, only the dashboard's Add form defaults to paused). Each ticker
also records a Primary Exchange/Market (picked from a fixed dropdown on
add, so filtering by it is reliable), and the table itself supports
filtering by exchange, sorting by any column, and pagination (10 tickers
per page). Pause/Resume/Remove are color-coded (amber/green/red) to keep
them visually distinct. Also shows: summary metrics, tickers
with alert history (derived from the audit trail — which tickers have
actually alerted, distinct from what's currently tracked), a live
expandable alert feed, and a filterable (ticker/action/severity) full
audit trail table. Auto-refreshes every `TALONX_DISPATCH_AUTOREFRESH_MS`
(default 5000ms) — that's also how often an add/remove made by someone
else shows up in your own browser tab. Also shows the **"💰 Paper
Trading"** section (§3.6) — portfolio value/win-rate/open-positions
metrics, a Settings panel (starting balance, trade allocation, which
tracked tickers have paper trading enabled, and a Reset Portfolio
button), an open-positions table marked to the latest known price, an
equity curve, a win/loss-colored per-trade PnL chart, and a downloadable
CSV of the full trade history.

```powershell
streamlit run talonx_dispatch\app.py --server.port 8502   # if 8501 is taken
```

### 5o. Run the paper trading engine (talonx_paper, standalone)

```powershell
pip install -r talonx_paper\requirements.txt
python -m talonx_paper.run
```
Listens to `talonx:alerts:dispatch` and `talonx:market:stream`, simulates
BUY/SELL execution for tickers with paper trading enabled (toggle in the
dashboard's Paper Trading section, §5n), and publishes each executed
trade to `talonx:paper:trades` — `talonx_dispatch.run` (§5m) picks that
up and sends its own short Telegram notification, decoupled from the
triggering alert's push. Runs continuously — `Ctrl+C` to stop; prints a
summary of alerts processed / trades executed / trades ignored on exit.

**Risk management and friction, added after reviewing a live session's
results** (negative risk-to-reward, gains too small to survive real
friction, and too many low-conviction round trips on one ticker):
- Every open position is checked against a **stop-loss/take-profit band**
  (`TALONX_PAPER_STOP_LOSS_PCT`/`TALONX_PAPER_TAKE_PROFIT_PCT`, default
  0.50%/1.00% — a 1:2 risk-to-reward ratio) on every market tick, not
  just when a reversal alert happens to arrive. This is *additional* to
  the existing alert-driven exit (`CONFIRMED_BEARISH`/`CONTRADICTED`
  still closes a position immediately, regardless of stop/take) — a
  genuine reversal signal is never suppressed, stop/take just adds a
  price-based floor and ceiling. Static percentages for now; an
  ATR-based dynamic version is a deliberately deferred follow-up.
- Every fill (BUY or SELL, however triggered) crosses a **simulated
  bid-ask spread** (`TALONX_PAPER_SIMULATED_SPREAD_BPS`, default 5bps),
  so realized PnL isn't unrealistically clean the way a zero-friction
  fill at the exact signal price is.
- New positions can be gated to a **minimum alert severity**
  (`TALONX_PAPER_MIN_ENTRY_SEVERITY`, default `warning`) — a
  `CONFIRMED_BULLISH` alert below that bar never opens a position
  (recorded `BELOW_MIN_SEVERITY`, visible in §5p's EOD report); exits are
  never severity-gated. "warning" is a starting point, not a tuned
  value — use the EOD report's `BELOW_MIN_SEVERITY` counts across a few
  real sessions to decide whether to loosen it to `info` or tighten it
  to `critical`.
- Two EXISTING knobs also directly address trade frequency/sizing
  without any code change: `TALONX_CORE_TICKER_COOLDOWN` (§9, how often
  a ticker can re-enter) and `TALONX_PAPER_TRADE_ALLOCATION` (larger
  positions make the spread cost a smaller fraction of each trade).

### 5p. Generate an End-of-Day report (standalone)

```powershell
python generate_eod_report.py
```
Reads every module's own local SQLite store for a single trading day and
writes a consolidated Markdown report (plus raw CSVs) to `reports/` —
built for exactly the question "why didn't ticker X trade today", so you
don't have to cross-reference the dashboard's tables or export a CSV by
hand after market close. Covers, per ticker: alerts received, trades
executed (with PnL), trades ignored (with the specific reason —
`NO_ACTIVE_POSITION`, `POSITION_ALREADY_OPEN`, `INSUFFICIENT_CASH`,
`DEGRADED_NOT_TRADABLE`), and — if `talonx_core`/`talonx_quant`/
`talonx_brain` have run with persistence enabled (the default) at least
once — the full signal funnel (quant signals generated → suppressed by
cooldown/throttle → reached `talonx_core` → suppressed there by
staleness/confidence/cooldown/no-state-change → became an alert) plus
LLM/cache economics (cache hits, stale fallbacks, degraded reports, cold
starts, genuine LLM calls). It reads only — nothing it does affects the
running pipeline, and it's safe to run at any time, not just after close.

```powershell
python generate_eod_report.py --date 2026-08-11     # default: today, in --tz
python generate_eod_report.py --tz Europe/London    # default: America/New_York
python generate_eod_report.py --out-dir C:\reports  # default: .\reports
```
Nothing in this project schedules it automatically — wire up a Windows
Task Scheduler entry yourself if you want it to run unattended right
after market close each day.

---

## 6. Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| `No module named 'talonx_ingest...'` | Running from the wrong folder | `cd` to `C:\workspace\TalonX` (the parent of `talonx_ingest`), not inside it |
| Command hangs, zero log lines | Corporate proxy/firewall blocking direct connections, or slow first-time model download | Run `check_connectivity.py`; set `HTTPS_PROXY` if needed |
| `403` errors from SEC | `TALONX_SEC_USER_AGENT` not set to a real contact string | Edit `.env`, set a real name/email |
| `pip install` fails on `chromadb`/`hnswlib` | Missing C++ build tools | Install VC++ Build Tools (see Prerequisites) |
| New dependency "not found" after editing `requirements.txt` | Editing a different copy of the file than the one `pip install -r` reads | Confirm you're editing `C:\workspace\TalonX\talonx_ingest\requirements.txt` specifically, then re-run `pip install -r` |
| `.env` values seem ignored | `.env` isn't at the repo root | Move it to `C:\workspace\TalonX\.env` — it's resolved relative to each module's own file location (`../.env` from inside each package), not the current directory |
| `talonx_brain` raises `ValueError: GEMINI_API_KEY is not set` | Missing/empty `GEMINI_API_KEY` in `.env` while `TALONX_BRAIN_LLM_PROVIDER` is `gemini` (the default) | Get a key from [Google AI Studio](https://aistudio.google.com/apikey) and set it in `.env` at the repo root, or switch to the local provider instead: `TALONX_BRAIN_LLM_PROVIDER=ollama` (§9.4) |
| `talonx_brain` reports always come back `insufficient_context` | No filings ingested yet for that ticker | Run `python -m talonx_ingest.pipeline <TICKER>` (§5b) first so there's something in ChromaDB to retrieve |
| `talonx_brain` logs `404 NOT_FOUND ... is not found for API version` | The pinned model name in `TALONX_BRAIN_GEMINI_MODEL` was retired/restricted for your key | Leave it unset to use the default `gemini-flash-latest` alias (tracks whatever Google currently recommends), or pick a live one from `client.models.list()` |
| `talonx_brain` logs `429 RESOURCE_EXHAUSTED ... limit: 0` | Your key's free tier grants **zero** quota for that model (typically Pro models) | Switch to a Flash model, or enable billing on the Google AI Studio project |
| `talonx_brain` logs `429 RESOURCE_EXHAUSTED` with a nonzero `limit` **and** `quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier` | Genuine free-tier PER-MINUTE rate limit (can be as low as 5 requests/minute) -- with enough tickers under surveillance, signals can arrive faster than that | Lower `TALONX_BRAIN_GEMINI_RPM` to match your actual quota (the built-in rate limiter paces calls to stay under it instead of retrying into it), or enable billing for a higher limit |
| `talonx_brain` logs `429 RESOURCE_EXHAUSTED` with `quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier` (e.g. `limit: 500`) | A DIFFERENT, PER-DAY quota for that specific model -- distinct from the per-minute one above and NOT paced by `TALONX_BRAIN_GEMINI_RPM` (that limiter only throttles requests/minute, it has no daily budget concept). Easy to exhaust during active testing/development across a single day | Either wait for the quota to reset (resets daily, Pacific time), point `TALONX_BRAIN_GEMINI_MODEL` at a DIFFERENT model (the quota is per-model, so an unused one has its own separate 500/day allowance), or switch providers entirely: `TALONX_BRAIN_LLM_PROVIDER=ollama` (§9.4) has no quota of any kind |
| `talonx_brain` logs `503 UNAVAILABLE ... high demand` | Transient: Google's model servers are temporarily overloaded (shared free-tier capacity), unrelated to your quota or config | No action needed -- both the `google-genai` SDK and `llm.py`'s own retry wrapper (`TALONX_BRAIN_GEMINI_MAX_RETRIES`, default 3) retry this automatically. Only worth investigating if it persists past all retries and the signal gets logged as `Failed to generate research report` |
| `talonx_brain` (with `TALONX_BRAIN_LLM_PROVIDER=ollama`) logs a connection error / `Failed to generate research report` on every signal | `ollama serve` isn't running, or `TALONX_BRAIN_OLLAMA_MODEL` hasn't been pulled | Run `ollama list` to confirm the service is up and the model is present; `ollama pull <model>` if not (see §9.4) |
| `talonx_core` never alerts even though both a signal and a report clearly arrived | Confidence below `TALONX_CORE_MIN_CONFIDENCE`, verdict is neutral/insufficient_context, one half is stale (outside `TALONX_CORE_CORRELATION_WINDOW`), or the ticker is still in cooldown (`TALONX_CORE_TICKER_COOLDOWN`) | Check the DEBUG-level reasoning isn't logged today -- inspect the actual `QuantSignal`/`ResearchReport` confidence and timestamps directly, or temporarily lower the thresholds to confirm the pipeline itself is wired correctly |
| `talonx_core` (or `run_talonx.py`) logs `database is locked` from `store.py` | Two processes pointed at the SAME `TALONX_CORE_STATE_DB` file at once (e.g. `talonx_core.run` standalone AND `run_talonx.py` both running) -- SQLite allows one writer at a time | Only run one talonx_core instance per state DB file; point a second instance at a different `TALONX_CORE_STATE_DB` path if you genuinely need two |
| Streamlit dashboard (`app.py`) stays empty | `talonx_dispatch.run` (§5m) isn't running -- the dashboard only READS the audit trail, it never touches Redis itself | Start `python -m talonx_dispatch.run` in another terminal; confirm alerts are actually reaching `talonx:alerts:dispatch` in the first place (§5l's dashboards can confirm this) |
| No Telegram push arrives even though the audit trail shows the alert | Severity below `TALONX_DISPATCH_MIN_SEVERITY` (default `warning` -- `info` alerts are recorded but not pushed on purpose), or `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` unset | Check the alert's `severity` in the audit trail/Streamlit feed; lower `TALONX_DISPATCH_MIN_SEVERITY` to `info` if you want everything pushed |
| Telegram send fails with `Forbidden` | The bot hasn't been messaged first (bots can't initiate a DM), or it was blocked/removed from the chat | Message your bot at least once from the Telegram app before running `talonx_dispatch.run` (§4) |
| Telegram message text looks garbled/truncated mid-sentence | An underscore/asterisk/backtick/bracket in Gemini-generated text wasn't escaped correctly, or a message exceeded Telegram's 4096-character limit | `formatter.py` escapes the 4 legacy-Markdown special characters and truncates the research summary to 500 chars -- if this still happens, it's likely in `key_findings`/`risk_factors` text, which isn't length-capped per-item today |
| `generate_eod_report.py`'s "LLM / cache economics" / signal-funnel sections say "Not available" | `talonx_core`/`talonx_quant`/`talonx_brain` haven't run with persistence enabled since this feature was added (or `TALONX_*_ENABLE_PERSISTENCE=false`) -- their stats stores have no rows yet | Run the pipeline normally for at least one session with persistence enabled (the default); the report only ever shows what those processes actually recorded |
| `generate_eod_report.py` shows an empty per-ticker section for a day you know had activity | `--date`/`--tz` picked a different trading-day window than you expected (a UTC timestamp near local midnight can land on the adjacent day) | Pass `--tz` explicitly if you're not in `America/New_York`, and double check `--date` is the LOCAL calendar date, not UTC |

---

## 7. Environment variable reference

See `.env.example` for the full list with defaults and descriptions —
`TALONX_SEC_USER_AGENT` is required for Module 1; Module 3 requires
`GEMINI_API_KEY` OR `TALONX_BRAIN_LLM_PROVIDER=ollama` (§9.4) depending on
which LLM provider you pick; everything else is optional tuning (rate
limits, chunk size, embedding model, ledger path, market data reconnect
behavior, `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`/`REDDIT_USER_AGENT`/
`TALONX_REDDIT_SUBREDDITS` for the optional Reddit source, Module 2's
indicator periods/thresholds plus its noise filters --
`TALONX_QUANT_COOLDOWN_SECONDS` / `TALONX_QUANT_MIN_MA_SPREAD_PCT` /
`TALONX_QUANT_THROTTLE_WINDOW_SECONDS` / `TALONX_QUANT_THROTTLE_MAX_SIGNALS`
(§3.2, §9.5), retrieval
top-K, `TALONX_BRAIN_LLM_PROVIDER` + Gemini model/temperature +
`TALONX_BRAIN_OLLAMA_MODEL`/`TALONX_BRAIN_OLLAMA_BASE_URL`, Module 3's
qualitative cache -- `TALONX_BRAIN_CACHE_ENABLED` / `TALONX_BRAIN_CACHE_BASE_TTL`
/ `TALONX_BRAIN_CACHE_SAFETY_TTL` / `TALONX_BRAIN_CACHE_LOCK_TTL` /
`TALONX_BRAIN_CACHE_LOCK_WAIT_SECONDS` / `TALONX_BRAIN_MARKET_TZ` /
`TALONX_BRAIN_MARKET_OPEN_HOUR` / `TALONX_BRAIN_MARKET_CLOSE_HOUR` (§3.3),
Module 4's `TALONX_CORE_MIN_CONFIDENCE` / `TALONX_CORE_CORRELATION_WINDOW` /
`TALONX_CORE_TICKER_COOLDOWN` / `TALONX_CORE_PRICE_DELTA_RETRIGGER_PCT` /
`TALONX_CORE_ENABLE_PERSISTENCE` / `TALONX_CORE_STATE_DB` (§3.4), and
Module 5's `TELEGRAM_BOT_TOKEN` /
`TELEGRAM_CHAT_ID` (both optional -- see §4) /
`TALONX_DISPATCH_MIN_SEVERITY` / `TALONX_DISPATCH_AUDIT_DB` /
`TALONX_DISPATCH_FEED_LIMIT` / `TALONX_DISPATCH_AUTOREFRESH_MS` /
`TALONX_DISPATCH_TELEGRAM_POLL_TIMEOUT` / `TALONX_DISPATCH_RETENTION_DAYS` /
`TALONX_DISPATCH_RETENTION_SWEEP_HOURS` (§3.5), and the
ticker watchlist's `TALONX_WATCHLIST_DB` / `TALONX_WATCHLIST_DEFAULT_SYMBOL`
/ `TALONX_WATCHLIST_DEFAULT_NAME` / `TALONX_WATCHLIST_DEFAULT_EXCHANGE` /
`TALONX_WATCHLIST_POLL_INTERVAL` (§5n), and Module 6's `TALONX_PAPER_DB` /
`TALONX_PAPER_INITIAL_BALANCE` / `TALONX_PAPER_TRADE_ALLOCATION` --
fresh-install defaults only, since the dashboard's Settings panel is the
actual live source of truth once a portfolio has been created (§3.6) --
etc). `.env.example`'s final "Phase 2" block covers everything specific
to the LONG_TERM horizon (§3.9) -- fundamental factor thresholds
(`TALONX_QUANT_ROIC_THRESHOLD` / `TALONX_QUANT_F_SCORE_THRESHOLD`), the
long-term decision matrix (`TALONX_CORE_LT_*`), the long-term cache TTL
(`TALONX_BRAIN_CACHE_BASE_TTL_LONG_TERM`), and the DCA-aware paper ledger
(`TALONX_PAPER_LT_*` / `TALONX_PAPER_DCA_*` / `TALONX_PAPER_REBALANCE_TRIM_PCT`)
-- none of it required; a fresh install with no `LONG_TERM`-tagged
tickers ignores all of it.

---

## 8. What's not built yet

- `talonx_brain` is purely signal-triggered (reacts to
  `talonx:signals:quant`) — there's no on-demand query interface (CLI/API)
  for asking it about a ticker outside of a quant signal firing.
- ~~`talonx_brain` doesn't listen to `talonx:filings:events`~~ --
  **partially fixed**: it now subscribes to that channel and DELETES
  `brain_cache:{ticker}` the moment a fresh filing lands (§3.3), so the
  NEXT signal for that ticker is guaranteed a fresh LLM call instead of a
  stale cache hit. Still open: this only invalidates the cache -- a fresh
  8-K/news item still doesn't trigger NEW research on its own the way a
  `QuantSignal` does; it's picked up passively, whenever the next
  technical signal happens to fire for that ticker. Also: only filings
  publish an invalidation event today (`NewFilingIngestedEvent`) -- fresh
  news articles don't, so a cached report can go stale relative to
  breaking news without anything forcing a refresh (only its TTL/
  market-boundary expiry eventually catches it).
- `talonx_brain`'s cache expiry (§3.3) uses plain daily 9am/4pm exchange
  clock-time boundaries -- there's no real trading-calendar awareness, so
  a cache entry set right before a market holiday or a weekend doesn't
  know the market isn't actually opening at the next 9am boundary.
- ~~**talonx_quant has no dynamic watchlist.**~~ -- **partially fixed**:
  which tickers get streamed (and periodically ingested for) is now a
  live, runtime-editable decision, via `talonx_watchlist`'s SQLite store
  and the dashboard's "🎯 Tracked tickers" section (§5n) — no restart to
  add/remove a ticker, closing consequences (1) and (3) from the original
  note below. Still open: (2), the ORIGINAL root cause itself. talonx_quant
  itself still has no allow-list of its own -- `buffer.py`'s
  `RollingBarBuffer.add_bar()` unconditionally creates a new per-symbol
  buffer for ANY ticker seen on `talonx:market:stream` --
  `if symbol not in self._bars: self._bars[symbol] = deque(...)` -- so a
  ticker removed from the watchlist simply stops receiving new bars (its
  buffer goes stale); the buffer itself is never evicted, so memory still
  grows unbounded by CUMULATIVE distinct symbol count over a long-running
  process's lifetime, not just the currently-tracked set. Fully closing
  this would mean giving talonx_quant its own allow-list check (filtering
  `BAR` events for symbols not on the current watchlist) plus buffer
  eviction for removed tickers.
- ~~No automated test suite for talonx_quant~~ -- **partially fixed**:
  `tests/test_quant_strategy.py` and `tests/test_quant_consumer.py` now
  cover `strategy.py`'s signal logic (including the noise filters in
  §3.2) and `consumer.py`'s cooldown/throttle orchestration, matching the
  mock-the-external-service pattern the other modules' consumer tests
  use. `buffer.py` (the yfinance-dedup rolling window) and
  `indicators.py` (the pandas_ta wrapping/column extraction) still have
  no dedicated tests -- only exercised indirectly today.
- ~~talonx_core's correlator state is in-memory only, not persisted~~ --
  **fixed**: `store.py`'s `TickerStateStore` (SQLite, same pattern as
  `talonx_ingest.storage.ledger`) rehydrates the correlator at startup and
  is written through on every update, so a restart mid-correlation no
  longer silently drops whichever half of a pair had already arrived
  (`TALONX_CORE_ENABLE_PERSISTENCE`, on by default). See §3.4.
- **talonx_core has no GLOBAL rate limiter**, only the per-ticker cooldown
  (`TALONX_CORE_TICKER_COOLDOWN`) -- a deliberate scope decision, not an
  oversight (see §3.4), but worth knowing if you scale to a large,
  correlated ticker list: a burst across many DIFFERENT tickers at once
  (e.g. a market-wide move) has no cross-ticker throttle the way
  `talonx_brain`'s Gemini calls do (`TALONX_BRAIN_GEMINI_RPM`).
- ~~No ACTIONABLE downstream consumer of `talonx:alerts:dispatch` is
  built~~ -- **fixed by Module 5 (`talonx_dispatch`)**: Telegram push
  notifications are the action, and the SQLite audit trail + Streamlit
  dashboard (§3.5, §5m/§5n) are the review surface. `dashboard.py` /
  `dashboard_web.py` (§5l) still cover live cross-channel visibility
  (all 5 channels, not just alerts); `talonx_dispatch` is the one that
  actually DOES something with an alert and remembers it happened.
- **talonx_dispatch's Streamlit dashboard has no authentication.**
  Anyone who can reach the port (`8501` by default) sees the full alert
  feed and audit trail -- fine on `localhost` for personal use, NOT fine
  if you ever bind it to a non-loopback address or expose it through a
  tunnel/reverse proxy without adding auth in front of it yourself
  (Streamlit has no built-in auth).
- **talonx_dispatch is Telegram-only** -- no Slack/Discord/email/webhook
  alternative. `formatter.py`/`telegram_client.py` are small and
  deliberately separated from `consumer.py`'s orchestration specifically
  so another channel could be added alongside Telegram later without
  restructuring anything, but that hasn't been built.
- **talonx_dispatch pushes are one-way.** There's no way to acknowledge,
  dismiss, or reply to an alert from Telegram and have that reflected
  back in the audit trail or Streamlit dashboard -- it's notify-only.
- Scheduling (e.g. a daily incremental ingestion run via Task Scheduler).
- ~~Social feed sources beyond RSS~~ -- **partially fixed**: Reddit is
  now a real (if optional, registration-gated) social source
  (`talonx_ingest.news.reddit_client`, §3.1). Twitter/X remains
  unbuilt, deliberately -- its API has no usable free read tier
  anymore (paid Basic tier, $100+/month required), which doesn't fit
  this project's free-by-default pattern. Revisit if that changes.
- **Phase 2 (§3.9) has no DRIP / dividend reinvestment.** No dividend
  data source exists anywhere in this pipeline (not in the SEC XBRL
  facts parsed today, not in market data) -- this needs a genuinely new
  external data integration before it's buildable at all, not just new
  code. Worth a dedicated design pass once a dividend data source is
  chosen.
- **Phase 2 has no separate End-of-Quarter report.** The EOD report's
  new Valuation Radar section (§3.9, §5p) already surfaces the same
  underlying snapshot daily; an EOQ report's distinct value (moat-
  stability history, quarter-over-quarter trend) needs this system to
  have actually been running for a full quarter before there's any
  history to report on.
- **Phase 2's structured JSON logging (§3.9) only covers the NEW
  long-term code paths**, not a retrofit of the ~15 pre-existing
  intraday `logger.info(...)` call sites across all 6 modules --
  deliberately deferred as a separate, purely mechanical follow-up.
- **Phase 2's DCA scheduling is fixed-interval, not calendar-aware.**
  `TALONX_PAPER_DCA_INTERVAL_DAYS` (default 30) approximates "monthly"
  rather than firing on, say, the 1st of every calendar month.
- **Phase 2's WACC is a flat assumed constant, not a real CAPM
  calculation.** No beta/market-risk-premium data source exists
  anywhere in this project -- `TALONX_CORE_LT_ASSUMED_WACC` (default 9%)
  stands in for it, same documented-simplification treatment as the
  Debt/EBITDA proxy (operating income substituting for EBITDA, no
  separate D&A line in the parsed XBRL facts).

---

## 9. Throughput profile & the Gemini model tradeoff (read before scaling)

This section exists because Module 3's Gemini model choice was NOT a
one-time decision — over the course of building it we hit three dead ends
in a row (a retired model, a zero-quota model, a newly-restricted model)
before landing on the current configuration. Model availability and
quotas on Google's free tier are a moving target; the goal here is that
the next person (or future you) can read this instead of re-discovering
the same failure modes from scratch.

### 9.1 Current effective throughput, per module

| Module | Component | Effective throughput | Hard cap in code? | Tune via |
|---|---|---|---|---|
| 1 | SEC EDGAR client | 8 req/sec, 4 concurrent (token bucket) | Yes | `TALONX_SEC_RPS`, `TALONX_SEC_CONCURRENCY` |
| 1 | News ingestion (NewsAPI/RSS) | Unthrottled locally — one call per ticker per ingestion cycle, backoff-retry only | No | `TALONX_NEWS_MAX_RETRIES` (retries, not rate) |
| 1 | News ingestion — Reddit (optional) | 60 req/min (token bucket), one search call per subreddit per ticker per cycle | Yes | `TALONX_REDDIT_RPM` |
| 1 | Market data — yfinance fallback | 1 batched poll every 5s covering ALL tracked tickers in a single call | Yes (poll interval) | `TALONX_YF_POLL_INTERVAL` |
| 1 | Market data — Polygon WebSocket | Real-time push, bounded by your Polygon plan tier, not by this code | No local cap | Polygon-side (plan tier) |
| 2 | Quant scanner — bar PROCESSING | No artificial cap — processes each BAR event synchronously as it arrives off Redis; sub-millisecond `pandas_ta` compute per bar | No | n/a |
| 2 | Quant scanner — signal OUTPUT (what actually reaches Redis) | Per-ticker: locked out for `TALONX_QUANT_COOLDOWN_SECONDS` (default 20 min) after any signal. Globally: at most `TALONX_QUANT_THROTTLE_MAX_SIGNALS` (default 3) published per `TALONX_QUANT_THROTTLE_WINDOW_SECONDS` (default 60s), ranked by volume surge ratio — see §3.2, §9.5 | Yes (both) | `TALONX_QUANT_COOLDOWN_SECONDS`, `TALONX_QUANT_THROTTLE_*` |
| 3 | talonx_brain (Gemini) | **5 requests/minute (~0.083 req/sec)**, token-bucket paced | Yes — see §9.2 | `TALONX_BRAIN_GEMINI_RPM` |
| 4 | talonx_core (correlate + decide) | No artificial cap on PROCESSING — in-memory dict lookups and comparisons, no external calls, sub-millisecond per message. In practice bounded entirely by how fast Modules 2/3 feed it | No (processing); per-ticker cooldown only (see §3.4) | `TALONX_CORE_TICKER_COOLDOWN` |
| 5 | talonx_dispatch — audit trail write | No artificial cap, sub-millisecond local SQLite insert per alert | No | n/a |
| 5 | talonx_dispatch — Telegram push | No PROACTIVE rate limiter (unlike Reddit/Gemini) — deliberately: by the time an alert reaches here it's already gated by talonx_core's cooldown AND upstream-bottlenecked by talonx_brain's ~5/min, so the realistic push rate is already well under Telegram's own flood-control limits (~1 msg/sec to one chat). Reactive retry (respecting Telegram's own `RetryAfter` hint) handles the rest | No | `TALONX_DISPATCH_TELEGRAM_MAX_RETRIES` |

**Module 3 is the bottleneck of the entire pipeline by 2+ orders of
magnitude** — it's the only component paying for LLM inference against a
free-tier quota, while everything upstream can produce `QuantSignal`s far
faster than Module 3 can research them. Module 2's own cooldown/throttle
(above) narrows that gap somewhat — capping output at 3/min globally
means Module 3 is no longer asked to research every raw threshold
breach — but it's a noise filter, not a rate-matching mechanism; it
wasn't tuned against Module 3's ~5/min Gemini limit and can still
outpace it. Under a burst (many tickers
crossing thresholds around the same time, e.g. a correlated market move),
reports queue up behind the rate limiter rather than being dropped or
erroring — expect multi-minute delay between signal and report during a
burst, not a failure. Module 4 inherits this same lag downstream of it:
since it only alerts once BOTH halves of a pair have arrived, its
effective alert rate is capped by however fast talonx_brain can produce
reports, not by anything talonx_core itself does. One caveat worth
knowing if you scale the ticker list up significantly: Redis Pub/Sub
(used for `talonx:signals:quant` and `talonx:reports:brain`) is not a
durable queue — if a subscriber falls far enough behind, Redis can drop
it under its `client-output-buffer-limit pubsub` setting. At 5 req/min
this has not been observed to matter in testing, but if you outgrow it,
Redis Streams (consumer groups, replayable) would be the fix, not this
rate limiter.

### 9.2 Current Gemini configuration (as of Aug 2026) and why

```
TALONX_BRAIN_GEMINI_MODEL          (unset -> default "gemini-flash-latest")
TALONX_BRAIN_GEMINI_RPM            (unset -> default 5)
TALONX_BRAIN_GEMINI_TEMPERATURE    (unset -> default 0.2)
TALONX_BRAIN_GEMINI_MAX_TOKENS     (unset -> default 2048)
TALONX_BRAIN_GEMINI_MAX_RETRIES    (unset -> default 3)
TALONX_BRAIN_GEMINI_BACKOFF_BASE   (unset -> default 2.0 seconds)
TALONX_BRAIN_GEMINI_BACKOFF_MAX    (unset -> default 30.0 seconds)
TALONX_BRAIN_RETRIEVAL_TOP_K       (unset -> default 6 chunks/signal)
```

**How we got here** (chronology, so the same dead ends aren't repeated):
1. Started with `gemini-1.5-pro` (the original module spec's model) —
   retired from the API entirely (`404 NOT_FOUND`).
2. Tried `gemini-2.5-pro` — a real, listed model, but the free tier grants
   literal **zero** quota for Pro models (`limit: 0` in the 429 response
   body); requires a billing-enabled Google Cloud project.
3. Tried `gemini-2.5-flash` — appears in `client.models.list()`, but
   returns `404 ... no longer available to new users` (an API-key-age
   restriction, not a real deprecation — confusing because it's still
   "listed").
4. Landed on `gemini-flash-latest` — Google's own alias for "current
   recommended Flash model." Verified working with a live call; at time
   of writing it resolves to `gemini-3.6-flash`, which DOES carry free
   quota, but only **5 requests/minute** (confirmed from the live 429
   body: `quotaValue: '5'`, metric
   `generate_content_free_tier_requests`).
5. Added the token-bucket rate limiter in `llm.py` (`_TokenBucket`) so
   Module 3 paces itself under that quota proactively, instead of
   retrying into repeated 429s under any real signal volume.
6. Tried overriding `TALONX_BRAIN_GEMINI_MODEL` to a pinned
   `gemini-2.5-flash-lite` for lower latency/cost — same "no longer
   available to new users" 404 as `gemini-2.5-flash`. The whole 2.5
   generation appears restricted for this key, not just the Flash tier.
   `gemini-flash-lite-latest` (the Lite-tier alias) worked.
7. **And one more wall, distinct from all of the above**: after extended
   same-day testing on `gemini-flash-lite-latest` (resolved to
   `gemini-3.5-flash-lite`), hit `429 RESOURCE_EXHAUSTED` with
   `quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier`,
   `limit: 500` — a PER-DAY cap, not the per-minute one steps 4-5 already
   handle. `_TokenBucket` paces requests/minute; it has no concept of a
   daily budget, so nothing in `llm.py` protects against this one. The
   quota is scoped per-model (not per-project), so a different model has
   its own separate 500/day allowance — but the real fix, given how many
   separate free-tier walls this chronology has now hit, was to stop
   depending on Gemini's free tier being reliably available for active
   development at all: `llm.py` now supports a second provider
   (`TALONX_BRAIN_LLM_PROVIDER=ollama`, §9.4) with no quota of any kind.

**Aliases verified working against this key** (live-tested, not just
"listed" — `client.models.list()` returning a name is NOT the same as it
actually accepting a `generateContent` call, as steps 3 and 6 above
show):

| Alias | Tier | Verified | Notes |
|---|---|---|---|
| `gemini-flash-latest` | Flash | Yes | Current default. Resolved to `gemini-3.6-flash` at last check; 5 req/min free tier. |
| `gemini-flash-lite-latest` | Flash-Lite | Yes | Lower latency/cost than Flash; free-tier RPM not yet separately confirmed — verify with `client.models.list()` + https://ai.dev/rate-limit before assuming it matches Flash's 5/min. |
| `gemini-pro-latest` | Pro | **No** — not yet tested | Free tier grants zero quota for Pro (see step 2); requires billing enabled first (§9.3). Confirm with a live call before relying on it, same as every other row here. |

**Verdicts aren't fully deterministic between runs.** `gemini_temperature`
defaults to `0.2` (low but nonzero). Observed live: the identical
`rsi_overbought_volume_surge` AAPL signal, with effectively the same 6
filing + 3 news citations retrieved, produced `verdict: "bullish"`
(confidence 0.4) on one run and `verdict: "bearish"` (confidence 0.85) on
a re-run moments later — a finely-balanced call (bearish technical signal,
mixed bullish/bearish context) can genuinely land either way at this
temperature. This is expected model sampling behavior, not a bug. If you
need reproducible verdicts (e.g. for backtesting), set
`TALONX_BRAIN_GEMINI_TEMPERATURE=0` — note this makes the model more
deterministic but not necessarily "more correct."

**Pinned model name vs. alias — the tradeoff that matters most:**
- **Pinned** (e.g. `gemini-3.5-flash`, `gemini-3.1-pro-preview`):
  reproducible behavior forever, but WILL eventually 404 when Google
  retires or restricts it — as happened twice above — silently, the next
  time the process restarts.
- **Alias** (`gemini-flash-latest`, `gemini-pro-latest`): survives that
  churn automatically (Google keeps it pointed at something current), but
  isn't reproducible — the underlying model, and therefore latency/quality/
  cost, can shift between runs without any code change on our side.
- **Current choice: alias.** We're optimizing for "keeps working without
  maintenance" over "pinned reproducibility." Revisit this if you need the
  latter — e.g. a backtested/audited research pipeline where consistent
  model behavior across runs matters more than zero-maintenance.

**Flash vs. Pro:**
- Flash: faster, cheaper, available on the free tier. For this module's
  actual job — grounding or challenging a technical signal against a
  handful of retrieved filing excerpts — Flash has been sufficient in
  testing (the `insufficient_context` verdicts observed were the
  *correct* call given genuinely irrelevant retrieved context, not a
  reasoning-quality miss).
- Pro: deeper reasoning, likely better at synthesizing across more/longer
  excerpts or more nuanced multi-document analysis — but zero free-tier
  quota, so it's a hard requirement to enable billing first.

**Free tier vs. paid:** the observed 5 req/min free-tier cap is the
tightest constraint in the whole pipeline (see §9.1). Paid tiers raise
per-model RPM substantially (varies by model and plan — check
https://ai.google.dev/gemini-api/docs/rate-limits for current numbers,
don't trust the figures in this README to still be accurate) and unlock
Pro models entirely.

### 9.3 Upgrade path: moving to a faster/Pro model later

1. **Enable billing** on the Google Cloud project backing your
   `GEMINI_API_KEY` (console.cloud.google.com → link a billing account to
   the project tied to your AI Studio key). This is what unlocks nonzero
   Pro quota and typically raises Flash RPM too.
2. **Re-verify what's actually available and its quota** under the new
   plan — don't assume, check:
   ```powershell
   python -c "from talonx_brain.config import BrainConfig; from google import genai; c = genai.Client(api_key=BrainConfig().gemini_api_key); [print(m.name) for m in c.models.list() if 'generateContent' in (m.supported_actions or [])]"
   ```
   Cross-reference actual per-model limits at https://ai.dev/rate-limit —
   these differ by plan tier and change over time.
3. **Set `TALONX_BRAIN_GEMINI_MODEL`** in `.env` at the repo root:
   - `gemini-pro-latest` — alias, recommended default if you want "current
     best Pro model, zero maintenance," mirroring the Flash choice made
     here.
   - Or a pinned snapshot (e.g. `gemini-3.1-pro-preview`) if you need
     reproducible behavior instead — see the pinned-vs-alias tradeoff in
     §9.2; you'll need to revisit this when it eventually gets retired.
4. **Raise `TALONX_BRAIN_GEMINI_RPM`** to match the new plan's actual
   limit, set slightly under the real quota (not exactly at it) to leave
   headroom for any other usage on the same key. This is the step that
   actually unlocks more throughput — changing the model alone does
   nothing while the rate limiter is still capped at 5.
5. **Optionally revisit** `TALONX_BRAIN_GEMINI_MAX_TOKENS` (Pro models may
   benefit from more headroom for deeper reasoning) and
   `TALONX_BRAIN_GEMINI_TEMPERATURE`.
6. **Re-run the validation flow before trusting it in production**: fire
   `send_test_signal.py --ticker <TICKER-WITH-INGESTED-FILINGS>` (§5b, §5g)
   and confirm a `ResearchReport` publishes to `talonx:reports:brain`
   with the new model before assuming the upgrade worked.

### 9.4 Local alternative: Ollama (no API key, no quota)

`llm.py` supports a second, fully local LLM provider via
[Ollama](https://ollama.com) — a thin wrapper (`OllamaResearchChain`) over
`langchain-ollama`, sharing the exact same `generate(signal, citations) ->
_LLMFindings` interface as `GeminiResearchChain` (`_BaseResearchChain` in
`llm.py`). `consumer.py` and `run_talonx.py` never branch on which
provider is active — `build_research_chain()` (the factory in `llm.py`) is
the one place that does, picking based on `TALONX_BRAIN_LLM_PROVIDER`.

**Setup:**
```powershell
# 1. Install Ollama (Windows installer, runs as a background service)
#    https://ollama.com/download

# 2. Pull a model that supports tool calling (needed for
#    with_structured_output(_LLMFindings) -- see "model choice" below)
ollama pull llama3.1

# 3. Confirm the service is up and the model is present
ollama list

# 4. Point talonx_brain at it
pip install -r talonx_brain\requirements.txt   # now also installs langchain-ollama
```
In `.env` at the repo root:
```
TALONX_BRAIN_LLM_PROVIDER=ollama
```
No `GEMINI_API_KEY` needed for this path — `GeminiResearchChain`'s API-key
check in `llm.py` only runs when the `gemini` provider is selected.

**Config knobs** (all in `talonx_brain/config.py`, `TALONX_BRAIN_OLLAMA_*`
env vars — kept fully separate from `TALONX_BRAIN_GEMINI_*` on purpose, so
switching providers back and forth can never accidentally reinterpret one
provider's tuned values as the other's):
```
TALONX_BRAIN_OLLAMA_BASE_URL       (unset -> default "http://localhost:11434")
TALONX_BRAIN_OLLAMA_MODEL          (unset -> default "llama3.1")
TALONX_BRAIN_OLLAMA_TEMPERATURE    (unset -> default 0.2)
TALONX_BRAIN_OLLAMA_MAX_RETRIES    (unset -> default 3)
TALONX_BRAIN_OLLAMA_BACKOFF_BASE   (unset -> default 2.0 seconds)
TALONX_BRAIN_OLLAMA_BACKOFF_MAX    (unset -> default 30.0 seconds)
```

**No rate limiter.** `GeminiResearchChain` self-throttles with a
`_TokenBucket` to respect Google's free-tier quota; `OllamaResearchChain`
passes `bucket=None` to `_BaseResearchChain` — there's no cloud quota to
pace against, only your own machine's throughput. If signals arrive faster
than your hardware can generate reports, they simply queue up as pending
`asyncio.Task`s the same way any slow consumer would; nothing paces them
proactively today.

**Model choice.** Default is `llama3.1` (8B) — small enough for a typical
dev machine's CPU (or GPU, if Ollama detects one) and supports the
tool-calling method `langchain-ollama`'s `with_structured_output()` uses by
default to force the `_LLMFindings` schema. Any Ollama model with tool-
calling support works (e.g. `qwen2.5`, `mistral-nemo`) — a model WITHOUT
tool-calling support will fail structured-output calls with an error from
`with_structured_output()`, not silently degrade. Larger models are slower
per-request but reason more thoroughly; this hasn't been benchmarked
against Gemini's output quality for this specific grounding/challenging
task — treat it as a starting point to tune, not a verified equivalence.

**Tradeoffs vs. Gemini** (why this isn't just a strict upgrade):
- **For:** zero API key, zero quota of any kind (no per-minute OR per-day
  wall — see §9.2 step 7, the whole reason this provider exists), zero
  marginal cost, works offline, no risk of a model being retired/restricted
  out from under you.
- **Against:** uses your machine's CPU/GPU/RAM instead of Google's
  infrastructure — throughput and latency depend entirely on local
  hardware, and generation quality for a Flash-tier cloud model vs. a
  similarly-sized local model hasn't been directly compared here. Running
  Modules 1+2+3+4 together (`run_talonx.py`) while Ollama is also
  generating reports adds real local resource contention that a cloud
  provider doesn't.
- **Reasonable default:** Ollama for active local development and testing
  (where you'd otherwise burn through Gemini's free-tier quota fastest,
  as this whole section documents happening); Gemini (or a paid Gemini
  tier, §9.3) if you want cloud-hosted throughput independent of your own
  machine, e.g. for a longer-running or higher-ticker-count deployment.

### 9.5 talonx_quant noise filters: why, and what changed

Live log analysis surfaced two distinct alert-chatter problems, both
downstream of `talonx_quant` publishing a `QuantSignal` for literally
every bar a threshold condition held:

1. **Ticker-level duplication** — the same ticker alerting twice within a
   ~10-minute window as *different* indicators fired off the same
   underlying price move (e.g. an RSI+volume setup, then an unrelated
   MACD cross a few minutes later on the same name).
2. **Micro-burst clustering** — 8 separate signals across multiple
   tickers within 49 seconds, several of them technically-real but
   economically-meaningless crossovers (a $0.03 moving-average drift on a
   $500 stock, ~0.006% — nowhere near a real trend change).

Each was unfiltered noise reaching `talonx_brain`, which meant real LLM
calls (and real Gemini free-tier quota, §9.2) spent on setups nobody
would act on.

**Four filters, layered in this order** (§3.2 has the mechanics of each):

| # | Filter | Fixes | Where |
|---|---|---|---|
| 1 | Edge-triggering | A condition re-firing every bar it stays true (the underlying cause of most repeat alerts, ticker-duplication included) | `strategy.py` |
| 2 | Hysteresis (min spread) | Micro-crossovers with no real economic significance (the $0.03 MSFT case) | `strategy.py` |
| 3 | Per-ticker cooldown | The remaining ticker-duplication case: genuinely different signal types firing close together in time | `consumer.py` |
| 4 | Batch throttle | Bursts across MANY tickers at once (a market-wide move) — global cap, ranked by conviction | `consumer.py` |

**Why this order:** 1 and 2 run inside `strategy.py` itself, before a
candidate signal exists at all — cheapest place to filter, and they
address *why* a signal would be spurious in the first place, not just how
often. 3 and 4 run in `consumer.py`, after candidates exist: cooldown
removes same-ticker repeats regardless of which filter or signal type
produced them, and the throttle is a last-resort global cap for exactly
the cross-ticker burst scenario nothing upstream addresses (each
individual signal in an 8-in-49-seconds burst can be perfectly legitimate
on its own — the problem is the aggregate rate, which only a
cross-ticker view can see).

**The batch throttle's tradeoff, worth restating:** "rank by conviction,
keep the top N" cannot be done without buffering candidates for the full
window first — there's no way to know a signal is top-3 until you've seen
everything else that arrived in its window. Default window is 60s
(`TALONX_QUANT_THROTTLE_WINDOW_SECONDS`), so a signal can be delayed by
up to a minute before it's published or dropped. This was a deliberate
choice over a lower-latency micro-batch design (rank+release every
10-15s against a rolling cap) — the tradeoff there is real, ranking
would only compare candidates within each short batch rather than the
full minute, so an earlier lower-conviction signal could beat a
later higher-conviction one in the same minute. Revisit if the added
latency turns out to matter more than whole-minute ranking accuracy in
practice.

**Suppression is counted, not silent** — `QuantScanner.signals_suppressed_cooldown`
and `.signals_suppressed_throttle` track how much each filter is actually
removing, and both log a line per suppression event (`consumer.py`). If
noise is still getting through, or too much is being dropped, these are
the first thing to check before retuning thresholds.