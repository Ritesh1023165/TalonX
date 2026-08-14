# `talonx_ingest` — Module 1: Data Ingestion & Event Producer

Four independent pipelines, sharing common infrastructure underneath.

## SEC filing ingestion (`talonx_ingest.pipeline`)

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

## News/social feed ingestion (`talonx_ingest.news`)

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
  a free app first (see [setup.md](../setup.md)), so it's layered on top
  rather than inserted into that fallback chain — if unconfigured,
  `RedditClient.fetch_for_ticker()` returns `[]` immediately with no
  network call and no warning, and the rest of the pipeline behaves
  exactly as it did before Reddit existed.
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

## Live market data (`talonx_ingest.market_data`)

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
  symbols into one call per poll cycle rather than one request each. See
  [../bar_buffer_persistence.md](../bar_buffer_persistence.md) for how a
  degraded/stuck poll cycle is now detected and self-healed, and
  [performance.md](../performance.md) for the yfinance data-feed
  operational notes.
- **`manager.py`** — the single entrypoint downstream code talks to. It
  never exposes which source is active; consumers only see normalized
  `MarketEvent` objects with a `source` field for observability.

## Redis event publishing (`talonx_ingest.events`)

The formal output contract, independent of ChromaDB. Pydantic schemas
(`MarketTickEvent`, `NewFilingIngestedEvent`, `NewFundamentalsIngestedEvent`,
`NewsArticleIngestedEvent`) define exactly what's published and where. If
Redis is unreachable, publishing is disabled for that run (logged once as
a warning) — it never crashes ingestion, since ChromaDB writes are the
source of truth and Pub/Sub is a real-time notification layer on top.

Also carries the Stage-Gate Metric Funnel counters (`incr_metric`) and the
`/ping` health-check's WebSocket-heartbeat key (`write_ws_heartbeat`) — see
[modules/dispatch.md](dispatch.md).
