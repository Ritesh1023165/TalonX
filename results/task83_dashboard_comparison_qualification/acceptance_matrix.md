# Task 83 — Acceptance Matrix (frozen at start)

Start SHA: `e15345034666dd7d8670ff39f872c5986b89bdbd` (Task 82 tip)
Branch: `research/talonx-strategy-validation`
Baseline suite (expected): `2696 passed, 0 failed, 0 skipped, 0 xfailed`

Status column is filled in during verification (§7). Every row names the
exact test(s) / artifact(s) that close it.

**Status legend:** ✅ = closed and verified by the named test/artifact.
All Task 83 focused suites pass twice (`focused_run1.txt`, `focused_run2.txt`,
133 passed each). Final full-suite reconciliation: see `verification_report.md`.

## §1 Baseline

| # | Requirement | Test / Artifact | Status |
|---|---|---|---|
| 1.1 | HEAD == expected SHA | `verification_report.md` §Checkpoint; `git rev-parse HEAD` | ✅ |
| 1.2 | origin sync (`0 0`), clean tree | `verification_report.md` §Checkpoint | ✅ |
| 1.3 | Task 56 stashes preserved (`stash@{0}`,`stash@{1}`) | `verification_report.md` §Checkpoint | ✅ |
| 1.4 | no TalonX/Python processes running at start | `verification_report.md` §Checkpoint | ✅ |
| 1.5 | Task 82 isolation re-audited before edits | `architecture_and_ownership.md` §"Re-audit of Task 82" | ✅ |
| 1.6 | acceptance matrix frozen | this file, committed in first checkpoint | ✅ |
| 1.7 | baseline suite reproduced | `raw_test_output/baseline_full_suite.txt` | ✅ |

## §2 Read-only comparison collector

| # | Requirement | Test / Artifact | Status |
|---|---|---|---|
| 2.1 | observer only — never publishes/acks/suppresses/dedups/alters either pipeline | `test_task83_collector.py::test_collector_never_writes_to_observed_redis`, `::test_collector_subscribe_only_no_publish` | ✅ |
| 2.2 | Original stays on DB 0 + existing channels (collector adds nothing there) | `::test_collector_observed_bindings_unchanged` | ✅ |
| 2.3 | PIV stays on DB 1 + `talonx:piv:*` (collector adds nothing there) | `::test_collector_observed_bindings_unchanged` | ✅ |
| 2.4 | channel prefixes remain mandatory (pub/sub crosses DB) | `::test_pubsub_crosses_db_requires_prefix` | ✅ |
| 2.5 | collector state/cursors/dedup/output in its own namespace + storage | `::test_collector_namespace_is_isolated`, `test_task83_offline_dual_run.py` scenario 9 | ✅ |
| 2.6 | never reuses Original/PIV locks, cooldowns, metrics, state files, session IDs | `::test_collector_no_shared_lock_or_state_paths` | ✅ |
| 2.7 | restart does not duplicate previously recorded events | `::test_restart_does_not_duplicate_events`, `::test_cursor_recovery_after_crash` | ✅ |
| 2.8 | preserves late-arriving events and EOD records | `::test_late_event_recorded`, `::test_late_eod_updates_correct_session` | ✅ |
| 2.9 | detects malformed / duplicate / missing / stale / wrong-session inputs explicitly | `::test_detects_malformed_input`, `::test_detects_duplicate`, `::test_detects_missing_stage`, `::test_detects_stale_source`, `::test_detects_wrong_session` | ✅ |
| 2.10 | date-partitioned evidence dir: immutable manifest (date, session IDs, SHAs, config hashes, feeds, universes, modes, start/end) | `::test_manifest_fields_present_and_immutable` | ✅ |
| 2.11 | Original event/stage records stored | `::test_original_stage_records_written` | ✅ |
| 2.12 | PIV readiness/freshness/decisions/shadow/lifecycle/reconciliation records stored | `::test_piv_records_written` | ✅ |
| 2.13 | Original Telegram totals + mandatory PIV zero-attempt assertion | `::test_telegram_totals_and_piv_zero_assertion` | ✅ |
| 2.14 | per-symbol/stage comparison | `::test_per_symbol_stage_comparison` | ✅ |
| 2.15 | file hashes + missing/corrupt/stale-source diagnostics | `::test_evidence_file_hashes`, `::test_source_diagnostics_recorded` | ✅ |
| 2.16 | comparison identity carries all 12 fields | `::test_comparison_identity_fields` | ✅ |
| 2.17 | alignment deterministic + timezone-aware; never compares unrelated dates/sessions/symbols | `::test_alignment_is_deterministic_and_tz_aware`, `::test_no_cross_date_or_cross_session_comparison` | ✅ |
| 2.18 | divergence classified into the 9 classes | `::test_divergence_classification[*]` (all 9) | ✅ |
| 2.19 | operational agreement kept separate from alpha/profitability evidence | `::test_operational_agreement_not_alpha_evidence` | ✅ |

