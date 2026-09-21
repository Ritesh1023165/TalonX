# Task 78I — Integration Completion, Application Orchestration and Offline Recovery Rehearsal

## Stage 0 — Baseline and actual architecture: COMPLETE
Verified branch/SHA/clean-tree/origin-sync at `6f6193f`; no conflicting session. Mapped the two
separate applications sharing this repository (the general `run_talonx.py` pipeline vs. the PIV
validation harness) and the confirmed, already-guarded double-evaluation risk between their two
independent `QuantScanner` instances. Selected the PIV-native path as authoritative. See
`architecture_and_ownership.md`.

## Stage 1 — Close remaining integration gaps: COMPLETE
A) Shadow independence audited (no correction needed — the implementation was already correctly
independent of `paper_entry_enabled`/broker/PAPER outcomes; proven with a byte-identical-outcome
test). B) Horizon-based shadow exits implemented, with a deliberately empty production policy
(no invented duration). C) Pure, recomputed status projections (`build_decision_status`),
`decision_id` threaded into `order_intent`. D) OS-level, crash-safe, account-scoped execution
ownership lock, enforced at the broker client's three mutating calls, proven with genuine
competing OS subprocesses. See `integration_gap_closure.md`.

## Stage 2 — Unified application supervisor: COMPLETE
New `talonx_piv/supervisor.py` + `cli.py supervise`: an ordered, fail-stop 5-step startup-safety
sequence, a required/optional component health registry, and a bounded restart/backoff wrapper
around the existing `SessionRunner.run()` (safe because `run()` already guarantees EOD-flattening
before returning/raising). See `supervisor_lifecycle_contract.md`.

## Stage 3 — Gemini as optional enrichment: COMPLETE
New `talonx_piv/gemini_enrichment.py`, wrapping `talonx_brain.llm`'s existing chain interface,
decision_id-keyed, additive-only (5 named informational fields, extracted by explicit `getattr`
calls). Proved zero effect from an injected action/price/approval response at both the outbox and
the real application-wiring level. See `gemini_authority_boundary.md`.

## Stage 4 — Existing dashboard and status integration: COMPLETE
One new, additive `GET /piv/status` route on the existing `dashboard_web.py` aiohttp server. Zero
change to existing routes; zero new mutating control. See `dashboard_reconciliation.json`.

## Stage 5 — Full offline failure/recovery rehearsal: COMPLETE
All 20 required scenarios PASSED, driving the real supervisor/decision/lifecycle/shadow/
notification/enrichment stack with isolated state, fake adapters, a fake clock, and blocked
external network access throughout — labelled `OFFLINE_APPLICATION_INTEGRATION_EVIDENCE`. One
genuine defect was discovered and fixed during this stage (see below). See
`rehearsal_scenarios.csv`.

## Discovered and fixed during Stage 5
`NotificationOutbox.dispatch_pending`'s retry-eligible status set did not include `UNCERTAIN` —
a notification left `UNCERTAIN` after an adapter exception was never retried on a later dispatch
call, silently stuck in limbo forever. Fixed (see `remaining_issues.md` item 4).

## Verification
Full collection: **2423 collected, 0 errors** (was 2327). Full suite: **2412 passed, 1 skipped,
10 xfailed** (was 2316 passed) — `2412 − 2316 = 96`, exactly matching the 96 new tests across 11
new test files. **Zero unexplained regression, zero failures.** See `test_results.txt`
(sha256 `83887d02c3c87262aafb002260e4e249a834660d0924eed35721b8e56398c631`).

Protected files (`talonx_quant/{strategy,indicators,consumer,config}.py`), `eod_lifecycle.py`, and
`talonx_brain/`: zero diff since `6f6193f`.

## Verdict
**READY_FOR_CONTROLLED_PAPER_REVIEW** — not permission to launch, approve a strategy, or enable
trading. See `controlled_paper_review_checklist.md`.

## Production defaults (unchanged posture, reconfirmed)
Strategy approval `UNVALIDATED` everywhere real; `paper_entry_settings.json` requires explicit
operator creation; no approval registry invented; no live session started; zero real
broker/Telegram/Gemini calls anywhere in this task's own verification.
