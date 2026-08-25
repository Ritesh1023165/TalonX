# Task72 Part 10 -- Holdout Lock

Committed and pushed BEFORE any holdout outcome is computed.

- **Strategy fingerprint (must match at run time):**
  `f3764b6794f2e00cc5262f73d241b5274ebf544dd65cc96e7a7ab175d7c6025a`
- **VALIDATION:** 2024-04-01 .. 2024-05-31
- **REPLICATION:** 2024-10-21 .. 2024-12-20
- **Provider:** Alpaca SIP, 35-symbol universe + SPY benchmark
- **Outcomes inspected before this lock: NO**

See `holdout_exposure_audit.{json,md}` for the full re-audit justifying
these two ranges as clean. Enforced structurally by
`research/task72_residual_momentum/holdout_guard.py::LockedRangeGuard`,
constructed with exactly these two date ranges -- any other range raises
before any file I/O.