## §3 Browser dashboard (localhost:8787)

| # | Requirement | Test / Artifact | Status |
|---|---|---|---|
| 3.1 | Original / PIV / Compare read-only views added | `test_task83_browser_dashboard.py::test_routes_present` | ✅ |
| 3.2 | Original view: market/Redis health, Warmup/Quant/Brain/Core/Dispatch/Telegram lifecycle, local simulated-paper activity + positions | `::test_original_view_sections` | ✅ |
| 3.3 | PIV view: provider state, per-symbol readiness/freshness, stale/recovery episodes, quant funnel + rejections, decisions/shadow/PAPER lifecycle, reconciliation + EOD, UNVALIDATED/feed mode/exec mode/real-capital prohibition | `::test_piv_view_sections` | ✅ |
| 3.4 | Compare view: per-stage totals, per-symbol agreement/divergence, missing/late stages + reason codes, Original-simulated vs PIV-shadow/PAPER shown separately | `::test_compare_view_sections` | ✅ |
| 3.5 | health states explicit: RUNNING/HEALTHY/DEGRADED/STALE/MISSING/DISCONNECTED/NOT_RUN/UNREADABLE/WRONG_SESSION | `test_task83_health_contract.py::test_all_health_states_defined`, `::test_classify_*` | ✅ |
| 3.6 | missing/unreadable/stale never shown as plausible zero | `::test_missing_source_not_zero`, `browser::test_not_run_is_not_zero_activity` | ✅ |
| 3.7 | "Original: NOT_RUN" never becomes "zero activity" | `browser::test_not_run_is_not_zero_activity` | ✅ |
| 3.8 | last-update timestamps + age shown | `browser::test_timestamps_and_age_present` | ✅ |
| 3.9 | never combine Original simulated P&L / PIV shadow P&L / PIV PAPER P&L / experimental | `browser::test_pnl_streams_separated`, `health::test_pnl_never_merged` | ✅ |
| 3.10 | every route GET/read-only; no launch/order/authorization/safety-control endpoints | `browser::test_all_routes_are_get_only`, `::test_no_mutating_endpoints` | ✅ |

## §4 Streamlit dashboard

| # | Requirement | Test / Artifact | Status |
|---|---|---|---|
| 4.1 | existing Original monitoring + settings behavior preserved | `test_task83_streamlit_dashboard.py::test_existing_sections_intact` | ✅ |
| 4.2 | read-only PIV & Comparison section added with all listed panels | `::test_piv_comparison_section_panels` | ✅ |
| 4.3 | trading-date/session selection | `::test_date_session_selection` | ✅ |
| 4.4 | shadow/PAPER outcomes separated by execution class | `::test_outcomes_separated_by_execution_class` | ✅ |
| 4.5 | source-health + archive-integrity diagnostics shown | `::test_archive_integrity_diagnostics` | ✅ |
| 4.6 | no PIV activation / broker / experimental / safety override / strategy-approval controls | `::test_no_control_widgets` | ✅ |

## §5 Offline Original+PIV rehearsal

