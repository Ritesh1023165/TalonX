# Task 66B-PREP Part 1 — Full application runtime graph

Traced directly from [run_talonx.py](../../run_talonx.py)'s `main()` as it exists at this task's
starting SHA, not from docs. Machine-readable form: `full_app_runtime_manifest.json`
(also `talonx_ops/runtime_manifest.py`, importable).

## Top-level data flow

```
watchlist (talonx_watchlist, SQLite, dashboard-editable)
        |
        +--> market-data provider selection (Polygon WS if POLYGON_API_KEY, else yfinance polling)
        |         + long_term_price_poll (LONG_TERM-only tickers, daily cadence)
        |         + earnings_fast_track (8-K/10-Q + extended-hours quote, earnings-window tickers)
        |         + premarket_poller (04:00-09:30 ET, whole watchlist, DST-aware)
        |
        +--> quant_preseed_initial (Task 66B-PREP: run_initial_preseed(), AWAITED before any
        |         task exists -- causal, not a task itself)
        |
        +--> QuantScanner.run() (quant_scanner task) + FundamentalScanner.run() (fundamental_scanner task)
        |         + quant_preseed_reactive (WatchlistDrivenQuantPreseed -- newly added/resumed tickers only,
        |           after Task 66B-PREP moved the initial pass ahead of task creation)
        |
        +--> ResearchAgent.run() (research_agent task) -- Gemini or Ollama, ChromaDB retrieval
        |         Degrades to fully disabled if the LLM provider isn't ready (production philosophy,
        |         UNCHANGED here) -- but talonx_ops.preflight's brain_operational_hard_requirement
        |         check refuses FULL_APP_E2E_READY if that happens, specifically for E2E validation.
        |
        +--> DecisionEngine.run() (decision_engine task) -- correlates Quant + Brain per ticker
        |
        +--> DispatchAgent.run() (dispatch_agent task)
        |         + telegram_reply_listener (started INSIDE DispatchAgent.run(), only if
        |           telegram_client.is_configured -- already wired with a REAL dispatch_agent,
        |           not the dispatch_agent=None degrade path talonx_piv needs. No restoration work
        |           needed here, unlike PIV in Task 66A -- verified, not built, in this task.)
        |
        +--> PaperTradingEngine.run() / LongTermPaperEngine.run() -- LOCAL simulated ledger (SQLite),
        |         never Alpaca. See talonx_ops.provider_status.paper_execution_path_label().
        |
        +--> periodic_ingestion / periodic_long_term_financials / periodic_earnings_calendar_sync /
        |     reactive_ingestion / reconcile_long_term_factors -- SEC filings/news/financials,
        |     independent of the live-decision path above
        |
        +--> periodic_wal_checkpoint -- pure maintenance, always runs if anything else does

(offline, run separately after EOD)
        |
        +--> generate_eod_report.py -- reads every module's own SQLite store for one calendar day
```

## What differs from PIV (talonx_piv), explicitly

| Aspect | Normal application (run_talonx.py) | PIV (talonx_piv) |
|---|---|---|
| Market-data provider | Polygon WebSocket (if configured) or yfinance polling | Alpaca IEX/SIP REST, feed-mode-pinned |
| Broker/paper execution | `talonx_paper` — local simulated ledger (SQLite), never a broker | Alpaca's real PAPER broker endpoint (real paper-mode orders) |
| Brain/Core/Dispatch | All three participate; Brain degrades gracefully in production | None of the three exist in PIV's decision path — `talonx_piv.decision_engine` drives `QuantScanner` directly |
| Readiness/staleness architecture | No formal per-symbol-session readiness gate; live accumulation only, best-effort | `SessionReadinessValidator`, restart-safe persisted state, explicit staleness detector |
| Reconciliation architecture | None of PIV's kind — no broker to reconcile a local ledger against | `talonx_piv.lifecycle` reconciles internal vs Alpaca broker state |

These are **not merged** by this task — Task 66B-PREP hardens the normal application's own startup
determinism and observability; it does not make the two runtimes converge. `talonx_ops/comparator.py`
exists to report where evidence from both sides agrees or is missing, never to force parity.

## Explicitly out of scope (not omitted, never part of either runtime's purpose)

- `talonx_dispatch/app.py` (Streamlit dashboard) — separate process, run alongside, never inside this
  asyncio loop (see its own module docstring).
- `talonx_backtest` — offline research tooling, not a live runtime component.

## Startup ordering (Task 66B-PREP Part 2 change)

Before this task, `WatchlistDrivenQuantPreseed`'s own initial preseed pass ran as an `asyncio.create_task()`
in the exact same batch as `market_data_runner`'s task and `quant_scanner.run()`'s own task — all
scheduled with no ordering guarantee against preseed's real yfinance network I/O. A live tick could
reach `QuantScanner._handle_message` before its buffers were hydrated, purely by scheduling luck.

`talonx_quant/preseed_ordering.py::run_initial_preseed()` is now **awaited directly in `main()`**,
before any task is created. `WatchlistDrivenQuantPreseed` accepts `already_preseeded_symbols` so its
own initial pass doesn't repeat that work — its reactive loop for later additions is unchanged. See
`tests/test_task66b_prep_preseed_ordering.py` for the behavioral proof (causal ordering, partial
failure isolation, zero-ready non-fatal, no double-preseed, reactive preseed preserved).
