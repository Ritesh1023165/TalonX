# Task 139 — Requirement-by-Requirement Completion Map (A1)

| requirement | status | evidence |
|---|---|---|
| A2: classify the 9+ historical exits | IMPLEMENTED_AND_VERIFIED | `exit_classification.md` — 9 original rows graded HIGH/MEDIUM confidence (none UNRESOLVED, none blanket-classified); 2 Task 138 self-restarts + 1 OS-reboot pair kept explicitly separate |
| A3: investigate unresolved exits | IMPLEMENTED_AND_VERIFIED | no row was genuinely unresolved once classified with real evidence; bounded diagnostic (`_exit_code_hint`) added and confirmed NOT YET loaded in the then-running supervisor (stated honestly, not restarted solely for it) |
| A3: interrupted-work recovery tests | IMPLEMENTED_AND_VERIFIED (reused) | `test_subprocess_crash_after_persist_before_enrich_is_recoverable`, `test_claim_is_persisted_before_the_network`, `test_restart_recovers_a_stale_in_flight_row_to_ambiguous`, `test_competing_drainer_cannot_send_a_claimed_row` — all pass; reused per A1's own instruction, not duplicated |
| A4: yesterday's EOD never marks today reconciled | IMPLEMENTED_AND_VERIFIED | 3 new clock-controlled tests (`test_task139_session_rollover.py`) closing the one real gap (date-boundary, not status-coincidence) found by inspection |
| A4: yesterday's close doesn't disable today's processing | IMPLEMENTED_AND_VERIFIED | code inspection (zero references to eod_reconciled/today_reconciled in either ingestion or V2 pipeline code) + live evidence (both ticked normally post-recovery with a PARTIAL prior-day record present) |
| A4: late intent cannot justify a past open | IMPLEMENTED_AND_VERIFIED (reused) | `test_task113_stale_entry_guard.py` (4 tests) + live evidence (`stale_entry_skipped_this_tick: 3` on the very first post-recovery tick) |
| A4: reservation expiry exactly-once | **UPGRADED to IMPLEMENTED_AND_VERIFIED** (superseded the code-inspection-only note below) | `docs/research/evidence/task140/requirement_closure_matrix.md` §4 — `tests/test_task140_reservation_expiry_exactly_once.py` (2 new): real `V2Service`/`V2Store`, isolated db, close/reopen, exactly-once release proven with cash-unchanged asserted directly (not invented as a credit) |
| A4: one valid checkpoint owner, fresh checkpoints | IMPLEMENTED_AND_VERIFIED | live: fresh session dir, `checkpoint_0001` written, `campaign_day` correctly continued (not reset) |
| A4: existing positions remain exit-eligible after scope changes | **CLOSED** (was NOT_IMPLEMENTED) | `tests/test_task140_exit_eligibility_after_scope_change.py` (commit `c9fb63d`, prior turn) — 2 isolated tests |
| A5: documentation corrections | IMPLEMENTED_AND_VERIFIED | placeholder timestamp, stale push-pending line, superseded fingerprint, 4 overclaimed "byte-identical" statements all corrected with notes, raw historical artifacts preserved unchanged |
| Priority interrupt: broad-discovery + delivery-enablement restoration | IMPLEMENTED_AND_VERIFIED | `9ee3ee0` + `bde2d28`, both verified live (569 effective_symbols; `delivery.mode: "enabled"`) |
| Admission-mode reporting provenance | IMPLEMENTED_AND_VERIFIED | `56b8fad` — companion-sourced `durable_store_gate_enabled`, both readers cite `source: "live companion"` |
| GATED admission activation (operator-authorized) | IMPLEMENTED_AND_VERIFIED | `.env` persisted, live `durable_store_gate_enabled: true` confirmed in the real companion |
| Substantive-content requirement (stricter, post-Task-138) | **CLOSED this turn** (was NOT_IMPLEMENTED per the 2026-09-15 follow-up directive) | see `docs/research/evidence/task140/requirement_closure_matrix.md` §1 — commit `2c96c8f` |
| Digest-off demonstrated at a genuinely due schedule | **CLOSED this turn** (prior evidence was insufficient — cited `digest_not_due`, not the disable reason) | §2 of the same matrix |
| Execution/collection scope reconciled by membership, not count alone | **CLOSED this turn** | §3 of the same matrix |

All items in this table are now IMPLEMENTED_AND_VERIFIED or explicitly
CLOSED with direct evidence. No remaining NOT_IMPLEMENTED item as of
this update.
