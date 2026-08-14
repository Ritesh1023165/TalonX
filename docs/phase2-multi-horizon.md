# Phase 2 — Multi-Horizon Architecture (`LONG_TERM` alongside `INTRADAY`)

TalonX started as a purely intraday momentum scanner (minutes-to-hours
holding period). Phase 2 adds a SECOND, fully independent horizon --
fundamentals-driven quality/value investing (6-months-to-multi-year
holding) -- running alongside the first, without touching how the
intraday engine behaves. Both horizons share the same watchlist, the
same Redis connection, and (for `talonx_paper`) the same SQLite file,
but every other piece of state is a SIBLING, not a shared/merged one --
that segregation is the core design decision behind everything below.

**Tagging a ticker's horizon.** `talonx_watchlist`'s "🎯 Tracked
tickers" table ([running.md](running.md)) gained a Horizon selector per
row (and on the add-ticker form): `INTRADAY` (default, Phase 1 behavior,
unchanged), `LONG_TERM` (fundamentals path only -- bypasses minute-bar
technical scanning entirely), or `DUAL_HORIZON` (both paths run
independently for the same ticker). A `DUAL_HORIZON` ticker's intraday
and long-term state, positions, and alerts never collide -- see "Why
sibling objects, not composite keys" below.

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

## Per-module additions

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
  provider already configured for the intraday chain. The
  qualitative-research cache gained a `horizon` parameter -- intraday
  keys are byte-identical to before (no invalidation of existing cache
  entries), long-term keys use a flat 90-day TTL cap (no
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
  (SELL-type / fundamental-stop) triggers are NEVER gated. Which tickers
  it actually trades is its OWN toggle -- `talonx_watchlist`'s
  `paper_trading_enabled_long_term` column, set via the dashboard's
  "💎 Long-Term Paper Trading Settings" multiselect -- fully independent
  of the intraday engine's `paper_trading_enabled` flag, so a
  `DUAL_HORIZON` ticker can be paper-traded on one horizon without the
  other. Note: no DRIP/dividend reinvestment — see
  [roadmap.md](roadmap.md).
- **`talonx_dispatch`** -- a separate `long_term_alerts` audit table and
  its own Telegram push format (price vs. fair value, margin of safety,
  quality/moat, the take-profit exit target, expected holding horizon).
  Because `alerts` and `long_term_alerts` are two independently-
  auto-incrementing tables, long-term Telegram IDs are prefixed --
  `#LT12` in the push, reply `LT12` (case-insensitive) for full detail,
  disambiguated from a bare intraday `#12`.
- **Dashboard (`talonx_dispatch/app.py`)** -- 4 sections: **📈 Intraday
  Monitor** (Phase 1), **💎 Long-Term Radar** (an Upcoming Earnings
  Calendar widget — 🟢 within 48h / 🟡 within 7 days / ⚪ beyond, synced
  weekly by `periodic_earnings_calendar_sync_loop`, see
  [earnings-radar.md](earnings-radar.md) — a Valuation & Margin of Safety
  table with a "Last earnings event" column, the moat/capital-allocation/
  DCF writeup behind each ticker, and the long-term portfolio's
  cash/positions/DCA-contributed/equity curve), **📊 Daily Funnel &
  Metrics** (Stage-Gate Metric Funnel — see
  [modules/dispatch.md](modules/dispatch.md)), and **⚙️ Watchlist &
  Settings** (the ticker watchlist with its horizon selector,
  paper-trading toggle, and filters, both portfolios' settings, and a
  horizon-filterable unified audit trail).
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
  (see [roadmap.md](roadmap.md)).
- **Reactive ingestion** (`run_talonx.py`'s `WatchlistDrivenIngestion`) --
  fixes a real gap a live smoke test caught: `periodic_ingestion_loop`/
  `periodic_long_term_financials_loop` only re-scan the watchlist once
  every `--interval-hours` (default 6h), so a ticker added or re-tagged
  LONG_TERM mid-session used to sit with zero filing/financials data for
  up to several hours -- silently, since nothing else in the pipeline
  surfaces "this ticker has no data yet" as an error. `WatchlistDrivenIngestion`
  polls the watchlist on the same short cadence market data streaming
  already uses (`TALONX_WATCHLIST_POLL_INTERVAL`, default 10s), diffs
  against its own last-known state, and triggers a ONE-OFF ingestion for
  just the ticker(s) that changed: newly active (added or resumed) gets
  immediate filing+news ingestion; newly LONG_TERM-eligible (added with
  that horizon, or re-tagged from `INTRADAY`) gets immediate structured-
  financials ingestion. Same reconcile-by-diffing shape
  `WatchlistDrivenMarketData` already uses for market data. The periodic
  `--interval-hours` cycle stays in place as the retry/safety net for
  anything this reactive path fails to ingest (a transient SEC API
  error, say) -- it isn't retried reactively, only on the next scheduled
  cycle.

**Not built this pass** (see [roadmap.md](roadmap.md) for the reasoning
behind each): DRIP / dividend reinvestment, a separate End-of-Quarter
report, a full structured-logging retrofit of the pre-existing intraday
log lines, true calendar-month DCA scheduling, and a real CAPM-based
WACC.
