# Task 81-R2 §7 — State-transition matrix

Every cell is covered by a named test in one of the Task 81 / R1 / R2
suites. Node ids are given for the R2-added coverage; "R1" / "T81" mark
cells already locked by an earlier suite that still passes.

## Order lifecycle status × broker/internal agreement

| internal status | broker open list shows it | broker `get_order` says | verdict | test |
|---|---|---|---|---|
| SUBMITTED / new / accepted | yes, fields agree | non-terminal | OK (still blocks via PENDING_ENTRY) | `test_task81_r2_reconcile_identity::test_full_field_consistency_required_for_ok` |
| SUBMITTED | yes, wrong `client_order_id` | — | CONTRADICTION | `::test_id_with_wrong_client_order_id_is_contradiction` |
| SUBMITTED | yes, wrong symbol/side/qty | — | CONTRADICTION | `::test_missing_intent_ambiguous_conflicting_malformed_never_ok[*]` |
| SUBMITTED | **no** (list omits it) | non-terminal | UNRESOLVED (`orders_missing_from_broker_list`) | `::test_internal_outstanding_order_absent_from_broker_list_is_unresolved` |
| SUBMITTED | — | refresh transport error | INCOMPLETE_READ | `::test_missing_intent_ambiguous...` / T81 `test_task81_reconciliation_admission` |
| **filled** | yes | — | CONTRADICTION (no eventual-consistency exemption) | `::test_no_eventual_consistency_exemption_for_filled`, `::test_internally_filled_order_still_open_at_broker_is_contradiction` |
| **canceled / rejected / expired** | yes | — | CONTRADICTION | R1 `test_task81_r1_reconciliation_completeness::test_cancelled_order_reported_open_is_contradiction_and_blocks` |
| partially_filled | yes, cumulative fill regressed vs recorded | — | CONTRADICTION | `::test_missing_intent_ambiguous...[impossible_filled_qty]` + `_verify_broker_order_row` regressed-fill branch |
| UNCONFIRMED_TIMEOUT | n/a | resolved to terminal | cleared | T81 `test_task77i_runtime_safety` |
| UNCONFIRMED_TIMEOUT | n/a | read still fails | stays unresolved, blocks | T81 `test_task81_reconciliation_admission::...unconfirmed_timeout...` |
| SUBMIT_FAILED_UNCERTAIN | n/a | 404 (repeated) | never auto-resolves; blocks | `test_task81_r2_orphan_recovery::test_orphan_never_auto_resolves_on_absence` |
| SUBMIT_FAILED_UNCERTAIN | n/a | exact match found | adopted once; real status applied | `::test_orphan_discovered_and_adopted_only_on_exact_match`, `::test_orphan_recovery_matrix[*]` |
| SUBMIT_FAILED_UNCERTAIN | n/a | unrelated response | not adopted; stays unresolved | `::test_orphan_unrelated_response_not_adopted` |
| ORDER_INTENT, no recorded order (orphan) | n/a | n/a | promoted -> SUBMIT_FAILED_UNCERTAIN; blocks | `::test_orphan_order_intent_promoted_and_blocked_until_resolved` |

## ID / intent linkage

| id present | client_order_id present | resolve to | verdict | test |
|---|---|---|---|---|
| correct | correct | same intent | OK | `::test_full_field_consistency_required_for_ok` |
| correct | wrong | conflicting | CONTRADICTION | `::test_id_with_wrong_client_order_id_is_contradiction` |
| correct (A) | correct (B) | two different intents | CONTRADICTION | `::test_conflicting_ids_map_to_different_intents_is_contradiction` |
| unknown | unknown | none | UNTRACKED | `::test_position_agreement_does_not_override_order_disagreement` |
| — | missing | — | MALFORMED (incomplete read) | `::test_missing_intent_ambiguous...[missing_client_id]` |

## Broker response validity (`apply_broker_update` / `_extract_order_update_fields`)

