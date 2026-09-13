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

## HOLD review findings and remediation (commit `58044a6` → this remediation)

A follow-up review issued a HOLD verdict against commit `58044a6` citing
6 launch-blocking defects. Each was independently verified against the
actual diff (not taken on faith — one claim, "a syntax error in
`routing.py`," named the wrong file, but the underlying defect it
pointed at was real) before any fix was made. Two of the six literal
remediation instructions, if followed exactly as worded, would have
introduced real regressions or violated this program's own frozen-
contract discipline — both are recorded below with what was implemented
instead and why.

| # | Reviewed finding | Verified? | Fix | Verification proof |
|---|---|---|---|---|
| 1 | "Syntax error in `routing.py`: `RoutingDecision.to_dict()` indented inside `broad_discovery_dispatch_enabled()`" | **Confirmed real** (file is actually `talonx_ops/official_dispatch.py`; not a SyntaxError but a structural bug — `to_dict` was unreachable dead code nested inside the toggle function, never callable as an instance method) | Restored `to_dict()` to `RoutingDecision`'s own class body, immediately after `should_send` | `tests/test_routing.py` (7 tests) — `.to_dict()` exercised across every family/origin/toggle combination |
| 2 | "Remove synchronous `time.sleep()` in `tick()`; implement async `PENDING_RETRY`" | **Confirmed real** (the Task 131 bounded-retry helper could block one `tick()` call for up to 5 minutes) | Removed the blocking retry entirely; `talonx_v2/price_resilience.py` deleted; replaced with a non-blocking, cross-tick retry (intent stays `PENDING`, naturally retried next tick, no sleep). Literal "async event loop" NOT implemented — this codebase has no asyncio anywhere in `talonx_v2`; see the design doc for why an unscoped asyncio rewrite was declined in favor of the equivalent non-blocking behavior | `tests/test_task131_nonblocking_retry.py` (4 tests) — wall-clock-timed proof a missing-price tick completes in <2s, survives 5 same-session ticks, reconciles on late data, escalates exactly once at the next session |
| 3 | "Store SEC EDGAR dissemination timestamp; enforce `T_dissemination < T_RTH_Open`" | **Confirmed real, and real design constraint discovered while fixing it**: the natural implementation (extend `cluster_engine.PurchaseRecord`/`ClusterEpisode`) breaks the hash-fingerprinted frozen strategy contract | Implemented entirely in `talonx_v2/service.py`: a per-tick dissemination lookup queried directly from InsiderStore, checked before every entry via `_verify_temporal_boundary` | `tests/test_task131_temporal_boundary.py` (4 tests) — a normally-timed filing passes, an anomalously late one is refused end-to-end, a direct unit sweep across the exact boundary, a date-only source no-ops safely |
| 4 | "Atomic SQLite transactions in `paper.py`; hard reservation gate (`REJECTED_CAPACITY_EXCEEDED`)" | **Confirmed real** (`enter_position`/`close_position` each made 4 separate, independently-committed store calls; `upsert_entry_intent` had no cash/capacity check at all) | `V2Store.transaction()` (reentrant, WAL-active) wraps both sequences; `V2Service._capacity_rejection_reason()` checked before every `upsert_entry_intent` call | `tests/test_task131_atomic_transactions.py` (8 tests) — real temp SQLite file, monkeypatched mid-sequence crash, a fresh store connection shows nothing partial; 21st-slot and over-reserved-cash rejection proven directly |
| 5 | "Tag SPCX closure `transaction_type='ADMINISTRATIVE_ADJUSTMENT'`; exclude from performance queries" | **Partially as literally worded**: the migration already tagged the row distinctly via the EXISTING `exit_reason` column (`administrative_force_close_task131`) — a new `transaction_type` column would require an `ALTER TABLE` on a live production database for a distinction the schema already supports. The REAL, verified gap: `talonx_ops/paper_performance.py`'s `closed_trades`/`trade_counts`/`realized_pnl` breakdown scanned `trade_history` directly and would have displayed/counted the row as a real trade | Excluded any `exit_reason` starting with `administrative_` from `closed`/`sells`/`realized_sum_check`; reported separately, in full, under a new `administrative_adjustments` key — never silently dropped | `tests/test_task131_admin_adjustment_isolation.py` (2 tests) — a real SPCX-shaped row is excluded from trade counts/P&L cross-check but fully visible under `administrative_adjustments` |
| 6a | "Feature-flag V2 durable store changes behind `TALONX_V2_DURABLE_STORE_ENABLED`, default False" | **Real requirement, literal scope corrected**: WAL/SQLite durability itself predates Task 131 (Task 110) — defaulting IT off would revert a live system to non-durable state, a regression, not a rollback | The flag instead gates the Task 131 admission-POLICY changes only (prior-intent requirement, hard capacity gate) — OFF reproduces the exact pre-Task-131 permissive policy | `tests/test_task131_remediation_directive6.py` — both flag states proven end-to-end (cold-start entry allowed when OFF, refused when ON) |
| 6b | "Replace dynamic CIK lookups with a static `CIK_MANIFEST_V1`" | **Real requirement, scope corrected**: replacing the general-purpose `CikDirectory` (used by the primary product watchlist and the identity guard) would be a live-correctness regression (new tickers/renames would silently stop resolving) | A static, versioned `CIK_MANIFEST_V1` was built and embedded in `discovery_universe_v1_626.json` for ONLY the 626-name Discovery Universe v1 population (569/626 resolved from a snapshot; 57 unresolved and reported, not silently dropped) — the primary watchlist and identity guard continue to use the live, dynamic `CikDirectory`, unchanged | `tests/test_task131_remediation_directive6.py::test_real_manifest_carries_a_valid_static_cik_manifest_v1` — resolves the full population with zero network/CikDirectory calls |

