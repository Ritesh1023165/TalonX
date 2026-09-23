# PR #19 final review and canary hardening (2026-09-23 night)

| | |
|---|---|
| **Scope** | Reliability hardening only. No weight, threshold, hard gate, cap, universe filter or candidate rule changed. `PREMARKET_RESEARCH_V1` fingerprint is `62ba413daf85e674` before and after (tested). |
| **V2** | Untouched: strategy `e2acf6454789217e`, provider `ac5e51aa3599d6c9`, 39-name scope, V2-PAPER-RC1. |
| **Start** | PR #19 head `2106cb7`; main `6bb89e1`; PR mergeable, state clean. |
| **Tests** | `tests/test_premarket_canary_hardening.py`: 44 tests. |

## Findings

### CRITICAL (2, both fixed)

**C1: a partial provider failure became a permanent data hole** (`alpaca_data.py`, `engine.LiveSource`)
- **Problem.** `AlpacaData.bars()` caught a failed 200-symbol batch, recorded the error and returned the other batches. `LiveSource.premarket()` then advanced one **global** `_fetched_to` to the window end. The failed symbols' interval was never requested again. The user's suspected failure sequence is confirmed step by step.
- **Live impact.** One transient HTTP error would silently erase up to 200 symbols' pre-market history for the rest of the day. Later scans would compute gap, volume and staleness from a hole, producing wrong features and false "stale" invalidations.
- **Fix.**
  - `bars_ex()` returns a `FetchResult` with `failed` symbols.
  - Each batch is retried once, and its pages are merged only if the whole batch succeeds.
  - `LiveSource` keeps a **per-symbol watermark** that advances only for symbols whose batch succeeded. A failed symbol is re-requested from its own watermark on every later scan, so the whole missing interval is recovered.
  - Symbols still incomplete are reported (`DATA_GAPS`) and held as `UNKNOWN:PROVIDER_INCOMPLETE`: no new candidate, no update, no invalidation.
- **Tests.** `test_PARTIAL_BATCH_FAILURE_DOES_NOT_ADVANCE_PAST_GAP`, `test_FAILED_BATCH_IS_RETRIED`, `test_NO_CANDIDATE_FROM_INCOMPLETE_PROVIDER_WINDOW`, `test_RECOVERY_FETCHES_MISSING_INTERVAL`.

