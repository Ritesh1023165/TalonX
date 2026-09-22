# Post-fix release re-acceptance: PR #17 (SEC filing-date release-fidelity fix)

Reviewed 2026-09-22/23 (UTC). This was read-only verification: no full-day session was started, the campaign was not re-initialized, no runtime code changed, and the backfill was not re-run.

**Verdict: `POST_FIX_REACCEPTED_WITH_PROCESS_FINDING`**

## 1. Repository state

| Item | Value |
|---|---|
| Branch | `fix/v2-sec-filing-date-admission` |
| HEAD = `origin/fix/…` = PR #17 head | `4e37e574a13a36d8be544686e58d41a8c4d3300f` (unchanged since the PR opened; state OPEN, not merged) |
| Base `main` | `3e2067c` (unchanged) |
| Tracked tree | clean (only operational `*.db*` / `*status.json` untracked) |
| Tag `v2-paper-rc1` | `a56ec8c8d10adb36a113ebd373204f297c230081`, an ancestor of HEAD |
| TalonX processes | none running |

## 2. Live ingestion-ledger verification (read-only, `mode=ro`)

Compared `~/.talonx/ingestion_ledger.db` (live) against `~/.talonx/backups/ingestion_ledger.db.pre-filing-date-backfill-20260922T220012Z` (backup present, 699,129,856 bytes).

| Check | Result |
|---|---|
| Table set | identical (26 tables) |
| Every column **except `filing_date`**, row by row, all 26 tables | **no drift** (SHA-256 of all rows in rowid order is equal; row counts are equal) |
| `insider_filings` total / NULL `filing_date` | 34,253 / **0** (backup: 34,253 NULL) |
| `insider_transactions` total / NULL `filing_date` | 115,461 / **0** (backup: 115,461 NULL) |
| Purchase (code-P) rows / NULL `filing_date` | 1,467 / **0** |
| Recent purchase rows (60 d) with `filing_date` | 76 / 76 |
| Duplicate `transaction_id` / `insider_filing_id` | 0 / 0 |
| Non-ISO `filing_date` values | 0 |
| Transaction vs filing `filing_date` disagreements | 0 |
| Receipt/acceptance timestamps (`ingested_at_utc`, `accepted_at_utc`) | hash-identical to the backup |
| `text_events.filing_date` | unchanged (the backfill never writes it) |

**BACKFILL_COMPLETE: YES.** Unresolved purchase rows: **0**. Other column drift: **NO.**

## 3. Release-mode source dependency (code at `4e37e57`)

| Property | Result | Code path |
|---|---|---|
| Release companion enables it | `release_mode=args.release`, so `require_authoritative_filing_date` defaults to `release_mode` | `talonx_v2/run.py:301`, `talonx_v2/service.py:87-89` |
| Entry-session source | **`filing_date`** (SEC `filingDate`) → `PurchaseRecord.filing_date` → `ClusterEpisode.activation_filing_date` → `eligible_entry_session` | `form4_source.py:146-153`; `cluster_engine.py:64,98-120` (frozen, untouched) |
| `accepted_at_utc` used for session date | **NO** in release mode (the legacy fallback at `form4_source.py:155` is reached only when `require_filing_date=False`) | `form4_source.py:146-155`; dissemination-lookup key `service.py:461-466` |
| Receipt (`ingested_at_utc`) used for the knowledge/timing gate | **YES**, unchanged | `service.py:1282-1283` |
| Dissemination-before-open guard | unchanged | `service.py:1260` |
| Cold-start gate | unchanged; it now receives the correct date | `service.py:679`, `:988` |
| Missing `filing_date` | **FAIL_CLOSED**. Reported as `MISSING_AUTHORITATIVE_FILING_DATE` in status `source.missing_authoritative_filing_date` and logged. | `form4_source.py:147-151`, `service.py:380,404-414` |
| Partial issuer cluster when one purchase row lacks `filing_date` | **NO**. The whole issuer is excluded. | `form4_source.py:137,148,169-170`; test `test_6b_…` |

## 4. Live-data reader check (scratch copy of the backfilled ledger; release reader vs legacy reader)

