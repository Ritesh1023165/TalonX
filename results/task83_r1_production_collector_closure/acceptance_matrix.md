# Task 83-R1 — Acceptance Matrix (frozen before editing)

Start SHA: `fd9b66ac1ee9ba64ead44c5cc764c285a4d2c36b`
Branch: `research/talonx-strategy-validation`
Baseline suite (expected): `2793 passed, 0 failed, 0 skipped, 0 xfailed`

Every requirement maps to an exact **production-path** test (real
`CollectorService` / `ComparisonCollector` / archive reader / dashboard
projection — not helper-only). Status filled during §8 verification.

## §1 Baseline

| # | Requirement | Test / Artifact | Status |
|---|---|---|---|
| 1.1 | HEAD == `fd9b66a`; origin sync `0 0`; clean tree | `verification_report.md` §Checkpoint | ✅ |
| 1.2 | Task 56 stashes preserved | `git stash list` | ✅ |
| 1.3 | no running TalonX processes | `verification_report.md` §Checkpoint | ✅ |
| 1.4 | Task 81/82 safety + isolation behaviour preserved | adjacent suites pass unchanged (§8) | ✅ |
| 1.5 | acceptance matrix frozen before edits | this file, checkpoint 1 | ✅ |
| 1.6 | baseline suite reproduced (`2793 passed`) | `raw_test_output/baseline_full_suite.txt` | ✅ |

## §2 Immutable bindings vs mutable runtime status

| # | Requirement | Test / Artifact | Status |
|---|---|---|---|
| 2.1 | reproduce the false `manifest_conflict` from `generated_at` (two passes, +5 s, identical bindings) | `test_task83_r1_manifest.py::test_repeated_pass_different_clock_no_conflict` | ✅ |
| 2.2 | immutable manifest contains ONLY stable identity/binding fields | `::test_immutable_manifest_field_whitelist` | ✅ |
| 2.3 | manifest excludes collection time / redis reachability / session-enabled / health / counters | `::test_manifest_excludes_mutable_fields` | ✅ |
| 2.4 | manifest written only after trading date + PIV session/bindings available | `::test_manifest_deferred_until_bindings_available` | ✅ |
| 2.5 | identical bindings across repeated passes never conflict regardless of elapsed time | `::test_repeated_pass_different_clock_no_conflict`, `::test_manifest_stable_over_many_passes` | ✅ |
| 2.6 | genuine change to session id / runtime SHA / config hash / feed / redis / channel / universe / execution binding fails visibly, original manifest not overwritten | `::test_binding_change_fails_visibly[*]` (8 params) | ✅ |
| 2.7 | generated/updated timestamps, transport health, lifecycle status, collection stats live in a separate mutable, atomically-written runtime-status file | `::test_runtime_status_file_written_atomically`, `::test_runtime_status_has_mutable_fields` | ✅ |
| 2.8 | EOD update updates the correct session evidence without changing immutable identity | `::test_eod_update_keeps_immutable_manifest`, `test_task83_r1_production_loop.py` scenario 33 | ✅ |
| 2.9 | changing-clock / health-transition / EOD-transition / restart / genuine-conflict all covered | `test_task83_r1_manifest.py` + `test_task83_r1_production_loop.py` | ✅ |

## §3 Session- and event-safe comparison

| # | Requirement | Test / Artifact | Status |
|---|---|---|---|
| 3.1 | never compare records from different PIV sessions | `test_task83_r1_alignment.py::test_different_piv_sessions_never_aligned` | ✅ |
| 3.2 | Original run scope derived only from verified runtime metadata/bindings, labelled collector-derived (not an Original-emitted session id) | `::test_original_scope_is_collector_derived_and_labelled` | ✅ |
| 3.3 | Original scope unavailable/ambiguous → `UNSCOPED`/`SOURCE_UNAVAILABLE`; no event-level agreement asserted | `::test_unscoped_original_no_event_agreement` | ✅ |
| 3.4 | event-level alignment uses stable event identity: `decision_id` when present, else documented causal identity (stage, symbol, source-bar time/event identity, payload fingerprint) | `::test_event_identity_prefers_decision_id`, `::test_causal_identity_when_no_decision_id` | ✅ |
| 3.5 | aggregate counters use explicit aggregate record type/key; compare aggregate values, not collapsed events | `::test_aggregate_records_compared_as_aggregates` | ✅ |
| 3.6 | multiple AAPL Quant/Decision/Lifecycle records on one day remain distinct | `::test_multiple_same_symbol_events_stay_distinct` | ✅ |
| 3.7 | late arrivals append/re-align the correct event without replacing unrelated evidence | `::test_late_arrival_does_not_replace_unrelated`, production loop scenario 22/29 | ✅ |
| 3.8 | same-day restart with different session/run scope stays separated | `::test_same_day_two_sessions_separated`, production loop scenario 23 | ✅ |
| 3.9 | per-stage totals count actual comparable records or explicitly-labelled aggregates | `::test_per_stage_totals_are_typed` | ✅ |

