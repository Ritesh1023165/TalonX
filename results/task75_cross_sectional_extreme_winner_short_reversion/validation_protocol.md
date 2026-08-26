# Task75A Part 7/8 -- Pre-Registered Validation Protocol

Declared BEFORE any holdout outcome is known. See
`validation_protocol.json` for the machine-readable 17-criterion list.

**Precondition gate (checked FIRST): corporate-action-safe dataset
required.** Task75B is currently **BLOCKED** pending resolution of the
raw/unadjusted data problem (`corporate_action_policy.json`). Running
against the current raw dataset is prohibited outright.

**Primary pass/fail cost: 25bps all-in** (not 10bps) -- this is a
short-only strategy and 10bps was shown insufficient reasoning per this
task's own instruction. Task74B's own `net@10bps >= +0.15%` bar is
still separately preserved as a mandatory criterion, unweakened.

**New overlapping-dependence checks** beyond anything Task71/72/74B
required: an entry-day cluster bootstrap AND a calendar moving-block
bootstrap (block length = 5 trading days, pre-chosen, >= the 3-day
holding horizon) must both show a CI that is not clearly negative for
net expectancy at 25bps.

**Effective search count disclosed:** 40 (not 20) direction-level
comparisons underlie this candidate's provenance -- criteria are held
at Task74B's bar or stricter to compensate, not loosened.

Classifications: `BLOCKED` / `VALIDATION_PASS` / `VALIDATION_FAIL` /
`VALIDATION_INCONCLUSIVE`. Validation runs exactly once. Replication is
forbidden unless classification is exactly `VALIDATION_PASS`.
