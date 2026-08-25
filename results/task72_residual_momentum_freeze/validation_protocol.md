# Task72 Part 8 -- Pre-Registered Validation Protocol

Declared BEFORE any holdout outcome is known. See `validation_protocol.json`
for the machine-readable 15-criterion list (transcribed directly from the
overnight task specification's own Part 8, not re-derived). Fingerprint
that must match before anything else is trusted:
`f3764b6794f2e00cc5262f73d241b5274ebf544dd65cc96e7a7ab175d7c6025a`.

Key emphasis: Task71's own main disclosed weakness for this candidate is
day-dependence (day-clustered CI crosses zero at every development cell).
This protocol does not require the validation day-cluster CI to exclude
zero (that would be an unrealistically strict bar for a smaller holdout
sample), but a clearly negative day-cluster CI combined with a weak point
estimate is disqualifying (criterion 10).

Classifications: VALIDATION_PASS / VALIDATION_FAIL / VALIDATION_INCONCLUSIVE.
Replication is forbidden unless classification is exactly VALIDATION_PASS.
No criterion may be loosened after seeing the actual numbers.
