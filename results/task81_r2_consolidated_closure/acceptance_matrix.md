# Task 81-R2 — Acceptance / State-Transition Matrix (frozen before implementation)

Baseline: branch `research/talonx-strategy-validation`, HEAD
`d8e530e4b80131e1d92a7184b229333219e3e697` (verified == expected). Tree
clean. `stash@{0}`/`stash@{1}` (task56) preserved. Reported baseline
`2625 passed, 1 skipped, 10 xfailed` — re-run in progress
(`raw_test_output/baseline_full_suite.txt`).

Boundaries: no isolation, no live session, no broker mutation, no
notification, PAPER entries disabled, strategy `UNVALIDATED`, Gemini
informational, `talonx_quant/{strategy,indicators,consumer,config}.py`
unchanged, portfolios/historical evidence preserved.

Numerical tolerance for quantity/price comparisons: `RECONCILE_QUANTITY_TOLERANCE = 1e-6` (unchanged).

## §2 — Complete order identity + state (one coherent contract)

| # | Requirement | Production boundary | Pre-fix reproduction | Regression test (node id) |
|---|---|---|---|---|
| R2a.1 | Internally **filled** order that the broker reports open/unfilled while position quantities agree → NOT `matched`; block held | `lifecycle.py:_verify_broker_order_row` (was `_classify_broker_open_order`), `reconcile` | `test_task81_r2_reconcile_identity.py::test_reproduce_filled_order_reported_open_false_pass` | `::test_internally_filled_order_still_open_at_broker_is_contradiction` |
| R2a.2 | Known broker **id** carrying the **wrong `client_order_id`** → NOT `matched`; conflicting IDs never an accepted match | same | `::test_reproduce_wrong_client_order_id_false_pass` | `::test_id_with_wrong_client_order_id_is_contradiction` |
| R2a.3 | Match requires broker id + client id + exact durable intent consistently; verify symbol, side, requested qty, cumulative filled qty, compatible lifecycle status | `_verify_broker_order_row` | — | `::test_full_field_consistency_required_for_ok` |
| R2a.4 | Missing intent/payload, ambiguous matches, conflicting IDs, malformed required fields → never an accepted match | same | — | `::test_missing_intent_ambiguous_conflicting_malformed_never_ok` (parametrized) |
| R2a.5 | Every terminal-vs-open contradiction is unresolved — **including `filled`**; no eventual-consistency exemption | same | — | `::test_no_eventual_consistency_exemption_for_filled` |
| R2a.6 | Position agreement must not override order disagreement | `reconcile` | — | `::test_position_agreement_does_not_override_order_disagreement` |
| R2a.7 | Validate both directions: every internally outstanding order needs a verified current disposition (present in broker open list, refreshed-to-terminal, or a recorded read failure this pass) | `reconcile` reverse check | `::test_reproduce_internal_order_missing_from_broker_list_false_pass` | `::test_internal_outstanding_order_absent_from_broker_list_is_unresolved` |
| R2a.8 | Durable BUY block held until a complete + consistent pass; transient inconsistent snapshots are retryable, not a clean pass; restart-safe | `reconcile` + `reconciliation_flags` persistence | — | `::test_block_persists_over_transient_snapshot_and_clears_on_clean_pass`, `::test_block_survives_restart` |
| R2a.9 | One coherent validation contract applied across `_resolve_unconfirmed_orders`, `_resolve_uncertain_submissions`, `_refresh_non_terminal_orders`, `_verify_broker_order_row` | `lifecycle.py` (`_parse_broker_order_response`, `_verify_broker_order_row`, `_validate_broker_update`) | — | `::test_all_reconcile_entry_paths_reject_malformed_response` (parametrized), call-path audit |

## §3 — Real orphan recovery (production code only)

| # | Requirement | Production boundary | Test (node id) |
|---|---|---|---|
| R3.1 | An orphan `ORDER_INTENT` stays blocked until resolved through production code (promoted to `SUBMIT_FAILED_UNCERTAIN` in `reconcile`, then the audited discovery/adoption/operator machinery) | `lifecycle.py:_promote_orphan_order_intents`, `reconcile` | `test_task81_r2_orphan_recovery.py::test_orphan_order_intent_promoted_and_blocked_until_resolved` |
| R3.2 | Discovery via stable client-order id; adoption only after `find_order_by_client_id` result matches the exact durable intent | `_resolve_uncertain_submissions` + `_order_response_matches_intent` | `::test_orphan_discovered_and_adopted_only_on_exact_match`, `::test_orphan_unrelated_response_not_adopted` |
| R3.3 | Correct recovery for pending / partially filled / filled / terminal outcomes incl. fill timing, exit plan, actual holdings | adoption → `apply_broker_update` | `::test_orphan_recovery_matrix` (parametrized: pending/partial/filled/rejected) |
| R3.4 | Production operator-resolution for independently-verified non-submission: explicit confirmation + audit reason; refuses wrong-state / ambiguous / unsupported | `operator_resolve_uncertain_submission` (reachable after promotion) | `::test_operator_resolution_requires_confirmation_and_audits`, `::test_operator_resolution_refuses_wrong_state` |
| R3.5 | Restart-safe persistence; idempotent repeated reconciliation; no blind resubmission; no timeout/count-based "never existed" | `reconcile` / `_resolve_uncertain_submissions` | `::test_orphan_recovery_idempotent_and_restart_safe`, `::test_orphan_never_auto_resolves_on_absence` |
| R3.6 | Replace R1 tests that resolved an orphan by editing `.status` directly | `tests/test_task81_r1_reconciliation_completeness.py` | updated in place; helper removed |

