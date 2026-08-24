"""Task 66A Part 2 -- machine-readable manifest of the components a full
PAPER PIV session is expected to run, and which preflight check (if any)
covers each. Traced from the actual runtime entrypoints:

- `run_talonx.py` (the normal/full TalonX application) starts 6+ modules:
  market data ingest, QuantScanner, ResearchAgent (brain), DecisionEngine
  (core), DispatchAgent (Telegram outbound+inbound, audit trail), paper
  trading engine, plus watchlist-driven pre-seeding/ingestion reconcilers.
- The Task 65/65B PIV runtime (`talonx_piv.cli start`) is deliberately
  NARROWER by design -- it is a paper-only order-lifecycle harness driving
  the same QuantScanner, not the full research/decision/dispatch pipeline
  (talonx_brain/talonx_core/talonx_paper play no role in PIV; ActionableAlert
  correlation and mobile-push filtering are a downstream, non-PIV concern).
  What Task 65B omitted that IS in scope for a PIV session -- because it's
  operational health/observability, not alpha-adjacent -- was the inbound
  Telegram /ping command listener. That gap is closed in Task 66A (see
  telegram_inbound.py). Everything else `run_talonx.py` runs beyond that
  (brain/core/dispatch/paper's research-report and multi-signal-correlation
  machinery) remains intentionally out of scope for a PIV session; it is
  not "silently disabled," it was never part of the PIV harness's purpose.
"""

from __future__ import annotations

from dataclasses import dataclass

RUNTIME_COMPONENTS: tuple[str, ...] = (
    "market_data_provider",
    "warmup_preseed",
    "session_readiness_validator",
    "quant_scanner",
    "redis",
    "decision_engine",
    "paper_broker_lifecycle",
    "telegram_outbound",
    "telegram_inbound_command_listener",
    "health_metrics_status",
    "reconciliation",
    "kill_switch",
    "eod_handling",
)


@dataclass(frozen=True)
class ComponentCoverage:
    component: str
    present_in_piv_runtime: bool
    covered_by_preflight_check: str | None
    notes: str


# Preflight check names are literal cross-references into preflight.py's
# `check(...)` call sites -- kept in sync manually since preflight.py has
# no registry of its own to introspect; a mismatch would only mean this
# manifest's `covered_by_preflight_check` string goes stale, not a runtime
# safety issue (verified against preflight.py at Task 66A time).
COMPONENT_COVERAGE: tuple[ComponentCoverage, ...] = (
    ComponentCoverage(
        "market_data_provider", True, "market_data_feed_accessible",
        "Alpaca REST bars/latest, explicit feed_mode-pinned, no fallback.",
    ),
    ComponentCoverage(
        "warmup_preseed", True, "warmup_mechanism_capability",
        "QuantScanner.preseed_symbols() via yfinance, causal, fail-closed per symbol (Task 65B).",
    ),
    ComponentCoverage(
        "session_readiness_validator", True, None,
        "Always constructed by SessionRunner; restart-safe as of Task 66A Part 1 (session_readiness_state.json).",
    ),
    ComponentCoverage(
        "quant_scanner", True, "decision_path_mode",
        "Real, unmodified talonx_quant.consumer.QuantScanner, driven by decision_engine.py.",
    ),
    ComponentCoverage(
        "redis", True, "decision_path_mode",
        "Required when TALONX_PIV_DECISION_PATH is enabled; fail-closed if unreachable.",
    ),
    ComponentCoverage(
        "decision_engine", True, "decision_path_mode",
        "talonx_piv.decision_engine.DecisionEngine.",
    ),
    ComponentCoverage(
        "paper_broker_lifecycle", True, "paper_account_verified",
        "AlpacaPaperClient + PaperLifecycle, immutable paper endpoint.",
    ),
    ComponentCoverage(
        "telegram_outbound", True, "telegram_reachable",
        "Existing EventBus -> telegram.sender fan-out (Task 64).",
    ),
    ComponentCoverage(
        "telegram_inbound_command_listener", True, "telegram_inbound_capability",
        "Reuses talonx_dispatch.telegram_listener.TelegramReplyListener (dispatch_agent=None) -- "
        "restored in Task 66A; omitted in Task 65B. See telegram_inbound.py for the single-poller-per-token caveat.",
    ),
    ComponentCoverage(
        "health_metrics_status", True, "telegram_inbound_capability",
        "The /ping reply itself -- degraded (many fields 'unknown') without a full run_talonx.py "
        "DispatchAgent to source pipeline-stage metrics from, since PIV doesn't run brain/core/dispatch.",
    ),
    ComponentCoverage(
        "reconciliation", True, "internal_broker_reconciled",
        "PaperLifecycle.reconcile(), also run at EOD.",
    ),
    ComponentCoverage(
        "kill_switch", True, "kill_switch_available",
        "PaperLifecycle.activate_kill_switch(); SessionRunner.run() checks lifecycle.reload() every tick.",
    ),
    ComponentCoverage(
        "eod_handling", True, "eod_flatten_configured",
        "cli.py eod command; PaperLifecycle.eod_flatten().",
    ),
)


def runtime_parity_status() -> tuple[str, tuple[ComponentCoverage, ...]]:
    missing = tuple(c for c in COMPONENT_COVERAGE if not c.present_in_piv_runtime)
    status = "RUNTIME_PARITY_FAIL" if missing else "RUNTIME_PARITY_PASS"
    return status, COMPONENT_COVERAGE
