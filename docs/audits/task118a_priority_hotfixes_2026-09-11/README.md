# Task 118A — priority hotfixes evidence bundle

Added 2026-09-11 (Task 118B) — this index file did not exist when Task
118A originally published this bundle, which is why a direct fetch of
`README.md` returned 404; the other four files were present and pushed
(`d61b920`) from the start. Indexed here rather than moved, to keep every
existing inbound link working.

- [`ACTIVATION_REPORT.md`](ACTIVATION_REPORT.md) — overall verdict,
  preflight, controlled deployment sequence, post-restart acceptance
  evidence (start here).
- [`PRIORITY1_EXPERIMENTAL_EXIT_LIFECYCLE.md`](PRIORITY1_EXPERIMENTAL_EXIT_LIFECYCLE.md)
  — Experimental paper exit lifecycle: trace, fix, tests, recovery policy.
- [`PRIORITY2_ORIGINAL_WARMUP.md`](PRIORITY2_ORIGINAL_WARMUP.md) —
  Original intraday warmup/readiness investigation (no code change).
- [`PRIORITY3_OPERATOR_VISIBLE_CORRECTNESS.md`](PRIORITY3_OPERATOR_VISIBLE_CORRECTNESS.md)
  — digest rendering, dashboard message counting, EOD-reconciled flag
  fixes.

See also, on the research branch (`research/talonx-profitability-2026-09`):
`docs/research/TASK118A_RESEARCH_CORRECTIONS.md` and the Task 118B
follow-ups (`TASK118B_EXIT_TIMING.md`, `TASK118B_EQUITY_RECONCILIATION.md`,
`TASK118B_READINESS.md`, `TASK118B_RESEARCH_PROTOCOL.md`).
