# Task 81 — Acceptance Matrix (recorded before implementation)

Baseline: branch `research/talonx-strategy-validation`, HEAD
`47afb8c9630c0eee5394063a3f574db1b52173dd` (= the task's expected starting SHA;
the `docs(task80): preserve cleanup evidence and handoff` commit landed
immediately after this session opened). Tracked worktree clean. Stashes
`stash@{0}`/`stash@{1}` (task56) preserved untouched. Codex paused.

Preserved Task 80 evidence (must not be mutated):
`results/task80_cleanup/2026-08-28/...`, `results/task80_live_20260828/runtime/`,
`results/task80_p0_readonly_preflight_audit/`, `results/task80_p1_process_guard/`.
Entry settings remain all-disabled; monitoring automation
`monitor-talonx-paper-session` remains PAUSED.

Numerical tolerance convention (documented once, referenced by rows below):
quantity comparisons use absolute tolerance `1e-6` (share quantities are
integers in this product; the tolerance only absorbs float round-trips through
JSON/`str`). Any difference above tolerance is a mismatch.

Contradiction resolution decided up front:
- "Failed/malformed/incomplete/contradictory reads durably block new entries"
  vs "preserve protective exits": the block is **BUY_TO_OPEN-only**. SELL,
  alerts, shadow tracking, monitoring, EOD are never gated by it. (Consistent
  with existing `reconciliation_flags.entry_admission_blocked` semantics.)
- "Entry blocking must not disable EOD cleanup": `eod_flatten` / EOD lifecycle
  never consult `entry_admission_blocked`. Regression test asserts this.
- "Unknown exposure must not produce blind retries or overselling": when
  holdings/pending-sells cannot be verified, SELL sizing must fail visibly
  (no default-to-constant, no unbounded retry), while a *verified* protective
  exit still proceeds.

