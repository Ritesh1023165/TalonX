# What's Not Built Yet

- `talonx_brain` is purely signal-triggered (reacts to
  `talonx:signals:quant`) — there's no on-demand query interface (CLI/API)
  for asking it about a ticker outside of a quant signal firing.
- ~~`talonx_brain` doesn't listen to `talonx:filings:events`~~ --
  **partially fixed**: it now subscribes to that channel and DELETES
  `brain_cache:{ticker}` the moment a fresh filing lands (see
  [modules/brain.md](modules/brain.md)), so the NEXT signal for that
  ticker is guaranteed a fresh LLM call instead of a stale cache hit.
  Still open: this only invalidates the cache -- a fresh 8-K/news item
  still doesn't trigger NEW research on its own the way a `QuantSignal`
  does; it's picked up passively, whenever the next technical signal
  happens to fire for that ticker. Also: only filings publish an
  invalidation event today (`NewFilingIngestedEvent`) -- fresh news
  articles don't, so a cached report can go stale relative to breaking
  news without anything forcing a refresh (only its TTL/market-boundary
  expiry eventually catches it).
- `talonx_brain`'s cache expiry uses plain daily 9am/4pm exchange
  clock-time boundaries -- there's no real trading-calendar awareness, so
  a cache entry set right before a market holiday or a weekend doesn't
  know the market isn't actually opening at the next 9am boundary.
- ~~**talonx_quant has no dynamic watchlist.**~~ -- **partially fixed**:
  which tickers get streamed (and periodically ingested for) is now a
  live, runtime-editable decision, via `talonx_watchlist`'s SQLite store
  and the dashboard's "🎯 Tracked tickers" section — no restart to
  add/remove a ticker. Still open: `talonx_quant` itself still has no
  allow-list of its own -- `buffer.py`'s `RollingBarBuffer.add_bar()`
  unconditionally creates a new per-symbol buffer for ANY ticker seen on
  `talonx:market:stream` -- so a ticker removed from the watchlist simply
  stops receiving new bars (its buffer goes stale); the buffer itself is
  never evicted, so memory still grows unbounded by CUMULATIVE distinct
  symbol count over a long-running process's lifetime, not just the
  currently-tracked set. Fully closing this would mean giving
  `talonx_quant` its own allow-list check plus buffer eviction for
  removed tickers.
- **talonx_core has no GLOBAL rate limiter**, only the per-ticker cooldown
  (`TALONX_CORE_TICKER_COOLDOWN`) -- a deliberate scope decision, not an
  oversight, but worth knowing if you scale to a large, correlated
  ticker list: a burst across many DIFFERENT tickers at once (e.g. a
  market-wide move) has no cross-ticker throttle the way `talonx_brain`'s
  Gemini calls do (`TALONX_BRAIN_GEMINI_RPM`).
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
- **talonx_dispatch pushes are one-way** for alert delivery (`/ping` is
  now interactive, see [modules/dispatch.md](modules/dispatch.md)) --
  there's still no way to acknowledge, dismiss, or reply to an ALERT
  from Telegram and have that reflected back in the audit trail or
  Streamlit dashboard.
- Scheduling beyond the daily restart task (e.g. a proper cron-style
  scheduler for other periodic jobs).
- ~~Social feed sources beyond RSS~~ -- **partially fixed**: Reddit is
  now a real (if optional, registration-gated) social source
  (`talonx_ingest.news.reddit_client`, see
  [modules/ingest.md](modules/ingest.md)). Twitter/X remains unbuilt,
  deliberately -- its API has no usable free read tier anymore (paid
  Basic tier, $100+/month required), which doesn't fit this project's
  free-by-default pattern. Revisit if that changes.
- **Phase 2 has no DRIP / dividend reinvestment.** No dividend data
  source exists anywhere in this pipeline (not in the SEC XBRL facts
  parsed today, not in market data) -- this needs a genuinely new
  external data integration before it's buildable at all, not just new
  code. Worth a dedicated design pass once a dividend data source is
  chosen.
- **Phase 2 has no separate End-of-Quarter report.** The EOD report's
  Valuation Radar section already surfaces the same underlying snapshot
  daily; an EOQ report's distinct value (moat-stability history,
  quarter-over-quarter trend) needs this system to have actually been
  running for a full quarter before there's any history to report on.
- **Phase 2's structured JSON logging only covers the NEW long-term code
  paths**, not a retrofit of the ~15 pre-existing intraday
  `logger.info(...)` call sites across all 6 modules -- deliberately
  deferred as a separate, purely mechanical follow-up.
- **Phase 2's DCA scheduling is fixed-interval, not calendar-aware.**
  `TALONX_PAPER_DCA_INTERVAL_DAYS` (default 30) approximates "monthly"
  rather than firing on, say, the 1st of every calendar month.
- **Phase 2's WACC is a flat assumed constant, not a real CAPM
  calculation.** No beta/market-risk-premium data source exists
  anywhere in this project -- `TALONX_CORE_LT_ASSUMED_WACC` (default 9%)
  stands in for it, same documented-simplification treatment as the
  Debt/EBITDA proxy (operating income substituting for EBITDA, no
  separate D&A line in the parsed XBRL facts).
- **`talonx_quant`'s own allow-list check for its `1m` buffer never
  evicts a removed ticker** (same root cause as the dynamic-watchlist
  item above) — bar-buffer persistence (see
  [bar_buffer_persistence.md](bar_buffer_persistence.md)) similarly has
  no eviction for a ticker that's been removed from the watchlist; its
  last checkpoint just sits in `quant.db` unused until it ages past the
  1-min buffer's gap limit on the next restart (the 15-min buffer would
  reload it regardless, forever, until manually cleared).
