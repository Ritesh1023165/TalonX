# Task 137 Evidence — Review Index

Sanitized, directly-reviewable evidence for Task 137 ("Overnight
Continuity, Scope Accuracy and Delivery Fairness") and its immediate
predecessor Task 136 EOD reconciliation, published as plain files under
version control instead of requiring a ZIP download. This folder is
itself the output of a *separate* evidence-publication task; the
investigative work it documents was already committed and pushed before
this folder was created.

## Task objective and scope

Task 137 closed five concrete findings surfaced by review of Task 136's
own evidence: (1) an EOD "reconciled today" field that could never read
true for this deployment, (2) a delivery-selection starvation gap when a
bounded batch is filled entirely by permanently-failing lookups, (3) a
39-vs-626 execution-scope reporting mismatch between the observational
funnel and the live V2 companion, (4) an Original/V1 strategy fingerprint
mismatch, and (5) 35 stuck delivery rows rejected by a false-positive
content-safety match. It also investigated (without a code fix, since no
defect was proven) the exact latency breakdown for one naturally-
delivered card (LULU). No profitability research, filter relaxation, or
new architecture was in scope, and none was performed.

## Commits

| commit | role |
|---|---|
| `32f8bc5` | starting HEAD for the Task 137 investigation |
| `ae61cdb` | tested runtime candidate — all 5 fixes + their focused tests |
| `cc7fa1d` | documentation — journal Addendum 8 ([`docs/research/TASK132_EXPANDED_DISCOVERY_DEV_RUN.md`](../../TASK132_EXPANDED_DISCOVERY_DEV_RUN.md)) |
| *(this folder's own commit)* | evidence publication only — no runtime/code/config change |

## Actual running component versions (UTC, with confidence)

| component | code loaded | evidence basis | confidence |
|---|---|---|---|
| Intelligence | `ae61cdb` | restarted 2026-09-14T21:57:41Z by this task specifically; clean startup log (569-symbol scope, single owner) + functional confirmation (BBY claim-safety rows resolved live at 22:41Z; the `'unqualified'` delivery-summary key, only present in this code, seen in every post-restart cycle) | **high** — directly restarted and functionally verified this task |
| Original (`run_talonx.py`) | `66a49f9` | restarted 2026-09-14T17:59:31Z for an unrelated, earlier Task 135 fix; not touched by Task 137's own commit | **high** for "not `ae61cdb`", **inherited** (not independently re-verified this task) for the exact SHA |
| Experimental, V2 companion, Dashboard, supervisor | pre-Task-137 code | none of these processes were restarted; `ae61cdb` did not modify any file they import | **high** for "unaffected by this task's changes" — their own exact loaded SHA was not re-verified here, since Task 137 did not need to restart them |

A repository HEAD is not the same claim as "every component's loaded
code" — this table exists specifically to avoid that conflation.

## Key observation timestamps (UTC)

- `2026-09-14T20:13:32Z` — Task 136's `close --no-shutdown` reconciliation (still the latest as of this evidence).
- `2026-09-14T21:57:41Z` — Intelligence restarted, loading `ae61cdb`.
- `2026-09-14T22:02:31Z` — scheduled retry time for the 35 BBY rows.
- `2026-09-14T22:21:03Z` — checkpoint daemon's actual (explained, clean) exit, vs. its nominal `22:00:00Z` deadline.
- `2026-09-14T22:41Z` — confirmed live: all 35 BBY rows resolved (`FAILED_RETRYABLE` 35→0), correctly landed `EXPIRED` (historical filings), nothing sent.

## File index

| file | what it proves |
|---|---|
| [`TASK137_OVERNIGHT_CONTINUITY_REPORT.md`](./TASK137_OVERNIGHT_CONTINUITY_REPORT.md) | the full investigation report: process ownership, EOD reconciliation, scope trace, saturation reproduction, fingerprint per-file/per-commit comparison, LULU latency trace, backlog/retry findings, separate verdicts |
| [`commit_ae61cdb_message.txt`](./commit_ae61cdb_message.txt) | full commit message — the exact, self-contained rationale for every fix, as committed |
| [`commit_ae61cdb_stat.txt`](./commit_ae61cdb_stat.txt) | `git show --stat` — file-level shape of the change (sanitized: author email redacted) |
| [`commit_ae61cdb_code.diff`](./commit_ae61cdb_code.diff) | the production code diff (`talonx_ingest/`, `talonx_ops/`, `talonx_backtest/`) — sanitized: author email redacted |
| [`commit_ae61cdb_tests.diff`](./commit_ae61cdb_tests.diff) | the test diff (new + updated test files) — sanitized: author email redacted |
| [`focused_test_run_output.txt`](./focused_test_run_output.txt) | raw `pytest -q` output for the newest/most-targeted test slice: `92 passed` |
| [`live_scope_and_fingerprint_verification.json`](./live_scope_and_fingerprint_verification.json) | live re-derivation of the scope union (39 ∪ 626-manifest = 626, matching the running V2 companion's own reported scope) and the fingerprint per-commit trace (freeze-commit blobs / current HEAD blobs / working-tree raw / working-tree LF-normalized), plus the claim-safety before/after scan results for the BBY case |
| [`final_live_confirmation_snapshot.json`](./final_live_confirmation_snapshot.json) | the checkpoint-daemon exit evidence (file names/timestamps, final health) and the BBY retry's live resolution, captured after the fact, not manufactured |
| [`before_after_outbox_and_backlog_snapshots.json`](./before_after_outbox_and_backlog_snapshots.json) | intelligence_delivery / enrichment-backlog state counts immediately before and shortly after the one restart this task performed |

## Test counts and raw-output coverage

- **19 new/updated focused tests** (5 test files — see `commit_ae61cdb_
  tests.diff` for the exact list of test names and their bodies).
- **92 passed** — the newest/most-targeted slice re-run specifically for
  this evidence pass (`test_task137_overnight_continuity.py` +
  `test_task136b_freshness_edge_cases.py` + `test_delivery_claim_safety.py`
  + `test_backtest_reproducibility.py` + `test_task65b_protected_
  fingerprints.py` + the two now-fixed `test_task114_prospective.py`
  fingerprint tests). **Raw output included** (`focused_test_run_output.
  txt`).
- **575 passed** — the broader regression batch across every directly
  affected module, reported in `TASK137_OVERNIGHT_CONTINUITY_REPORT.md`
  §8 and the commit message. **Reported; raw pytest output was not
  retained as a separate file** in this evidence set — the report
  narrates the batch and its scope, but the full terminal transcript
  (a much larger run covering many unrelated test files) was not saved.
- **11 pre-existing, unrelated failures**, each named individually in
  the report/commit message, reconfirmed present on unmodified `32f8bc5`
  via `git stash` before this task's changes were applied. **Reported;
  raw before/after pytest output for that specific comparison was not
  retained** — the finding is documented in prose (file/test names,
  failure class, and the stash-based reproduction method) but the actual
  terminal transcripts from that comparison are not included here.

## Known limitations

- **Source-to-local-discovery latency (LULU, accession
  `0001397187-26-000129`)**: enrichment and delivery stages are
  precisely measured (sub-second and ~8-9s respectively, no defect). The
  interval between SEC's own acceptance timestamp (16:15:47Z) and our
  poller's actual first successful fetch is **explicitly not
  localizable** from available evidence — the only candidate marker
  (`ingested_at_utc`) is confirmed batch-fixed (shared across unrelated
  records), and no per-symbol poll-fetch log line survives for this
  accession. The report states this as an open evidence gap rather than
  inferring a number; no instrumentation was added to close it (optional,
  not implemented).
- **Component SHA confidence**: as tabulated above, Original/Experimental/
  V2-companion/Dashboard/supervisor's exact currently-loaded SHA was not
  independently re-verified in Task 137 (none of them were restarted, and
  none of their imported files were touched by `ae61cdb`) — confidence is
  "unaffected by this change," not "independently reconfirmed."
- **Full-suite raw output**: as noted above, the 575-test and 11-failure
  batches are reported narratively, not attached as raw transcripts.

## Fingerprint values and their distinct meanings

| name | value | meaning |
|---|---|---|
| V2 release fingerprint (frozen) | `11107198c5b81237` | the V2 (`INSIDER_BUY_CLUSTER_V2@1`) strategy release fingerprint — a **separate mechanism** (`research/scripts/task112_v2_release_fingerprint.py`) from the two below; confirmed **unchanged** by this task |
| Original/V1 fingerprint — stale expected value (superseded) | `2ae6216bca70` | the value `V1_FINGERPRINT_EXPECTED` held before Task 137; frozen at commit `18e93d9` (Task 114), never updated after a later, legitimate change |
| Original/V1 fingerprint — actual, pre-fix computed value | `2dea67a6f6d2` | what `get_strategy_version()` returned before this task's fix — raw working-tree bytes (CRLF), against the stale expected constant |
| Original/V1 fingerprint — corrected baseline (current) | `ed8272fe568d` | `V1_FINGERPRINT_EXPECTED` after this task's fix; equals the LF-normalized hash of the 5 fingerprinted files at current `HEAD` — reproducible directly from `git show HEAD:<files>`, LF-normalized, sha256, first 12 hex chars |

The V1 mismatch had two distinct, separately-confirmed causes (full
per-file/per-commit trace in the main report and in
`live_scope_and_fingerprint_verification.json`): CRLF-vs-LF line-ending
representation (now neutralized by normalizing before hashing), **and**
a real, already-authorized commit (`66a49f9`, Task 135, same session)
that legitimately modified one of the 5 fingerprinted files
(`talonx_quant/consumer.py`, confined to Pub/Sub delivery-observability
logging — not gating/scoring logic) after the old constant was frozen.

## Sanitization notes

- **Excluded from this folder entirely**: the original ZIP
  (`results/task137_evidence.zip`, still present locally, not committed
  — `results/` is git-ignored by project convention and this task did
  not need to change that); any production database, database backup,
  cache, or bulk filing content; any credential, token, authorization
  header, or connection secret; any Telegram chat ID or private
  recipient detail (none were present in the source evidence — see scan
  below).
- **Redacted in place**: the git commit author's personal email address
  (`Ritesh Talwadekar <[REDACTED-EMAIL]>`) in `commit_ae61cdb_stat.txt`,
  `commit_ae61cdb_code.diff`, and `commit_ae61cdb_tests.diff` — the only
  personal-identifier pattern found. The author's name and the commit
  SHA/date/message are preserved (useful, non-sensitive provenance); only
  the email string itself was replaced with the literal marker
  `[REDACTED-EMAIL]`.
- **Preserved deliberately** (useful correlation evidence, not sensitive):
  SEC accession numbers, event/delivery IDs, Telegram **message IDs**
  (945/946 — these identify a message within TalonX's own already-
  configured, non-secret channel, not a recipient), commit SHAs, and all
  UTC timestamps.
- **Scan performed** across the complete staged content (case-insensitive):
  `gmail`, git author name/email, `chat_id`, Telegram bot-token shape
  (`bot[0-9]{5,}:...`), `api_key`/`api-key`, `authorization:`, `bearer `,
  `password`, `private_key`, AWS-key shape (`AKIA...`). Only the one git
  author email (above) matched; everything else was already clean before
  redaction.
- **Distinguishing sanitized copies from originals**: this folder's
  copies are marked, in this README, as sanitized redistributions of the
  evidence originally produced during the Task 137 investigation
  (unmodified aside from the one redaction above) — no factual result,
  number, timestamp, or verdict was altered.

## Runtime/config/services

This evidence-publication task made **no change** to runtime code,
configuration, strategy settings, or any running service — it only added
files under `docs/research/evidence/task137/`. The investigative fixes
themselves (already applied, tested, and live-verified) are documented
in the referenced commits (`ae61cdb`, `cc7fa1d`), both already on
`feature/task131-option-a-integration` before this folder was created.
