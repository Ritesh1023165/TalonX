# Acceptance matrix — Task 117 delivery + timestamp completion

`DONE` implemented + tested · `PARTIAL` partly, remainder documented · `DOC`
designed not executed · `INCOMPLETE` blocked by unavailable external evidence.

## §1 Fix false SENT states before wiring delivery

| requirement | status | where |
|---|---|---|
| disabled delivery: fresh rows remain PENDING/HELD with a clear reason | **DONE** | `process_pending(mode="disabled")` → rows stay PENDING, `held` + `held_reason="delivery_disabled"`, `HELD` log line; `test_disabled_delivery_holds_fresh_rows_pending_with_a_reason` |
| simulation: isolated, never represented as delivery | **DONE** | `mode="simulate"` (and `dry_run=True` alias) → outbox **not mutated**, `simulated`/`simulated_ids`; `test_simulate_never_marks_sent_or_touches_the_transport` |
| SENT requires a real transport ack in the enabled path | **DONE** | only `mode="enabled"` + `SenderResult.ok` → `mark_sent`; `NullSender` removed from the drain path |
| failure/ambiguity: honest durable state, no blind duplicate retries | **DONE** | `STATE_AMBIGUOUS` + `mark_ambiguous` (no `next_retry`); `TelegramSenderAdapter` maps permanent vs transient vs ambiguous; `test_ambiguous_send_is_durable_and_not_retried` |
| separate backlog expiry from sending; document whether disabled mode permits expiry | **DONE** | `enforce_age_cutoff` is an explicit opt-in; `mode="disabled"` does **not** pass it → no expiry. Documented in `backlog_rehearsal.md` §"Does disabled mode permit expiry?" |
| test disable → enable → successful send incl. restart; fresh event must not disappear | **DONE** | `test_disabled_by_default_holds_then_enable_sends_after_restart` |
| telemetry reports queued / held / simulated / actually-sent separately | **DONE** | `DrainResult` fields `held`, `simulated`, `delivered`, `retried`, `failed`, `ambiguous`, `expired`; `counts_by_state()` distinct states |
| inspect affected callers | **DONE** | only prod caller of `process_pending` is the new `deliver_cycle`; test `_drain` helpers updated to `mode="enabled"` |

## §2 Complete the actual runner integration

| requirement | status | where |
|---|---|---|
| single bounded delivery drain in the real supervised path | **DONE** | `IntelligenceService.deliver_cycle` called once per `run_poll_loop` cycle |
| explicit config, safe disabled default, existing transport authority | **DONE** | `deliver_intelligence_cards=False` default; `TelegramSenderAdapter` wraps the shared `TelegramClient` |
| no second Telegram poller / parallel sender loop | **DONE** | one adapter per cycle; no `get_updates` loop |
| config reaches the running service constructor | **DONE** | `ServiceConfig.from_env()` fields + `_svc(...)` test proving mode selection |
| eligible new IMMEDIATE cards reach the final transport boundary | **DONE** | `test_disabled_by_default_...` intercepted send |
| DIGEST respected, not treated as immediate | **DONE** | separate `IMMEDIATE`/`DIGEST` passes; `test_digest_not_treated_as_immediate` |
| backoff does not block source polling | **DONE** | `asyncio.wait_for` per route + `TimeoutError` caught, loop continues |
| restart preserves pending delivery | **DONE** | disabled cycle leaves PENDING; fresh service delivers the same row |
| permanent + ambiguous do not produce retry storms | **DONE** | permanent → FAILED; ambiguous → AMBIGUOUS; neither retried |
| duplicate events / overlap with Original long-term — explicit policy | **DONE** | `delivery_id` dedup + `update_policy`; Original long-term is a distinct channel/consumer (documented) |
| informational cards do not become BUY/SELL | **DONE** | `claim_safety.assert_clean` (pre-existing, AST-tested) |
| real adapter, network boundary intercepted for isolated tests | **DONE** | `_Intercept` monkeypatched over `TelegramSenderAdapter` |
| backlog: rehearse on isolated copy; preserve rows + audit transitions; no old row SENT | **DONE** | `backlog_rehearsal.md` + `backlog_rehearsal.json` on a `shutil.copy2` |
| freshness from trustworthy event time + origin, not only enqueue time | **DONE** | `expire_stale(event_time_lookup=…)` uses `min(event_time, enqueue_time)`; `test_old_event_enqueued_today_is_not_fresh` |
| distinguish stale backfill from timely new events | **DONE** | rehearsal: 9,841 EXPIRED / **2 still PENDING** at the 2026-09-11T13:30Z cutoff |
| verify stale backlog cannot flood the first enabled drain | **DONE** | `test_enabled_cycle_expires_stale_backlog_and_delivers_only_fresh` |
| do not assume all 9,843 stale; compute actual dispositions at the cutoff | **DONE** | 9,841 expire / 2 survive (ORCL + JPM DIGEST, ~21 h old) at the stated cutoff |
| prepare production migration/activation steps without executing | **DOC** | `deployment_candidate.md` |

