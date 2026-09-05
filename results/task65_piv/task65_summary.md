# Task 65 / 65B — Paper PIV: Feed Mode, Decision Path, Warmup, Crash Resilience

Branch: `research/talonx-strategy-validation`. Final approved SHA: `b935588b69967081eebacb8f9ae8d3685ae1e578`.

## What today validated

Starting point: Task 64 had built the safety harness (preflight, order lifecycle, reconciliation, Telegram) but `cli.py start` only flipped a flag -- nothing ever drove it from real market data. Today built and live-validated the missing pieces, in order:

1. **Explicit `IEX_PAPER_PIV` feed mode** -- pinned per-request, no fallback between SIP/IEX in either direction, classified operational-only vs. canonical-alpha-evidence.
2. **Live session runner** -- polls Alpaca's batched multi-symbol REST bars endpoint, drives `SessionReadinessValidator`.
3. **Real strategy decision path** -- `talonx_piv/decision_engine.py` drives the actual, unmodified `talonx_quant.consumer.QuantScanner` in-process (its real ingestion entrypoint, its real throttle flush, its real gating -- confluence/RR/trend/cooldown -- all reused, none reimplemented), observed via a real Redis subscription to its own signal channel. ORPB_V1 was deliberately never used (rejected/retired at Task 63P; using it live would be a forbidden replay).
4. **PIV_LIFECYCLE_PROBE** -- an isolated, disabled-by-default, explicitly-confirmed fallback with a predeclared 15:00 ET cutoff, guaranteeing full order-lifecycle coverage even on a zero-natural-signal day.
5. **Warmup fix (WARMUP_DEFECT_FOUND -> fixed)** -- traced the actual runtime path and found `QuantScanner` started completely cold: `compute_indicators()` needs 120 1-minute bars, and the HTF trend gate drops every regular-session bullish candidate while `htf_sma_200` is None -- which, with zero pre-roll, could never become available within a single live day. Fixed by reusing `QuantScanner.preseed_symbols()` (unmodified, the same mechanism `run_talonx.py` already uses) before any live bar is consumed, with independent per-symbol verification (not "preseed returned" alone) and fail-closed exclusion of any symbol that can't be sufficiently hydrated.
6. **Crash-resilience fix** -- found live: an unhandled `requests.exceptions.ReadTimeout` from the Alpaca REST poll crashed the entire multi-hour session ~34 minutes in. Fixed by wrapping each tick in try/except inside the loop; a transient failure is now logged and skipped, not fatal.

## What actually happened live, 2026-08-24

**Run 1** (commit `fbc0a0d`, ~09:31-10:33 ET): started cleanly, preflight `PIV_READY`, warmup completed, readiness finalized at 10:00 ET with 21/35 symbols READY (14/35 genuine IEX opening-minute gaps -- real data-quality evidence, correctly detected, nothing synthesized). Crashed at 10:33:58 ET on an unhandled network timeout. Zero orders/positions were open at the time of the crash (verified against the live account).

**Fix applied and verified** (commit `b935588`): 75 focused PIV tests + full regression suite (1958 passed, 1 known pre-existing failure) confirmed clean before restart.

**Run 2** (commit `b935588`, ~14:41-15:50 ET, ran to completion): preflight reconfirmed `PIV_READY`, warmup reached **35/35 symbols ready**. Session-readiness state does not persist across a process restart (`SessionReadinessValidator` is in-memory only) -- restarting after 10:00 ET meant this run's own readiness check found 0/35 READY, so the natural strategy path never reached a readiness-eligible symbol this run, despite full warmup and an active decision engine. At the predeclared 15:00 ET cutoff, with no natural `STRATEGY`-sourced order observed, the `PIV_LIFECYCLE_PROBE` fired exactly as designed: AAPL buy filled @311.47, held ~60s, sold filled @311.40, both round-trips through the real PAPER broker with full telemetry. EOD ran clean: `matched=true`, zero residual orders/positions.

## Classification

- **PIV classification: `PARITY_OK`** -- the currently-approved checkpoint (`b935588`) ran a complete, clean live session end-to-end with full order-lifecycle coverage and clean reconciliation. The run-1 defect was found, root-caused, fixed, tested, and re-validated live within the same session -- not an open/unresolved issue.
- **Infrastructure conclusion: `V1_PIV_OPERATIONALLY_VALIDATED`**, with one explicit, load-bearing caveat: **the natural strategy decision-to-order handoff was never exercised against a readiness-eligible symbol in live conditions today.** That specific link is verified via focused/integration tests (18 Part-E scenarios) and standalone smoke tests against real `QuantScanner`/real yfinance data, but not as one continuous live run reaching an actual signal. This is the single most important gap for the next PIV session to close -- see `claude_handoff_next.md`.
- **Known limitation discovered (not blocking, tracked for follow-up):** `SessionReadinessValidator` state is in-memory only; a mid-session restart loses it. Recommended fix: persist readiness state to disk the same way `lifecycle_state.json` already is, or restrict restarts to before 10:00 ET.

## Safety

Real-capital execution remains structurally unsupported (no live broker adapter exists; every guard from Task 64 -- paper endpoint pin, identity verification, duplicate protection, kill switch -- ran unmodified all day). ORPB_V1 and FPRC_V1 remain rejected and retired; both fingerprints reconfirmed unchanged (`b1e283bd36eb0cb2ecc5303b104ec2bd8defc60f6eacef4879e7711d560d113f`, `be91c38047cf9aa9dbb6c8a948eaf52dd64ed4b16c7d8a70359388b58e5c2a64`). Zero diff on every protected `talonx_quant` file across the entire day. **Alpha remains UNPROVEN** -- every event today, natural-path or probe, is tagged `alpha_evidence=false`; today produced zero alpha evidence by design.

## Next major task

Broad development-only alpha discovery (see `next_alpha_discovery_plan.md`) -- not executed today, per instruction. Before the next PIV session: fix the readiness-persistence gap so a restart doesn't structurally block natural-signal evaluation for the rest of that session.
