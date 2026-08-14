# Running Things

All commands below assume: `.venv` is activated, and your terminal's
current directory is `C:\workspace\TalonX`.

Having trouble getting something to produce output at all? See
[troubleshooting.md](troubleshooting.md) — including how to diagnose a
hang/connectivity issue.

## Run everything together (recommended)

```powershell
python run_talonx.py
```
Single process, single terminal, single Ctrl+C to stop. This starts:
- SEC filing + news ingestion, immediately, then again every 6 hours
  (`--interval-hours` to change) -- PLUS a reactive watcher
  (`WatchlistDrivenIngestion`, see [phase2-multi-horizon.md](phase2-multi-horizon.md))
  that triggers an immediate one-off ingestion the moment a ticker is
  added, resumed, or re-tagged LONG_TERM via the dashboard, instead of
  waiting for the next scheduled cycle
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
  execution for tickers with paper trading enabled and pushes its
  own short Telegram notification per executed trade.
- **Phase 2** ([phase2-multi-horizon.md](phase2-multi-horizon.md)),
  automatically for any ticker tagged `LONG_TERM` or `DUAL_HORIZON` in
  the watchlist -- structured financials ingestion, the fundamental
  factor scanner, a slow daily-close price poll for `LONG_TERM`-only
  tickers (a `DUAL_HORIZON` ticker already gets prices from the regular
  stream above), and the DCA-aware long-term paper engine. Modules 3/4/5
  (`talonx_brain`/`talonx_core`/`talonx_dispatch`) already handle both
  horizons internally within the same task started above -- no separate
  flag needed for those three. A fresh install with no `LONG_TERM`-tagged
  tickers simply has nothing for any of this to do.

**The Streamlit dashboard is separate** -- run
`streamlit run talonx_dispatch\app.py` (see below) in its own terminal
alongside this one if you want to view it live (alerts, the ticker
watchlist, the paper trading portfolio, and the Daily Funnel & Metrics
tab all live there).

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

**Convenience scripts**: `scripts\start_talonx.ps1` /
`scripts\stop_talonx.ps1` start/stop `run_talonx.py` + Streamlit together
(hidden background processes with logs under `.run\logs\`, or
`-Interactive` for visible console windows); `scripts\start_dashboard_web.ps1`
/ `scripts\stop_dashboard_web.ps1` do the same for `dashboard_web.py`
independently.

The sections below describe each component separately -- useful for
debugging one piece in isolation, or if you want independent control over
each rather than running them as one process.

## Ingest SEC filings (standalone)

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

## Inspect what's in the vector store

```powershell
# Overall stats: total chunks, breakdown by ticker and form type
python inspect_store.py --summary

# Semantic search
python inspect_store.py --query "supply chain risk" --ticker NVDA

# More results, full text instead of a preview
python inspect_store.py --query "share buybacks" --ticker AAPL --form 10-K -n 10 --full
```

## Stream market data (standalone)

```powershell
python -m talonx_ingest.market_data.run AAPL MSFT NVDA
```
Uses Polygon WebSocket if `POLYGON_API_KEY` is set in `.env`, otherwise
automatically falls back to yfinance polling (every 5s, delayed data).
**This runs continuously — it does not exit on its own.** Stop it with
`Ctrl+C`. If the WebSocket keeps failing to reconnect, it automatically
switches to polling for the rest of that run rather than giving up
entirely. See [performance.md](performance.md) for yfinance's
degraded-cycle self-healing behavior.

## Ingest news/social feeds (standalone)

```powershell
python -m talonx_ingest.news.pipeline AAPL MSFT NVDA
```
Uses NewsAPI.org if `NEWS_API_KEY` is set in `.env`, otherwise automatically
falls back to Yahoo Finance's public per-ticker RSS feed (no key needed).
ALSO searches Reddit (`wallstreetbets`, `stocks`, `investing` by default)
if `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` are set ([setup.md](setup.md)) — additive on
top of NewsAPI/RSS, silently skipped (no error, no warning) if unset.
Embeds into a separate ChromaDB collection (`news_feed` by default) so
filing text and news text stay independently queryable. Same incremental
ledger behavior as filings — re-running skips articles/posts already
ingested; `--force-refresh` bypasses that.

## Redis event publishing

`talonx_ingest.pipeline`, `talonx_ingest.market_data.run`, and
`talonx_ingest.news.pipeline` publish events to Redis Pub/Sub as their
formal output contract, in addition to writing to ChromaDB / printing to
console:

| Channel | Event | Published when |
|---|---|---|
| `talonx:filings:events` | `NewFilingIngestedEvent` | A filing's chunks are fully written to ChromaDB |
| `talonx:market:stream` | `MarketTickEvent` | Every trade/quote/bar tick |
| `talonx:news:events` | `NewsArticleIngestedEvent` | A news/social article's chunks are fully written to ChromaDB |
| `talonx:fundamentals:events` | `NewFundamentalsIngestedEvent` | Fresh structured XBRL financials land for a `LONG_TERM`/`DUAL_HORIZON` ticker |

No setup is required to run the pipeline without Redis — if it's not
reachable at `TALONX_REDIS_URL` (default `redis://localhost:6379/0`),
publishing is disabled for that run (logged once as a warning) and
everything else continues normally. To actually see events flowing, make
sure Redis is running (`docker compose up -d`) and subscribe from another
terminal:
```powershell
docker exec talonx-redis redis-cli subscribe talonx:filings:events
```

## Run the quant scanner (standalone)

```powershell
pip install -r talonx_quant\requirements.txt
python -m talonx_quant.run
```
Listens to `talonx:market:stream`, maintains a rolling OHLCV buffer per
ticker from BAR events, and publishes `QuantSignal` events to
`talonx:signals:quant` when RSI+volume, MACD crossover, or MA crossover
conditions trigger. Runs continuously — `Ctrl+C` to stop. Needs bars to
accumulate before signals can fire (`TALONX_QUANT_MIN_BARS`, default 120),
so pair it with `market_data.run` streaming the same tickers, and expect
a warm-up period before the first signal — unless a recent buffer
checkpoint exists, see [bar_buffer_persistence.md](bar_buffer_persistence.md).

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
conditions, see `send_test_signal.py` at the project root. To trace one
ticker's full pipeline journey (ingest → quant → brain → core → dispatch
→ paper) from persisted data, read-only and safe against a live
instance:
```powershell
python scripts\ticker_funnel_report.py NVDA
```