| field | bad value | outcome | test |
|---|---|---|---|
| status | unrecognised | refused, no mutation | `test_task81_r2_apply_update_validation::test_invalid_update_rejected_before_mutation[teleported-*]` |
| filled_qty | NaN / inf | refused | `[*-nan-*]`, `[*-inf-*]` |
| filled_qty | negative | refused | `[*--1-*]` |
| filled_qty | boolean | refused | `[*-True-*]` |
| filled_qty | > requested | refused; status + high-water mark not poisoned | `[filled-99-*]`, `::test_contradictory_update_does_not_poison_status_or_high_water_mark` |
| fill_price | NaN / negative / zero | refused | `[*-nan-FILL_PRICE]`, `[*--5.0-*]`, `[*-0.0-*]` |
| open_orders body | non-list / null | INCOMPLETE_READ, block held | R1 `test_task81_r1_reconciliation_completeness::test_malformed_order_row_does_not_clear` |
| position qty | unparseable | INCOMPLETE_READ | T81 `test_task81_reconciliation_admission::test_position_with_unparseable_qty_blocks` |

## Fill sequencing

| sequence | expectation | test |
|---|---|---|
| duplicate identical fill | idempotent no-op | `test_task81_r2_apply_update_validation::test_duplicate_and_stale_idempotent` |
| older/smaller cumulative after larger | no rewind, no double-count | R1 `test_task81_r1_late_fill_recovery::test_out_of_order_updates` |
| genuine positive delta after a protective close (position CLOSED) | re-open monitoring, preserve exit qty/P&L/latch/levels | `::test_genuine_delta_preserves_exits_levels_linkage_latch`, R1 `test_task81_r1_late_fill_recovery::*` |
| partial BUY -> protective close -> later BUY fill -> restart -> remaining exit | correct throughout | `::test_partial_buy_close_late_fill_restart_remaining_exit` |

## Restart

| restart point | preserved | test |
|---|---|---|
| after submission (SUBMITTED order) | pending reservation, block | `test_task81_r2_reconcile_identity::test_block_survives_restart` |
| after orphan promotion | SUBMIT_FAILED_UNCERTAIN + block | `test_task81_r2_orphan_recovery::test_orphan_recovery_idempotent_and_restart_safe` |
| after adoption + fill | position, exit plan | same |
| after partial exit + late fill | remaining_quantity, exit_quantity, latch | R1 `test_task81_r1_late_fill_recovery::test_restart_before_and_after_late_fill` |
| after operator resolution | terminal disposition, audit fields | `test_task81_r2_orphan_recovery::test_operator_resolution_requires_confirmation_and_audits` |
| missing / corrupt identity + unresolved exposure | RECOVERY_REQUIRED, no identity minted | R1 `test_task81_r1_missing_identity_recovery::*` |

## Block persistence + recovery

| condition | block | clears when | test |
|---|---|---|---|
| transient inconsistent snapshot | held, retryable | a complete + consistent pass | `test_task81_r2_reconcile_identity::test_block_persists_over_transient_snapshot_and_clears_on_clean_pass` |
| full restart mid-block | held | — | `::test_block_survives_restart` |
| orphan intent | held | operator resolution + clean pass | R1 `test_task81_r1_reconciliation_completeness::test_orphan_intent_clears_only_after_documented_operator_resolution` |

## Block never suppresses

| path | still available under a block | test |
|---|---|---|
| protective SELL (sized to verified holdings − pending sells) | yes | `test_task81_r2_apply_update_validation::test_block_preserves_sell_shadow_monitoring_eod` |
| EOD cleanup (`eod_flatten` / `run_eod_lifecycle`) | yes | same + T81 `test_task72o_eod_lifecycle` |
| unknown exposure SELL | fails visibly (`OVERSIZED_OR_DUPLICATE_SELL`) | `::test_unknown_exposure_sell_fails_visibly` |