## §4 — Validate before mutating accounting

| # | Requirement | Production boundary | Test (node id) |
|---|---|---|---|
| R4.1 | Reject missing required fields, non-finite / boolean / negative quantities, impossible cumulative fills, inconsistent identities BEFORE changing trusted accounting | `lifecycle.py:apply_broker_update` (`_validate_broker_update` upfront guard) | `test_task81_r2_apply_update_validation.py::test_invalid_update_rejected_before_mutation` (parametrized) |
| R4.2 | A contradictory response must not poison an order's terminal status or fill high-water mark | `apply_broker_update` | `::test_contradictory_update_does_not_poison_status_or_high_water_mark` |
| R4.3 | Genuine positive fill deltas, previous exits/P&L, protective levels, linkage, exit latch preserved | `apply_broker_update` | `::test_genuine_delta_preserves_exits_levels_linkage_latch` |
| R4.4 | Duplicate / stale responses remain idempotent | `apply_broker_update` | `::test_duplicate_and_stale_idempotent` |
| R4.5 | Scenario: partial BUY → protective close → later BUY fill → restart → remaining protective exit | production lifecycle path | `::test_partial_buy_close_late_fill_restart_remaining_exit` |
| R4.6 | Reconciliation blocks do not suppress alerts / eligible shadow tracking / monitoring / EOD cleanup; protective SELL sized vs verified holdings − pending sells; unknown exposure fails visibly | `order_intent` SELL, `reconcile`, `eod_lifecycle` | `::test_block_preserves_sell_shadow_monitoring_eod`, `::test_unknown_exposure_sell_fails_visibly` |

## §5 — Close the 10 xfails + the skip

| # | Requirement | Artifact | Test node ids closed |
|---|---|---|---|
| R5.1 | Regenerate `examples/data/sample_multi_trade_1m.csv` deterministically via the unchanged strategy: causal pre-roll + 3 long-only setups → TARGET / STOP / END_OF_SESSION; reproducible generator/spec; no hand-edited ledgers; TEST_FIXTURE_ONLY label | `scripts/gen_sample_multi_trade_1m.py` + `results/task81_r2_consolidated_closure/fixture_spec.md` | the 6 `test_backtest_sample_data.py::test_multi_trade_*` + 4 `test_backtest_cost_sensitivity.py::test_multi_trade_*` (markers removed only after pass) |
| R5.2 | Preserve genuine cost-sensitivity / trade-count / P&L / equity-curve / report assertions (no weakening) | test files unchanged except marker removal | same |
| R5.3 | Correct the skip: it uses the generated trade-free `sample_df` (`_small_bars`), NOT `sample_AAPL_trade_1m.csv`; retain explicit zero-trade coverage AND exercise expectancy-vs-cost with a trade-producing fixture (no new skip/xfail) | `tests/test_backtest_cost_sensitivity.py::test_higher_cost_never_improves_expectancy` | rewritten to assert zero-trade behaviour explicitly; monotonicity covered by `test_multi_trade_higher_cost_never_improves_expectancy_without_skipping` |

## §6 — Evidence corrections (append, never rewrite)

| # | Requirement | Artifact |
|---|---|---|
| R6.1 | Correct the R1 skip-attribution statement (`sample_AAPL_trade_1m.csv` → generated `_small_bars` `sample_df`) and any inaccurate test-count/coverage statements | `report_corrections.md` |
| R6.2 | IEX conclusion stays bounded: counts reconcile; receipt-vs-source-time unverified without raw timestamp evidence; documented as a disclosed evidence-limited follow-up, not a proven absence of defects | `report_corrections.md` (Task 81 / R1 IEX docs preserved) |
| R6.3 | Document minimum future capture; no data acquisition / session launch | `report_corrections.md` |

## §7 — Verification

State-transition matrix executed across: pending/partial/filled/cancelled/
rejected/expired/uncertain orders × correct/conflicting/missing IDs ×
valid/malformed/incomplete responses × duplicate/older/genuine fills ×
restart before/after submission/adoption/fill/exit/operator-resolution ×
missing/corrupt identity with unresolved exposure × block persistence and
verified recovery. Deterministic clocks, isolated realistic broker fakes
(Alpaca REST contract confirmed from docs), temp state dirs. Pre-fix
reproduction + post-fix production-path test per defect. Negative
controls. Focused suites ×2, full suite with no edits in flight, exact
count reconciliation, rerun on any subsequent change.

Verdict: `BASELINE_VERIFIED_READY_FOR_ISOLATION` only when every row above
passes and the full suite reconciles exactly; otherwise `BLOCKED` with the
unmet requirement + required authority/decision.
