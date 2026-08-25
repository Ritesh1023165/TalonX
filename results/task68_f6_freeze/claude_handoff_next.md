# Handoff — Task 68A Complete

Read this before doing anything else; no prior chat history needed.

## State

- **Research branch**: `research/talonx-alpha-phenomenon-discovery` at `c:\workspace\TalonX-alpha-phenomenon-discovery`, pushed to origin.
- **Canonical runtime branch**: `research/talonx-strategy-validation` at `c:\workspace\TalonX`, HEAD `d9749f3813d2c5495109b470df616faceb127ffc` — untouched.
- **Alpha status**: UNPROVEN.

## What exists now

`F6_FADE_V1` — one exact, frozen, causal trade rule derived from Task 67B's Family 6 discovery. Spec: `results/task68_f6_freeze/f6_fade_v1_spec.json`/`.md`. Fingerprint: `f6_fade_v1_fingerprint.json` (`6beb8eebe50053aae27cab90226534b5d4392c46bd6e9c094873f7ad37466084`). Implementation: `research/task68_f6/{strategy,evaluator,fingerprint}.py`, isolated research code. 20/20 focused tests, 144/144 combined with the Task 67 suite.

**The rule in one line**: fade strong (top-tertile, |return| ≥ 1.339%) 13:30–14:00 UTC opening moves, decide at 14:00 UTC, enter next bar's open, exit 60m later (capped at RTH close), no stop, 1 trade/symbol/session.

**Development-only verification** (`development_implementation_verification.json`) proves the code is correct — 735 trades, matches Task 67B's screening count, deterministic, gross direction matches discovery. It is NOT a validation result and must not be read as one; net return at 10bps is slightly negative, exactly as expected from Task 67B's own "thin vs. friction" finding.

## Data discipline — unchanged from Task 67A/67B

VALIDATION (2026-08-25→2026-09-22) and REPLICATION (2026-09-23→2026-10-21) remain unmaterialized, enforced by `research/task67a_lib/data_guard.py`. **Do not materialize VALIDATION before 2026-09-23** (the whole range must have actually traded). Do not materialize REPLICATION before VALIDATION returns `VALIDATION_PASS`.

## Exact next task: Task 69 — one-shot validation

Everything Task 69 needs is pre-registered in `results/task68_f6_freeze/validation_protocol.json`/`.md`: exact input contract, exact output contract, and — critically — an 8-criterion `VALIDATION_PASS`/`VALIDATION_FAIL`/`VALIDATION_INCONCLUSIVE` decision rule fixed BEFORE any validation data exists. **Task 69 must not loosen these criteria after seeing results.** It must verify the strategy fingerprint above matches before running anything.

## What Task 68A deliberately did NOT do

No validation run, no replication, no inspection of any post-DEVELOPMENT price data, no production/runtime code touched, no live/paper session started, no parameter sweep or retuning of the frozen rule (the one apparent "surprise" — net return slightly negative at 10bps on DEVELOPMENT — was left exactly as computed, not massaged).

## Today's priority

The full end-to-end PAPER live application session takes priority over any further research. Do not let Task 69 or anything else delay it. Task 69 should only run once the VALIDATION window has actually elapsed (on/after 2026-09-23), well after today.
