# Task 121 Part 1 — Task 120(A–C) accounting corrections

Bounded corrections only (per this task's own instruction: "Keep this
bounded; do not rerun the full V2 baseline unless necessary to resolve a
concrete accounting discrepancy"). No replay was rerun — this is arithmetic
on the ALREADY-COMPUTED, already-committed local artifact
`results/task120b_chronological_baseline/b3_full_300k_summary.json`
(the $300,000-primary, 2019-01-01→2026-03-31, N=57 chronological V2
baseline).

## 1. "Properly powered" wording withdrawn

See corrections already applied directly in
`docs/research/TASK120ABC_CORRECTED_BASELINE_AND_DECISION.md` (two edits,
2026-09-12) and a correction blockquote appended to
`docs/task_journal/entries/2026-09-12_task120abc_baseline_correction_decision/outcome.md`.
Restated once here for a single point of reference: **N=57 closed trades,
19 distinct issuers, negative observed net expectancy, 95% CI including
zero** is the full supported description. No formal statistical power
calculation was ever performed for this or the earlier N=10 result;
"properly powered" / "adequately powered" was an unsupported characterization
and is withdrawn. Completion of the computation (a real, correctly-engineered
chronological replay) is a separate claim from strength of the resulting
inference, and only the former is asserted.

## 2. Gross vs. cost-adjusted ending equity — the actual bug

Task 120B's `equity_final.equity` field ($296,307.36) is **`portfolio
ending_cash + marked_open_value`, read directly from V2's own paper
ledger — and V2's paper engine (`talonx_v2/paper.py`) models NO cost at
all** (no spread, no slippage, no commission; confirmed in this task's own
manifest-hashing and in Task 119A's `_V2_COST_BREAKDOWN` finding). The
research 20bps-round-trip convention is applied **only** inside the
script's separate `net_return_pct_20bps` per-trade column, which never
flows back into `ending_cash`. Presenting `$296,307.36` next to
`net@20bps=-0.8478%` therefore invited exactly the misreading this task's
prompt named: the equity figure is **gross of the 20bps research cost
convention**, not "cost-adjusted equity."

### Exact reconciliation (computed from the committed trade table, not
approximated)

| | value |
|---|---:|
| Starting capital | $300,000.00 |
| N closed trades | 57 |
| Avg entry notional per trade | $10,000.00 (V2's fixed 20-slot $10k sizing — exact, not approximate) |
| Gross realized P&L (sum of trade-level gross $ P&L) | **−$3,692.63** |
| Gross P&L cross-check (ending_cash − starting_cash) | −$3,692.64 (agrees to the cent; rounding only) |
| Explicit research cost adjustment (57 × $10,000 × 20bps round-trip) | **−$1,140.00** (verified exact per-trade sum: $1,140.00, matching the task's own back-of-envelope 57 × $10,000 × 0.002 = $1,140 precisely) |
| Open-position treatment | N/A — 0 open positions at window end; `marked_open_value = $0`, `open_position_cost_basis = $0` |
| **Cost-adjusted ending equity** | **starting_capital + gross_pnl − cost = $300,000.00 − $3,692.63 − $1,140.00 = $295,167.37** |
| Gross ending equity (the figure Task 120B originally reported unlabelled) | $296,307.36 |
| Net dollar P&L (sum of the already-reported `net_return_pct_20bps` × $10,000 per trade) | −$4,832.63 (agrees with gross − cost above to the cent) |

**Cost is applied exactly once** — the $1,140.00 subtracted from gross
equity is the SAME quantity already embedded in the per-trade
`net_return_pct_20bps` column (verified: `gross_pnl_usd − cost_usd_total
== net_pnl_usd` to within $0.01, reproduced by
`tests/test_task121_task120_equity_reconciliation.py`).

### What this does and does not change

- The **headline decision** (`CHRONOLOGICAL_BASELINE_COMPLETE_INCONCLUSIVE`,
  95% CI including zero) is **unchanged** — it was always computed from the
  per-trade net-return column, never from the mislabelled equity figure.
- What changes is **presentation only**: any reader citing "$296,307.36" as
  a cost-adjusted number was reading a gross figure. The correct
  cost-adjusted figure is **$295,167.37**.
- This correction is APPENDED to `TASK120ABC_CORRECTED_BASELINE_AND_DECISION.md`
  (see that file's own dated correction block) — the original number is
  preserved, not deleted, per this session's established convention.

## 3. Population mislabels corrected

No new mislabels were found beyond those Task 120A–C already corrected
(historical-replay-vs-live, episode-study-vs-chronological-replay,
6-name coverage bug). This task's own replay (Experimental,
`task121_experimental_replay.py`) draws on a **completely separate**
dataset (`task93_canonical_v1`, 1-minute equity bars) and a **completely
separate** strategy contract (`EXPERIMENTAL_RELAXED_V1`) from V2's Form-4
insider-cluster replay — the two populations are never pooled, and no
number from one is presented as evidence for the other anywhere in this
task's output.
