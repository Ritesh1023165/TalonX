# Regression results

All commands were run with `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` on branch `fix/v2-sec-filing-date-admission`.

## 1. New focused tests: `tests/test_v2_sec_filing_date_admission.py`: **21 passed**

| Required case | Test | Result |
|---|---|---|
| 1 morning ET → correct filing_date → correct next session (real poll cycle) | `test_1_morning_et_filing_persists_sec_filing_date_and_maps_to_next_session` | PASS |
| 2 ~20:30 ET → same SEC filing day although `accepted_at_utc` is the next UTC date | `test_2_3_4_…[post_rewrite_true_utc]` | PASS |
| 3 ingested **before** SEC's rewrite → same filing_date | `test_2_3_4_…[pre_rewrite_et_wallclock_labelled_z]` | PASS |
| 4 ingested **after** SEC's rewrite → same filing_date | `test_2_3_4_…[post_rewrite_true_utc]` | PASS |
| (no fabrication when SEC omits filingDate) | `test_live_ingest_without_sec_filing_date_does_not_fabricate_one` | PASS |
| (all live callers forward filingDate) | `test_all_live_callers_forward_sec_filing_date` | PASS |
| (release mapping uses filing_date; legacy unchanged) | `test_release_mapping_uses_filing_date_not_utc_acceptance_date`, `test_legacy_mapping_is_unchanged_outside_release_mode` | PASS |
| 5 cold start that the wrong UTC date admitted → now rejected (old derivation shown to admit: 1 intent / 1 position) | `test_5_cold_start_previously_admitted_is_now_rejected` | **PASS** |
| 6 missing filing_date in release → fail closed + reported (issuer-level, no partial cluster) | `test_6_missing_filing_date_fails_closed_and_is_reported`, `test_6b_one_missing_row_blocks_the_whole_issuer_no_partial_cluster` | **PASS** |
| 7 ADC: entry 2026-09-18, late receipt rejected (`SKIPPED_NO_PRIOR_INTENT`, 0 intents) | `test_7_adc_entry_session_and_late_receipt_rejection_unchanged` | **PASS** |
| 8 ABCL: classification unchanged (`SKIPPED_ENTRY_STALE`) | `test_8_abcl_classification_unchanged` | PASS |
| 9 EDT | `test_9_10_11_dst_cases_map_by_sec_filing_date[EDT…]` | **PASS** |
| 10 EST (the UTC day flips at 19:00 ET) | `…[EST…]` | **PASS** |
| 11 around the DST transitions (fall-back 2026-11-01 before and after; spring-forward 2026-03-08) | `…[EST_after_fall_back…]`, `…[EDT_before_fall_back…]`, `…[EDT_after_spring_forward…]` | PASS |
| backfill: dry run writes nothing; filing_date only; SEC value not `date(accepted_at_utc)`; recent + shard; unresolved stays NULL; idempotent; receipt/acceptance untouched | `test_backfill_*` (2) | PASS |
| release gate readiness PASS/FAIL/WARN/absent | `test_release_gate_filing_date_readiness` | PASS |
| allowlist closed and strategy-free | `test_release_fidelity_fix_allowlist_is_closed_and_strategy_free` | PASS |

## 2. Focused existing suites (ingestion, Form-4 adapter, V2 session mapping / admission / cold start / temporal boundary, release gate, freeze guard)

```
tests/test_v2_sec_filing_date_admission.py tests/test_insider_pipeline.py tests/test_insider_bulk_xml.py
tests/test_task131_identity_guard.py tests/test_service_runner_singleton.py tests/test_service_enrichment.py
tests/test_intelligence_edgar_normalize.py tests/test_task117_acceptance_timezone.py tests/test_task131_temporal_boundary.py
tests/test_task117_phase0_source_repairs.py tests/test_task117_live_lookback_boundary.py tests/test_task117_phase0_causality.py
tests/test_task113_stale_entry_guard.py tests/test_task117_overnight_e2e.py tests/test_task117_execution_scope.py
tests/test_task131_remediation_directive6.py tests/test_task131_targeted_remediation.py tests/test_task131_concurrent_admission.py
tests/test_pre_full_day_cleanup.py tests/test_v2_final_release_acceptance.py
```
Result: **218 passed, 1 failed**.

