# Controlled weekend shutdown assessment, 10 October 2026

**PARTIAL_SHUTDOWN_ONLY — KEEP THE MACHINE ON.** A full application shutdown through Monday would miss the required Sunday V2 forward observation at 06:00 UTC / 07:00 BST. The authoritative daily loop and `forward_runner.next_slot` have no weekend exclusion. Saturday completed SUCCESS at 06:03:48.795792 UTC. No study outcomes or protected ERM inputs were inspected, and no study cycle was triggered.

Actual checkout and live remote branch HEAD: `41375bb3477c926be53f3a571408fe5069dec9a3`, `feature/continuous-opportunity-engine`. This includes the latest compact icon-template deployment record; its runtime promotion provenance is version `de24a9891031`, code `643c22aece4c-dirty`, started 9 October 20:30:42 UTC. Natural delivery is still unverified. Component-specific loaded versions differ from checkout HEAD; the manifest records their actual runtime provenance. Long-lived base-stack components do not provide a trustworthy loaded source commit, so none is inferred from current disk HEAD.

## Executed shutdown

Only the four horizon evaluators were stopped. Existing API `talonx_opportunity.supervise.request_stop(None,name)` was called for all four, followed by `wait_stopped(None,name,45)`. Request time 19:03:37.980940 UTC; all locks released by 19:03:42.994459 UTC (20:03:42 BST). There was no forced kill. Their documented runtime checks the flags after completing a tick/transaction, and the supervisor skips components whose stop flag exists. Four persistent stop flags therefore prevent immediate relaunch. No notification sender was stopped or send interrupted by these actions. Cursor/record writes commit together; stopped stores and backups passed SQLite quick_check.

The four evaluators create no paper orders, send no notifications, have no authorised BUY/SELL strategies, and consume a durable event stream through independent cursors. They can safely remain off until restoration before Monday's overnight window. Their existing consumption semantics are preserved.

## Retained state and obligations

- V2 forward wrapper/loop/sleeper retained, one logical chain. Required next cycle Sunday 11 October 06:00 UTC; Monday 12 October 06:00 UTC. It acquires EDGAR/Alpaca inputs with fresh stage interpreters and local research caches. No missed-run catch-up is built into the sleep-first wrapper; the raw loop starts immediately and must not be manually launched.
- VR retained: entries blocked at the original interruption boundary, zero OPEN trades and one historical PAPER_ENTRY_PENDING. Pending management disposition is unresolved; it was not deleted, declared harmless or abandoned. End date remains 16 October.
- Ops supervisor, Original, Intelligence, dashboard and V2 companion retained. Original/long-term paper positions zero; V2 positions and pending intents zero. V2 heartbeat 19:06:31 UTC at verification, data CURRENT, PAPER, release SIP contract active. Redis PONG and dashboard port 8787 reachable. No shared dependency was stopped.
- Opportunity supervisor, ingestion, discovery, notifier, outcomes, reporting, promotion and Sentinel retained. Retained components have one exclusive OS-lock owner each. Venv launcher/interpreter pairs are not duplicate owners. Outcomes/management work remains running; no candidate or outcome rows were changed by this assessment.
- Intelligence retained because 1 PENDING and 3 AMBIGUOUS deliveries require their existing handling; safe disposition of the pending row is not established. Existing durable processing, dedup and backfill checkpoints support resume, existing expiry runs before send, and ambiguous outcomes are never automatically retried. No stale-message guarantee is invented. All delivery components remain unchanged.
- PDM is inactive, approved first session 19 October. Existing task is Ready with first trigger 20 October 00:15 BST / 19 October 23:15 UTC, then 06:30 BST. Config/locks/task preserved. All other relevant scheduler tasks are expired one-shot ERM/UniverseVerify tasks with no next run. No new tasks were registered.
- DTU collector remains stopped under its closed endpoint; ERM remains parked. No process inventory showed a resumed collector or ERM worker. External workspace ERM inputs were not opened.

## Universe and restoration timing

Policy schedule remains `DTU_V3_TOP600` effective from 9 October. Latest published window is 9 October, Core 600, fingerprint `2849da5594f272db`, no event tier. Ingestion reports that policy, reconciled report and 603 fetched names (Core union V2 scope), no fallback. Monday window starts **00:00 UTC / 01:00 BST**, independently verified with the actual trading calendar. Ingestion remains on to build the Monday snapshot through the normal path; current data/Friday membership is not a substitute for Monday publication. New admissions must await agreement among ingestion, discovery and Sentinel.

Restore paused evaluators by **11 October 23:30 UTC / 12 October 00:30 BST**. Recheck operational health by **12 October 05:30 UTC / 06:30 BST** before the study slot. This is earlier than premarket and regular open. Keep the laptop on, on AC, connected and logged in throughout the weekend.

## Evidence and protection

`RESTORE_MANIFEST.json` contains actual process ancestry, runtime loaded versions, stop commands/times, final lock states, controls, scheduler backup paths/hashes, database/outbox counts and 38 consistent database/config backups. SQLite online backup API accounted for committed WAL state; no active main-file-only copies, checkpoints, WAL deletions or lock removals were used. Every database backup passed quick_check and every backup hash matched. Local scheduler XML backups add eight task definitions. Backups are protected by a directory DACL for the current Windows account, SYSTEM and administrators; no machine security policy or power setting changed. Databases, configuration contents, Telegram identifiers, tokens and lock-owner secrets are excluded from Git.

All backed-up controls and the owner's `forward_alpha_validation.md` matched their original hashes after shutdown. The dirty document's SHA256 is `b1c886baf34d00fde4eece73e927c500432581bc6040f38c0549df3cdcfd7936`; it is excluded from this commit. Unrelated tracked/untracked files remain untouched.

Concrete limitations: VR pending disposition, Intelligence pending/ambiguous deliveries, and the previously missing checkpoint-daemon owner remain findings. The retained components avoid abandoning them. A live process alone does not establish operational freshness; use advancing heartbeat/poll/data times and the next natural run record. Monday's future publication and template delivery cannot yet be verified. The runbook provides checks and conditional recovery commands without authorising backfill or changing study rules.

Runbook: `docs/runbooks/2026-10-12_MONDAY_RESTART.md`.