## §3 Repair timestamp parsing using source provenance

| requirement | status | where |
|---|---|---|
| generic ISO with Z/+00:00 retains UTC | **DONE** | `parse_acceptance_datetime_ex` — `Z`/`+00:00` marker → UTC, no shift; `test_submissions_Z_marker_is_genuine_utc` |
| explicit non-zero offsets respected | **DONE** | `test_explicit_nonzero_offset_is_trusted` |
| naive interpretation requires an explicit source contract | **DONE** | `source=` param + `ACCEPTANCE_SOURCE_TZ`; naive default (`submissions`) → UTC + `acceptance_offset_absent` |
| source-specific exception only when supported by raw source evidence | **DONE** | `sgml_header` → Eastern, VERIFIED by the 10-accession SGML↔JSON cross-reference (`timestamp_source_contract.md`) |
| never infer tz solely from the 4-hour gap | **DONE** | the 4 h gap is now a **separate UNRESOLVED anomaly**, not the basis for any rule |
| use raw SEC payloads / filing-index acceptance fields / docs; distinguish EDGAR display wall-clock from API semantics | **DONE** | raw `<ACCEPTANCE-DATETIME>` SGML vs `data.sec.gov/submissions` JSON cross-referenced; conclusion: SGML = Eastern display, submissions API = converted UTC |
| retain raw / source field / parser version / interpretation / normalized UTC | **DONE** | `timestamp_correction_manifest.csv` columns + persisted DQ flags |
| if a source exception cannot be verified: remove the global reinterpretation, preserve raw evidence, mark unresolved; no synthetic confirmation | **DONE** | the **global** Eastern reinterpretation is **removed**; the S1–S3 persisted-value anomaly is `UNRESOLVED` and unchanged |
| tests: genuine UTC no-shift; verified Eastern-naive winter+summer; explicit offsets; UTC/ET date boundaries; DST gap/overlap; session classification; causal cutoffs; 2nd-owner activation + eligible entry | **DONE** | `tests/test_task117_acceptance_timezone.py` (25) covers every listed case |

## §4 Replace the unsafe rebuild proposal

| requirement | status | where |
|---|---|---|
| do not select rows by zero-offset | **DONE** | manifest keyed by `{accession}\|acceptance` + source field, not by offset shape |
| correction manifest keyed by stable source identity, with raw / old-parser / existing / verified-proposed / evidence / confidence / dependents | **DONE** | `timestamp_correction_manifest.csv` (22 rows) |
| classify VERIFIED_CORRECTION / ALREADY_CORRECT / UNRESOLVED; leave unresolved unchanged; preserve originals; idempotent + reversible | **DONE** | 10 ALREADY_CORRECT · 12 UNRESOLVED · **0 VERIFIED_CORRECTION** → nothing changes |
| rehearse correction / restart / rollback on copies; compare InsiderStore episodes/intents/eligibility before/after | **DONE** | `insiderstore_before_after.md` — **NO CHANGE** (0 verified corrections); before/after identical; Task-116 replay path proven independent |
| unchanged parquet results alone do not validate | **DONE** | stated; the InsiderStore comparison (not just parquet) is the basis, and it is unchanged |
| report every changed entry/session/disposition + cause | **DONE** | **zero changed** — reported as such |
| publish a production migration proposal; execute none | **DOC** | `deployment_candidate.md` (idempotent, reversible, gated on resolving the anomaly) |

