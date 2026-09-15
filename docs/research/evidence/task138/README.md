# Task 138 Evidence Index — Overnight Operational Corrections and Concise Telegram Alerts

**Objective/scope**: close the three Task 137 review gaps (delivery
fairness, runtime scope evidence, EOD completeness); design and ship a
quieter, deterministic informational-notification delivery policy; add
durable reply-for-details correlation to the existing Telegram listener;
validate and cut over with the smallest necessary managed restarts;
document morning handover. Full governing directive, constraints and
required report format: reproduced verbatim in this session's own working
notes; summarized faithfully throughout this bundle.

**Starting commit**: `13c9902`. **Tested/verified commit at report time**:
`5eb9f36` (full SHA `5eb9f360a183ce6a310b1725aaf119cc7bc52744`). **Doc
commit**: this evidence bundle's own commit, immediately following.

**Per-component running versions at report time** (see
`before_after_cutover_snapshots.json` for full detail):

| component | code confidence | method | limitation |
|---|---|---|---|
| Original (`run_talonx.py`) | HIGH | in-process `commit_sha` via live `git rev-parse HEAD` at its own startup | none material |
| Intelligence (`...service poll`) | MEDIUM-HIGH | exact PIDs killed + fresh process launch + clean `git status` at HEAD `5eb9f36` before/after | no in-process SHA readout exists for this service |
| Experimental / V2 companion / Dashboard | N/A (untouched) | unchanged PIDs throughout, no code imported by this task | not applicable — not restarted |

**UTC observation timestamps**: task start `2026-09-14T23:06:52Z`;
managed restarts `2026-09-14T23:52:15Z` (Intelligence),
`2026-09-14T23:53:06Z` (Original); one-time backlog-reclassification
cutover step immediately after; post-cutover verification through
`2026-09-15T00:0XZ`. All read via `date -u` / Python
`datetime.now(timezone.utc)`, never inferred from the supervisor log's own
unlabelled Europe/London-local prefixes (confirmed UTC+1 offset this
period by direct comparison against embedded `_utc` fields).

## File index

| file | what it is | raw evidence, or reported-only? |
|---|---|---|
| `TASK138_OVERNIGHT_REPORT.md` | the full narrative report (11-item format) | — |
| `commit_96a6457_message.txt` / `_stat.txt` | Workstream 1 commit (personal author email redacted) | raw |
| `commit_5734b8c_message.txt` / `_stat.txt` | Workstream 2 commit (personal author email redacted) | raw |
| `commit_5eb9f36_message.txt` / `_stat.txt` | Workstream 3 commit (personal author email redacted) | raw |
| `focused_test_run_output.txt` | `-v` output, the 5 Task 137/138 test files, 106/106 pass | raw |
| `full_suite_run_output.txt` | full repository suite summary (17 failed/4,805 passed/6 skipped) + baseline-comparison verdict | raw |
| `full_suite_failures_detail.txt` | every one of the 17 failures' individual traceback | raw |
| `before_after_cutover_snapshots.json` | pre/post-restart PIDs, accounting, outbox counts, fingerprint | raw, hand-verified against live DBs |
| `post_cutover_checkpoint_capture.json` | full `talonx_ops.prospective.checkpoint.capture()` output post-cutover | raw, live |
| `reply_details_945_post_restart.txt` | real "details" reply for a real LULU card (pre-restart data), resolved post-restart | raw, live |
| `reply_details_958_live_post_cutover_digest.txt` | real 14-event digest (message 958) generated entirely AFTER cutover, indexed | raw, live |
| `reply_details_958_item1.txt` | item 1 of that digest — real live confirmation of the DIGEST-routing rule (MEDIUM band, no substantive trigger) | raw, live |

**Known limitations, stated once here and not repeated per-file**:

- **Source-to-discovery latency** for Intelligence ingestion is not
  re-measured in this task; Task 132/134's prior measurements stand
  unchanged (this task did not touch the ingestion-latency path).
- **Live inbound Telegram reply verification is PENDING** — no natural
  operator reply occurred in this session's window; not manufactured. See
  `TASK138_OVERNIGHT_REPORT.md` §5.
- **No live, naturally-occurring CONCISE-tier IMMEDIATE send was directly
  observed to complete** within this report's window, though a real
  post-cutover DIGEST send (message 958) was directly verified working
  end-to-end, including a live confirmation of the disposition rule
  itself. See `TASK138_OVERNIGHT_REPORT.md` §9. Reported as a valid,
  non-manufactured outcome, not omitted.
- `full_suite_run_output.txt` reflects the completed run (17 failed,
  4,805 passed, 6 skipped, 52m31s) plus this session's own
  baseline-comparison verdict for every failure (all 17 reproduce
  identically on the pre-Task-138 commit `13c9902`, verified via a
  temporary `git worktree`, never assumed).

**Sanitization notes**: git author personal email redacted to
`[REDACTED-EMAIL]` in all three commit-message files (the
`noreply@anthropic.com` co-author line is not personal and was left
intact). No credentials, Telegram chat IDs, database files, bulk SEC
filings, or binary archives are included anywhere in this bundle — every
file here is a text report, a git commit artifact, or a JSON snapshot
built from targeted, read-only (or one authorized, logged, additive)
queries against the live stores, never a raw database copy. Event IDs,
accessions, commit SHAs, Telegram message IDs (945, 953-957) and UTC
timestamps are preserved throughout as they carry no secrecy and are
necessary for verifiability.

**Fingerprint values, distinct meanings** (do not conflate):

- `11107198c5b81237` — the frozen V2 strategy release fingerprint
  (`INSIDER_BUY_CLUSTER_V2@1`), verified unchanged before and after this
  task.
- `5eb9f360a183ce6a310b1725aaf119cc7bc52744` — this task's own final git
  commit SHA (code identity, not a strategy fingerprint).
- `2ae6216bca70` — the separate, also-frozen, Original V1 strategy
  fingerprint, not touched or re-verified by this task (no V1 strategy
  code was in this task's authorized surface).