| # | Requirement (task section) | Production boundary (file:symbol) | Regression test (fails pre-fix) | Evidence artifact |
|---|---|---|---|---|
| A1 | §2 Internal AAPL qty 10 vs broker qty 1 must NOT report matched | `talonx_piv/lifecycle.py:reconcile` | `tests/test_task81_reconciliation_admission.py::test_quantity_mismatch_same_symbol_is_not_matched` | RCA §2; raw pytest |
| A2 | §2 Untracked broker BUY order with empty portfolios must NOT report matched | `talonx_piv/lifecycle.py:reconcile` (compare `broker.open_orders()` identities vs `state.orders`/intents) | `::test_untracked_broker_open_order_blocks_admission` | RCA §2; raw pytest |
| A3 | §2 Individual pending-order refresh failure must durably block; a later reconcile must NOT clear it on symbol-set match alone | `talonx_piv/lifecycle.py:_refresh_non_terminal_orders` + `reconcile` completeness gate | `::test_single_order_refresh_failure_keeps_block_across_reconcile_and_restart` | RCA §2; raw pytest |
| A4 | §2 Compare quantities, sides, outstanding-order identities, unresolved submissions — not only symbol sets | `talonx_piv/lifecycle.py:reconcile` | `::test_side_mismatch_not_matched`, `::test_uncertain_submission_prevents_clear` | RCA §2 |
| A5 | §2 Validate broker response completeness/shape; malformed/incomplete/None ≠ empty | `talonx_piv/broker.py:open_orders/positions` + `lifecycle.py:reconcile` | `::test_malformed_positions_response_blocks`, `::test_non_list_orders_response_blocks` | RCA §2 |
| A6 | §2 Block clears ONLY after a complete, consistent, matched reconcile | `talonx_piv/lifecycle.py:reconcile` | `::test_block_clears_only_after_complete_consistent_pass` | RCA §2 |
| A7 | §2 Verified pending orders remain reserved and attributable through a clearing pass | `talonx_piv/lifecycle.py:reconcile` / `pending_buy_intent_ids` | `::test_verified_pending_order_stays_reserved_after_clear` | RCA §2 |
| A8 | §2 Admission enforced at the actual broker boundary (no weaker path) | `talonx_piv/lifecycle.py:order_intent` BUY guard before `broker.submit_order` | existing `test_task76s_broker_boundary.py` + `::test_probe_and_manual_paths_still_blocked_by_reconcile_block` | RCA §2 |
| A9 | §2 Preserve alerts / shadow tracking / monitoring / protective exits under a block | `lifecycle.py:order_intent` SELL path; decision engine exit path | `::test_block_does_not_suppress_sell_or_shadow` + existing protective-exit suite | RCA §2 |
| A10 | §2 SELL sizing respects verified remaining holdings & pending sells; unknown exposure → visible failure, no blind retry/oversell | `lifecycle.py:order_intent` SELL branch; `remaining_holdings` | `::test_sell_sizing_unknown_exposure_fails_visibly` | RCA §2 |
| A11 | §2 Entry block must NOT disable EOD cleanup path | `talonx_piv/eod_lifecycle.py` / `lifecycle.py:eod_flatten` | `::test_entry_block_does_not_disable_eod_cleanup` | RCA §2 |
| B1 | §3 Same-session restart under unchanged verified bindings preserves identity/plans/budgets/exit obligations | `talonx_piv/session_identity.py:resolve_session_identity` | `tests/test_task81_recovery_binding.py::test_same_session_restart_preserves_everything` | RCA §3 |
| B2 | §3 Changed runtime/config/feed/account binding, corrupt identity, or incomplete EOD must NOT silently mint a replacement while exposure unresolved — preserve context, block entries, report required operator action | `session_identity.py:resolve_session_identity` + supervisor/cli recovery reporting | `::test_changed_binding_with_open_exposure_blocks_and_reports`, `::test_corrupt_identity_blocks_not_silently_replaced` | RCA §3 |
| B3 | §3 Fresh session only through a defined, verified transition | `session_identity.py` + cli/supervisor | `::test_fresh_session_requires_defined_transition` | RCA §3 |
| B4 | §3 Exact order-to-intent pending-plan recovery; fail visibly on ambiguity | `talonx_piv/decision_engine.py:_rehydrate*` / `lifecycle.pending_buy_intent_ids` | `::test_exact_pending_plan_recovery_and_ambiguity_fails_visibly` | RCA §3 |
| B5 | §3 Cumulative fills idempotent: repeated/delayed/older updates don't resurrect sold qty, erase latches, or corrupt accounting | `talonx_piv/lifecycle.py:apply_broker_update` | `::test_cumulative_fill_idempotency_matrix` | RCA §3 |
| B6 | §3 Scenario: partial entry → partial exit → later entry fill → restart → remaining exit, incl. reconciliation failure | `session_runner.py:process_tick` + lifecycle | `::test_partial_entry_partial_exit_later_fill_restart_remaining_exit` | RCA §3 |
| C1 | §4 Missing/corrupt/wrong-session/stale inputs → explicit source-health diagnostics, not plausible zero activity | `talonx_piv/reporting.py:build_session_report` + `observability.py:build_integrated_projection` | `tests/test_task81_source_health.py::test_missing_required_source_is_diagnosed_not_zero` | RCA §4 |
| C2 | §4 Distinguish verified-zero vs absent-optional-ledger vs unreadable-required-source | `reporting.py` / `observability.py` source-health block | `::test_three_way_source_state_distinction` | RCA §4 |
| C3 | §4 Applies to existing PIV projection/API only (no future comparison UI) | `talonx_piv/observability.py`, `dashboard_web.py` PIV status endpoint | `::test_piv_projection_surfaces_source_health` | RCA §4 |
| C4 | §4 Automatic session shutdown emits correctly-scoped session report for success/failure/inconclusive EOD | `talonx_piv/eod_lifecycle.py` / `cli.py` auto-shutdown path | `tests/test_task81_auto_report.py::test_auto_shutdown_emits_scoped_report_{passed,failed,inconclusive}` | RCA §4 |
| C5 | §4 Report retries never repeat broker cancel/close | auto-shutdown/report path | `::test_report_retry_does_not_recancel_or_reclose` | RCA §4 |
| C6 | §4 Preserve original session/runtime identity; distinguish broker/EOD status from report-generation status | report scoping + status fields | `::test_report_identity_and_status_separation` | RCA §4 |
| C7 | §4 Do not mark positions confirmed-closed merely because a close request was accepted | `lifecycle.py:eod_flatten` / reporting | `::test_close_request_accepted_is_not_confirmed_closed` | RCA §4 |
| D1 | §5 IEX readiness churn RCA from preserved local evidence; separate coverage / stale / polling-bar-timestamps / readiness transitions / provider failures / dedup | analysis over `results/task80_live_20260828/runtime/piv_events.jsonl` etc. | causal regression test(s) iff a runtime bookkeeping/freshness defect is confirmed | `iex_findings.md` |
| D2 | §5 Do not relax thresholds / fabricate bars / assume "IEX sparsity"; infra exclusions kept separate from strategy rejections | n/a (analysis + guard tests) | `::test_infra_exclusion_not_counted_as_strategy_rejection` (if defect found) | `iex_findings.md` |
| E1 | §6 Strengthen weak tests (dict/return-only) to assert required state/outcome | affected `tests/*` | updated assertions; prove each fails pre-fix | `test_quality_changes.md` |
| E2 | §6 Broker contract fixtures from documented API behavior | `tests/` broker fakes | fixture doc references Alpaca docs | `test_quality_changes.md` |
| E3 | §6 Freeze clocks; isolate files/DBs/env; stop tests writing into historical evidence dirs | `tests/` | grep-proof no writes under `results/task*` historical dirs | `test_quality_changes.md` |
| E4 | §6 Prove each regression fails pre-fix; for critical guards inject the forbidden outcome and prove detection | `tests/test_task81_*` | recorded pre-fix failure output | `prefix_failure_log.txt` |
| E5 | §6 Run targeted + adjacent during dev; full suite + repeat critical recovery/time tests after edits | pytest | recorded commands + exact counts | `raw_test_output/` |
| F | §7 Compact report, acceptance matrix, raw output, IEX findings, blockers vs backlog, isolation-task handoff | `results/task81_safety_baseline_closure/` | n/a | this directory |

