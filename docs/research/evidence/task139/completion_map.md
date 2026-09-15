# Task 139 — Requirement-by-Requirement Completion Map (A1)

| requirement | status | evidence |
|---|---|---|
| A2: classify the 9+ historical exits | IMPLEMENTED_AND_VERIFIED | `exit_classification.md` — 9 original rows graded HIGH/MEDIUM confidence (none UNRESOLVED, none blanket-classified); 2 Task 138 self-restarts + 1 OS-reboot pair kept explicitly separate |
| A3: investigate unresolved exits | IMPLEMENTED_AND_VERIFIED | no row was genuinely unresolved once classified with real evidence; bounded diagnostic (`_exit_code_hint`) added and confirmed NOT YET loaded in the then-running supervisor (stated honestly, not restarted solely for it) |
| A3: interrupted-work recovery tests | IMPLEMENTED_AND_VERIFIED (reused) | `test_subprocess_crash_after_persist_before_enrich_is_recoverable`, `test_claim_is_persisted_before_the_network`, `test_restart_recovers_a_stale_in_flight_row_to_ambiguous`, `test_competing_drainer_cannot_send_a_claimed_row` — all pass; reused per A1's own instruction, not duplicated |
| A4: yesterday's EOD never marks today reconciled | IMPLEMENTED_AND_VERIFIED | 3 new clock-controlled tests (`test_task139_session_rollover.py`) closing the one real gap (date-boundary, not status-coincidence) found by inspection |
| A4: yesterday's close doesn't disable today's processing | IMPLEMENTED_AND_VERIFIED | code inspection (zero references to eod_reconciled/today_reconciled in either ingestion or V2 pipeline code) + live evidence (both ticked normally post-recovery with a PARTIAL prior-day record present) |
| A4: late intent cannot justify a past open | IMPLEMENTED_AND_VERIFIED (reused) | `test_task113_stale_entry_guard.py` (4 tests) + live evidence (`stale_entry_skipped_this_tick: 3` on the very first post-recovery tick) |
| A4: reservation expiry exactly-once | IMPLEMENTED_AND_VERIFIED | verified by code inspection: `mark_entry_intent(...,"EXPIRED_STALE")` is gated on `intent["status"]=="PENDING"`, structurally idempotent — cannot re-fire once transitioned |
| A4: one valid checkpoint owner, fresh checkpoints | IMPLEMENTED_AND_VERIFIED | live: fresh session dir, `checkpoint_0001` written, `campaign_day` correctly continued (not reset) |
| A4: existing positions remain exit-eligible after scope changes | NOT_IMPLEMENTED (no gap found requiring a fix; not separately isolated-tested) | 0 open positions throughout this campaign to date — nothing to exercise; flagged as untested-in-isolation, not claimed covered |
| A5: documentation corrections | IMPLEMENTED_AND_VERIFIED | placeholder timestamp, stale push-pending line, superseded fingerprint, 4 overclaimed "byte-identical" statements all corrected with notes, raw historical artifacts preserved unchanged |
| Priority interrupt: broad-discovery + delivery-enablement restoration | IMPLEMENTED_AND_VERIFIED | `9ee3ee0` + `bde2d28`, both verified live (569 effective_symbols; `delivery.mode: "enabled"`) |

**Genuine remaining gap, stated plainly**: exit eligibility after a scope
change was never isolated-tested (no open position has existed this
campaign to exercise it against). This is `NOT_IMPLEMENTED` as a
verified, tested guarantee — not claimed otherwise.
