# EOD / reconciliation preflight (fixtures/tests only; no market-day EOD run)
- `_v2_reconcile()` executed read-only on the isolated fresh campaign: every assertion PASS (buys = sells + open + unresolved, cash + open cost, no negative cash, whole shares,
  corporate-action + dividend consistency, no duplicates) except `v2_status_readable` (no session has run - expected pre-launch): `eod_reconcile_isolated_campaign.txt`.
- Session-10 / +5 recovery, EXIT_UNRESOLVED (no SELL/price/P&L; capacity retained; account-wide block), ordinary-dividend ACCRUED->CREDITED, split/dividend reconciliation and
  block surfacing are proven by flows 1, 3, 3b, 5, 8, 9 of the final-acceptance suite and Packages 1-2 / PQ-2A tests (all pass in the regression, see 18_smoke_test_evidence.txt).
- EOD evidence output: `prospective close` writes the ledger EOD copy + status + lane accounting into `results/prospective_<date>/` (paths follow the env-selected ledger).
- Carried failure `test_task114_prospective.py::test_b7_close_reconciles_zero_activity_ledger` fails identically on the pre-freeze baseline (documented carried set), not introduced here.
