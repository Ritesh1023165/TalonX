# Task72 Part 9 -- Holdout Exposure Re-Audit

Independently re-verified (not trusting Task71's inventory blindly): repo-wide
grep for "2024" across every JSON result artifact, the research ledger, and
every `research/scripts/*.py` / `scripts/*.py` file, cross-checked against
`results/task70_f6_validation/historical_exposure_audit.json` (which performed
an equivalent audit one task earlier).

**Conclusion: calendar year 2024 is EXPOSED_DATA_ONLY at worst, except
Task70's two consumed blocks (2024-02-01..03-15, 2024-09-03..10-18), which
are OUTCOME_CONTAMINATED and are not reused.** No JSON artifact, script, or
ledger entry shows any strategy P&L outcome ever computed for 2024 outside
those two blocks -- the only marginal touches are (a) pure calendar-session
arithmetic in two old protocol scripts (zero price data), and (b) a
generic backtester documentation example (data-quality/row-count report
only, structurally unrelated strategy family, classified conservatively).

## Chosen holdouts (exactly the predeclared preferred ranges -- confirmed CLEAN)

- **VALIDATION:** 2024-04-01 .. 2024-05-31
- **REPLICATION:** 2024-10-21 .. 2024-12-20

Both confirmed non-overlapping with Task70's consumed blocks, Task71's own
development range, and each other. The pre-existing forward-reserved plan
(2026-08-25 onward) cannot be used -- today (2026-08-26) is only one day
into that window and it has not traded yet.

## Beta warmup disclosure

No lead-in data outside the exact locked ranges will be downloaded, to
avoid any ambiguity about touching territory adjacent to Task70's consumed
blocks. The first ~20 trading days of each locked block will therefore show
`DATA_NOT_READY` (beta not yet estimable) by construction -- the same
precedent Task71 itself already established and disclosed for its own
DEVELOPMENT slices. This is a data-readiness rejection, not an outcome
computed on excluded days.

Outcomes inspected before this lock: **NO**.
