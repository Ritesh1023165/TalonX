# Task 83-R3C — Clean-Room Offline Requalification

## Entry conditions

- Begin from the pushed, synchronized R3B evidence checkpoint.
- Require a clean tracked working tree and preserve the Task 56 and Task 83-R2 stashes.
- Confirm the protected Quant files remain unchanged.
- Treat the R3B network guard and explicit Telegram fake boundary as mandatory test-isolation controls.

## Objective

Perform a clean-room, offline requalification using only the scope and acceptance criteria supplied for Task 83-R3C. Establish fresh temporary and evidence locations and do not reuse an active runtime, credential-bearing configuration, or mutable test state from R3B.

## Constraints

- Keep external networking fail-closed and use injected fakes for Telegram polling.
- Do not launch production services, broker activity, dashboards, Original, or PIV unless a later R3C instruction explicitly authorizes a bounded offline substitute.
- Do not access holdouts, tune or approve strategies, modify protected Quant files, or begin any later task.
- Preserve all R3B raw and sanitized evidence without rewriting it.

Task 83-R3C has not been started by this handoff.
