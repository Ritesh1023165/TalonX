# Task 81-R1 — Acceptance Checklist (frozen before implementation)

Baseline: branch `research/talonx-strategy-validation`, HEAD
`81d18d5eed00e1aa4b630d31d3f1d1281091f77a` (== expected). Tracked tree
clean. `stash@{0}`/`stash@{1}` (task56) preserved, never reset. Reported
baseline suite: `2597 passed, 1 skipped, 10 xfailed` — re-run in progress
(`raw_test_output/baseline_full_suite.txt`).

Boundaries: no isolation, no live session, no broker mutation, no
notification, PAPER entries disabled, experimental auth absent, monitoring
paused, strategy `UNVALIDATED`, Gemini informational only. No changes to
`talonx_quant/{strategy,indicators,consumer,config}.py`. No portfolio /
historical-evidence resets.

| # | Requirement | Production boundary | Pre-fix reproduction | Regression test (node id) | Evidence |
|---|---|---|---|---|---|
| R2.1 | Genuine late BUY-fill completion after the partial share was already sold must re-open monitoring for the newly acquired share, not leave the order at qty 2 with the position CLOSED/0 | `talonx_piv/lifecycle.py:apply_broker_update` (BUY branch, CLOSED-position path) | `test_task81_r1_late_fill_recovery.py::test_reproduce_late_fill_leaves_order_2_position_closed_zero` (pre-fix) | `test_task81_r1_late_fill_recovery.py::test_late_fill_completion_reopens_monitoring_without_resurrecting_sold_qty` | RCA §2; raw pytest |
| R2.2 | Distinguish duplicate/stale updates (idempotent no-op) from genuine positive cumulative-fill deltas | same | — | `::test_duplicate_and_stale_updates_are_idempotent`, `::test_terminal_order_refill_is_noop` | RCA §2 |
| R2.3 | Prior exit qty / P&L / intent linkage / triggered-exit latch preserved through the re-open | same | — | `::test_reopen_preserves_exit_accounting_and_latch` | RCA §2 |
| R2.4 | Survive restart both before and after the late fill | `apfrom_dict`/`_load` + decision_engine `_flag_orphaned_positions` | — | `::test_restart_before_and_after_late_fill` | RCA §2 |
| R2.5 | Contradictory updates (filled_qty > requested; qty regression on non-terminal) fail visibly, never silently discard exposure | `apply_broker_update` | — | `::test_contradictory_overfill_fails_visibly` | RCA §2 |
| R2.6 | Same sequence with partial exits, cancellation races, out-of-order updates | `apply_broker_update` / `reconcile` | — | `::test_partial_exit_then_late_fill`, `::test_cancellation_race_then_late_fill`, `::test_out_of_order_updates` | RCA §2 |
| R3.1 | An internally cancelled/terminal order that the broker still reports open is a CONTRADICTION, not an accepted match (historical id membership is insufficient) | `talonx_piv/lifecycle.py:reconcile` + `_known_broker_order_identities` | `test_task81_r1_reconciliation_completeness.py::test_reproduce_cancelled_order_still_open_false_pass` (pre-fix) | `::test_cancelled_order_reported_open_is_contradiction_and_blocks` | RCA §3 |
| R3.2 | Outstanding broker orders matched against their exact durable intents with symbol/side/qty + compatible lifecycle state, not id membership alone | `reconcile` | — | `::test_broker_order_matched_only_with_consistent_symbol_side_qty` | RCA §3 |
| R3.3 | Orphan `ORDER_INTENT` (no recorded broker order) counted as unresolved; blocks admission-clear until verified match or documented operator resolution | `reconcile` unresolved-submissions set | `::test_reproduce_orphan_order_intent_excluded_from_unresolved` (pre-fix) | `::test_orphan_order_intent_is_unresolved_and_blocks_clear` | RCA §3 |
| R3.4 | Malformed/incomplete/contradictory responses still never clear the block; required fields + finite quantities validated | `reconcile` | — | `::test_malformed_order_row_does_not_clear`, existing `test_task81_reconciliation_admission.py` | RCA §3 |
| R3.5 | Block persists across restart; clears only after a complete, consistent pass; protective exits still sized vs verified holdings − outstanding sells; unknown exposure ⇒ no blind sell | `reconcile` + `order_intent` SELL | — | `::test_block_persists_and_clears_only_on_clean_pass`, `::test_unknown_exposure_no_blind_sell` | RCA §3 |
| R4.1 | Missing (absent) `session_identity.json` + OPEN position ⇒ `RECOVERY_REQUIRED`, not `FRESH_SESSION_CLEAN` | `talonx_piv/session_identity.py:assess_session_recovery` | `test_task81_r1_missing_identity_recovery.py::test_reproduce_missing_identity_with_open_position_returns_fresh` (pre-fix) | `::test_missing_identity_with_open_position_requires_recovery` | RCA §4 |
| R4.2 | Corrupt/unusable identity + unresolved orders/intents ⇒ `RECOVERY_REQUIRED`; existing evidence preserved; no identity minted/overwritten around unresolved state | `assess_session_recovery` + `resolve_session_identity` | — | `::test_corrupt_identity_with_pending_order_requires_recovery`, `::test_recovery_required_does_not_write_identity` | RCA §4 |
| R4.3 | Assessment `mode`, `reasons`, `unresolved_exposure` agree (no FRESH with exposure; reasons name the missing/corrupt identity) | `assess_session_recovery` | — | `::test_assessment_fields_are_consistent` | RCA §4 |
| R4.4 | CLI `start`/`supervise` refuse unsafe startup and print the required recovery; read-only/recovery commands proceed | `talonx_piv/cli.py:main` | — | `::test_cli_start_refuses_on_missing_identity_with_exposure` | RCA §4 |
| R4.5 | Coverage: missing + corrupt identity, pending/uncertain orders, open positions, incomplete EOD, unchanged-binding restart, genuinely clean startup | `assess_session_recovery` | — | `::test_recovery_matrix` (parametrized) | RCA §4 |
| R4.6 | Existing runtime/config/feed/date binding requirements preserved | `assess_session_recovery` | — | existing `test_task81_recovery_binding.py` + `::test_binding_requirements_unchanged` | RCA §4 |
| R5 | All 10 xfail + 1 skip enumerated with node id, marker reason, actual underlying result, root cause, safety/dual-run relevance, fix, disposition | `xfail_skip_disposition.md` | `--runxfail` run | disposition table | `xfail_skip_disposition.md`, raw output |
| R6 | IEX evidence claim corrected: count reconciliation ≠ establishing why bars missing / excluding source-time issues; minimum future evidence documented | `iex_evidence_correction.md` (Task 81 `iex_findings.md` preserved) | n/a | n/a | `iex_evidence_correction.md` |
| R7 | Negative controls prove each critical guard detects the forbidden outcome; deterministic clocks; temp state dirs; no writes to historical `results/task*` | new + existing `test_task81_guard_negative_controls.py` | n/a | `test_task81_r1_guard_negative_controls.py` | §7 |

Verdict rule: `BASELINE_VERIFIED_READY_FOR_ISOLATION` only when every
baseline/isolation blocker (R2.*, R3.*, R4.*) is closed and the full suite
reconciles exactly with zero unexpected failures; otherwise `BLOCKED` with
precise reasons. Retained xfail/skip (if any) each carry a specific
justification + impact assessment in `xfail_skip_disposition.md`.