A genuine, unplanned 7th finding surfaced only while fixing #3: reverting
`cluster_engine.py` via `git checkout --` silently corrupted the frozen
strategy fingerprint via this machine's `core.autocrlf=true` line-ending
conversion (LF → CRLF), even though `git diff` showed no differences.
Caught immediately by the existing fingerprint test suite
(`test_task114_prospective.py` et al.), root-caused, and fixed by
restoring the exact blob bytes directly. See the design document.

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
- Task 131's original integration work was committed and pushed at
  `58044a6` (superseding the "no commit yet" statement above, which
  described the state at the time it was originally written).

## Remediation runtime provenance log (this pass, on top of `58044a6`)

- Baseline verified: `feature/task131-option-a-integration` at `58044a6`
  (clean, matches `origin`), on top of release `f2898699` (still
  untouched, still clean).
- Fixed, in order: (1) `RoutingDecision.to_dict()` restored to the class
  body; (2) blocking retry removed from `tick()`,
  `talonx_v2/price_resilience.py` deleted, replaced by the non-blocking
  `PENDING_RETRY` model; (3) the temporal dissemination boundary
  implemented entirely in `talonx_v2/service.py` after an initial
  `cluster_engine.py` attempt was reverted for breaking the frozen
  strategy fingerprint (and a line-ending self-corruption from that
  revert was found and fixed); (4) `V2Store.transaction()` (reentrant)
  + `paper.py` atomic writes + the hard capacity-reservation gate at
  intent creation; (5) administrative-adjustment exclusion in
  `talonx_ops/paper_performance.py`; (6) the
  `TALONX_V2_DURABLE_STORE_ENABLED` flag (default False, gating the
  admission-policy changes only) and the static `CIK_MANIFEST_V1` for
  the 626-name Discovery Universe v1 population.
- New test files: `tests/test_routing.py` (7),
  `tests/test_task131_nonblocking_retry.py` (4),
  `tests/test_task131_temporal_boundary.py` (4),
  `tests/test_task131_atomic_transactions.py` (8),
  `tests/test_task131_admin_adjustment_isolation.py` (2),
  `tests/test_task131_remediation_directive6.py` (5) — 30 new tests, all
  passing.
