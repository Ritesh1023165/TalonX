# Task 76S — Long-Only Decision and PAPER Execution Safety

## Stage 0 — Verify and map every execution path: PASS
Branch/HEAD (`b0c11b7`)/clean-tree/origin-sync confirmed, no concurrent session. Inventoried every
broker-mutation path: **all per-order submissions funnel through exactly one function,
`PaperLifecycle.order_intent`**, with exactly 4 callers (natural strategy entry/exit, PIV lifecycle
probe entry/exit). No CLI manual order command, no Core/Brain-originated path exists today. Bulk
flatten (EOD/kill-switch/cleanup) is a separate, exempt code path. **No protected-file dependency found.**
See `execution_path_inventory.md`, `implementation_plan.md`.

## Stage 1 — Decision contract: COMPLETE
New, standalone `talonx_piv/decision_contract.py`: `MarketView`/`Recommendation`/
`StrategyApprovalStatus`/`DataReadiness`/`ExecutionStatus` enums, a frozen `Decision` record with every
required field, and a pure `decide()` implementing the full required behaviour table exactly (verified
by 18 tests). The hard invariant — `SELL_TO_CLOSE` reachable only via `has_open_long AND
approved_exit_condition`, never from `market_view` alone — is enforced structurally. Strategy approval
defaults to `UNVALIDATED` (no production approval mechanism exists; none invented). Levels are
passthrough-only, never fabricated. See `decision_contract.md`.

## Stage 2 — Per-ticker PAPER-entry setting: COMPLETE
New `talonx_piv/execution_settings.py::PaperEntrySettings` + `load_paper_entry_settings`, fail-closed on
missing file / non-dict body / missing ticker / non-`True` value. Wired into production
(`cli.py::runtime()` loads `{state_dir}/paper_entry_settings.json`) — meaning no ticker may open a new
entry in the next live session until an operator explicitly populates that file (disclosed in
`remaining_integration_work.md`). Verified: never changes the recorded recommendation; never suppresses
exits/EOD/reconciliation. See `paper_setting_migration.md`.

## Stage 3 — Enforce at the broker boundary: COMPLETE
`PaperLifecycle.order_intent` hardened in place — the single real chokepoint, so every existing caller
is covered with zero new call sites needed. Explicit `ActionIntent` (BUY_TO_OPEN/SELL_TO_CLOSE) derived
from `side`; source allowlist (rejects a hypothetical BRAIN/GEMINI source); quantity well-formedness;
BUY guards (unexpected-short trip-wire, no-pyramiding, no-pending-duplicate, PAPER-entry-disabled);
SELL guards (flat rejection, oversell/duplicate rejection via held-minus-pending-exposure, re-read fresh
from persisted state every call — never trusting caller-side bookkeeping). `reconcile()` extended to
detect and flag (never auto-remediate) an unexpected broker-side short. See `broker_boundary_contract.md`.

## Stage 4 — Protective exits and EOD compatibility: COMPLETE, no regression
7 new tests prove: disabling entries after opening does not suppress the stop/target exit; a
never-enabled ticker's existing position is still fully managed; EOD retries remain idempotent
(no duplicate cancel/close); original session identity remains attached across a retry; a
reconciliation mismatch resolves FAILED (never a false PASSED) and `SESSION_COMPLETED` never fires on
it; a broker outage during cancel resolves INCONCLUSIVE. `eod_lifecycle.py` itself is unmodified — the
pre-existing 22-test EOD suite passes unchanged. See `protective_exit_evidence.json`,
`eod_regression_evidence.json`.

## Stage 5 — Deterministic verification: COMPLETE
72 new tests across 4 files (decision contract 17, execution settings 9, broker boundary 39, protective
exit/EOD 7 — see `bypass_test_matrix.csv` for the full boundary-safety matrix). A `_no_real_network`
autouse fixture in the boundary-test file monkeypatches
`requests`/`requests.sessions.Session` to raise if any real network call is attempted. Every existing,
pre-Task-76S test that exercised a successful BUY was updated (6 files) to explicitly enable its test
symbol(s) via `PaperEntrySettings.for_test(...)`, labelled `TEST_FIXTURE_ONLY -- NOT ALPHA EVIDENCE`,
under the new fail-closed default — the exact, intentional, disclosed source of behavior change (no
incidental breakage).

## Verification and git
- Full collection: **2257 collected, 0 errors** (was 2185, 0 errors, before this task).
- Full suite: **2246 passed, 1 skipped, 10 xfailed** (was 2174 passed before this task) —
  `2246 − 2174 = 72`, exactly the number of new tests added. **Zero unexplained regression.**
- Protected files (`talonx_quant/{strategy,indicators,consumer,config}.py`): zero diff since `b0c11b7`.
- `talonx_piv/eod_lifecycle.py`: zero diff (read-only reference).
- Zero real broker mutations, zero real notifications, zero live session, zero market-data downloads,
  zero holdout access, zero threshold tuning, zero protected-file changes.
- Historical research reproducibility unaffected — no archived research result file touched.

## Acceptance criteria
All met — see `task76s_summary.json::acceptance_criteria`. No control was weakened to pass.

## Recommendation
Next task: **execution-independent alerts and shadow tracking** — building the notification/shadow-
ledger layer this task's `Decision` record and `PAPER_ORDER_REJECTED` events are designed to feed,
without itself touching execution. Not started here, per instruction.