**C2: live windows duplicated a bar every scan** (`engine.LiveSource`)
- **Problem.** Verified against the live API tonight: Alpaca's `end` parameter is **inclusive** (`[12:00,12:05]` returns 12:05, and `[12:05,12:10]` returns 12:05 again). Consecutive incremental windows therefore both returned the boundary bar, which was appended twice. That bar can also still be incomplete when first fetched.
- **Live impact.** Pre-market volume, dollar volume, bar count and activity/ADV were inflated in the **live** canary only (the replay's single prefetch was unaffected). That gave biased scores and a live ≠ replay divergence. The earlier live-path smoke test was affected.
- **Fix.** Requests end at `end − 1s`, and bars are stored under the canonical key (symbol, bar time) with last-write-wins, so a re-fetch replaces rather than doubles.
- **Tests.** `test_live_incremental_windows_never_duplicate_the_boundary_bar`, `test_live_and_replay_see_identical_premarket_volume`, `test_merge_bars_replaces_by_symbol_and_timestamp`, `test_a_failed_page_discards_the_whole_batch_attempt_so_retry_cannot_duplicate`.

### HIGH (4, all fixed)

| # | File | Problem | Live impact | Fix | Test |
|---|---|---|---|---|---|
| H1 | `engine` `daily()` | The first daily response was cached forever, even if batches failed | Failed symbols permanently `INSUFFICIENT_DAILY_HISTORY` (provider failure misreported as a data fact) | Pending set per symbol; re-requested each scan until success; reported as `PROVIDER_INCOMPLETE` | `test_partial_daily_download_is_not_cached_as_authoritative` |
| H2 | `alerts.decide` | Missing data (`gap=None`) was read as "gap faded", so the candidate went INVALIDATED | A false INVALIDATED alert on provider failure or lag | `UNKNOWN:*` is a **hold** (DATA_STATE_UNKNOWN). New universe-wide `provider_stale` guard (no fresh bar anywhere for 15 min → every symbol held). Genuine fades on complete data still invalidate. | `test_provider_failure_never_invalidates_an_existing_candidate`, `test_provider_stale_holds_every_symbol`, `test_genuine_market_fade_on_complete_data_still_invalidates`, `test_unknown_classification_is_a_hold_in_the_state_machine` |
| H3 | `engine._apply_alerts` | The alert was routed before the candidate was durably written | A crash between the two meant a restart re-created the candidate and sent a **second NEW alert** | Alert and candidate are persisted in one transaction (`PENDING_ROUTE`), then routed. `resume_pending_routes()` re-routes idempotently (outbox keyed by `event_id`). | `test_crash_between_persist_and_route_is_rerouted_once_on_restart` |
| H4 | `engine`, `store` | `candidates.delivered` was set to 1 when an alert was merely **ENQUEUED**, even to a disabled destination | "Delivered" was reported for alerts that were never sent | `delivered` = 1 **only** when the outbox reports `SENT`. New `alerts.delivery_state` is synced from the outbox each scan (PENDING / SENT / RETRY / FAILED / EXPIRED / HELD / AMBIGUOUS). Routing result and delivery state are separate fields. | `test_enqueued_is_not_delivered_until_the_outbox_reports_sent`, `test_record_only_mode_never_touches_an_outbox`, `test_undeliverable_research_alert_expires_instead_of_arriving_late` |

### MEDIUM (6, all fixed)

| # | File | Problem | Fix | Test |
|---|---|---|---|---|
| M1 | `catalysts.SecSubmissions` | A SEC failure looked like "no catalyst"; no 429 back-off; a failed refresh discarded the cached copy | `CATALYST UNKNOWN` (labelled and counted; still 0 score points, so frozen scoring is unchanged); 60 s pause of all SEC lookups after a 429; the previous copy is kept on refresh failure | `test_sec_failure_is_catalyst_unknown_not_none_and_429_backs_off`, `test_sec_refresh_failure_keeps_the_previous_copy`, `test_engine_labels_catalyst_unknown` |
| M2 | `catalysts.insider_open_market_owners` | An unreadable ledger was treated as 0 owners. In **replay**, a filing TalonX received after the decision time still counted (small look-ahead). | Returns `None` (unknown) on read failure; requires TalonX receipt ≤ decision time for every row | `test_insider_ledger_unreadable_is_unknown` |
| M3 | `__main__` run loop | A scan that overran could start the next pre-market scan after 09:30 ET | Guard: no pre-market scan at or after the open | `test_slow_scans_that_overrun_the_open_are_skipped`, `test_start_time_edges_never_scan_after_open` |
| M4 | `__main__` stop.flag | The flag was checked only while waiting. A restart with the flag present could still scan. | A same-session `stop.flag` → `run` **refuses** (exit 3) and says to rename it. It is checked before every scan, and never deleted. A previous session's flag lives in another directory and is harmless. | `test_same_session_stop_flag_stops_the_loop_and_is_preserved`, `test_cmd_run_refuses_to_restart_over_a_same_session_stop_flag`, `test_stale_previous_session_stop_flag_is_harmless` |
| M5 | `engine.track_outcomes` | A failed post-open fetch overwrote persisted outcomes with `OUTCOME_PENDING` / nulls | Symbols in a failed batch keep their last outcome and retry next cycle | covered by the source contract tests |
| M6 | `__main__` status | No operator view of provider completeness, cap usage, delivery states, outcomes or restarts | `status` shows every field requested (see below); `runs` table (restart count); new `report --date` evidence collector | `test_status_and_report_expose_the_operator_fields` |

### LOW (3)

- **L1.** `run` after the session's close now exits cleanly instead of idling.
- **L2.** SQLite: one writer (the engine) and read-only URI readers (`status`, `report`) with a 5–10 s busy timeout. Decisions are single transactions, and the schema migration is additive and idempotent. WAL is **not** enabled, because there is no concurrent writer and no evidence it's needed.
- **L3 (outside this lane): the 2026-09-22 Experimental incident is `INSUFFICIENT_EVIDENCE`.**
  - **Pattern (read-only log review).** Of 8 Experimental process starts since 09-15, only the 09-23 start logged `subscribed:`. After the dashboard line the consumer logged nothing and did **zero** exit-checks all day (09-22: 0 lines; 09-23: 922).
  - **Explanation.** This is consistent with the `consume()` task hanging before `pubsub.subscribe` returned, or dying silently under `asyncio.gather(..., return_exceptions=True)`. There is no traceback or process dump, so the cause can't be confirmed. No speculative change was made. The pre-market lane does not use Experimental.

## Provider completeness semantics (now)

| Item | Rule |
|---|---|
| Batch | Retried once; merged only if every page succeeded; otherwise all its symbols are `failed` |
| Live watermark | Per symbol; advances only for fetched symbols; a failed symbol re-requests from its own watermark (the whole gap) |
| Daily | Per-symbol pending set, re-requested each scan; never cached partially as authoritative |
| Scan funnel | `PROVIDER_INCOMPLETE` count, plus `provider.{PROVIDER_COMPLETE, PROVIDER_STALE, DATA_GAPS, DATA_GAP_SYMBOLS, FETCH{batches, failed_batches, retried_batches}, FAILED_BATCHES_TOTAL, RETRIED_BATCHES_TOTAL, LAST_SUCCESSFUL_PROVIDER_FETCH, CATALYST_UNKNOWN}` |
| Decisions on unknown data | HOLD: no new candidate, no MATERIAL_UPDATE, no INVALIDATED. Unknown is never classified as `NO_PREMARKET_PRINTS`, `INSUFFICIENT_DAILY_HISTORY` or `INSUFFICIENT_LIQUIDITY`. |

## SIP delay: one application, exact latency

At decision time T: `as_of = floor_minute(T − 15 min)`. The newest usable bar is the one **ending** at `as_of`, i.e. starting at `as_of − 1 min`. Live requests end at `as_of − 1 s`, which is never newer than the subscription allows (tested).

- **Effective lag** from the last trade included to the decision: **15:00 to 15:59** (15 min plus the sub-minute floor).
- **There is no second 15-minute delay.** `complete_bars_as_of` applies only the one-minute bar-completion rule to the already-delayed `as_of`.
- **Boundary tests:** T = 12:00:00 → 11:44 bar; 12:00:59 → 11:44; 12:01:00 → 11:45; 11:59:59 → 11:43.

## Restart / resume

| Behaviour | Result |
|---|---|
| Research DB and candidates | Reopened and reused |
| Duplicate NEW alerts | **0** |
| Cap | Durable (counts first-alerted candidate identities from the DB) |
| INVALIDATED identity | Stays closed |
| MATERIAL_UPDATE clock | `last_alert_utc` survives |
| Outcomes | Preserved |
| In-memory watermark | Rebuilt from the pre-market start: full history, no duplicates, nothing after as-of |
| Crash between persist and route | Re-routed once, idempotently |
| Audit | Every start is a `runs` row (restarts = runs − 1) |

Tests: `test_restart_same_session_reuses_state_without_duplicates`, `test_restart_preserves_invalidated_closure_cap_and_material_update_timing`, `test_crash_between_persist_and_route_is_rerouted_once_on_restart`.

## Cap semantics (unchanged: 25)

The cap counts **candidate identities first alerted in the session**, not Telegram sends:
- a suppressed candidate does not consume it;
- MATERIAL_UPDATE, upgrades and INVALIDATED do not consume it;
- delivery failure or a disabled destination does not affect it;
- it is durable across restart.

Test: `test_cap_counts_first_alerted_candidate_identities_not_sends`.

## Durable ingestion telemetry (Phase 16): implemented, pure observability

- **What.** `talonx_ingest/intelligence/service/poll_history.py` appends one line per completed Intelligence poll cycle to `~/.talonx/intelligence/poll_history.jsonl`: `at_utc`, `cycle`, `symbols_polled`/`failed`, `new_form4`, `new_events`, `freshness`, `error_count`, recovery timeouts/failures, `delivery_ok`, `health_causes`.
- **Bounds.** Rotates at 5 MB, keeping one `.1` generation.
- **Safety.** It records counts and codes only, never error text. The runner call is wrapped in `try/except`, so a telemetry failure never affects the cycle. Nothing in V2 reads it (tested).
- **Effect.** Once running, it lets a session evidence packet show per-poll 39/39 coverage directly instead of by inference (`FULL_PROSPECTIVE_COVERAGE: YES` instead of `YES_WITH_INFERENCE`).
- **Allowlist.** The file is added to the closed `FREEZE_SESSION03_HARDENING_FILES` list.

## Tomorrow paths (rehearsed, nothing live started)

| Item | Result |
|---|---|
| V2 | `results/prospective_2026-09-24/` (UTC-date keyed; created by `prospective start` after 00:00Z) |
| Research | `results/premarket_research/2026-09-24/` (New York session-date keyed) |
| Stop flags | None present anywhere; a previous-day flag is harmless by construction |
| Rehearsal | Dependency-injected `cmd_run` at a simulated 2026-09-24 07:30Z, with real universe and scope loading and the loop stubbed: session `2026-09-24`, fp `62ba413daf85e674`, 5,655 eligible, V2 scope **39** parsed from the current companion log, RESEARCH **OFF** (`deliver_flag=false`, `research_destination_enabled=false`), no notification DB created, run recorded and closed |
