# Session 03: EOD and reconciliation

`python -m talonx_ops.prospective close` ran at **2026-09-23 21:13:52 BST (20:13:52Z)**, inside the post-close window (XNYS close 20:00Z; grace deadline 21:30Z). The accepted flow ran: final checkpoint → reconciliation → report → controlled shutdown.

## EOD_RECONCILIATION: **PASS_WITH_FINDINGS**

| Assert | Result |
|---|---|
| buys = sells + open + unresolved | PASS |
| cash + open cost reconciles (cash arithmetic) | PASS |
| no negative cash / whole shares / positive finite cost | PASS |
| corporate-action adjustments consistent | PASS |
| dividend accounting consistent (receivables 0) | PASS |
| no duplicate buy / position episode (no duplicate settlement) | PASS |
| no stale episode entered | PASS |
| no illegal EOD flatten / real capital off / shorts off | PASS |
| experimental external sends zero / no cross-lane contamination | PASS |
| official dispatch healthy | PASS |
| **base_reconciliation** | **PARTIAL**: no PIV reader injected (known, documented), mismatches = [] |
| V2 ledger preserved copy / lane accounting snapshot | PASS |
| controlled shutdown complete | PASS: 0 residual processes, ports released |

## V2 campaign at EOD (`V2-PAPER-RC1`)

| Item | Value |
|---|---|
| Starting / settled cash | $100,000.00 / $100,000.00 |
| Reserved | $0 |
| Open / closed positions | 0 / 0 |
| Intents (pending / total) | 0 / 0 |
| Active account blocks | 0 |
| EXIT_UNRESOLVED | 0 |
| Realized P&L / dividends / total return | $0.00 / $0.00 / $0.00 |
| V2 alert outbox rows (trade/outbox consistency) | 0, consistent with 0 trades |
| Processed episodes | 2 terminal skips (ABCL, ADC), unchanged since 2026-09-21 |

## Provider and notifications

- **SIP:** HEALTHY. No pricing unavailability, no witness disagreements, fallback NONE, no CSV. Market feed HEALTHY, coverage 1.0.
- **Signal:** 0 sent, 0 failed.
- **Sentinel:** STARTUP SENT, DEGRADED_HEALTH SENT (transient Intelligence), SHUTDOWN PENDING (known).
- **Ingestion final state:** pid 7272, last poll 20:09:51Z FRESH, 0 failed, 0 errors.

## Release integrity

- SOURCE CODE CHANGED: **NO** (HEAD `9f0ab38` throughout; tracked tree clean)
- STRATEGY RULES CHANGED: **NO** (fingerprint `e2acf6454789217e`)
- PROVIDER CONTRACT CHANGED: **NO** (`ac5e51aa3599d6c9`)
- ACCOUNTING CHANGED: **NO**
- CAMPAIGN REINITIALIZED: **NO**
