# Task 131 — retrospective and traceability matrix

Branch `feature/task131-option-a-integration`, from release baseline
`f28986999eec5e313cfc89db24e4dbacfb378891`. This document maps every
vulnerability/gap discovered across Task 129 (research pause) and
Task 130/130A/130B (Option A discovery research) to the exact code in
this task that resolves it in the LIVE application — and names, just as
explicitly, what remains a disclosed, deliberate non-goal.

## Authorization record

Task 131 was presented as a full production-integration mandate that
directly contradicted Task 130B's own explicit "NOT authorized:
production integration, broad ingestion activation, dashboard changes,
Telegram, broker, paid data, production ledger/config changes,
release/main merges" boundary, and the standing Task 129 research pause.
Before any file was touched, this conflict was surfaced directly and the
user gave an explicit, direct confirmation to override both — recorded
here as the authorization basis for every change in this document. Real-
money trading remained explicitly out of scope throughout and was never
touched.

## Traceability matrix

| Source finding | Task | Exact gap | Task 131 resolution | File(s) : line(s) |
|---|---|---|---|---|
| Track B was permissive-then-post-hoc-filtered, not genuinely gated | 130 review / 130A | Live `V2Service.tick()` called `process_episode` for every ripe episode regardless of whether a durable reservation existed first | `_phase_open` requires a pre-existing `PENDING` intent; ungated episodes get `SKIPPED_NO_PRIOR_INTENT` | `talonx_v2/service.py` `_phase_open` (~L352-410) |
| "−2.25%"/"−44%" mislabeled drawdown; no genuine daily mark-to-market in the live app | 130 / 130A | The live service never computed a per-position daily mark at all | New `_phase_mark` reports requested date, actual mark date, staleness, unrealized P&L per open position every tick | `talonx_v2/service.py` `_phase_mark` (~L555-585); surfaced as `open_position_marks` in tick status |
| State kept in-memory only in the research repair driver; "a genuine mid-replay restart/idempotency test was not built" (Task 130A's own disclosed gap) | 130A | The LIVE app already used `V2Store`/SQLite (this gap was research-only) — but WAL wasn't verified to have actually taken effect | `V2Store._init()` now reads back `PRAGMA journal_mode` and raises loudly if it is not `wal` | `talonx_v2/store.py` `_init` (~L172-193) |
| Same-session exit proceeds must never fund that session's own entries | 130A (repaired in research) | The live app's entry loop already ran before exit settlement in the same tick (order was already correct) — but this was never expressed as an explicit, separately-testable phase boundary | Renamed/extracted into `_phase_open` → `_phase_close`, called in that fixed order; the causal property is now structural, testable in isolation | `talonx_v2/service.py` `tick()` (~L318-323) |
| Same-day filing information must never retroactively fund that morning's entries | 130B Part 7 (research) | The live app detected episodes and created intents BEFORE resolving entries in the same tick — a structural risk (never actually exploited, but not provably closed) | Episode detection / intent creation moved to `_phase_post_close`, which runs strictly AFTER `_phase_open`/`_phase_close` in the same tick | `talonx_v2/service.py` `tick()` (~L324-326), `_phase_post_close` (~L420-495) |
| 60-day-grace identity heuristic; a symbol can legitimately (or illegitimately) map to more than one issuer CIK | 130B Part 2/3 (research, after-the-fact) | The live SEC ingest pipeline had no forward-looking identity check at all — any filing under a ticker was trusted implicitly | `identity_guard.check_filing_issuer_identity` compares each filing's own declared `issuerCik` against the caller's authoritative resolution; a mismatch is dropped, never persisted | `talonx_ingest/intelligence/service/identity_guard.py` (new); wired via `_insider.py::ingest_form_ownership` `enforce_issuer_identity` (~L96-193) |
| CIK zero-padding bug inflated apparent ambiguity in the research reconciliation script | 130B | N/A to live code (research-script-only bug) — but the SAME normalization discipline is applied here | `identity_guard.normalize_cik` mirrors Task 130B's own `_norm_cik` fix | `talonx_ingest/intelligence/service/identity_guard.py` `normalize_cik` |
| 626-name Discovery Universe v1 validated only offline (research parquet), never available to the live SEC poller | 130/130A/130B | The live ingestion scope was hard-limited to the ~39-48-name product watchlist | `broad_discovery.extend_scope_with_broad_discovery`, additive/opt-in, unions the frozen 626-name manifest into the SAME scope/process | `talonx_ingest/intelligence/service/broad_discovery.py` (new); wired via `runner.py::_apply_broad_discovery` |
| No governance for what happens if 626-name ingestion and the 8 req/s SEC budget interact | 131 directive (new requirement, not a prior finding) | A naive second-process poller would silently double the effective SEC request rate | Broad-discovery symbols are unioned into the SAME `EdgarClient`/token-bucket process, never a second poller | `talonx_ingest/intelligence/service/broad_discovery.py` design note; `runner.py` |
| Paper fills are not executable returns; historical consistency is not independent confirmation (130B's own explicit caveat) | 130B Part 10 | N/A — a documentation/framing discipline, not a code gap | Preserved verbatim in this document's own framing (see "What remains disclosed" below) | this document |
| Missing-price handling in the live app had no bounded retry or explicit terminal release | (gap surfaced during this task's own implementation, not a prior finding) | A missing entry bar in a true live tick would retry indefinitely across ticks with no time bound and no explicit "gave up" state | `price_resilience.fetch_price_with_bounded_retry` (5-minute bounded, live ticks only) + `FAILED_NO_MARKET_DATA` terminal disposition/intent release | `talonx_v2/price_resilience.py` (new); `talonx_v2/service.py` `_phase_open` (~L400-410) |
| A restart with the primary 39-name watchlist unaffected by a future broad-discovery toggle | (Directive 5 requirement) | N/A — new requirement | `TALONX_INTEL_ENABLE_BROAD_DISCOVERY` / `--enable-broad-discovery` default OFF; `v2_active_strategy()` dashboard panel completely unmodified | `talonx_ingest/intelligence/service/broad_discovery.py` `broad_discovery_enabled()`; `talonx_ops/dashboard_read.py` (new `v2_broad_discovery()`, `v2_active_strategy()` untouched) |
| Telegram delivery eligibility had no symbol-origin concept at all | (Directive 5 requirement) | N/A — new requirement | `OfficialExternalRouter.decide(..., origin=...)` + `TALONX_DISPATCH_ENABLE_BROAD_DISCOVERY`, a SEPARATE gate from ingestion/execution scope | `talonx_ops/official_dispatch.py` (~L52-70, ~L152-182) |
| Stranded SPCX position, stopped app, never closed, stale metrics | 129 closure task | N/A — operational cleanup, not a code-correctness gap | One-time, backed-up, idempotent administrative closure (flat, zero fabricated P&L) | `scripts/migrations/task131_close_stranded_spcx.py` (new) |

## What remains disclosed, not fixed here

- **Paper fills are not executable returns.** Nothing in this task
  changes that; `allow_real_capital` stays `False` everywhere, and
  `V2_FROZEN_CONTRACT`'s values are untouched.
- **This is still not a production activation.** Every toggle introduced
  (`TALONX_INTEL_ENABLE_BROAD_DISCOVERY`, `TALONX_DISPATCH_ENABLE_
  BROAD_DISCOVERY`, `--enable-broad-discovery`) defaults OFF. No
  continuous overnight poller was actually started against the real
  network in this task, and no real Telegram message was sent — flipping
  any of these on is a distinct, separate operational decision for the
  user to make explicitly.
- **The frozen `cluster_engine`'s greedy window-consumption
  characteristic** (Task 130B's own disclosed finding: a legitimate,
  independent insider cluster arriving within 10 trading sessions of an
  already-fired cluster on the same issuer can be silently absorbed
  without forming its own episode) is unchanged — no algorithm change
  was in scope for Task 131 either.
- **Identity validation here is narrower than Task 130B's own research**:
  it is a live, forward-looking "does this filing's own CIK match what
  we currently, authoritatively believe this ticker is" check, not a
  full historical rename/reorganisation resolution built with hindsight.

## Runtime provenance log

- Baseline verified: release `f28986999eec5e313cfc89db24e4dbacfb378891`
  (clean), matching the branch point exactly.
- Feature branch created: `feature/task131-option-a-integration`.
- Discovery Universe v1 manifest (626 symbols) copied from the research
  branch's own Task 130B-validated `population_manifest.json`
  (`C_full_panel_A_union_B`), research commit
  `5282219b076aa340d36c387e2709b4464c5fa5f2`, into
  `talonx_ingest/intelligence/service/data/discovery_universe_v1_626.json`
  (a tracked package-data file, not under the gitignored `/results/`
  directory — corrected mid-task after the first copy was placed under
  `/results/` and found to be silently invisible to `git`).
- SPCX migration executed once for real (`CLOSED_ADMINISTRATIVELY`),
  verified idempotent on a second run (`NOOP_NO_OPEN_SPCX_POSITION`);
  backup at `~/.talonx/experimental/experimental_paper.db.pre-task131-
  spcx-close.<timestamp>.bak`; audit record at
  `results/task131_migrations/spcx_close_<timestamp>.json`.
- Full repository test suite run before any Task 131 code change:
  4 pre-existing failures (verified, on the clean baseline, unrelated to
  this task — 2 are `git diff --stat` comparisons against historical
  commits predating this branch entirely, 2 are delivery-outbox/
  dashboard-message-count tests unrelated to any file this task
  touches), 4567 passed, 6 skipped.
- Full repository test suite run after all Task 131 code changes:
  same 4 pre-existing failures only, 1066+ additional/re-run tests
  passed in the final targeted sweep (V2 service, execution scope,
  migration, pricing readiness, overnight journey, dashboard, dispatch,
  intelligence-service, and all new `test_task131_*` files), 0 new
  regressions.
- 4 existing tests were intentionally updated to reflect a real,
  disclosed behavior change (cold-start entries are no longer admitted
  without a prior durable intent) rather than left asserting the old,
  now-superseded permissive behavior:
  `test_task113_stale_entry_guard.py::test_fresh_episode_still_enters`,
  `test_task117_execution_scope.py` (5 tests, added a prior tick),
  `test_task117_migration.py::test_interrupted_tick_leaves_a_consistent_
  recoverable_ledger`, `test_task117_overnight_journey.py` (rewrote
  the cold-start test into two, `test_p1_same_session_first_tick_
  defers_never_enters_cold` and `test_p1_late_first_tick_is_a_permanent_
  miss_not_a_stale_backfill`), `test_task117_pricing_readiness.py` (2
  tests, restructured to isolate a transient provider error from the
  underlying liquidity-history data, since the original fixtures had no
  valid data until well after the causal entry window — which is now,
  correctly, a permanent miss under the corrected contract).
- 4 exact-key-set dashboard assertions were updated to include the new,
  additive `v2_broad_discovery` section key:
  `test_task100c_unified_dashboard.py` (3 assertions),
  `test_task119_paper_performance.py` (1 assertion).
- New test files: `tests/test_task131_identity_guard.py` (3),
  `tests/test_task131_broad_discovery.py` (4),
  `tests/test_task131_broad_discovery_dispatch.py` (5),
  `tests/test_task131_dashboard_broad_discovery.py` (5) — 17 new tests,
  all passing.
- No commit has been made to `feature/task131-option-a-integration` as
  of this document; the branch has not been pushed or merged toward
  `main`/`release` at any point in this task.