## §4 Honest transport health

| # | Requirement | Test / Artifact | Status |
|---|---|---|---|
| 4.1 | `ComparisonCollector` receives Redis client/connection state from `CollectorService` | `test_task83_r1_transport_health.py::test_service_passes_transport_snapshot_into_collect` | ✅ |
| 4.2 | per-pipeline health: attempted / connected / subscribed channels / last message / last error / reconnect count / state (RUNNING/STALE/DISCONNECTED/NOT_RUN) | `::test_transport_health_state_machine[*]` | ✅ |
| 4.3 | thread-safe snapshot passed into every collection pass | `::test_snapshot_is_a_copy_not_live_ref` | ✅ |
| 4.4 | failed subscription → `DISCONNECTED`, not `NOT_RUN` | `::test_failed_subscription_is_disconnected_not_not_run` | ✅ |
| 4.5 | one pipeline's disconnection does not change the other's health or suppress its evidence | `::test_one_sided_failure_isolated`, production loop scenario 25/26 | ✅ |
| 4.6 | Original metrics reads use a genuinely read-only client; read failures recorded | `::test_original_metrics_client_is_read_only`, `::test_metrics_read_failure_recorded` | ✅ |
| 4.7 | PIV Pub/Sub health represented separately from PIV state-file health | `::test_piv_pubsub_health_separate_from_state_file_health` | ✅ |
| 4.8 | reconnect produces recovery evidence without losing buffered events | `::test_reconnect_recovery_evidence_no_event_loss`, production loop scenario 27 | ✅ |
| 4.9 | buffer drain + collection race-safe; messages arriving during a pass remain for next pass | `::test_messages_during_pass_retained` | ✅ |
| 4.10 | collector writes confined to collector-owned state/evidence | `::test_collector_writes_confined` | ✅ |

## §5 Authoritative PIV Telegram zero-attempt evidence

| # | Requirement | Test / Artifact | Status |
|---|---|---|---|
| 5.1 | session-scoped PIV notification ownership persisted at runtime construction (outbound enabled/disabled; sender constructed/absent; inbound poller constructed/started/absent) | `test_task83_r1_notification_telemetry.py::test_runtime_persists_notification_ownership` | ✅ |
| 5.2 | durable outbound attempt/failure/success counters persisted at the actual send boundary | `::test_outbound_counters_persist_at_send_boundary` | ✅ |
| 5.3 | inbound poller start/attempt counters persisted at its boundary | `::test_inbound_poller_counters_persist` | ✅ |
| 5.4 | missing telemetry → `MISSING`/`UNVERIFIED`, never zero | `::test_missing_telemetry_is_unverified_not_zero` | ✅ |
| 5.5 | archive asserts zero only when telemetry exists for the matching PIV session AND outbound+inbound disabled AND counters verified zero | `::test_zero_assertion_requires_all_three_conditions` | ✅ |
| 5.6 | fake enabled sender with one attempted send → archives one attempt even if sending raises/fails | `::test_enabled_sender_failed_send_archives_one_attempt` | ✅ |
| 5.7 | PIV disabled by default; no real Telegram request | `::test_piv_disabled_by_default`; no network in any test | ✅ |
| 5.8 | Original notification ownership unchanged | `::test_original_notification_ownership_untouched` (grep + adjacent suite) | ✅ |

## §6 Fail-closed archive integrity

