# Task 78I — Implementation Plan

## Stage 2 — `talonx_piv/supervisor.py`
A new module wrapping the EXISTING `SessionRunner`/`DecisionEngine`/`PaperLifecycle`/ownership/
preflight machinery — no duplicate consumer, no second execution writer. Startup sequence
(matches the task's own required order exactly): (1) verify configuration (`PivConfig` +
`Preflight`), (2) verify no duplicate PIV/full-app process (reuse
`talonx_ops.preflight.no_duplicate_full_app_or_piv_process`'s pattern), (3) `acquire_execution_
ownership`, (4) `PaperLifecycle.reconcile()` (establishes/reconciles account+order state, resolves
any `UNCONFIRMED_TIMEOUT`), (5) data readiness (`SessionReadinessValidator`, unchanged), (6)
strategy approval + PAPER settings confirmation (read-only report — this task invents no
approval). One `SessionIdentity` (session_id/trading_date_et/runtime_sha/config_hash) used
throughout; a SEPARATE `invocation_id` (one per process start, distinct from the trading
session_id) is added for restart/heartbeat bookkeeping. Component health classified
required/optional (matching `talonx_ops/runtime_manifest.py`'s existing schema shape). Bounded
restart/backoff reuses `talonx_brain`'s own `jittered_backoff_seconds` helper rather than
reinventing jitter math.

## Stage 3 — `talonx_piv/gemini_enrichment.py`
Wraps `talonx_brain.llm`'s `_BaseResearchChain` DI interface (reused, not reimplemented) behind a
decision_id-keyed, durable, restart-safe outbox (same `_load`/`_save` JSON pattern as every other
Task 77I/78I ledger). Production wiring constructs the REAL chain; offline rehearsal injects a
fake one. Output fields are additive-only (explanation/sources/risks/status) — the adapter
explicitly STRIPS/ignores any field resembling an order/price/approval instruction in the
response before ever persisting it, and a dedicated test injects exactly such an attempted
override to prove it has zero effect.

## Stage 4 — one additive `aiohttp` route on `dashboard_web.py`
Per the Stage 0 research: `dashboard_web.py` is a real `aiohttp` server (default `localhost:8787`,
loopback only). A new `GET /piv/status` route returns `observability.build_integrated_projection`
(already read-only, already reconciling) — no change to the existing `/`, `/static/*`, `/ws`
routes or their rendering.

## Stage 5 — rehearsal
Drives the real `supervisor.py` with fakes/isolated storage/a fake clock throughout, executing the
20 required scenarios, each independently reported (trigger/expected/observed/evidence/verdict/
limitation).