## Run the research agent (talonx_brain, standalone)

`run_talonx.py` already starts this automatically when its LLM
provider is configured -- run it standalone instead if you want it
decoupled from Modules 1+2 (e.g. running on a different machine/schedule),
or you're just iterating on `talonx_brain` itself.

```powershell
pip install -r talonx_brain\requirements.txt
python -m talonx_brain.run
```
Listens to `talonx:signals:quant`, and for each `QuantSignal` retrieves
relevant SEC filing context for that ticker from ChromaDB, asks the
configured LLM (Gemini by default, or a local Ollama model -- see
[modules/brain.md](modules/brain.md) and [performance.md](performance.md))
to assess it against the technical trigger, and publishes a
`ResearchReport` to `talonx:reports:brain`. Requires either `GEMINI_API_KEY`
in `.env` (default `gemini` provider) or `ollama serve` running locally
(`TALONX_BRAIN_LLM_PROVIDER=ollama`), and at least some filings already
ingested for the tickers you're scanning (see above) — with no filing context, reports still publish, just with
`verdict: "insufficient_context"` instead of a guess. Runs continuously —
`Ctrl+C` to stop. Pair it with `market_data.run` + `talonx_quant.run` (or
just `send_test_signal.py`) so signals actually arrive on the input
channel.

To watch reports arrive, subscribe in another terminal:
```powershell
docker exec talonx-redis redis-cli subscribe talonx:reports:brain
```

## Run the decision engine (talonx_core, standalone)

`run_talonx.py` already starts this automatically -- run it
standalone instead if you want it decoupled from the other four modules,
or you're just iterating on `talonx_core` itself.

```powershell
pip install -r talonx_core\requirements.txt
python -m talonx_core.run
```
Listens to BOTH `talonx:signals:quant` and `talonx:reports:brain`,
correlates them per ticker, runs the Decision Matrix, and publishes an
`ActionableAlert` to `talonx:alerts:dispatch` when a pair is CONFIRMED or
CONTRADICTED (see [modules/core.md](modules/core.md)). No API key or
extra setup required -- it needs only Redis, same as `talonx_quant`. Pair
it with `talonx_quant.run` + `talonx_brain.run` (or `send_test_signal.py`
for a synthetic trigger) so there's actually something to correlate.
Runs continuously — `Ctrl+C` to stop.

