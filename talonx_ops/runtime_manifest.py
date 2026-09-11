"""Task 66B-PREP Part 1: machine-readable runtime graph for the NORMAL
run_talonx.py application, traced directly from run_talonx.py's main()
(not from docs) as of this task. Mirrors the pattern talonx_piv/
runtime_manifest.py already established for the PIV harness -- a static,
hand-verified table, not introspection -- but describes a different
system and is not compared against PIV's manifest here (that's the
comparator's job, talonx_ops/comparator.py, and only where real evidence
from both sides exists).

Each entry's `asyncio_task_name` matches the `name=` argument
run_talonx.py's own asyncio.create_task() calls use, so a running
process's task list (or its logs, which include the task name on most
lines) can be checked directly against this table.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RuntimeComponent:
    name: str
    module: str
    asyncio_task_name: str | None
    skip_flag: str | None
    degrade_behavior: str
    notes: str

    def to_dict(self) -> dict:
        return asdict(self)


FULL_APP_RUNTIME_COMPONENTS: tuple[RuntimeComponent, ...] = (
    RuntimeComponent(
        "market_data_stream", "talonx_ingest.market_data.manager.MarketDataManager", "market_data",
        "--skip-market-data",
        "Polygon WebSocket if POLYGON_API_KEY set, else yfinance polling -- automatic fallback "
        "on auth failure/exhausted reconnects, never fatal.",
        "See talonx_ops.provider_status.configured_market_data_provider() for which one is configured.",
    ),
    RuntimeComponent(
        "long_term_price_poll", "run_talonx.LongTermPriceRunner (wraps YFinancePoller)", "long_term_price_poll",
        "--skip-market-data",
        "Started alongside market_data_stream; daily-cadence yfinance poll for LONG_TERM-only tickers.",
        "Excludes DUAL_HORIZON tickers (already covered by market_data_stream) and any ticker "
        "currently owned by earnings_fast_track.",
    ),
    RuntimeComponent(
        "earnings_fast_track", "run_talonx.EarningsFastTrackPoller", "earnings_fast_track",
        "--skip-earnings-fast-track",
        "Best-effort per-ticker; one bad ticker/poll cycle logged and skipped, never fatal.",
        "8-K/10-Q fast-track ingestion + extended-hours quote for tickers in their earnings window.",
    ),
    RuntimeComponent(
        "premarket_poller", "run_talonx.PreMarketPoller", "premarket_poller",
        "--skip-premarket",
        "Only active 04:00-09:30 America/New_York (DST-aware); idle outside that window, never fatal.",
        "Vectorized full-watchlist yfinance quote poll -- feeds the same talonx:market:stream channel.",
    ),
    RuntimeComponent(
        "quant_preseed_initial", "talonx_quant.preseed_ordering.run_initial_preseed", None,
        "--skip-quant",
        "Awaited directly in main(), not a task -- zero-ready is reported, never fatal to startup.",
        "Task 66B-PREP addition: causal, awaited BEFORE market_data_stream/quant_scanner tasks exist.",
    ),
    RuntimeComponent(
        "quant_scanner", "talonx_quant.consumer.QuantScanner", "quant_scanner",
        "--skip-quant",
        "No optional-dependency degrade -- always runs unless explicitly skipped.",
        "Real technical strategy engine (evaluate_signals()) -- same class talonx_piv drives directly.",
    ),
    RuntimeComponent(
        "fundamental_scanner", "talonx_quant.fundamental_consumer.FundamentalScanner", "fundamental_scanner",
        "--skip-quant",
        "Sibling to quant_scanner; same skip flag, no independent degrade.",
        "LONG_TERM/DUAL_HORIZON fundamental-factor scanner -- separate cooldown/throttle semantics.",
    ),
    RuntimeComponent(
        "quant_preseed_reactive", "run_talonx.WatchlistDrivenQuantPreseed", "quant_preseed",
        "--skip-quant",
        "Best-effort per newly-added/resumed ticker; fail-closed per symbol via preseed_symbols().",
        "Reactive-only after startup (Task 66B-PREP moved the initial pass ahead of task creation).",
    ),
    RuntimeComponent(
        "research_agent", "talonx_brain.consumer.ResearchAgent", "research_agent",
        "--skip-brain",
        "Degrades to fully disabled (ImportError/ValueError caught in main()) if the configured LLM "
        "provider isn't ready -- pipeline runs normally without it. NOT acceptable for tomorrow's "
        "E2E validation -- see talonx_ops.preflight's hard brain_operational check.",
        "Gemini or Ollama, per TALONX_BRAIN_LLM_PROVIDER.",
    ),
    RuntimeComponent(
        "decision_engine", "talonx_core.consumer.DecisionEngine", "decision_engine",
        "--skip-core",
        "No optional-dependency degrade -- always runs unless explicitly skipped.",
        "Correlates QuantSignals + ResearchReports per ticker into ActionableAlerts.",
    ),
    RuntimeComponent(
        "dispatch_agent", "talonx_dispatch.consumer.DispatchAgent", "dispatch_agent",
        "--skip-dispatch",
        "Degrades to fully disabled if its audit DB can't be opened (rare).",
        "Records ActionableAlerts to SQLite audit trail; pushes to Telegram if configured.",
    ),
    RuntimeComponent(
        "telegram_reply_listener", "talonx_dispatch.telegram_listener.TelegramReplyListener", "telegram_reply_listener",
        "--skip-dispatch",
        "Started by DispatchAgent.run() only if telegram_client.is_configured; otherwise simply absent "
        "(not a separate degrade path) -- Telegram itself is optional.",
        "Already constructed WITH a real dispatch_agent (not the dispatch_agent=None degrade path "
        "talonx_piv needs) -- /ping reports real uptime/CPU/RAM/pipeline-funnel metrics. No restoration "
        "work was needed here, unlike PIV in Task 66A -- this was verified, not built, in this task.",
    ),
    RuntimeComponent(
        "paper_trading_engine", "talonx_paper.consumer.PaperTradingEngine", "paper_trading_engine",
        "--skip-paper-trading",
        "Whole talonx_paper block (both engines) degrades to disabled if its shared store can't open.",
        "Local simulated ledger (SQLite) -- never Alpaca. See talonx_ops.provider_status.",
    ),
    RuntimeComponent(
        "long_term_paper_engine", "talonx_paper.consumer.LongTermPaperEngine", "long_term_paper_engine",
        "--skip-long-term-paper",
        "Same shared-store degrade as paper_trading_engine.",
        "DCA + rebalance loop for LONG_TERM/DUAL_HORIZON tickers.",
    ),
    RuntimeComponent(
        "periodic_ingestion", "run_talonx.periodic_ingestion_loop", "periodic_ingestion",
        "--skip-ingestion",
        "One bad cycle logged and skipped, loop continues.",
        "SEC filing + news ingestion, immediate on startup then every --interval-hours.",
    ),
    RuntimeComponent(
        "periodic_long_term_financials", "run_talonx.periodic_long_term_financials_loop", "periodic_long_term_financials",
        "--skip-ingestion",
        "One bad cycle logged and skipped, loop continues.",
        "SEC XBRL structured financials for LONG_TERM/DUAL_HORIZON tickers.",
    ),
    RuntimeComponent(
        "periodic_earnings_calendar_sync", "run_talonx.periodic_earnings_calendar_sync_loop",
        "periodic_earnings_calendar_sync", "--skip-earnings-sync",
        "Per-ticker fetch failure skipped, cycle continues.",
        "Weekly (interval_hours from process start, not wall-clock) earnings-date sync.",
    ),
    RuntimeComponent(
        "reactive_ingestion", "run_talonx.WatchlistDrivenIngestion", "reactive_ingestion",
        "--skip-ingestion",
        "Per-ticker failure logged, ticker still marked known (relies on periodic loop as retry).",
        "Immediate filing/news/financials ingestion for newly added/resumed/re-tagged tickers.",
    ),
    RuntimeComponent(
        "reconcile_long_term_factors", "run_talonx.reconcile_missing_long_term_factors",
        "reconcile_long_term_factors", "--skip-ingestion (also requires quant_store)",
        "Best-effort, self-healing on next restart if it also fails.",
        "One-shot startup fix for a confirmed lost-event race (NewFundamentalsIngestedEvent).",
    ),
    RuntimeComponent(
        "periodic_wal_checkpoint", "run_talonx.periodic_wal_checkpoint_loop", "periodic_wal_checkpoint",
        None,
        "Per-store checkpoint failure logged, loop continues -- always runs if any other task does.",
        "Pure maintenance (SQLite WAL checkpoint); no functional effect on the pipeline.",
    ),
)

# Explicitly out of PIV/full-app parity scope, by design -- not omitted,
# never part of either runtime's purpose:
OUT_OF_SCOPE_COMPONENTS: tuple[str, ...] = (
    "talonx_dispatch/app.py (Streamlit dashboard -- separate process, run alongside, never "
    "inside this asyncio loop; see its own module docstring)",
    "talonx_backtest (offline research tooling, not a live runtime component)",
)


def runtime_graph_stages() -> tuple[str, ...]:
    """Ordered top-level data-flow stages, for the human-readable
    full_app_runtime_graph.md -- not a 1:1 mapping to asyncio tasks (several
    tasks feed the same stage, e.g. every ingestion-related task feeds
    "ingestion")."""
    return (
        "market-data provider (Polygon WS or yfinance) + pre-market/long-term pollers",
        "quant preseed (initial, causal) -> talonx_quant.QuantScanner + FundamentalScanner",
        "talonx_brain.ResearchAgent (Gemini/Ollama + ChromaDB retrieval)",
        "talonx_core.DecisionEngine (correlates Quant + Brain per ticker)",
        "talonx_dispatch.DispatchAgent (audit trail + Telegram outbound/inbound)",
        "talonx_paper.PaperTradingEngine / LongTermPaperEngine (local simulated ledger)",
        "generate_eod_report.py (offline, run separately after EOD)",
    )
