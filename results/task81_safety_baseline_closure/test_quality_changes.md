# Task 81 §6 — Verification-weakness repairs

## E1 — weak / placeholder assertions strengthened

A static AST scan (`test_task*.py`) for test functions with no `assert` and
no `pytest.raises`, or whose only assertion was `isinstance(...)` /
`is not None`, surfaced two genuine weaknesses (the rest were mock-assertion
patterns — `assert_awaited_once` / `assert_not_awaited` / a raise-on-call
fake transport — which are real behavioural checks):

| Test | Was | Now |
|---|---|---|
| `test_task72o_eod_lifecycle.py::test_session_completed_never_emitted_on_failed` | `pass  # covered elsewhere` — asserted nothing | Drives a real accepted-but-unconfirmed EOD close: asserts `status==FAILED`, `EOD_RECONCILIATION_FAILED` emitted, `SESSION_COMPLETED`/`EOD_RECONCILIATION_PASSED` **not** emitted, and (C7) the internal position stays `OPEN`. |
| `test_task77i_decision_ledger.py::test_persists_and_reloads_across_a_new_instance` | `assert ledger2.get("d1") is not None` | Asserts the reloaded record **equals** the written record and carries the exact `event_id` / `evidence_category` / `recommendation`. |

The new Task 81 test files (`test_task81_reconciliation_admission.py`,
`test_task81_recovery_binding.py`, `test_task81_source_health_and_reporting.py`,
`test_task81_iex_readiness_bookkeeping.py`) assert concrete state and
outcomes throughout — never "returned a dict" / "did not raise".

## E2 — broker contract fixtures from documented API behaviour

All Task 81 fake-broker/transport fixtures build Alpaca REST shapes from the
documented contract (position rows always carry `symbol` + `qty` + `side`;
order rows carry `id` + `client_order_id` + `symbol` + `qty` + `filled_qty`
+ `side` + `status` + `filled_avg_price`; `GET /v2/orders:by_client_order_id`
returns the object or a 404), referenced in each file's module docstring.
Pre-existing fixtures that used implementation-assumption shapes
(`{"symbol": "AAPL"}` position rows with no `qty`/`side`) were corrected in
`test_task72o_eod_lifecycle.py`, `test_task76s_protective_exit_eod.py`, and
`test_task65b_lifecycle_probe.py` so they exercise the Task 81
quantity/side comparison.

## E3 — isolation; no writes into historical evidence directories

- Every Task 81 test freezes the clock (explicit `now=` / fixed
  `datetime`), uses a per-test `tmp_path` state dir, and installs an
  autouse `_no_real_network` guard.
- Two tests were overwriting historical evidence directories on every run:
  - `test_task77i_end_to_end.py::_write_scenarios_csv` →
    `results/task77i_integrated_application/end_to_end_scenarios.csv`
  - `test_task78i_stage5_rehearsal.py::_write_csv_after_module` →
    `results/task78i_full_application_rehearsal/rehearsal_scenarios.csv`

  Both now write to `TALONX_TEST_EVIDENCE_DIR` when an operator explicitly
  sets it, otherwise to a run-specific path under the OS temp dir — the
  historical directories are no longer touched by a routine `pytest` run.
- `test_task66b_prep_preflight.py::test_live_smoke_evidence_artifact_exists_and_is_recent_enough`
  only **reads** a preserved artifact (a presence guard) — left as-is.

## E4 — critical-guard negative controls

`tests/test_task81_guard_negative_controls.py` — for each critical guard,
the forbidden outcome is deliberately injected (the guard's persisted
effect is manually undone) and the test proves the forbidden outcome then
occurs, demonstrating the guard is load-bearing:

| Guard | Injection | Forbidden outcome proven observable |
|---|---|---|
| §2 reconcile entry-admission block | clear `reconciliation_flags.entry_admission_blocked` while a 10-vs-1 qty mismatch stands | a new BUY is admitted during an unreconciled mismatch |
| §3 cumulative-fill monotonic clamp | rewind stored `order.filled_qty` to a smaller value | the next genuine cumulative update inflates `remaining_quantity` above the amount ever entered |
| §3 `SessionRecoveryRequired` | swallow the assessment and mint a fresh identity | a replacement `session_id` is created while the prior session's open position is still unresolved |

## E4 — pre-fix failure proof

`raw_test_output/section2_prefix_failures.txt` records
`tests/test_task81_reconciliation_admission.py` run against the **pre-fix**
`lifecycle.py`: `11 failed, 3 passed` (the 3 passes are positive controls).
§3/§4/§5 regression tests were likewise authored against, and observed to
fail on, the pre-fix behaviour during development (recovery-binding raised
nothing; `finalize_session_report` did not exist so the auto path emitted
no report; the redelivered-bar / episode-count invariants were unlocked).

## E5 — command / count discipline

See `raw_test_output/` for every recorded command, exit code, and exact
pass/skip/xfail count, and `../task81_safety_baseline_closure_report.md` for
the consolidated table. No dependency was added or upgraded. Skip/xfail
counts are unchanged from baseline (1 skipped, 10 xfailed).