| # | Requirement | Test / Artifact | Status |
|---|---|---|---|
| 6.1 | required archive file set / schema defined explicitly | `test_task83_r1_archive_integrity.py::test_required_file_set_defined` | ✅ |
| 6.2 | verification detects: required missing / unexpected files / malformed JSON+JSONL / missing+duplicate `_id` / hash mismatch / truncated streams / wrong date+session / incomplete hash inventory | `::test_verifier_detects[*]` (8+ params) | ✅ |
| 6.3 | malformed evidence records never silently discarded | `::test_malformed_jsonl_not_silently_skipped` | ✅ |
| 6.4 | before modifying an existing archive, verify prior integrity; on failure stop writing, report `UNREADABLE`/`DEGRADED`, do not regenerate hashes over corruption | `::test_write_refused_on_pre_existing_corruption` | ✅ |
| 6.5 | atomic writes for mutable projections / status / hash index | `::test_mutable_writes_are_atomic` | ✅ |
| 6.6 | every collector write path (incl. `collect-once`) guarded by collector-owned concurrency control | `::test_collect_once_takes_collector_lock`, `test_task83_r1_production_loop.py` scenario 32 | ✅ |
| 6.7 | repeated legitimate appends update integrity metadata only after successful writes | `::test_integrity_metadata_updated_after_write` | ✅ |
| 6.8 | readers/dashboards surface corruption; corrupt-input derived totals not shown as trustworthy | `test_task83_r1_archive_integrity.py::test_dashboard_flags_corruption`, `test_task83_r1_production_loop.py` scenario 31 | ✅ |
| 6.9 | committed evidence manifest verifies from a fresh clone against committed blob content (line endings canonical / git-normalized) | `fresh_clone_manifest_verification.md` + `evidence_manifest.json` `verify` mode; `.gitattributes` | ✅ |
| 6.10 | no self-referential final-SHA/hash design; content commit recorded explicitly; manifest generator + manifest itself excluded | `evidence_manifest.json` (`content_commit`, `excluded`); `verification_report.md` | ✅ |

## §7 Expanded offline rehearsal

| # | Scenario (21–33 new; 1–20 retained) | Test | Status |
|---|---|---|---|
| 7.0 | original 20 scenarios retained and pass | `tests/test_task83_offline_dual_run.py` | ✅ |
| 7.21 | two real collector passes, different clocks, stable bindings | `test_task83_r1_production_loop.py::test_s21_two_passes_stable_bindings_no_conflict` | ✅ |
| 7.22 | same-day multiple decisions for one symbol | `::test_s22_same_day_multiple_decisions_one_symbol` | ✅ |
| 7.23 | same-day different session/run scopes | `::test_s23_same_day_two_run_scopes_separated` | ✅ |
| 7.24 | Original scope unavailable | `::test_s24_original_scope_unavailable` | ✅ |
| 7.25 | Original Redis disconnected while PIV healthy | `::test_s25_original_redis_down_piv_healthy` | ✅ |
| 7.26 | PIV Pub/Sub disconnected while Original healthy | `::test_s26_piv_pubsub_down_original_healthy` | ✅ |
| 7.27 | disconnect → reconnect with buffered message preservation | `::test_s27_reconnect_preserves_buffered_messages` | ✅ |
| 7.28 | missing PIV notification telemetry | `::test_s28_missing_piv_notification_telemetry` | ✅ |
| 7.29 | disabled PIV notification with verified zero counters | `::test_s29_disabled_notification_verified_zero` | ✅ |
| 7.30 | enabled fake sender with a persisted failed attempt | `::test_s30_enabled_sender_persisted_failed_attempt` | ✅ |
| 7.31 | archive corruption before the next collection pass | `::test_s31_archive_corruption_before_next_pass` | ✅ |
| 7.32 | concurrent collect-once / service writer contention | `::test_s32_concurrent_writer_contention` | ✅ |
| 7.33 | fresh-clone evidence-manifest verification | `::test_s33_fresh_clone_manifest_verification` | ✅ |

## §8 Verification & boundaries

| # | Requirement | Artifact | Status |
|---|---|---|---|
| 8.1 | focused Task 83 / 83-R1 suites run twice | `raw_test_output/focused_run{1,2}.txt` | ✅ |
| 8.2 | adjacent Task 81/82 isolation, lifecycle, dashboard, notification suites | `raw_test_output/adjacent_suites.txt` | ✅ |
| 8.3 | full repository suite | `raw_test_output/final_full_suite.txt` | ✅ |
| 8.4 | baseline + newly collected reconciled exactly; 0 failed/skipped/xfailed/xpassed/errors | `verification_report.md` §Count reconciliation | ✅ |
| 8.5 | rerun affected + full suite after any later executable change | `verification_report.md` | ✅ |
| 8.6 | final source audit vs every acceptance row | this matrix Status column | ✅ |
| 8.7 | no launch / market session / broker / Telegram / Redis prod mutation / PAPER / experimental / monitoring resume / holdout / alpha tuning / protected Quant change | `verification_report.md` §Boundaries | ✅ |
| 8.8 | strategy UNVALIDATED, profitability UNDETERMINED, PIV notification disabled, PAPER entries disabled, real capital/shorts/options/leverage prohibited | `verification_report.md` §Boundaries | ✅ |
| 8.9 | scoped checkpoints + sanitized evidence under `results/task83_r1_production_collector_closure/` | `git log` | ✅ |
