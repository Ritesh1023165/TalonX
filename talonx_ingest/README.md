# TalonX Ingest

Data ingestion engine for **Project TalonX** — a two-stage quantitative &
qualitative stock research pipeline. This module handles Stage 1 ingestion:
pulling SEC filings and market data into a local, searchable form so a
later RAG + LLM stage can research specific stocks.

- **Unstructured side**: SEC EDGAR 10-K/10-Q filings → cleaned text →
  chunked → embedded → stored in a local ChromaDB vector store.
- **Structured side**: real-time market data via Polygon.io WebSocket,
  with an automatic fallback to yfinance polling.

Nothing in this module does LLM reasoning or RAG retrieval itself — it
prepares the data those later stages will use.

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.11+** | Get it from [python.org/downloads](https://www.python.org/downloads/) — not the Microsoft Store version. Check "Add python.exe to PATH" during install. |
| **Visual C++ Build Tools** (Windows only) | Needed if `pip install` fails compiling `chromadb`/`hnswlib`. Get the "Desktop development with C++" workload from the [VC++ Build Tools installer](https://visualstudio.microsoft.com/visual-cpp-build-tools/). |
| **An editor** | VS Code (Python extension) or Visual Studio 2022 (Python Development workload). |
| **~2GB free disk** | `sentence-transformers` pulls in PyTorch on first install. |

---

## 2. Project layout

```
C:\workspace\TalonX\              <- open THIS folder as your project root
├── .env                           <- your local secrets/config (create from .env.example)
├── .env.example
├── .gitignore
├── inspect_store.py               <- CLI to spot-check what's in ChromaDB
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
│   │   ├── models.py                 <- NewsArticle
│   │   └── pipeline.py               <- fetch -> chunk -> embed news into ChromaDB
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
```

**Important:** `.env`, `inspect_store.py`, and `talonx_ingest\check_connectivity.py`
(that one specifically) must sit where shown above. Python's module resolution
and `.env` auto-discovery both depend on running commands from
`C:\workspace\TalonX`, not from inside `talonx_ingest\`.

---

## 3. First-time setup

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
# 3. Set up your .env file
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

---

## 4. Running things

All commands below assume: `.venv` is activated, and your terminal's
current directory is `C:\workspace\TalonX`.

### 4a. Ingest SEC filings

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

### 4b. Inspect what's in the vector store

```powershell
# Overall stats: total chunks, breakdown by ticker and form type
python inspect_store.py --summary

# Semantic search
python inspect_store.py --query "supply chain risk" --ticker NVDA

# More results, full text instead of a preview
python inspect_store.py --query "share buybacks" --ticker AAPL --form 10-K -n 10 --full
```

### 4c. Stream market data

```powershell
python -m talonx_ingest.market_data.run AAPL MSFT NVDA
```
Uses Polygon WebSocket if `POLYGON_API_KEY` is set in `.env`, otherwise
automatically falls back to yfinance polling (every 5s, delayed data).
**This runs continuously — it does not exit on its own.** Stop it with
`Ctrl+C`. If the WebSocket keeps failing to reconnect, it automatically
switches to polling for the rest of that run rather than giving up
entirely.

### 4e. Ingest news/social feeds

```powershell
python -m talonx_ingest.news.pipeline AAPL MSFT NVDA
```
Uses NewsAPI.org if `NEWS_API_KEY` is set in `.env`, otherwise automatically
falls back to Yahoo Finance's public per-ticker RSS feed (no key needed).
Embeds into a separate ChromaDB collection (`news_feed` by default) so
filing text and news text stay independently queryable. Same incremental
ledger behavior as filings — re-running skips articles already ingested;
`--force-refresh` bypasses that.

### 4f. Redis event publishing

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
everything else continues normally. To actually see events flowing, run
a local Redis server and subscribe from another terminal:
```powershell
redis-cli subscribe talonx:filings:events
```

### 4g. Diagnose a hang or connectivity issue

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

---

## 5. Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| `No module named 'talonx_ingest...'` | Running from the wrong folder | `cd` to `C:\workspace\TalonX` (the parent of `talonx_ingest`), not inside it |
| Command hangs, zero log lines | Corporate proxy/firewall blocking direct connections, or slow first-time model download | Run `check_connectivity.py`; set `HTTPS_PROXY` if needed |
| `403` errors from SEC | `TALONX_SEC_USER_AGENT` not set to a real contact string | Edit `.env`, set a real name/email |
| `pip install` fails on `chromadb`/`hnswlib` | Missing C++ build tools | Install VC++ Build Tools (see Prerequisites) |
| New dependency "not found" after editing `requirements.txt` | Editing a different copy of the file than the one `pip install -r` reads | Confirm you're editing `C:\workspace\TalonX\talonx_ingest\requirements.txt` specifically, then re-run `pip install -r` |
| `.env` values seem ignored | `.env` isn't at the project root | Move it to `C:\workspace\TalonX\.env`, next to (not inside) `talonx_ingest\` |

---

## 6. Environment variable reference

See `.env.example` for the full list with defaults and descriptions —
only `TALONX_SEC_USER_AGENT` is required; everything else is optional
tuning (rate limits, chunk size, embedding model, ledger path, market
data reconnect behavior, etc).

---

## 7. What's not built yet

- Quant filtering stage (pandas_ta) that would feed a dynamic watchlist
  into this ingestion pipeline, replacing the hardcoded default tickers.
- RAG query layer / Gemini integration that actually consumes the
  ChromaDB stores (both `sec_filings` and `news_feed`) for qualitative
  research, and subscribes to the Redis event channels.
- Automated test suite (chunker/cleaner/market event parsing are pure
  functions and good candidates).
- Scheduling (e.g. a daily incremental ingestion run via Task Scheduler).
- Social feed sources beyond RSS (e.g. a proper Twitter/X or Reddit
  client) — currently "social" is covered only via the RSS fallback path.