- `tests/conftest.py` now sets `TALONX_V2_DURABLE_STORE_ENABLED=true` as
  the TEST SUITE's own default (`os.environ.setdefault`) — the corrected
  policy is what the existing V2Service test suite is written to
  exercise; `V2Service`'s own runtime default (outside pytest, no env
  override) remains `False`, per the literal remediation requirement.
- 5 existing test files were updated for the SAME reason as the original
  integration's own cold-start-gate change (no new behavior beyond what
  `58044a6` already introduced, just fixture adjustments where a test
  fixture happened to construct data for the OLD manifest shape or the
  new field additions): `tests/test_task131_broad_discovery.py` (2
  tests, `cik_manifest` fixture data added to match the Directive 6
  static-manifest change).
- Full repository test suite run after all remediation changes:
  **4 failed, 4614 passed, 6 skipped** (52m03s) — the SAME 4 pre-existing,
  verified-unrelated failures as every prior baseline in this task
  (`test_task102_operational_finalization.py::test_36_original_strategy_unchanged`,
  `test_task104_p2_cleanup.py::test_32_33_original_strategy_and_thresholds_unchanged`,
  `test_task117_release_rehearsal.py::test_bounded_release_rehearsal`,
  `test_task118a_dashboard_message_count.py::test_immediate_and_digest_sends_count_messages_correctly`)
  — zero new regressions from this remediation.

## Final Remediation runtime provenance log (this pass, on top of `53c3e4a`)

A third directive list, closing 4 remaining production boundaries in
`talonx_v2/service.py` and `talonx_v2/store.py`; no SPA frontend or
Supervisor lifecycle change was in scope or made. Full design rationale
in the "Final Remediation pass" section of `TASK131_REMEDIATION_DESIGN.md`.

- Baseline verified: `feature/task131-option-a-integration` at `53c3e4a`
  (clean, matches `origin`).
- Fixed, in order: (1) the intent-creation-time deadline check added to
  `_verify_temporal_boundary` (gated on `live`), and the unknown-
  dissemination-timestamp strict-failure condition corrected from
  `form4_kind == "insider"` to a new `self._dissemination_lookup_
  refreshed_this_tick` flag (a real InsiderStore query actually ran this
  tick and still found nothing) to avoid spuriously failing tests that
  inject `svc._records` directly; (2) `V2Store.transaction()` made
  reentrant so `_phase_open` can wrap `pipeline.process_episode` +
  `mark_entry_intent(FILLED)` in one outer atomic transaction; (3) both
  `pre_intent["intent_id"]` legacy-mode crash sites in `_phase_open`
  guarded with `if pre_intent is not None:`, and the missing-price retry
  deadline restored to the approved
  `max_entry_staleness_sessions - 1`-session recovery window (the `-1`
  is required — see design doc — to avoid a race with the pre-existing
  staleness guard that would otherwise make the escalation unreachable);
  a genuine pre-existing bug found via that same debugging (stale-episode
  intent expiry silently skipped forever whenever the episode already
  carried an unrelated earlier disposition) was also fixed; (4) the
  `tests/conftest.py` global `TALONX_V2_DURABLE_STORE_ENABLED=true`
  default removed, replaced with 2 narrowly-scoped local
  `monkeypatch.setenv` calls in the 2 of ~198 V2-focused tests that
  actually needed the gate ON.
- Fingerprint re-verified unchanged after every edit in this pass:
  `11107198c5b81237`.
- Files changed (all uncommitted-in-progress, no new files):
  `talonx_v2/service.py`, `talonx_v2/store.py`, `tests/conftest.py`,
  `tests/test_task117_overnight_journey.py`,
  `tests/test_task131_atomic_transactions.py` (2 tests rewritten for
  reentrancy, replacing the now-obsolete non-reentrant-`RuntimeError`
  test),
  `tests/test_task131_nonblocking_retry.py` (1 test rewritten for the
  corrected retry-deadline formula).
- V2-focused battery (19 files covering all V2Service behavior,
  including every `test_task131_*` and `test_task117_*` file): **198
  passed**, 0 failed, run with NO global durable-store-flag override —
  confirming Directive 4's removal causes zero regressions once the 2
  locally-scoped overrides are in place.
