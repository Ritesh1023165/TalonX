# Architecture Overview

## Project layout

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
├── scripts\
│   ├── start_talonx.ps1              <- starts run_talonx.py + Streamlit
│   ├── stop_talonx.ps1
│   ├── start_dashboard_web.ps1
│   ├── stop_dashboard_web.ps1
│   ├── register_scheduled_tasks.ps1  <- Mon-Fri scheduled start/stop (08:00/22:00 default)
│   └── ticker_funnel_report.py       <- per-ticker pipeline diagnostic (read-only, safe against a live instance)
├── docs\                           <- this documentation
├── tests\                          <- see running.md §"Run the test suite"
├── talonx_ingest\                  <- Module 1: Data Ingestion & Event Producer
│   ├── config.py                   <- all settings, env-driven
│   ├── pipeline.py                 <- SEC filing ingestion entrypoint; also ingest_earnings_filing (Earnings Radar fast-track)
│   ├── earnings.py                 <- fetch_earnings_calendar -- yfinance calendar wrapper (Earnings Radar)
│   ├── check_connectivity.py       <- network diagnostic script
│   ├── common\
│   │   ├── backoff.py               <- shared retry/backoff helper
│   │   └── structured_logging.py    <- log_structured() -- JSON event logging (Phase 2 code paths)
│   ├── edgar\
│   │   ├── client.py                <- async SEC EDGAR client (rate-limited, retrying)
│   │   ├── financials.py            <- XBRL company-facts parsing (Phase 2)
│   │   └── models.py                <- filing data structures
│   ├── events\
│   │   ├── schemas.py                <- Pydantic contracts: MarketTickEvent, NewFilingIngestedEvent, NewFundamentalsIngestedEvent, NewsArticleIngestedEvent
│   │   └── publisher.py              <- async Redis Pub/Sub publisher (graceful if Redis down); also incr_metric, write_ws_heartbeat
│   ├── news\
│   │   ├── client.py                 <- NewsAPI primary, Yahoo Finance RSS fallback
│   │   ├── reddit_client.py          <- optional additional source: Reddit OAuth2 search
│   │   ├── models.py                 <- NewsArticle (shared shape: NewsAPI, RSS, and Reddit all normalize into this)
│   │   └── pipeline.py               <- fetch (news + Reddit) -> chunk -> embed into ChromaDB; publishes NewsArticleIngestedEvent
│   ├── processing\
│   │   ├── cleaner.py                <- HTML -> plain text
│   │   └── chunker.py                <- text -> embeddable chunks (shared by filings + news)
│   ├── storage\
│   │   ├── vector_store.py           <- ChromaDB wrapper (supports multiple collections)
│   │   └── ledger.py                 <- SQLite: tracks what's already ingested (filings + news)
│   └── market_data\
│       ├── manager.py                <- WebSocket-first, polling-fallback orchestration
│       ├── polygon_ws.py             <- Polygon.io WebSocket client
│       ├── yfinance_poll.py          <- yfinance polling fallback; degraded-cycle detection + session self-heal; also fetch_extended_hours_quote (Earnings Radar)
│       ├── models.py                 <- normalized market event type
│       └── run.py                    <- market data entrypoint; also publishes to Redis, writes WS heartbeat, increments bars_read
├── talonx_quant\                    <- Module 2: Technical & Quantitative Scanner
│   ├── config.py                     <- all settings, env-driven
│   ├── schemas.py                    <- MarketTickEvent (input, mirrors talonx_ingest's wire format), QuantSignal (output)
│   ├── buffer.py                     <- per-ticker rolling OHLCV buffer (in-memory, bounded, checkpointed to quant.db)
│   ├── session.py                    <- pre-market/regular/closed session classification
│   ├── indicators.py                 <- RSI/MACD/SMA/volume-surge/ATR/HTF-trend via pandas_ta
│   ├── strategy.py                   <- indicator snapshot -> QuantSignal trigger logic, edge-triggered + hysteresis-gated
│   ├── consumer.py                   <- async Redis subscriber; per-ticker cooldown + batch throttle + buffer persistence
│   ├── store.py                      <- QuantStateStore -- suppression counts, fundamental factors, bar_buffer checkpoints
│   └── run.py                        <- entrypoint: listens talonx:market:stream, publishes talonx:signals:quant
├── talonx_brain\                    <- Module 3: Deep Research Agent & RAG Engine
│   ├── config.py                     <- all settings, env-driven (LLM provider + Gemini + Ollama, retrieval, Redis)
│   ├── schemas.py                    <- QuantSignal (input, mirrors talonx_quant's wire format), ResearchReport/Citation (output)
│   ├── retriever.py                  <- ChromaDB RAG retrieval (imports talonx_ingest's VectorStore directly)
│   ├── llm.py                        <- structured-output chain: GeminiResearchChain (langchain-google-genai) or OllamaResearchChain (langchain-ollama), picked by build_research_chain()
│   ├── cache.py                      <- BrainCache -- Redis-backed qualitative cache, horizon-aware TTL
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
├── talonx_dispatch\                 <- Module 5: Notification Dispatcher & Streamlit Interface
│   ├── config.py                     <- all settings, env-driven (Telegram, audit DB, Streamlit refresh, Redis)
│   ├── schemas.py                    <- ActionableAlert mirror (input, mirrors talonx_core's wire format), incl. technical-detail fields
│   ├── store.py                      <- AuditStore -- SQLite audit trail; consumer.py writes, app.py reads (two separate processes)
│   ├── formatter.py                  <- pure ActionableAlert -> Telegram Markdown text
│   ├── telegram_client.py            <- thin async wrapper over python-telegram-bot, retry/backoff
│   ├── telegram_listener.py          <- incoming messages: alert-ID detail replies + /ping health check
│   ├── consumer.py                   <- async Redis subscriber: record to audit trail -> maybe push Telegram
│   ├── run.py                        <- entrypoint: listens talonx:alerts:dispatch (consumer half only)
│   └── app.py                        <- Streamlit dashboard: `streamlit run talonx_dispatch/app.py` (ALWAYS standalone)
├── talonx_paper\                    <- Module 6: Live Paper Trading Engine
│   ├── config.py, schemas.py, engine.py, store.py, consumer.py, run.py
└── talonx_watchlist\                <- shared ticker watchlist store (talonx_dispatch/app.py's control surface)
```

**Important:** `.env` lives at the repo root — every module resolves it by
path relative to its own package location (`../.env` from inside each
package, not by searching the current working directory), so it's found
reliably no matter which folder you run commands from. Every `talonx_*`
module reads the SAME file (they share `TALONX_REDIS_URL` and other
Redis settings; `talonx_brain` also needs `GEMINI_API_KEY` and
`talonx_dispatch` needs `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` from it)
rather than needing their own copies. `inspect_store.py` and `pytest`
still need to be run from the repo root (`C:\workspace\TalonX`), since
that's how Python resolves `talonx_*.*` imports.

## Per-module deep dives

- [modules/ingest.md](modules/ingest.md) — Module 1: Data Ingestion & Event Producer
- [modules/quant.md](modules/quant.md) — Module 2: Technical & Quantitative Scanner
- [modules/brain.md](modules/brain.md) — Module 3: Deep Research Agent & RAG Engine
- [modules/core.md](modules/core.md) — Module 4: Core Event Bus & Decision Engine
- [modules/dispatch.md](modules/dispatch.md) — Module 5: Notification Dispatcher & Streamlit Interface
- [modules/paper.md](modules/paper.md) — Module 6: Live Paper Trading Engine
- [modules/orchestrator.md](modules/orchestrator.md) — `run_talonx.py`

Cross-cutting features: [phase2-multi-horizon.md](phase2-multi-horizon.md),
[earnings-radar.md](earnings-radar.md), [premarket-radar.md](premarket-radar.md),
[bar_buffer_persistence.md](bar_buffer_persistence.md).

## End-to-end data flow

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
