# RI-3 validation record

All commands ran from `C:\workspace\TalonX` in PowerShell with
`TALONX_TEST_NETWORK_GUARD=1`, `PYTHONUTF8=1`, and a workspace-local
`TALONX_NOTIFY_DB_PATH` for the final runs. The test guard blocks external
network access. Every new database was created under an isolated pytest temp
root. `TALONX_RI3_EVIDENCE_DIR` selected this directory for the synthetic
JSON and HTML fixture export. No live server or Telegram transport was used.

The command format was:

```powershell
$env:TALONX_TEST_NETWORK_GUARD='1'
$env:PYTHONUTF8='1'
$env:TALONX_NOTIFY_DB_PATH='C:\workspace\TalonX\.ri3_missing_notifications.db'
$env:TALONX_RI3_EVIDENCE_DIR='C:\workspace\TalonX\docs\research\evidence\v2_release_integration_ri3'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.ri3_tests_07 tests/test_ri3_operator.py tests/test_ri1_campaign_identity.py tests/test_ri2_notification_routing.py tests/test_package1_settlement_integrity.py tests/test_package2_account_blocks.py tests/test_package2_acceptance_review.py tests/test_package3_pricing_timing.py tests/test_package4_sizing_accounting.py tests/test_delivery_pipeline.py tests/test_dispatch_consumer.py tests/test_task119_paper_performance.py tests/test_task100c_unified_dashboard.py tests/test_task117_phase0_dashboard_readiness.py tests/test_task110_v2_integration.py --tb=short
```

Result: **409 passed, 12 aiohttp NotAppKey warnings**. Output:
`tests_regression.txt`. This run covers the actual dashboard API/backend and
shipped JavaScript renderer plus RI-1/RI-2, Packages 1–4 and affected
Intelligence/Original/fee readers.

After the alternate V2 reader was made physically read-only:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.ri3_tests_08 tests/test_ri3_operator.py tests/test_task110_v2_integration.py --tb=short
```

Result: **80 passed**. Output: `tests_ri3.txt`.

After preserving primary `/ping` with the Research boundary:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.ri3_tests_09 tests/test_ri3_operator.py tests/test_dispatch_consumer.py tests/test_telegram_listener.py tests/test_telegram_ping_safety.py tests/test_task132_ping_discovery_section.py --tb=short
```

Result: **180 passed**. Output: `tests_reply_boundary.txt`.

The original sandbox test attempt could not create pytest temporary directories
(Windows ACL `PermissionError`); the isolated test commands above ran with
automatic elevation approval. Development runs found and corrected a missing
fixture allocation, a stale fee-description assertion and a syntax error;
none was classified as a pre-existing failure. An automatic approval review
once returned a usage-limit error; the action was not run, then user continuation
allowed the same isolated check. No regression failure remains.

## RI-3 required scenario coverage

| Scenario(s) | Proof |
|---|---|
| 1–6 campaign, seed, cash, reserve, available, cap | `test_full_operator_fixture`; `test_unknown_legacy_and_missing_database` |
| 7–11 OPEN/unresolved capacity/CLOSED/realized | `test_full_operator_fixture`; `test_alternate_v2_readers_preserve_unresolved`; `test_persisted_fee_economics_not_rebuilt` |
| 12–14 pending/deadline/cutover | `test_full_operator_fixture`; `test_expired_pending_remains_reserved_until_writer_changes_it`; RI-1 cutover suite |
| 15–16 block/evidence | `test_full_operator_fixture`; `test_clearance_attempt_history_visible` |
| 17–19 reconciliation healthy/failed/unknown | `test_full_operator_fixture`; `test_failed_reconciliation`; `test_unknown_legacy_and_missing_database`; `test_reconciliation_all_invariants_required` |
| 20–24 destinations, OFF, secrets, physical distinction | `test_full_operator_fixture`; `test_configuration_secrets_and_shared_physical_chat`; `test_research_no_primary_fallback`; `test_research_cannot_reuse_primary_bot_in_a_different_chat`; `test_historic_token_error_redacted` |
| 25–26 Intelligence route/failure | `test_intelligence_routes_trade_event`; `test_health_dedup_and_intelligence_failure_operations`; existing delivery pipeline tests |
| 27–28 degraded health/dedup | `test_live_tick_degraded_health_is_bounded`; `test_health_dedup_and_intelligence_failure_operations` |
| 29 intraday isolation | `test_original_default_transport_is_research_only`; `test_primary_listener_preserves_ping_but_blocks_original_details` |
| 30–31 stale PID, heartbeat/feed | `test_process_and_heartbeat`; `test_missing_identity_never_running_and_degraded_data`; dashboard readiness suite |
| 32 attention | `test_full_operator_fixture` |
| 33–34 no mutation/no send | `test_reads_never_mutate_or_send`; `test_status_cli_does_not_create_db` |
| 35 full fixture in operator and renderer | `test_full_operator_fixture`; `test_renderer_shows_end_to_end_fixture`; exported `operator_fixture.json`/`.html` |

Final command (same isolated environment):

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.ri3_tests_10 tests/test_ri3_operator.py tests/test_dispatch_consumer.py tests/test_telegram_listener.py tests/test_ri2_notification_routing.py --tb=short
```

Result: **190 passed**. Output: `tests_final.txt`. The frozen V2 strategy fingerprint was recomputed using `.\.venv\Scripts\python.exe research/scripts/task112_v2_release_fingerprint.py` and remained `e2acf6454789217e`. `git diff --check` passed.