## §5 D4 + D6

| requirement | status | where |
|---|---|---|
| D4: verdicts NOT_STARTED / STARTING / READY / FAILED_WITH_RESIDUALS | **DONE** | `startup_verdict`; `startup_accounting_acceptance.md` |
| D4: bounded readiness waiting | **DONE** | `verify_running` retry budget + 120 s heartbeat grace |
| D4: repeated/concurrent start must not create a dup stack/ledger writer | **DONE** | `assert_no_live_prior_stack` → `ConcurrentStartError`, exit 3, nothing spawned |
| D4: ownership-safe failure cleanup, isolated processes | **DONE** | `FAILED_WITH_RESIDUALS` → `stop_stack` reap + `start_cleanup.json`; `test_start_stack_guard_blocks_a_second_spawn` |
| D4: do not downgrade missing mandatory readiness to a cosmetic warning | **DONE** | `test_missing_mandatory_is_not_a_cosmetic_warning` |
| D6: distinguish Original / Experimental / V2 | **DONE** | `lane_accounting.build_lane_accounting` three separate blocks |
| D6: stable evaluation identities + explicit terminal dispositions | **PARTIAL** | terminal dispositions per lane from the durable stores; a per-candidate identity ledger is still not persisted (proposed) |
| D6: separate retries/re-evaluations from unique setups; record throttle/cooldown/revalidation | **DONE** | `off_counter_disposition_class` block + `funnel_closure.residual_class` |
| D6: preserve lane-scoped metrics snapshots at EOD | **DONE** | `lane_accounting_eod.json` written by `prospective close` |
| D6: reconciliation includes pending/in-flight | **DONE** | `in_flight` block (`v2_pending_entry_intents`, `v2_alert_outbox_pending`) |
| D6: do not rewrite the 94-gap as resolved without evidence | **DONE** | resolved **with** evidence — the retained Redis `metrics:2026-09-10:quant:*` counters close it to residual 4 (off-counter class); cited, not asserted. `UNRESOLVED` when no snapshot is reachable. |
| keep within existing infra; no new metrics platform | **DONE** | additive snapshot + verbatim counter capture |

## §6 Verify the actual user journey + dashboard

| requirement | status |
|---|---|
| one isolated end-to-end rehearsal (all 7 legs) | **DONE** — `tests/test_task117_delivery_runner_integration.py` + `backlog_rehearsal.*` |
| inspect rendered actual-SPA views | **INCOMPLETE (render)** / **DONE (data)** — `dashboard_acceptance.md` states the exact unverified render gate; API-only is not called rendered acceptance |

## §7 Correct the published conclusions

| statement to add | status |
|---|---|
| 14,973/15,002 = composition of recorded rejections, not necessarily the rate among all opportunities | **DONE** — `../task117_output_closure` correction (`remaining_gaps.md` here + a note) |
| "no qualifying V2 setup in local records" ≠ proof of complete external coverage | **DONE** |
| a changed Oracle valuation from the same filing ≠ a justified evidence-based update | **DONE** (already stated in `oracle_provenance.md`; reaffirmed) |
| parquet replay independence ≠ live-adapter timestamp parity | **DONE** |
| access failures are access failures — do not call the session dates fictional/forward-dated | **DONE** — wording corrected throughout this bundle |
| do not repeat the 43-ticker web audit | **DONE** — not repeated |

## §8 Validation & publication

| requirement | status |
|---|---|
| focused tests + affected regressions | **DONE** — see `remaining_gaps.md` §"Test status" |
| production ledger / source DBs / Redis / config unchanged | **DONE** — `ingestion_ledger.db` md5 `2ae2105c…`, `v2_lane.db` `29e57dbc…`, Redis PONG (run_id retained), no config activation |
| no test/app processes left running; no external messages | **DONE** |
| publish under `docs/audits/task117_delivery_timestamp_completion/` | **DONE** — 11 files |
