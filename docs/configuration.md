# Environment Variable Reference

See `.env.example` for the full list with defaults and descriptions —
`TALONX_SEC_USER_AGENT` is required for Module 1; Module 3 requires
`GEMINI_API_KEY` OR `TALONX_BRAIN_LLM_PROVIDER=ollama` (see
[performance.md](performance.md)) depending on which LLM provider you
pick; everything else is optional tuning:

- Rate limits, chunk size, embedding model, ledger path, market data
  reconnect behavior, `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET`/
  `REDDIT_USER_AGENT`/`TALONX_REDDIT_SUBREDDITS` for the optional Reddit
  source.
- Module 2's indicator periods/thresholds plus its noise and
  signal-quality filters — `TALONX_QUANT_COOLDOWN_SECONDS` /
  `TALONX_QUANT_MIN_MA_SPREAD_PCT` / `TALONX_QUANT_THROTTLE_WINDOW_SECONDS`
  / `TALONX_QUANT_THROTTLE_MAX_SIGNALS` / `TALONX_QUANT_ATR_MOVE_MULTIPLIER`
  / `TALONX_QUANT_CONFLUENCE_SCORE_MIN` / `TALONX_QUANT_MIN_RISK_REWARD_RATIO`
  / `TALONX_QUANT_LOSS_LOCKOUT_SECONDS` / `TALONX_QUANT_MIN_ATR_PCT` (the
  minimum-volatility gate, and the opening/closing entry blackout windows
  it sits alongside — see [modules/quant.md](modules/quant.md),
  [performance.md](performance.md)), plus the Phase 2 pre-market/trend-gate
  additions (`TALONX_QUANT_PREMARKET_VOLUME_SURGE_RATIO`,
  `TALONX_QUANT_PREMARKET_MIN_DOLLAR_VOLUME_PER_MIN`,
  `TALONX_QUANT_PREMARKET_MAX_SPREAD_PCT`,
  `TALONX_QUANT_NEWS_CATALYST_LOOKBACK_HOURS`,
  `TALONX_QUANT_HTF_SMA_PERIOD`, `TALONX_QUANT_TREND_GATE_ENABLED`,
  `TALONX_QUANT_RTH_ONLY_HTF`), buffer persistence
  (`TALONX_QUANT_BUFFER_CHECKPOINT_SECONDS`,
  `TALONX_QUANT_BUFFER_RELOAD_MAX_GAP_SECONDS`), and historical pre-seeding
  (`TALONX_QUANT_PRESEED_ENABLED`, `TALONX_QUANT_PRESEED_1M_PERIOD`,
  `TALONX_QUANT_PRESEED_15M_PERIOD`, `TALONX_QUANT_HTF_BACKFILL_GAP_SECONDS`
  — see [bar_buffer_persistence.md](bar_buffer_persistence.md)).
- yfinance polling and its degraded-cycle self-heal
  (`TALONX_YF_POLL_INTERVAL`, `TALONX_YF_DEGRADED_FAILURE_RATE`,
  `TALONX_YF_SESSION_RESET_AFTER` — see [performance.md](performance.md)).
- Retrieval top-K, `TALONX_BRAIN_LLM_PROVIDER` + Gemini model/temperature
  + `TALONX_BRAIN_OLLAMA_MODEL`/`TALONX_BRAIN_OLLAMA_BASE_URL`, Module 3's
  qualitative cache -- `TALONX_BRAIN_CACHE_ENABLED` /
  `TALONX_BRAIN_CACHE_BASE_TTL` / `TALONX_BRAIN_CACHE_SAFETY_TTL` /
  `TALONX_BRAIN_CACHE_LOCK_TTL` / `TALONX_BRAIN_CACHE_LOCK_WAIT_SECONDS` /
  `TALONX_BRAIN_MARKET_TZ` / `TALONX_BRAIN_MARKET_OPEN_HOUR` /
  `TALONX_BRAIN_MARKET_CLOSE_HOUR` (see [modules/brain.md](modules/brain.md)).
- Module 4's `TALONX_CORE_MIN_CONFIDENCE` / `TALONX_CORE_CORRELATION_WINDOW`
  / `TALONX_CORE_TICKER_COOLDOWN` / `TALONX_CORE_PRICE_DELTA_RETRIGGER_PCT`
  / `TALONX_CORE_ENABLE_PERSISTENCE` / `TALONX_CORE_STATE_DB` (see
  [modules/core.md](modules/core.md)).
- Module 5's `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (both optional --
  see [setup.md](setup.md)) / `TALONX_DISPATCH_MIN_SEVERITY` /
  `TALONX_DISPATCH_AUDIT_DB` / `TALONX_DISPATCH_FEED_LIMIT` /
  `TALONX_DISPATCH_AUTOREFRESH_MS` / `TALONX_DISPATCH_TELEGRAM_POLL_TIMEOUT`
  / `TALONX_DISPATCH_RETENTION_DAYS` / `TALONX_DISPATCH_RETENTION_SWEEP_HOURS`
  / `TALONX_DISPATCH_MUTE_CONTRADICTIONS` / `TALONX_DISPATCH_PUSH_COOLDOWN_MINUTES`
  / `TALONX_DISPATCH_RETRIGGER_PRICE_DELTA_PCT` /
  `TALONX_DISPATCH_MIN_CONFIDENCE` (see [modules/dispatch.md](modules/dispatch.md)).
- The ticker watchlist's `TALONX_WATCHLIST_DB` /
  `TALONX_WATCHLIST_DEFAULT_SYMBOL` / `TALONX_WATCHLIST_DEFAULT_NAME` /
  `TALONX_WATCHLIST_DEFAULT_EXCHANGE` / `TALONX_WATCHLIST_POLL_INTERVAL`.
- Module 6's `TALONX_PAPER_DB` / `TALONX_PAPER_INITIAL_BALANCE` /
  `TALONX_PAPER_TRADE_ALLOCATION` -- fresh-install defaults only, since
  the dashboard's Settings panel is the actual live source of truth once
  a portfolio has been created -- plus the automated End-of-Day flatten
  sweep's `TALONX_PAPER_EOD_FLATTEN_ENABLED` / `_HOUR_ET` / `_MINUTE_ET`
  (see [modules/paper.md](modules/paper.md)).

`.env.example`'s "Phase 2" block covers everything specific to the
`LONG_TERM` horizon (see [phase2-multi-horizon.md](phase2-multi-horizon.md))
-- fundamental factor thresholds (`TALONX_QUANT_ROIC_THRESHOLD` /
`TALONX_QUANT_F_SCORE_THRESHOLD`), the long-term decision matrix
(`TALONX_CORE_LT_*`), the long-term cache TTL
(`TALONX_BRAIN_CACHE_BASE_TTL_LONG_TERM`), and the DCA-aware paper ledger
(`TALONX_PAPER_LT_*` / `TALONX_PAPER_DCA_*` / `TALONX_PAPER_REBALANCE_TRIM_PCT`)
-- none of it required; a fresh install with no `LONG_TERM`-tagged
tickers ignores all of it.
