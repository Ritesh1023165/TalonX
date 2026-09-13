# Record

## Baseline verification (start of task)

- Research branch `research/talonx-profitability-2026-09` last
  confirmed documentation SHA `7afdfc7e625066e21be9a6ff2751a3de9c165629`.
  **Resolved current HEAD to `2542e1210a3a6a46001f1508f4ae0c642bd10042`**
  — the later documentation-only correction from this same
  conversation turn (the two-statement handoff/journal correction) —
  inspected and recorded per the task's own instruction, not reset to
  the older SHA.
- Release worktree HEAD: `f28986999eec5e313cfc89db24e4dbacfb378891`
  (matches expected exactly), clean throughout.
- Treated Option A as the user's own explicit, bounded resumption
  decision — Task 129's blanket pause was NOT reapplied to block this
  authorized work.

## Actions taken, in order

1. Resolved Tier 1 live: `talonx_ops.watchlist_coverage.build_coverage_map()`
   → 48 configured / 43 active / 39 `v2_collection_scope=="POLLED"`
   (SEC-resolved) — exact match to the stated "previous snapshot,"
   re-verified live, not assumed.
2. Located and read `docs/research/TASK118D_SCOPE_COMPARISON.md` +
   `TASK118D_LIVE_EVIDENCE.md` (the "subsequent matched-runtime
   evidence including Task118D" the prompt named) — found Task 118D
   had already built and matched-runtime-tested a 626-name broader
   population ("Population C" = Task 116's 620-name panel ∪ the 39
   SEC-resolved names), re-run under the post-Task-117 runtime (with
   execution-allowlist enforcement + F3 dissemination-slack fix that
   Task 116's original run predates) — adopted directly as Discovery
   Universe v1, not reconstructed from scratch.
3. Direct source reads (`talonx_v2/{liquidity,config,pipeline,paper,
   service,store,cluster_engine}.py`) resolved, from actual code:
   the eligibility rule is LIQUIDITY-ONLY in every executed run
   (the documented membership-OR-liquidity branch is not implemented
   anywhere — confirmed by grep, only 2 comments describe it);
   `max_concurrent_positions=20`, `reentry_cooldown_trading_days=5`,
   `exit_fallforward_max_sessions=5`, `per_position_allocation_usd`
   defaulting to $10,000 all already match Tier 4's frozen numbers
   exactly (existing frozen contract, not newly invented); capacity
   enforcement (`store.n_open() >= max_concurrent_positions`) and
   no-leverage (`calculate_buy`: `spend = min(allocation, cash)`) are
   real, existing, verified behavior; `pending_entry_intents` (Task
   117) already exists and is populated causally by the real
   `V2Service.tick()`'s own pre-open-intent pass; current runtime
   permits labelled "cold-start backfill" entries without a prior
   intent (verified via `_on_entry_recorded`'s own `delayed = pre_intent
   is not None` and the alert body's own "no earlier intent existed"
   text) — confirming the prompt's own claim precisely, not disputed.
4. Built `research/scripts/task130_universe_manifest.py` — enriched
   Discovery Universe v1 with issuer-CIK mapping, filing/price
   coverage, and ambiguity flags from the existing Form 4 research
   parquet and daily-bar directories (no new data acquisition). Found:
   35/626 symbols with an ambiguous (>1 distinct) CIK mapping, 12/626
   with zero Form 4 coverage (including SHOP, one of Tier 1's own 39),
   1/626 with zero price coverage — all disclosed, none silently
   dropped.
5. Wrote and committed `docs/research/TASK130_OPTION_A_CONTRACT.md` +
   `TASK130_FROZEN_EVALUATION_PROTOCOL.md` (commit `9a484a4`, pushed)
   — BEFORE any return was computed.
6. Wrote `research/scripts/task130_discovery_evaluation.py`, reusing
   `talonx_research.replay_engine.run_chronological_replay` (the real,
   unmodified `V2Service`) exactly per Task 118D's own
   `run_populations_bc.py` pattern (imports from the RESEARCH
   worktree's own `talonx_v2`/`talonx_research`, fingerprint-verified
   `11107198c5b81237` before running, matching Task 118D's own
   convention). Added Track A (historical, unfiltered) / Track B
   (timestamp-proven prospective — only trades with a pre-existing
   `pending_entry_intents` row) derivation, with Track B's own
   independently reconstructed chronological cash/equity series.
7. Wrote `tests/test_task130_discovery_evaluation.py` (9 tests: cost-
   once, closed-trade construction, Track B cold-start exclusion +
   isolated cash, no-negative-cash/allocation-cap reconstruction,
   bootstrap determinism, top-N sensitivity ranking, AND direct
   fixture confirmation of the reused production contract — second-
   owner activation + duplicate dedup, liquidity gate math, capacity
   cap + no-leverage) — ran BEFORE the real evaluation; 1 initial
   failure (a test fixture missing required `V2Decision` fields, fixed)
   and 1 design correction (the capacity test initially tried to
   override `max_concurrent_positions` to a toy value, but
   `cfg.validate_frozen()` asserts it must stay 20 — fixed to exercise
   the real frozen value). **9/9 pass.**
8. Ran the real evaluation (~35s, measured — consistent with Task
   118D's own 34.5s figure for the same population/window at a
   different cash level, used as the pre-run runtime estimate per this
   task's own "measure before extrapolating" instruction).
9. **Found and fixed two implementation-correctness issues in this
   task's OWN analysis code before reporting any result** (not in
   production code): (a) `trades.executed_at` is a real wall-clock
   timestamp, not the simulated session date — every half-year/
   date-block figure was silently wrong (all 157 trades collapsed into
   one bucket) until corrected to read `positions.entry_session`/
   `exit_session` instead; (b) the first Track B "reconstructed
   equity" reported a −44% to −47% "drawdown" that was actually
   capital-deployment (cash committed to open positions), not a loss —
   corrected to a `realized_equity` basis (open positions marked at
   cost, only realized losses count), reducing the reported drawdown
   to a defensible −2.25% with the limitation (no daily marks)
   explicitly disclosed. Both fixes applied, tests updated/re-passed,
   evaluation re-run before any result was used for the decision.
10. Applied the frozen decision criteria (§5) to Track B's real result
    — all four `PASS_FOR_INTEGRATION_REVIEW` conditions met. Wrote
    `docs/research/TASK130_OPTION_A_ECONOMIC_DECISION.md` (Parts 7+8,
    including the required integration handoff since the result
    passed — design only, nothing implemented).
11. Copied compact evidence (`task130_evaluation_results.json` 5.4KB,
    `closed_trades_track_{A,B}.json` ~50KB each,
    `universe_manifest_discovery_v1_compact.json` 36KB — the full
    435KB universe manifest and the isolated replay ledger stay local
    only) to `docs/research/evidence/task130/`.
12. Re-verified production/Redis/process preservation (same result as
    baseline) — no process started, no port opened, Redis untouched.

## Production preservation (end of task)

Unchanged from baseline — no process started, no port opened, Redis
`talonx:*` key count still 0, release worktree still clean at
`f28986999eec5e313cfc89db24e4dbacfb378891`. The isolated replay ledger
(`results/task130_option_a_discovery/replay_v2_lane_discovery_v1.db`)
is a fresh, isolated file under `results/` (gitignored) — never
`v2_lane.db`, the hard safety check in
`talonx_research.replay_engine.assert_research_ledger_path` enforced
and passed.
