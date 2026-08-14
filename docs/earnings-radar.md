# Event-Driven Earnings Radar (`LONG_TERM`/`DUAL_HORIZON` tickers)

Moves LONG_TERM evaluation from "quarterly-cadence factor scoring only"
to an active earnings lifecycle:

```
Weekly Calendar Sync -> T-48h Heads-Up Push -> Fast-Track 8-K/10-Q Ingestion
    -> Two-Stage Valuation Recalculation -> Post-Earnings Push
```

```
talonx_watchlist.upcoming_earnings (one row per LONG_TERM/DUAL_HORIZON ticker)
    <- weekly (run_talonx.periodic_earnings_calendar_sync_loop, default
       every 168h from process start -- NOT anchored to actual wall-clock
       Sunday-00:00-UTC, this codebase has no day-of-week scheduling
       precedent anywhere) calls talonx_ingest.earnings.fetch_earnings_calendar
       (yfinance's undocumented .calendar property) for every ticker
    -> talonx_dispatch.DispatchAgent's _earnings_heads_up_loop (daily)
       sends a T-48h "reporting soon" push, UNCONDITIONALLY (bypasses
       every dispatch suppression gate -- severity, cooldown, eligibility
       -- same "always send" precedent trade-execution pushes already
       establish), sourced from an in-memory latest-signal/report cache
       DispatchAgent keeps by ALSO subscribing to talonx:signals:fundamental
       and talonx:reports:longterm (NOT the audit trail -- see below for why)
    -> on the earnings date, run_talonx.EarningsFastTrackPoller (every 15
       min, default) fetches 8-K/10-Q for tickers currently in a flat
       2-calendar-day window around the known date (session-aware
       Before/After-Market windowing is skipped -- yfinance's session
       data isn't reliable enough to window precisely against), and
       captures an extended-hours price quote (yfinance's
       history(prepost=True), unlike the regular batch poll's fast_info)
    -> talonx_ingest.pipeline.ingest_earnings_filing fetches the body of
       each new 8-K and text-scans it for the literal string "Item 2.02"
       before treating it as the earnings release (a 10-Q always counts;
       an 8-K that doesn't match is still ingested for RAG context, just
       not flagged) -- publishes NewFilingIngestedEvent with
       is_earnings_related=True only for confirmed filings
    -> talonx_quant.fundamental_consumer.FundamentalScanner's Stage 1:
       on a confirmed 8-K, republishes a FundamentalFactorSignal from
       PERSISTED factors (talonx_quant/store.py's
       latest_fundamental_factors table -- real XBRL numbers aren't in
       an 8-K), is_earnings_related=True, bypassing its OWN 7-day
       standard cooldown via a separate short-TTL
       earnings_republish_cooldown:{TICKER} key
    -> once the 10-Q lands (Stage 2), the EXISTING NewFundamentalsIngestedEvent
       path re-scores ROIC/F-Score/FCF-Yield for real, also flagged
       is_earnings_related=True
    -> talonx_brain.consumer's long-term generation: retrieves
       ["10-K","10-Q","8-K"] (not just "10-K") when the triggering
       signal is earnings-related, and skips its own fresh-cache-hit
       shortcut so a same-day re-read is never served a stale cached
       report; the LLM is also asked (only when relevant) for
       guidance_revision_notes/revenue_eps_surprise
    -> talonx_core.decision's long-term matrix bypasses its own 30-day
       cooldown AND price-delta no-state-change gate when either input
       is earnings-related, and captures previous_fair_value (from the
       correlator's state, the moment the new report overwrites the old
       one -- same timing previous_moat_rating already uses) for the
       "before vs after" push
    -> talonx_dispatch sends a DISTINCT post-earnings push format
       (format_telegram_post_earnings_alert -- old vs. new fair value,
       fundamental shift, guidance revision), bypassing BOTH the
       severity gate and Smart Dispatch Filtering's push-eligibility
       check for this one alert
```

## Key design decisions