Verdict rule: `BASELINE_VERIFIED_READY_FOR_ISOLATION` only if mandatory
safety/reporting/test rows (A*, B*, C*, E*) pass; otherwise `BASELINE_BLOCKED`
with exact remaining items. §5 (D*) unresolved data-coverage questions stated
explicitly and assessed for whether they block isolation engineering or only a
future pilot.

---

## Outcome (post-implementation)

| Rows | Landed change | Regression tests | Status |
|---|---|---|---|
| A1–A11 | `talonx_piv/lifecycle.py` `reconcile` / `_refresh_non_terminal_orders` / `order_intent` BUY-guard order; `eod_lifecycle` INCONCLUSIVE mapping (commit `3dbac5d`) | `test_task81_reconciliation_admission.py` (14) — proven `11 failed / 3 passed` pre-fix | PASS |
| B1–B6 | `session_identity.py` `assess_session_recovery` + `SessionRecoveryRequired`; `cli.py` start/supervise refusal; `lifecycle.apply_broker_update` monotonic clamp + closed-position guard (commit `18dc8e3`) | `test_task81_recovery_binding.py` (15) | PASS |
| C1–C7 | `observability.build_integrated_projection` `source_health`; `reporting.build_session_report` `events_source_health`; `reporting.finalize_session_report`; `session_runner._run_eod_lifecycle` wiring; `eod_lifecycle` C7 (commit `fee25a0`) | `test_task81_source_health_and_reporting.py` (15) | PASS |
| D1–D2 | analysis only — `iex_findings.md` (commit `a2b14c8`) | `test_task81_iex_readiness_bookkeeping.py` (4) | RESOLVED (no defect) + 1 evidence-limited question, non-blocking for isolation |
| E1–E5 | weak-test strengthening; evidence-dir isolation; negative controls (commit `4085f58`) | `test_task81_guard_negative_controls.py` (3); strengthened `test_task72o_…::test_session_completed_never_emitted_on_failed`, `test_task77i_decision_ledger.py::test_persists_and_reloads…` | PASS |

Full-suite runs recorded in `raw_test_output/`. Post-§2 full suite:
`2560 passed, 1 skipped, 10 xfailed`, exit 0. Final full suite after all
edits: `2597 passed, 1 skipped, 10 xfailed`, exit 0
(`raw_test_output/full_suite_final.txt`). Verdict:
`BASELINE_VERIFIED_READY_FOR_ISOLATION`.
