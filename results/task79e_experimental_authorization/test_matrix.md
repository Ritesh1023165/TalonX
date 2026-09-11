# Task 79E — Test Matrix

59 new tests across three files, plus zero-regression re-verification of
every pre-existing suite the diff touches.

## `tests/test_task79e_experimental_authorization.py` (34 tests)

Pure unit tests of `ExperimentalAuthorization`/`load_experimental_authorization`
in isolation — no lifecycle/broker/decision_engine involved.

| Area | Scenarios covered |
|---|---|
| Strict-parsing / fail-closed loading | missing file, malformed JSON, non-dict JSON, `enabled` missing/non-bool/`false`, each required string field missing/empty, `operator_acknowledged_unvalidated` not literally `true`, `allowed_symbols` missing/empty/non-string entries, `activated_at`/`expires_at` missing/non-ISO/timezone-naive/`expires_at<=activated_at`, `paper` malformed/non-finite/non-positive/boolean-where-numeric-expected |
| `permits_entry` binding checks | symbol not allowed, wrong trading date, wrong strategy id, wrong strategy version, wrong runtime_sha, wrong config_hash, not-yet-active, expired, timezone-naive `now` rejected, exact match permitted |
| `permits_paper_execution` | delegates to `permits_entry` first (same rejections apply), `paper is None` rejected, `paper.enabled is False` rejected, wrong account rejected, exact match permitted |
| Type-strictness edge cases | JSON string `"true"`/`"false"` never coerced, `bool` excluded from numeric-limit checks despite being an `int` subclass, non-finite (`inf`/`nan`) and non-positive limits rejected, non-integer count fields rejected |

## `tests/test_task79e_lifecycle_experimental.py` (18 tests)

Drives the REAL `PaperLifecycle.order_intent`/`apply_broker_update` against
a fake Alpaca transport — proves guard enforcement at the true broker
boundary, independent of the decision layer.

| Scenario | Verifies |
|---|---|
| `test_no_authorization_configured_rejected` | no `ExperimentalAuthorization` at all → `EXPERIMENTAL_AUTHORIZATION_NOT_CONFIGURED`, zero broker calls |
| `test_valid_authorization_succeeds_and_reserves_budget` | full success path, budget incremented |
| `test_experimental_id_mismatch_rejected` | caller-supplied id must match the authorization's own |
| `test_wrong_account_rejected` | PAPER account binding enforced |
| `test_wrong_symbol_rejected` | symbol must be in `allowed_symbols` |
| `test_wrong_trading_date_rejected` | date binding enforced |
| `test_wrong_strategy_version_rejected` | version binding enforced |
| `test_wrong_runtime_sha_rejected` | code-identity binding enforced |
| `test_expired_permission_rejected` | expiry re-checked against the real wall clock |
| `test_quantity_exceeds_limit_rejected` | per-entry quantity cap enforced |
| `test_missing_reference_price_rejected` | fails closed when notional cannot be estimated |
| `test_notional_budget_exhausted_rejected` | cumulative notional budget enforced across entries |
| `test_entry_count_exhausted_rejected` | cumulative entry-count budget enforced |
| `test_budget_survives_restart` | a fresh `PaperLifecycle` reading the same state file sees the prior budget |
| `test_budget_not_reset_by_reloading_a_fresh_authorization_object` | re-minting the authorization object does not zero the ledger |
| `test_normal_strategy_source_unaffected_by_experimental_guards` | `source="STRATEGY"` orders are completely unaffected (backward compatible) |
| `test_submission_failure_before_id_marks_uncertain_and_blocks_pyramiding` | HTTP failure before a broker id exists → marked `SUBMIT_FAILED_UNCERTAIN`, original exception type propagates unwrapped, a second same-symbol attempt is blocked by `PENDING_ENTRY_EXISTS` |
| `test_submission_failure_does_not_refund_experimental_budget` | the budget reservation for a failed submission is NOT refunded |

## `tests/test_task79e_decision_engine_experimental.py` (7 tests)

Full end-to-end evidence that the feature is reachable from a live signal
through the REAL `DecisionEngine.on_bars`/`_handle_entry`/`_check_exit`
construction (`talonx_piv.cli.runtime()`'s exact wiring pattern), not a
helper or test-only override — reuses the Task 78I rehearsal harness
(`RehearsalTransport`, `FakeRedisClient`/`FakePubSub`).

| Scenario | Verifies |
|---|---|
| `test_no_authorization_preserves_old_behavior` | no `ExperimentalAuthorization` configured (the default) → byte-identical pre-Task-79E behaviour: `NO_TRADE`, WATCH classification, no shadow experimental flag, no broker order |
| `test_valid_authorization_produces_experimental_buy_alert_shadow_and_paper_entry` | full path: `EXPERIMENTAL_BUY` recorded, notification carries `CLASSIFICATION_EXPERIMENTAL_BUY` + the required banner, shadow position opened and flagged experimental, a real PAPER buy order is submitted, `OpenDecisionPosition.experimental`/`experimental_id` set |
| `test_paper_permission_denied_does_not_suppress_alert_or_shadow` | entry permitted, PAPER not permitted → alert + shadow still produced, zero broker orders |
| `test_stale_signal_rejected_for_experimental_admission` | a signal far older than `config.stale_seconds` is never admitted to the experimental path even under an otherwise-valid authorization |
| `test_bearish_signal_never_reaches_experimental_buy` | `market_view != BULLISH` short-circuits before the experimental branch is ever consulted |
| `test_exit_remains_available_after_experimental_entry` | a stop-triggered exit on an experimental position still fires and submits a sell order |
| `test_wrong_symbol_authorization_blocks_experimental_entry` | an authorization scoped to a different symbol never leaks permission cross-ticker |

## Zero-regression re-verification (pre-existing suites touched by this diff)

All re-run after every code change in this task, final counts:

| Suite | Result |
|---|---|
| `test_task76s_decision_contract.py` | 17/17 unchanged |
| `test_task76s_broker_boundary.py`, `test_task77i_runtime_safety.py`, `test_task72o_eod_lifecycle.py`, `test_task76s_protective_exit_eod.py`, `test_task64_piv.py`, `test_task65b_lifecycle_probe.py` | 107/107 unchanged |
| `test_task77i_notification_outbox.py` + `test_task77i_alert_shadow_independence.py` | 14/14 unchanged |
| `test_task77i_shadow_ledger.py` + `test_task78i_horizon_exit.py` + `test_task78i_shadow_independence.py` | 30/30 unchanged |
| `test_task65b_decision_engine.py`, `test_task77i_decision_engine_wiring.py`, `test_task77i_end_to_end.py` | 32/32 unchanged |
| `test_backtest_execution.py`, `test_task76s_protective_exit_eod.py`, `test_task78i_stage5_rehearsal.py` | 53→54/54 (one pre-existing test's exception-propagation contract restored — see `implementation_plan.md`'s "Regression found and fixed") |
| `test_task78i_cli_ownership.py`, `test_task78i_cli_supervise.py` | 6/6 unchanged |
| `test_task77i_observability.py` | unchanged, plus new `experimental` section additive-only |
| Full repository suite | see `regression_results.txt` |
