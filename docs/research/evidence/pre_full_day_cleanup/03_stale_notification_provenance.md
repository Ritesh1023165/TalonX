# Stale Sentinel messages - provenance (TASK B)

**STALE TEST MESSAGES IDENTIFIED: YES - COUNT: 9 - RELATED TO V2-PAPER-RC1: NO**

- **Store:** `notifications.db` (repo root; the cwd-relative DEFAULT of `NotifyStore`), table `ops_notification_outbox`, destination `OPERATIONS` (Sentinel).
- **Producer:** `talonx_ops.prospective.close` -> `_record_v2_reconciliation_blocks()` -> `enqueue_reconciliation_failure()` -> `_default_ops_notify_store()` (= `NotifyStore(os.environ.get("TALONX_NOTIFY_DB_PATH", "notifications.db"))`).
- **Test origin:** `tests/test_package2_account_blocks.py:324` (`"cash_plus_open_cost_reconciles: FAIL some detail"`) and `tests/test_package4_sizing_accounting.py:479/508/529`
  (fixture ledgers with episode `ep1`, 12.5 shares, -50.0 position cost, $300,000 cash, campaign `V2`). No test set `TALONX_NOTIFY_DB_PATH`, so every run wrote to the shared production file.
- **Why they were consumed:** the outbox has no campaign/environment scoping and these rows had no `deliver_by` (never expire); they sat PENDING because no real transport was active during tests.
  The release start's OPERATIONS drain (V2 companion, same default path) delivers every due row for the destination -> all 9 were SENT at 18:42:36-18:42:48Z, during startup.
- **Predated RC1:** yes. Created 2026-09-18 (3), 2026-09-19 (3), 2026-09-21 07:16-07:17Z (3) - all before the release campaign ledger was created (2026-09-21 16:29Z). The 2026-09-21 rows came from regression runs
  earlier the same day (including the release-acceptance work of this operator), the 09-18/19 rows from earlier package tests.
- **Unrelated to V2-PAPER-RC1:** provenance `campaign_id = "V2"`, $300,000 arithmetic, `ep1`, "FAIL some detail" - none exists in the RC1 ledger (0 trades, 0 positions, cash 100,000).
- **State after canary:** all 9 were `SENT` (attempts 1). Telegram history cannot be rewritten; the cleanup goal is preventing recurrence.

| event_id | created | sent | first finding |
|---|---|---|---|
| eddccc99bf02f06c21fbb628 | 2026-09-18T08:43:11Z | 2026-09-21T18:42:36Z | whole_share_positions: [('ep1', 12.5)] |
| da5731fbdb4d2e2e6b45a346 | 2026-09-18T08:43:11Z | 2026-09-21T18:42:37Z | cash_plus_open_cost_reconciles: cash 290000.0 + open_cost -5 |
| cb4283aeb6b01588b62c64af | 2026-09-18T08:43:12Z | 2026-09-21T18:42:38Z | cash_plus_open_cost_reconciles: FAIL some detail |
| 36523b9e0b7e2b8227025b4b | 2026-09-19T09:05:34Z | 2026-09-21T18:42:39Z | whole_share_positions: [('ep1', 12.5)] |
| 36bb769fd1eba909f63a1fa3 | 2026-09-19T09:05:34Z | 2026-09-21T18:42:41Z | cash_plus_open_cost_reconciles: cash 290000.0 + open_cost -5 |
| 150039728a73ee551a48ca76 | 2026-09-19T09:43:43Z | 2026-09-21T18:42:42Z | cash_plus_open_cost_reconciles: FAIL some detail |
| 7b0b311d842d00496fda4a15 | 2026-09-21T07:16:57Z | 2026-09-21T18:42:44Z | cash_plus_open_cost_reconciles: FAIL some detail |
| 4ac55d17ff785f0198b76391 | 2026-09-21T07:17:02Z | 2026-09-21T18:42:46Z | whole_share_positions: [('ep1', 12.5)] |
| 8c0d60745134776fb33982fe | 2026-09-21T07:17:02Z | 2026-09-21T18:42:48Z | cash_plus_open_cost_reconciles: cash 290000.0 + open_cost -5 |

Full sanitized export: `notification_rows_before_cleanup.json` (12 rows: 9 fixture + canary STARTUP + DEGRADED_HEALTH + SHUTDOWN).
