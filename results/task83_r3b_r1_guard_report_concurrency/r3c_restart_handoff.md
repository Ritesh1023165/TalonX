# Task 83-R3C — Clean-Room Offline Requalification Restart

## Entry checkpoint

- Start from the pushed R3B-R1 evidence checkpoint on `research/talonx-strategy-validation`.
- Require synchronized local and remote-tracking SHAs, a clean tracked tree, preserved Task 56 and Task 83-R2 stashes, no active Python/pytest/TalonX process, and an empty protected Quant diff.

## Restart requirement

Restart R3C from its clean-room checkpoint and pre-test integrity gate. Do not resume at Phase C: the earlier R3C attempt stopped in Phase B and remains historical blocked evidence.

Use the committed in-process guard reporter boundary, fresh per-phase reports and `%TEMP%` directories, direct output redirection, separate exit-code/status files, credential sanitization, and sequential fail-closed execution.

## Scope boundary

This handoff does not begin R3C. It does not authorize R3D, production runtimes, external services, broker activity, holdout access, or strategy changes.