| # | Scenario | Test | Status |
|---|---|---|---|
| 5.1 | Original alone | `test_task83_offline_dual_run.py::test_scenario_01_original_alone` | ✅ |
| 5.2 | PIV alone (shadow) | `::test_scenario_02_piv_alone_shadow` | ✅ |
| 5.3 | Original + isolated PIV | `::test_scenario_03_original_plus_isolated_piv` | ✅ |
| 5.4 | duplicate Original rejected | `::test_scenario_04_duplicate_original_rejected` | ✅ |
| 5.5 | duplicate PIV rejected | `::test_scenario_05_duplicate_piv_rejected` | ✅ |
| 5.6 | overlapping/uncertain bindings rejected | `::test_scenario_06_overlapping_bindings_rejected` | ✅ |
| 5.7 | Redis DB separation + channel overlap rejected | `::test_scenario_07_db_separate_channel_overlap_rejected` | ✅ |
| 5.8 | correct DB + prefixed channels accepted | `::test_scenario_08_correct_db_prefixed_channels_accepted` | ✅ |
| 5.9 | collector observes both without republishing | `::test_scenario_09_collector_observes_without_republish` | ✅ |
| 5.10 | PIV outbound Telegram attempts == 0 | `::test_scenario_10_piv_outbound_telegram_zero` | ✅ |
| 5.11 | PIV inbound Telegram poller starts 0 times | `::test_scenario_11_piv_inbound_poller_zero_starts` | ✅ |
| 5.12 | PIV shadow mode == 0 broker-mutating calls | `::test_scenario_12_shadow_zero_broker_mutations` | ✅ |
| 5.13 | Original notifications unaffected | `::test_scenario_13_original_notifications_unaffected` | ✅ |
| 5.14 | missing/stale/corrupt/wrong-session states appear honestly | `::test_scenario_14_bad_source_states_honest` | ✅ |
| 5.15 | collector/dashboard restart does not duplicate events | `::test_scenario_15_restart_no_duplicate` | ✅ |
| 5.16 | late EOD record updates correct archived session | `::test_scenario_16_late_eod_correct_session` | ✅ |
| 5.17 | one pipeline failure does not suppress/corrupt the other | `::test_scenario_17_one_failure_isolated` | ✅ |
| 5.18 | reconciliation/recovery-required retains priority over startup markers | `::test_scenario_18_recovery_priority_over_startup` | ✅ |
| 5.19 | abrupt termination releases only owned locks, preserves evidence | `::test_scenario_19_abrupt_termination_owned_locks_only` | ✅ |
| 5.20 | dashboard + collector remain read-only throughout | `::test_scenario_20_read_only_throughout` | ✅ |

## §6 Source-health / known limitation

| # | Requirement | Test / Artifact | Status |
|---|---|---|---|
| 6.1 | PIV lacks durable QuantStateStore exposed as explicit capability/health limitation | `test_task83_health_contract.py::test_quant_state_store_limitation_exposed`, observability projection `capability_limitations` | ✅ |
| 6.2 | isolated configured path does NOT imply persistence exists | `::test_isolated_path_not_implied_as_persistence` | ✅ |
| 6.3 | QuantStateStore NOT implemented (documented as separate blocker) | `remaining_blockers.md`; `git diff` shows no QuantStateStore | ✅ |
| 6.4 | IEX receipt-time vs source-time kept unresolved; schema supports both timestamps later; no live/history acquisition | `::test_schema_supports_both_bar_timestamps`, `remaining_blockers.md` | ✅ |

## §7 Verification

| # | Requirement | Artifact | Status |
|---|---|---|---|
| 7.1 | focused collector/isolation/dashboard suites run twice | `raw_test_output/focused_run1.txt`, `focused_run2.txt` | ✅ |
| 7.2 | full repository suite | `raw_test_output/final_full_suite.txt` | ✅ |
| 7.3 | collected/pass/fail/skip/xfail counts reconciled exactly | `verification_report.md` §Count reconciliation | ✅ |
| 7.4 | impacted checks + final full suite rerun after any later edit | `verification_report.md` | ✅ |
| 7.5 | final source-level audit vs every acceptance row | this matrix, Status column | ✅ |

## §8 Boundaries

| # | Requirement | Evidence | Status |
|---|---|---|---|
| 8.1 | strategy UNVALIDATED / profitability UNDETERMINED / experimental disabled / PAPER pilot unauthorized | `verification_report.md` §Boundaries | ✅ |
| 8.2 | real capital / shorts / options / probes prohibited | unchanged; `verification_report.md` §Boundaries | ✅ |
| 8.3 | protected `talonx_quant/{strategy,indicators,consumer,config}.py` unchanged | `git diff --stat e153450..HEAD -- talonx_quant/` empty | ✅ |
| 8.4 | monitoring paused; Task 56 stashes preserved | `git stash list` | ✅ |
| 8.5 | no live session / broker call / Telegram API / holdout / tuning / external data / production activation | `verification_report.md` §"Operational actions not performed" | ✅ |
| 8.6 | bounded checkpoints + sanitized evidence committed under `results/task83_dashboard_comparison_qualification/` | `git log` | ✅ |
