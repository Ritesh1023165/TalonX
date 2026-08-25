# Task 68A — F6_FADE_V1 Frozen

Converted Task 67B's Family 6 discovery into one exact, frozen, causal research rule: **F6_FADE_V1**, fingerprint `6beb8eebe50053aae27cab90226534b5d4392c46bd6e9c094873f7ad37466084`.

**Rule**: fade strong opening (13:30–14:00 UTC) moves, decided at 14:00 UTC, entered at the next bar's open, exited 60 minutes later (capped at RTH close), no stop, one trade per symbol/session. Full detail: `f6_fade_v1_spec.md`.

**Implementation**: `research/task68_f6/` — isolated research code, not wired into production. 20/20 new focused tests pass; 144/144 combined with the existing Task 67 suite.

**Development verification** (not a validation result): running the frozen evaluator on real DEVELOPMENT data (via `DataSplitGuard`) reproduces exactly Task 67B's 735-trade count, with a positive gross direction (consistent with the fade discovery) and a small negative net return at the frozen 10bps cost assumption — exactly consistent with Task 67B's own "POTENTIALLY_TRADEABLE but thin" classification. Nothing was retuned to change this.

**Validation protocol pre-registered** for Task 69, including an explicit, fixed-in-advance 8-criterion PASS bar and a FAIL/INCONCLUSIVE distinction — see `validation_protocol.md`. Replication is gated on VALIDATION_PASS.

**Holdout feasibility**: read-only audit (no F6 returns computed) confirms the already-reserved VALIDATION (2026-08-25→2026-09-22) and REPLICATION (2026-09-23→2026-10-21) windows are both genuinely unexposed and correctly sequenced.

**Not done, on purpose**: no validation run, no replication, no production/runtime changes, no live session start, no parameter sweep, no retuning.

Alpha status: **UNPROVEN**. Next: today's live PAPER session; Task 69 (one-shot validation) only after the VALIDATION window has actually traded.