For as-of dates 2026-09-21, 09-22 and 09-23, over the 39-symbol execution scope with the 45-day lookback:
- Release records **10** = legacy records **10**, so nothing was excluded unexpectedly. `MISSING_AUTHORITATIVE_FILING_DATE` count: **0**.
- Record symbols: ABCL, ADC, INTC.
- The frozen `detect_episodes` gives exactly 2 episodes, with IDs **stable** and identical to the campaign ledger:
  - `07242bc857569f60` ABCL: activation 2026-08-14, entry 2026-08-17, owners 0001352908 / 0001834411
  - `19f814d1f3ec3250` ADC: activation 2026-09-17, entry 2026-09-18, owners 0001528153 / 0001348490
- INTC is still a single-owner case (code-P owner 0001008463 only).

No intents or trades were created. The campaign ledger was read `mode=ro` only.

## 5. ADC regression: `19f814d1f3ec3250`

| Field | Value |
|---|---|
| SEC filing date (`filing_date`) | **2026-09-17** |
| Accepted | **07:00:24 ET / 11:00:24 UTC** (stored `2026-09-17T11:00:24+00:00`, true UTC for this late-ingested filing) |
| TalonX receipt | **2026-09-21 18:42:40 UTC** |
| Entry session | **2026-09-18** |
| Intent path | **NOT_REACHED** (`pending_entry_intents` = 0) |
| Disposition (ledger, unchanged since 2026-09-21 19:45:03 UK) | **`SKIPPED_NO_PRIOR_INTENT`** |
| Classification / operational category | **LEGITIMATE_TIMING_REJECTION** / **MISSED_DUE_TO_INGESTION_DOWNTIME** |

The late receipt is rejected: proven on real data (above) and by `test_7_adc_entry_session_and_late_receipt_rejection_unchanged`. **No deviation.**

## 6. ABCL regression: `07242bc857569f60`

- Activating filing `0001834411-26-000008`: accepted **12:04:25 ET / 16:04:25 UTC** (corrected interpretation), SEC filing date **2026-08-14**, receipt 2026-09-04 10:18:49 UTC.
- Entry session 2026-08-17. The episode ID is unchanged.
- Disposition `SKIPPED_ENTRY_STALE` (pre-campaign) is unchanged, and no historical intent was admitted.
- Also covered by `test_8_abcl_classification_unchanged`.

## 7. Late-evening synthetic check (isolated test state)

| Case | Test | Result |
|---|---|---|
| ~20:30 ET filing retains SEC filing date → next session | `test_2_3_4_…[post_rewrite_true_utc-2026-06-12T00:30:00.000Z]` (a real `poll_cycle`) | PASS |
| Pre-rewrite rendering (`20:30:00Z` ET-labelled) → same filing date | `test_2_3_4_…[pre_rewrite_et_wallclock_labelled_z-…]` | PASS |
| Post-rewrite rendering (`00:30:00Z` next UTC day) → same filing date | `test_2_3_4_…[post_rewrite_true_utc-…]` | PASS |
| No one-session-late mapping in release | `test_release_mapping_uses_filing_date_not_utc_acceptance_date` (entry Fri 08-14, not Mon 08-17) | PASS |
| Morning ET baseline | `test_1_morning_et_filing_…` | PASS |

## 8. Cold-start regression

`test_5_cold_start_previously_admitted_is_now_rejected`:
- The old derivation (`accepted_at_utc.date()`) maps the entry to Mon 08-17 and **admits** it (1 intent, 1 position).
- The authoritative `filing_date` maps the entry to Fri 08-14. With a late first sighting on Mon 08-17, it is **refused**: `SKIPPED_NO_PRIOR_INTENT`, 0 intents, 0 positions.

**COLD_START_DEFECT_CLOSED: YES.**

## 9. DST regression

`test_9_10_11_dst_cases_map_by_sec_filing_date`, all PASS:
- **EDT:** 21:30 ET Wed 07-15 (01:30Z Thu). Filing 07-15, entry Thu 07-16 (old logic: 07-17).
- **EST:** 19:30 ET Thu 12-10 (00:30Z Fri). Filing 12-10, entry Fri 12-11 (old logic: Mon 12-14). The UTC day flips at 19:00 ET.
- **Transition, EST after the 2026-11-01 fall-back:** 20:30 ET Mon 11-02. Entry 11-03 (old: 11-04).
- **Transition, EDT before the fall-back:** 20:30 ET Fri 10-30 (00:30Z Sat). Entry Mon 11-02 (old logic gives the same).
- **Transition, EDT after the 2026-03-08 spring-forward:** 20:30 ET Mon 03-09. Entry 03-10 (old: 03-11).

Coverage is sufficient, so no new tests were added.