- Full repository test suite run after all Final Remediation changes:
  **4 failed, 4615 passed, 6 skipped** (1:54:16) — the SAME 4
  pre-existing, verified-unrelated failures as every prior baseline in
  this task (`test_task102_operational_finalization.py::test_36_
  original_strategy_unchanged`, `test_task104_p2_cleanup.py::test_32_33_
  original_strategy_and_thresholds_unchanged`,
  `test_task117_release_rehearsal.py::test_bounded_release_rehearsal`,
  `test_task118a_dashboard_message_count.py::test_immediate_and_digest_
  sends_count_messages_correctly`) — zero new regressions from this
  Final Remediation pass.

## Targeted Remediation runtime provenance log (this pass, on top of `9a81e5c`)

A fourth directive list, closing 3 further production boundaries, all
inside `talonx_v2/service.py`'s `_verify_temporal_boundary` and
`_phase_post_close`. Full design rationale in the "Targeted Remediation
pass" section of `TASK131_REMEDIATION_DESIGN.md`.

- Baseline verified: `feature/task131-option-a-integration` at `9a81e5c`
  (clean, matches `origin`).
- Fixed, in order: (1) an unknown dissemination timestamp is now a
  strict failure on ANY live tick (`live or self._dissemination_lookup_
  refreshed_this_tick`), not only when a real InsiderStore query happened
  to run this tick; a missing or malformed intent `created_at_utc` on a
  live tick is now itself a strict failure rather than silently falling
  through to a pass; (2) `_verify_temporal_boundary` is now also called
  from `_phase_post_close`, BEFORE a reservation exists, with
  `intent=None` — comparing the real "right now" against the target
  session's RTH open so a `BUY` intent (and its actionable alert) is
  never created for a session whose admission window has already closed
  (new disposition `SKIPPED_ADMISSION_DEADLINE_PASSED`, new counter
  `_admission_deadline_rejected` / `admission_deadline_rejected_this_
  tick`); `_phase_post_close` gained a `live: bool = False` parameter,
  threaded from `tick()`; (3) the capacity check, intent creation, and
  notification generation in `_phase_post_close` now run inside one
  `with self.store.transaction():` block (reusing the reentrant
  primitive from the Final Remediation pass) — the success path (intent
  + alert) and the rejection path (a single disposition write) both
  commit atomically, and a crash anywhere in the success path rolls back
  the whole sequence.
- Fingerprint re-verified unchanged after every edit in this pass:
  `11107198c5b81237`.
- Files changed: `talonx_v2/service.py` only. New test file:
  `tests/test_task131_targeted_remediation.py` (14 tests) — direct
  unit-level coverage of both live and non-live behavior for all 3
  directives (matching this codebase's own established pattern for
  wall-clock-dependent logic, per `test_task131_temporal_boundary.py`),
  plus end-to-end wiring proofs through real `_phase_post_close()` calls
  and two failure-injection atomicity tests (one of which opens a
  genuinely separate `V2Store` connection mid-transaction to prove real
  SQLite-level isolation under contention, not merely eventual rollback).
- V2-focused battery (19 prior files + the new one, 20 files covering all
  V2Service behavior): **212 passed**, 0 failed.
- Full repository test suite run after all Targeted Remediation changes:
  **4 failed, 4629 passed, 6 skipped** (0:44:12) — the SAME 4
  pre-existing, verified-unrelated failures as every prior baseline in
  this task (`test_task102_operational_finalization.py::test_36_
  original_strategy_unchanged`, `test_task104_p2_cleanup.py::test_32_33_
  original_strategy_and_thresholds_unchanged`,
  `test_task117_release_rehearsal.py::test_bounded_release_rehearsal`,
  `test_task118a_dashboard_message_count.py::test_immediate_and_digest_
  sends_count_messages_correctly`); the pass count rose by exactly 14
  over the prior baseline (4615 → 4629), matching the 14 new tests in
  `tests/test_task131_targeted_remediation.py` — zero new regressions
  from this Targeted Remediation pass.