Correlator state persists to `C:\Users\<you>\.talonx\core_state.db`
(SQLite, `TALONX_CORE_STATE_DB` to change it) — stopping and restarting
this process picks up right where it left off rather than losing
whichever half of an in-flight pair had already arrived. Set
`TALONX_CORE_ENABLE_PERSISTENCE=false` to always start clean instead.

To watch alerts arrive, subscribe in another terminal:
```powershell
docker exec talonx-redis redis-cli subscribe talonx:alerts:dispatch
```

## Run the test suite

```powershell
pip install -r requirements-dev.txt
pytest
```
Covers every module: the cleaner, chunker, incremental ledger (filings
and news), Redis event schemas, and ledger/upsert safety logic in
`talonx_ingest`; `talonx_quant`'s strategy/indicator/consumer logic
(including the buffer-persistence gap-gating and yfinance degraded-cycle
handling); `talonx_brain`'s schemas, retrieval transform, and
orchestration; `talonx_core`'s Decision Matrix (every suppression check,
as a pure function) and its dual-channel correlate/decide/publish
orchestration; `talonx_dispatch`'s Markdown formatter, `AuditStore`
(real SQLite, including persistence across a simulated restart), the
`/ping` handler, and the Smart Dispatch Filtering orchestration. Redis,
ChromaDB, Gemini, and Telegram are all mocked; SQLite is exercised for
real throughout. Network-dependent code (EDGAR client, market data
sources, Gemini, Telegram, yfinance) is exercised via mocks, not live
calls -- this is a fast, offline-safe suite you can run on every change.
`requirements-dev.txt` pulls in every module's own `requirements.txt`, so
a fresh checkout running just `pip install -r requirements-dev.txt && pytest`
collects and runs the ENTIRE suite.

## Watch the live pipeline dashboard

```powershell
pip install -r requirements-dashboard.txt
python dashboard.py
```
A read-only, live-refreshing terminal view across ALL Redis channels
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
(LLM failed)** ([modules/brain.md](modules/brain.md)'s caching),
`talonx:signals:quant` splits by signal type, `talonx:alerts:dispatch`
splits by action, and `talonx:paper:trades` splits by BUY/SELL plus a
running realized-PnL total. **What this can't show**: anything that gets
SUPPRESSED before publishing -- for that, use the Streamlit dashboard's
Daily Funnel & Metrics tab instead, which reads the Stage-Gate Metric
Funnel's persisted Redis counters (see
[modules/dispatch.md](modules/dispatch.md)) or
`scripts\ticker_funnel_report.py` for a per-ticker view. Run this
dashboard alongside `run_talonx.py` (or any combination of standalone
module processes) — it only subscribes, it never publishes, so it can't
affect the pipeline it's watching.

```powershell
python dashboard.py --top-n 8       # show more tickers per channel (default: 5)
python dashboard.py --refresh 0.5   # redraw faster (default: 1.0s)
```

In-memory only — counts reset if you restart it; this is a live view of
"what's happening right now," not a historical record.
`Ctrl+C` to stop; prints a final summary of totals per channel on exit.

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
the connection drops.

```powershell
python dashboard_web.py --port 9000     # if 8787 is taken
```
Reuses `dashboard.py`'s channel-watching logic directly (imports it) so
the two tools can never drift out of sync on which channel maps to which
ticker field — pick whichever one fits the moment; there's no need to run
both.

## Run the notification dispatcher (talonx_dispatch, standalone)

`run_talonx.py` already starts this automatically — run it
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
`warning`) if `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` are set
([setup.md](setup.md)) — otherwise it logs one warning at startup and
keeps recording to the audit trail without pushing. **The Streamlit
dashboard (below) is never started this way, or by `run_talonx.py`** —
see [modules/dispatch.md](modules/dispatch.md) for why; always run it as
its own separate process. Runs continuously — `Ctrl+C` to stop; prints a
summary of alerts processed / Telegram sent / failed on exit.

## Run the Streamlit dashboard — live alerts + ticker watchlist