- **`is_earnings_related` propagates end-to-end from the SOURCE ingestion
  call** (`ingest_earnings_filing`/`run_long_term_financials_ingestion`),
  not re-derived downstream at each stage -- every cooldown-bypass check
  along the pipeline (`talonx_quant`, `talonx_core`, `talonx_dispatch`)
  just reads this one flag rather than each independently re-checking
  "is this ticker in its earnings window."
- **Two-stage recalculation, not one.** An 8-K's press release text
  arrives fast but has no real XBRL numbers; the 10-Q has the numbers but
  arrives days later. Stage 1 lets `talonx_brain` re-read the fresh
  filing text immediately (reusing the LAST real ROIC/F-Score); Stage 2
  re-scores for real once the 10-Q lands. Up to two Telegram pushes per
  earnings cycle is expected behavior, not a duplicate-alert bug. A
  ticker's FIRST-EVER earnings cycle since being tagged `LONG_TERM` (no
  persisted factors yet) correctly produces only the Stage 2 push.
- **`FundamentalScanner`'s ROIC-vs-WACC streak dedupes on fiscal year,
  not event count** (`LongTermTickerState.last_streak_fiscal_year`) --
  without this, a Stage 1 republish reusing the same cached ROIC would
  double-count one real data point toward the 2-consecutive-quarter
  fundamental-stop trigger, a false `UNDER_PERFORM_REBALANCE` risk.
  **Restart-survival fix**: `last_streak_fiscal_year` (and
  `previous_fair_value`, captured at the same moment for the post-
  earnings "before vs after" push) were captured on `LongTermTickerState`
  alongside `roic_below_wacc_streak`/`previous_moat_rating`, but
  `talonx_core/store.py` originally only persisted the latter two --
  `save_long_term_fundamental_stop_state`/`load_into_long_term` now
  persist and rehydrate all four, so a restart between two
  same-fiscal-year signal arrivals can no longer silently defeat the
  dedupe guard.
- **The T-48h heads-up push's data source is a live in-memory cache, not
  the audit trail.** `talonx_dispatch`'s own `long_term_alerts` table
  only gets a row once a ticker clears the FULL decision matrix and
  produces an alert -- a ticker whose fundamentals never clear
  `FundamentalScanner`'s threshold would have zero rows there forever,
  not just on day one. Subscribing directly to the signal/report
  channels instead means the heads-up push has data the moment ANY
  signal or report exists for a ticker. **Restart-survival fix**: this
  cache (and Smart Dispatch Filtering's separate per-ticker push-cooldown
  cache) used to reset to empty on every `DispatchAgent` restart, with no
  persisted backing and no replay source (Redis Pub/Sub delivers only
  messages published after a fresh subscribe) -- a restart during a
  ticker's heads-up window could permanently lose that cycle's push, and
  a restart mid-cooldown let the very next alert bypass whatever cooldown
  should still have been active. Both are now persisted to
  `dispatch_audit.db` (`latest_earnings_context`, `last_telegram_push`)
  and reloaded at startup via `DispatchAgent._load_restart_survival_caches`.
- **`LongTermPriceRunner` excludes any ticker `EarningsFastTrackPoller`
  currently owns** (`active_earnings_symbols_fn`), the same "avoid
  double-publishing ticks for the same symbol" reasoning it already
  applies to `DUAL_HORIZON` tickers -- otherwise Redis pub/sub's
  unordered delivery between two independent producers could let a
  regular-session tick silently overwrite the post-earnings
  extended-hours price this whole feature exists to capture.

**Not built this pass:** true session-aware (Before/After-Market)
fast-track windowing (yfinance doesn't reliably expose this, so a flat
2-day window is used instead), and real wall-clock-anchored weekly
scheduling (an interval-since-process-start is used instead, matching
every other periodic loop in this codebase).

See also: [phase2-multi-horizon.md](phase2-multi-horizon.md),
[premarket-radar.md](premarket-radar.md).
