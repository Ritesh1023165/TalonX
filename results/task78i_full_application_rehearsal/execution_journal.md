# Task 78I — Execution Journal

## Baseline
- Branch: research/talonx-strategy-validation
- Starting SHA: 6f6193ff76fb4d459c1b1b95e7f284e23a38058e
- Working tree: clean at start, in sync with origin
- No conflicting session/process (talonx.pids.json absent, no python.exe processes running)
- `.venv/Scripts/python.exe` used throughout (same environment note as Task 77I)
- Full collection before this task: 2327 collected, 0 errors (matches Task 77I's end state)

## Stage 0 — COMPLETE
Architecture mapped via a research subagent (run_talonx.py, talonx_brain, dashboard/dispatch
surfaces) plus direct code review. Selected the PIV-native path as authoritative; confirmed and
reused the existing `talonx_ops/preflight.py::no_duplicate_full_app_or_piv_process` guard rather
than inventing a new one. See `architecture_and_ownership.md`.

## Stage 1 — COMPLETE
All four gaps closed:
- A. Shadow independence: audited (no correction needed), evidence produced.
- B. Horizon-based shadow exits: implemented in shadow_ledger.py, DEFAULT_HORIZON_POLICY empty
  by design (no invented duration).
- C. Status projections: `observability.py::build_decision_status`, pure/recomputed, decision_id
  threaded into `order_intent`.
- D. Execution ownership: `execution_ownership.py`, OS-level advisory file lock, enforced at
  `broker.py`'s three mutating calls, wired into `cli.py`.
- New tests: 42 (see stage_status.json for the exact file list). Full collection now 2369
  collected, 0 errors.
- See `integration_gap_closure.md` for the full write-up.

## Stage 2 — COMPLETE
New `talonx_piv/supervisor.py`: `ComponentHealthRegistry`, ordered `run_startup_sequence` (5
required steps, fail-stop), `run_with_bounded_restart` (crash-safe since `SessionRunner.run()`
already guarantees EOD before returning/raising), persisted recovery state and component health.
New `talonx_piv/cli.py supervise` subcommand (additive — `start` unchanged). Also added
`no_duplicate_full_app_or_piv_process` to `talonx_piv/preflight.py` itself (reusing the exact
check from `talonx_ops/preflight.py`) so PIV's own preflight independently guards against running
alongside `run_talonx.py`. 20 new tests. Full collection now 2385 collected, 0 errors.

## Stage 3 — COMPLETE
New `talonx_piv/gemini_enrichment.py`: decision_id-keyed, restart-safe outbox wrapping
`talonx_brain.llm`'s existing `_BaseResearchChain`/`build_research_chain` (reused, not
reimplemented). Additive-only extraction (5 named fields only); proved an injected action/price/
approval field in a fake response has zero effect, at both the outbox level and the real
DecisionEngine+SessionRunner application-wiring level. Wired into `decision_engine.py`
(`request()`, decoupled from the alert), `session_runner.py` (independent async
`dispatch_pending` tick step), `cli.py` (opt-in via `TALONX_PIV_GEMINI_ENABLED`, degrades to None
on any construction failure), `observability.py` (`gemini_status` in the decision projection,
`gemini_enrichment` counts in the integrated projection). 24 new tests. Full collection now 2399
collected, 0 errors.

## Stage 4 — COMPLETE
One new, additive GET `/piv/status` route on the EXISTING `dashboard_web.py` aiohttp server
(default `localhost:8787`, loopback only) — returns `observability.build_integrated_projection`
as JSON, computed fresh on every request, HTTP 500 with an explicit error body on a read failure.
Zero change to `/`, `/static/*`, `/ws`. 5 new tests via `aiohttp.test_utils.TestClient/TestServer`
(isolated, loopback, in-process). Full collection now 2404 collected, 0 errors.

## Stage 5 — COMPLETE
New `tests/test_task78i_stage5_rehearsal.py` -- all 20 required scenarios PASSED, driving the real
supervisor/decision/lifecycle/shadow/notification/enrichment stack with isolated state, fake
adapters, a fake clock, and blocked external network access throughout. Results recorded to
`rehearsal_scenarios.csv`. One genuine defect discovered and fixed during this stage:
`NotificationOutbox.dispatch_pending`'s retry-eligible status set did not include `UNCERTAIN`,
leaving a record permanently stuck after an adapter exception -- fixed in
`talonx_piv/notification_outbox.py`. Full repository suite re-run: 2412 passed, 1 skipped,
10 xfailed, 0 failures (was 2316 passed at this task's Stage 0 start) -- `2412-2316=96`, exactly
matching the 96 new tests added across all 5 stages. Full collection: 2423 collected, 0 errors.

## Commands used (representative, not exhaustive — see test files for full detail)
```
.venv/Scripts/python.exe -m pytest tests/test_task78i_*.py -q
.venv/Scripts/python.exe -m pytest --collect-only -q
```