```powershell
streamlit run talonx_dispatch\app.py
```
Opens in your browser automatically (Streamlit's default behavior).
Reads the SAME audit trail `talonx_dispatch.run` writes to for its
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
filtering by exchange, strategy horizon, paper-trading status, and
active/paused status, sorting by any column, and pagination (10 tickers
per page). An inline **Enable Paper Trading** checkbox column sits next
to the horizon selector — toggling it writes straight to
`paper_trading_enabled`/`paper_trading_enabled_long_term` immediately,
same live-control-surface behavior as everything else in this table. A
`DUAL_HORIZON` ticker shows BOTH checkboxes (they're independently
tracked flags, one per paper-trading engine); `INTRADAY`/`LONG_TERM`
show only the one that applies. Pause/Resume/Remove are color-coded
(amber/green/red) to keep them visually distinct. Also shows: summary
metrics, tickers with alert history (derived from the audit trail —
which tickers have actually alerted, distinct from what's currently
tracked), a live expandable alert feed, and a filterable
(ticker/action/severity) full audit trail table. Auto-refreshes every
`TALONX_DISPATCH_AUTOREFRESH_MS` (default 5000ms) — that's also how
often an add/remove made by someone else shows up in your own browser
tab. Also shows the **"💰 Paper Trading"** section (portfolio
value/win-rate/open-positions metrics, a Settings panel, an
open-positions table marked to the latest known price, an equity curve,
a win/loss-colored per-trade PnL chart, and a downloadable CSV of the
full trade history) and the **"📊 Daily Funnel & Metrics"** tab (see
[modules/dispatch.md](modules/dispatch.md)).

```powershell
streamlit run talonx_dispatch\app.py --server.port 8502   # if 8501 is taken
```

## Run the paper trading engine (talonx_paper, standalone)

```powershell
pip install -r talonx_paper\requirements.txt
python -m talonx_paper.run
```
Listens to `talonx:alerts:dispatch` and `talonx:market:stream`, simulates
BUY/SELL execution for tickers with paper trading enabled (toggle in the
dashboard's Paper Trading section, above), and publishes each executed
trade to `talonx:paper:trades` — `talonx_dispatch.run` picks that
up and sends its own short Telegram notification, decoupled from the
triggering alert's push. Runs continuously — `Ctrl+C` to stop; prints a
summary of alerts processed / trades executed / trades ignored on exit.

**Risk management and friction, added after reviewing a live session's
results** (negative risk-to-reward, gains too small to survive real
friction, and too many low-conviction round trips on one ticker):
- Every open position is checked against a **stop-loss/take-profit band**
  on every market tick, not just when a reversal alert happens to arrive.
  This is *additional* to the existing alert-driven exit
  (`CONFIRMED_BEARISH`/`CONTRADICTED` still closes a position immediately,
  regardless of stop/take) — a genuine reversal signal is never
  suppressed, stop/take just adds a price-based floor and ceiling. Now
  ATR-anchored per-signal when available (`stop_price`/`target_price`
  from the triggering alert), falling back to static percentages
  (`TALONX_PAPER_STOP_LOSS_PCT`/`TALONX_PAPER_TAKE_PROFIT_PCT`, default
  0.50%/1.00%) — see [modules/paper.md](modules/paper.md).
- Every fill (BUY or SELL, however triggered) crosses a **simulated
  bid-ask spread** (`TALONX_PAPER_SIMULATED_SPREAD_BPS`, default 5bps),
  so realized PnL isn't unrealistically clean the way a zero-friction
  fill at the exact signal price is.
- New positions can be gated to a **minimum alert severity**
  (`TALONX_PAPER_MIN_ENTRY_SEVERITY`, default `warning`) — a
  `CONFIRMED_BULLISH` alert below that bar never opens a position
  (recorded `BELOW_MIN_SEVERITY`, visible in the EOD report below); exits
  are never severity-gated.
- Two EXISTING knobs also directly address trade frequency/sizing
  without any code change: `TALONX_CORE_TICKER_COOLDOWN` (larger =
  fewer re-entries) and `TALONX_PAPER_TRADE_ALLOCATION` (larger
  positions make the spread cost a smaller fraction of each trade).

## Generate an End-of-Day report (standalone)

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
For a live, per-ticker version of this same question against a currently
running instance, see `scripts\ticker_funnel_report.py` above.

```powershell
python generate_eod_report.py --date 2026-08-11     # default: today, in --tz
python generate_eod_report.py --tz Europe/London    # default: America/New_York
python generate_eod_report.py --out-dir C:\reports  # default: .\reports
```
Nothing in this project schedules it automatically — wire up a Windows
Task Scheduler entry yourself if you want it to run unattended right
after market close each day.