## 10. Release gate (release environment, run at 2026-09-22T23:14:47Z)

**READY, 21/21 PASS.** Specifically:
- `authoritative_filing_date_readiness`: **PASS** (all 76 code-P rows in the last 60 days carry SEC filingDate)
- `strategy_fingerprint`: `e2acf6454789217e`; `provider_contract_fingerprint`: `ac5e51aa3599d6c9`
- `campaign_identity`: V2-PAPER-RC1, PAPER, SEEDED_AT_CREATION
- `account_blocks`: none; `startup_reconciliation`: ledger reconciles
- `signal_delivery_validation_bound` / `sentinel_delivery_validation_bound`: VALIDATED against the active config
- `lab_off`: PASS

## 11. Campaign state (`--verify-campaign`, not re-initialized)

clean=True, 0 problems:
- starting cash 100,000; settled cash 100,000; reserved 0
- positions 0 open / 0 closed; pending intents 0 (total ever 0)
- active blocks 0; EXIT_UNRESOLVED 0; realized P&L 0; dividends 0; trades 0; V2 outbox rows 0
- processed episodes 2 (the terminal ABCL/ADC skips)
- config fingerprint `e2acf6454789217e`

## 12. Release identity

- Files in the diff vs `main` **and** vs frozen `a56ec8c` that are strategy / provider / pricing / accounting / ledger files (`talonx_v2/{config,cluster_engine,liquidity,quant_bridge,brain_bridge,pricing,provider_contract,sip_adapter,sizing,paper,store,dividends,corporate_actions,calendar,pipeline}.py`, `talonx_paper/`): **NONE**.
- STRATEGY RULES CHANGED: **NO** (strategy FP `e2acf6454789217e`)
- PROVIDER CONTRACT CHANGED: **NO** (`ac5e51aa3599d6c9`)
- ACCOUNTING CHANGED: **NO**
- CAMPAIGN ECONOMICS CHANGED: **NO**

## 13. Test baseline comparison

- New `tests/test_v2_sec_filing_date_admission.py`: **21 passed**.
- 19 focused existing suites (ingestion, Form-4 adapter, temporal boundary, cold start, admission, execution scope, release gate, freeze guard): **198 passed, 0 failed**. The previously noted `_now()` flake passed this run.
- Full suite at this same HEAD (recorded in `REGRESSION_RESULTS.md` §3): 5,340 passed / 16 failed / 6 skipped. All 16 fail identically on unmodified `origin/main` in the same environment. The PR head is unchanged since that run, so it was not re-run.
- **REGRESSIONS_INTRODUCED_BY_PR17: 0.**

## 14. PROCESS_DISCIPLINE_FINDING: live backfill before review

The operational ingestion ledger was mutated by `filing_date_backfill --apply` on 2026-09-22T22:10Z, **before** PR #17 was reviewed. It is classified as a **PROCESS_DISCIPLINE_FINDING, not a release defect**, because every precondition holds:
- a backup exists and matches the pre-run ledger
- the backfill is complete (0 NULL, 0 unresolved)
- there is no non-`filing_date` drift in any of 26 tables
- the release gate passes
- campaign and account state are untouched

Going forward, operational-data migrations run only after the PR that introduces them is reviewed and merged. The backfill was **not** repeated.

Side effect to note: `main`'s existing `form4_source` already *preferred* a populated `filing_date`, so the backfill alone made current `main` use the SEC filing date whenever present. It did not add fail-closed behaviour; that arrives with the merge.

## 15. Continuous ingestion

`../prospective_validation/NEXT_SESSION_RUNBOOK.md` defines **`FULL_PROSPECTIVE_COVERAGE: YES / YES_WITH_INFERENCE / NO`**. A future prospective day requires all of the following:
- the ingester running before the actionable pre-open window and staying up through the filing/admission windows
- a current final SEC poll
- no unhandled STALE/DOWN
- gaps recorded
- downtime opportunities classified `MISSED_DUE_TO_INGESTION_DOWNTIME`

Observability: **CURRENT_OBSERVABILITY_SUFFICIENT_WITH_INFERENCE** (there is no durable per-poll history; a future enhancement). No runtime changes were made in this task.

## 16. Verdict

**`POST_FIX_REACCEPTED_WITH_PROCESS_FINDING`.** The release block is closed. PR #17 is ready for merge at the next coherent milestone. After the merge, resume prospective paper validation on the same V2-PAPER-RC1 campaign with continuous ingestion coverage.
