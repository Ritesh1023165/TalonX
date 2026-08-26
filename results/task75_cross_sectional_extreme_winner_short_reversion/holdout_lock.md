# Task75A Part 8 -- Holdout Lock

- **Validation:** 2024-06-01 .. 2024-09-02 (reserved, untouched)
- **Replication:** 2024-10-21 .. 2024-12-20 (reserved, untouched)
- **Outcomes inspected this task: NO**
- Replication remains untouched unless validation passes.

**Task75B must NOT proceed until the corporate-action-safe-dataset
precondition (`corporate_action_policy.json`) is resolved** -- re-download
with a non-raw Alpaca adjustment, or an equivalent verified corporate-
action correction.

Task75B must construct its own `LockedRangeGuard`-style guard (following
`research/task72_residual_momentum/holdout_guard.py`'s pattern) before
touching any 2024 data -- not built here, since Task75A itself must not
prepare to read any 2024 outcome.