The one failure is `test_task113_stale_entry_guard.py::test_stale_episode_skipped_every_tick`, a **pre-existing timing flake unrelated to this fix**:
- It asserts `first_seen_at == updated_at` on a disposition row.
- `V2Store.record_disposition` (`talonx_v2/store.py:619`, untouched) calls `_now()` twice, so the two can differ by a microsecond.
- The test overrides `_records` with in-memory rows, so no changed code path is exercised.
- Re-runs of the file: 4/4 passed, three times in a row.
- Not fixed here, because `store.py` is a ledger file outside this task's scope. Recorded as a bounded follow-up.

After the fix commit (so the freeze-ancestry test sees HEAD), `tests/test_pre_full_day_cleanup.py` plus the new file gave **45 passed**. That includes `test_19` (the ops-hardening allowlist, unchanged) and `test_20` (HEAD = frozen release + only declared changes).

## 3. Full suite (`pytest -q -p no:cacheprovider tests`)

**5,340 passed, 16 failed, 6 skipped** in 55 min 18 s.

**All 16 failures are pre-existing or environmental. None is caused by this fix.** Proof: the exact 16 tests were re-run on a clean `git worktree` of **unmodified `origin/main` (`3e2067c`)**, with the same untracked repo-root runtime files copied in (`v2_lane.db`, `v2_release_rc1*.db`, `*status.json`, `notifications.db`). The result was **16 failed, identical set**.

| Failing tests | Cause (identical on unmodified main) |
|---|---|
| `test_task102…::test_36`, `test_task104…::test_32_33`, `test_task111…::test_item3`, `test_task112…::test_03` | Original/V1 fingerprint pins (`2ae6216bca70` era) vs the current V1 `ed8272fe568d`; pre-existing |
| `test_task117_migration.py` (5), `test_task117_deployment_rehearsal…`, `test_task117_release_rehearsal…` | they MD5-pin the repo-root legacy `v2_lane.db` (last modified **2026-09-15**, now `cff00b0f…`, not in the expected set); environmental drift, and that file is untouched by this work |
| `test_task69p…::test_handle_ping_pipeline_line…` | the `/ping` reply splits into 2 messages when repo-root runtime status data is present, and the test reads only the last part; environmental |
| `test_ri3_operator…`, `test_task118a_dashboard_message_count…`, `test_task131_dashboard_broad_discovery…`, `test_task118a_checkpoint_daemon_restart…` | pre-existing on main (the last is also timing-sensitive) |

Plus the pre-existing flake in §2 (`test_task113…::test_stale_episode_skipped_every_tick`), which passed in the full run.

## 4. Release identity and gate (live, release environment)

- Strategy fingerprint: `e2acf6454789217e` (PASS). Provider contract: `ac5e51aa3599d6c9` (PASS).
- `python -m talonx_v2.release_gate` gives **READY, 21/21 checks**, including the new `authoritative_filing_date_readiness`: PASS, "all 76 code-P rows in the last 60d carry SEC filingDate".
- `frozen_release_ok(HEAD, a56ec8c)` returns True ("only docs/tests/pin/declared ops-hardening and release-fidelity-fix files changed").
- `--verify-campaign` gives clean=True, cash $100,000, 0 open, 0 intents, 0 trades, 0 blocks, realized P&L 0, 2 processed (terminal skip) episodes. **The campaign is unchanged.**

## 5. Bounded follow-ups surfaced (not fixed here)

- `V2Store.record_disposition` stamps `first_seen_at`/`updated_at` with two separate `_now()` calls, which makes one test flaky.
- The stale fingerprint/MD5 pins and the `/ping` 2-part capture in the tests listed in §3 are pre-existing test-maintenance items.
- `accepted_at_utc` remains mixed legacy semantics. A future ingestion-lane task could normalise it, for example from the SGML header. It no longer affects V2 session mapping.
- There is no durable per-poll ingestion history (observability, `CURRENT_OBSERVABILITY_SUFFICIENT_WITH_INFERENCE`).
