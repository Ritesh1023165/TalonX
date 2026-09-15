# Task 138 — Overnight Operational Corrections and Concise Telegram Alerts

Branch `feature/task131-option-a-integration`. Actual UTC start time verified
at execution: **2026-09-14T23:06:52Z** (`date -u`). Report generated
**2026-09-15T00:56:59Z** (UTC; matches the committing commit `0fe57f4`'s own
`2026-09-15T01:56:59+01:00` timestamp; never inferred from unlabelled
Windows-local log prefixes — this repo's supervisor log is in Europe/London
local time, UTC+1 during this period, confirmed by direct comparison against
every event's own `_utc` field, e.g. supervisor log `00:52:33` local = `23:52:33Z`).

**Correction (added 2026-09-15, under Task 139/140)**: this report
originally read "Report generated 2026-09-15T00:0X:XXZ" — an unfilled
placeholder left in by mistake. Filled in above from the committing
commit's own timestamp, the actual best available evidence for when this
file's content was finalized.

## 1. Starting/final SHA, push result, running component versions

- Starting HEAD (per the directive): `13c9902`.
- This session's commits on top, in order:
  - `96a6457` — Workstream 1 (the three Task 137 review-gap corrections)
  - `5734b8c` — Workstream 2 (notification policy)
  - `5eb9f36` — Workstream 3 (reply "details")
- **Final HEAD: `5eb9f360a183ce6a310b1725aaf119cc7bc52744` (`5eb9f36`).**
- Push: **completed**. Pushed as part of commit `0fe57f4`
  (`13c9902..0fe57f4` on `origin/feature/task131-option-a-integration`).
  **Correction (added 2026-09-15, under Task 139/140)**: this line
  originally read "pending as the last step of this report" — stale by
  the time of final commit/push; corrected here rather than left
  misleading. See §9 of the Task 139 evidence bundle for everything
  pushed since.
- Running component versions, verified after the managed restarts (§7):
  - **Original** (`run_talonx.py`, PID 23600→14332): `commit_sha` =
    `5eb9f360a183ce6a310b1725aaf119cc7bc52744`, read directly from
    `talonx_ops.supervisor status` → `producers.original.metadata.commit_sha`,
    which `run_talonx.py` itself writes via a live `git rev-parse HEAD`
    subprocess call at its OWN startup (`talonx_ops/runtime_metadata.py`) —
    a genuine in-process attribution, not a log-marker inference.
  - **Intelligence** (`talonx_ingest.intelligence.service poll
    --with-backfill`, PID 24332→24372): no in-process SHA readout exists for
    this service. Attribution is INDIRECT: the exact PIDs were killed and a
    fresh process was launched after that kill; `git status --short` was
    verified clean immediately before and after the restart, with HEAD at
    `5eb9f36`. This is the stated limitation for this component, not a
    claim of exact in-process verification.
  - **Experimental**, **V2 companion**, **Dashboard**: unchanged PIDs,
    untouched code — no restart needed or performed (see §7).
- V2 frozen strategy fingerprint verified **unchanged**: `11107198c5b81237`
  (recomputed live via
  `research.scripts.task112_v2_release_fingerprint.v2_release_fingerprint()`).

## 2. Task 137 review gaps — reproduced/fixed status and evidence

### A. Delivery fairness at real scheduling intervals — **REPRODUCED, FIXED**

The existing saturation fixture advanced cycles by 1 second (inside the
fixed 30s DEFER backoff), which could not demonstrate fairness at the real
~3–4 minute production cycle interval. A corrected fixture (more rows than
the bulk-scan limit; persistently failing high-priority rows outside that
scan; a valid row behind them; cycles separated by minutes, not seconds)
reproduced genuine indefinite starvation under the OLD fixed-backoff design.
**Fix**: a dedicated `defer_count` column (additive migration, distinct
from the unrelated send-attempt `attempts` counter) drives an exponential,
capped backoff (`30s × 2^(n-1)`, capped at 3600s) written by
`_expire_row_if_stale`'s DEFER branch. The bulk `expire_stale()` sweep's own
filter was deliberately left untouched after an earlier attempted change to
it was found to break 3 unrelated pre-existing tests (that column is shared
with the send-retry backoff `mark_failed()` sets on a different clock basis
— see the Errors-and-fixes note in commit `96a6457`'s own diff). No
unbounded scan, no arbitrary long sleep. Evidence:
`commit_96a6457_stat.txt`, `focused_test_run_output.txt`.

### B. Runtime scope evidence — **REPRODUCED (a bare count was previously
treated as sufficient), FIXED**

`evaluate_scope_evidence()` (`talonx_ops/prospective/checkpoint.py`) now
qualifies broad-discovery scope evidence against freshness, process
ownership (PID + argv from `session.pids.json`, `psutil`-backed liveness),
manifest readability, and reported-vs-reconstructed count reconciliation —
returning `SCOPE_FRESH_VALID` / `SCOPE_STALE` / `SCOPE_MISSING_MALFORMED` /
`SCOPE_WRONG_PROCESS` / `SCOPE_MANIFEST_UNREADABLE` / `SCOPE_MISMATCH`
instead of a bare count comparison. **Live verification**, captured
post-cutover (`post_cutover_checkpoint_capture.json`):

```json
"evidence": {
  "qualification": "FRESH_VALID",
  "broad_discovery_active": true,
  "reason": "fresh, owned snapshot; argv confirms --enable-broad-discovery; reported scope matches the reconstructed watchlist-union-manifest scope",
  "reported_scope_count": 626,
  "watchlist_only_count": 39,
  "reconstructed_scope_count": 626
}
```

626 (broad execution scope) vs 39 (watchlist-only) are preserved as
genuinely distinct figures, per the explicit instruction not to conflate
them.

### C. Available-scope EOD completeness — **REPRODUCED (any present-component
set could previously read as complete), FIXED**

`reconciled_to_available_scope()` (`talonx_ops/eod_reconciliation.py`) now
requires an EXACT match against
`_EOD_EXPECTED_COMPONENTS = {original_paper, experimental_paper, piv_paper,
alert_stores}` — no missing, no extra, no duplicate — before it can ever
return true, distinct from the pre-existing STRICT reconciliation field
(unchanged meaning). **Live verification**, same capture:
`eod_reconciled_today_available_scope: true` while the STRICT
`eod_latest.status` for the (already-closed) 2026-09-14 session remains
`"PARTIAL"` (PIV genuinely `NOT_CHECKED` — real limitation honestly
preserved, not silently converted to PASS). Test coverage: complete record
with only PIV NOT_CHECKED, missing component, duplicate/conflicting
component, UNKNOWN/failed required component, non-empty mismatches,
wrong-session record — all in `tests/test_task138_operational_corrections.py`.

## 3. Notification policy now active

Full deterministic policy: `docs/research/NOTIFICATION_POLICY.md` (this
report's evidence copy under this directory is the same file, unmodified,
referenced by relative link — see the README index). Summary:

- Three dispositions: `IMMEDIATE` (existing route, unchanged mechanism),
  `DIGEST` (existing route, unchanged mechanism), `DASHBOARD_ONLY` (new —
  `_enqueue_delivery` simply skips `enqueue_card`; the event/enrichment/
  significance score remain fully persisted and dashboard-queryable).
- `CRITICAL` band → always `IMMEDIATE` (the significance engine's own
  CRITICAL floor already requires ≥2 substantive families / ≥5 substantive
  points).
- `LOW` band → always `DASHBOARD_ONLY`.
- `MEDIUM`/`HIGH` band → `IMMEDIATE` only with an explicit substantive
  trigger present (a qualifying filing-comparison reason code, a
  ≥$1,000,000 single open-market insider transaction, or a ≥2-distinct-
  insider open-market BUY cluster checked directly, not via the generic
  cluster reason code that also fires for sell-only clusters); otherwise
  `DIGEST`.
- Watchlist membership, a bare "Form 4 filed" / "8-K Item 7.01" label,
  multiple disclosure types, and a HIGH label alone are explicitly NOT
  sufficient on their own — matching the directive's named examples.
- Already-PENDING backlog is brought under the new policy via a bounded,
  idempotent one-time reclassification pass, run once as the cutover step
  (§7) — never deletes a row, never touches a SENT/AMBIGUOUS row.
- V2's own paper entry/exit Telegram route is untouched — a structurally
  separate system this task does not modify.

## 4. Representative old vs. new alert examples

**Old (pre-Task-138) EXPANDED-tier card actually sent** (verbatim, HTML
stripped, from `reply_details_945_post_restart.txt` — a real LULU
Charter/Bylaw-amendment 8-K sent 2026-09-14 20:18 UTC, BEFORE this cutover):

```
🟠 HIGH INFORMATION SIGNIFICANCE
LULU (lululemon athletica inc.) · regular hours

Charter / bylaw amendment (8-K Item 5.03)
LULU filed an 8-K reporting a charter or bylaw amendment (Item 5.03)
Accepted: 2026-09-14 16:15 UTC
Form 8-K · items 5.02, 5.03, 9.01

Why surfaced:
• this company has not filed a CHARTER_BYLAW_AMENDMENT event in 24 months of tracked history
• 2 distinct disclosure types from this company within 7 days
• this company is on your watchlist (user priority, not market significance)

⚠️ Source freshness unknown at emit time
⚠️ Data limitations: multi_item_filing

🔗 SEC filing · ref 0001397187-26-000129

ℹ️ Information, not advice. TalonX makes no prediction about future price or returns.
```

**New CONCISE-tier shape** (target 3–5 lines, produced by `render_concise`,
verified by `tests/test_delivery_renderer.py`/`test_task138_notification_
policy.py` — no live example fell inside this report's bounded post-cutover
observation window, see §9 honestly; illustrative shape from the renderer's
own template, per `NOTIFICATION_POLICY.md` §7):

```
[INFO] LULU — Charter/bylaw amendment, rare for this filer (24mo)
LULU filed an 8-K amending its charter/bylaws; no prior such filing in 24 months tracked.
Source: 2026-09-14 16:15 UTC / age 3h59m
Reply "details" for facts and filing link.
```

**Generic Reg FD / routine sell-side cases now suppressed to DIGEST/
DASHBOARD_ONLY** (per `NOTIFICATION_POLICY.md` §6): a DXCM/PSA-style generic
Reg FD notice with no qualifying comparison, and a routine AXON insider-sale
summary under the $1M single-transaction / buy-cluster thresholds, both now
route to `DIGEST` instead of an immediate push — verified by
`test_reclassify_pending_rows_downgrades_a_non_substantive_immediate_row`
and the disposition-classification unit tests.

**Live, real, post-cutover confirmation** (not a synthetic test): a genuine
14-event digest went out at `2026-09-15T00:07:55Z` (Telegram message 958,
generated entirely under the new code, well after both restarts). Item 1
of that digest — Parker-Hannifin's routine 8-K Item 8.01 — carries exactly
`EVENT_TYPE_BASE` + `ON_WATCHLIST` as its only reasons (MEDIUM band, no
substantive trigger) and correctly routed to `DIGEST`, matching the policy
rule precisely: "a bare form/item number and watchlist membership alone
are explicitly NOT sufficient for `IMMEDIATE`." Full text:
`reply_details_958_item1.txt`; the digest's compact 14-item index:
`reply_details_958_live_post_cutover_digest.txt`.

## 5. Reply-for-details — implementation and verdicts

Implementation: `talonx_ingest/intelligence/delivery/reply_correlation.py`
+ `message_resolvers` extension point on `TelegramReplyListener`/
`DispatchAgent`, wired into `run_talonx.py` (commit `5eb9f36`). Correlates
via the existing `transport_message_id` column (bare id = single card;
`digest:<id>:<message_id>` = every constituent row of a digest) — no new
schema. Read-only (`mode=ro`) against Intelligence's own
`ingestion_ledger.db`, mirroring the established Experimental D/X/R/E
resolver contract exactly.

- **Isolated verdict: PASS.** 51 new tests (43 in
  `test_task138_reply_correlation.py`, 8 in
  `test_task138_telegram_message_resolvers.py`), covering: text-trigger
  parsing; single-card vs. digest correlation; full details rendering
  (facts/link/timestamps/significance reasons/HTML-stripped text/data
  limitations); missing event/significance honestly reported, never
  guessed; multi-event indexed summary + "details N" + out-of-range
  guidance; reply-length safety cap; downstream store-failure degradation;
  a real on-disk sqlite fixture exercising the exact `mode=ro` production
  path — non-details passthrough, no-reply-target, unmapped-old-message
  (truthful "predates durable reply correlation" response), missing-db
  graceful `(None, None)`, idempotent repeat, simulated restart recovery
  (independent reader re-opened against the same file), concurrent-writer
  mid-session (new card written after the resolver was built still
  resolves without restart); listener dispatch ordering vs.
  `extra_resolvers` and the numeric alert-ID path; full `Message` object
  access (`reply_to_message.message_id`); `plain=True`/`parse_mode=None`
  verified via the mock send call (fixing a real risk: default MARKDOWN
  parse mode could reject arbitrary SEC-sourced text); exception-in-
  resolver safety; unauthorized chat never reaches resolvers.
- **Live verdict: PASS for the read path, re-verified against real
  production data AFTER the managed restart, including data generated
  entirely AFTER cutover** — `reply_details_945_post_restart.txt` shows a
  correct, complete details response for a pre-restart LULU card (message
  945), read through the exact production
  `build_intelligence_details_resolver()` entrypoint with no arguments
  (default `~/.talonx/ingestion_ledger.db` path), confirming the
  correlation survives the restart and depends only on durable storage.
  Stronger still: `reply_details_958_live_post_cutover_digest.txt` +
  `reply_details_958_item1.txt` resolve a real 14-event digest (Telegram
  message 958) sent at `2026-09-15T00:07:55Z` — entirely generated under
  the new code, after both restarts — into a correct compact index and a
  correct per-item detail (see §4 for the substantive content of item 1,
  which also doubles as a live confirmation of the notification policy
  itself).
- **Live INBOUND Telegram verification: PENDING.** No natural operator
  reply occurred during this session's execution window. Per the explicit
  instruction, this is reported as pending, not manufactured — a
  successful outbound send is not proof inbound handling works, and the
  isolated tests above (including a fully realistic fake-`Message`-object
  round trip through the actual listener code) stand in for it until a
  real reply happens.

## 6. Tests, failures, baseline comparison

- Focused Task 137/138 batteries: **106/106 passed**
  (`focused_test_run_output.txt`).
- Broader regression run this session (dispatch/telegram/delivery/
  enrichment/prospective): **307/309 passed**, 2 pre-existing failures —
  `test_start_stack_omits_enable_broad_discovery_by_default` and
  `test_start_stack_passes_enable_broad_discovery_through_to_the_v2_
  companion` in `tests/test_task114_prospective.py` — confirmed
  **environmental, not a regression**: both call `start_stack()`, whose
  real-OS process scan (`_live_prior_stack()`) is not mocked by these two
  tests, and this machine had a genuinely running prospective stack
  throughout (PIDs 13288/17080/19984/23456 confirmed alive via
  `Get-CimInstance Win32_Process` before any Task 138 change was made);
  neither test imports any file this task touched.
- Full repository suite: run once, in background, per the repository-gate
  instruction. **Result: 17 failed, 4,805 passed, 6 skipped (52m31s).**
  Every one of the 17 failures was individually re-run against a
  temporary `git worktree` checked out at the pre-Task-138 baseline
  commit `13c9902` (never touching the live primary worktree or the
  live running stack) — **all 17 fail identically on that baseline**,
  confirming zero regressions from this task's commits. Root causes
  (each independently verified, not assumed): 4 are pre-existing drift
  from commit `ae61cdb` (Task 137, already in the baseline) and commit
  `4531fe2` (Task 118F) touching files this task never modified; 2
  hardcode a superseded V1 fingerprint value that Task 137 already
  changed; 2 are fully isolated `DeliveryOutbox` tests directly
  reconfirmed to fail identically pre-Task-138 (not caused by the
  Workstream 1A fairness fix); 6 assert the live production
  `v2_lane.db`'s md5 hash against a small historical allowlist that the
  continuously-ticking live V2 companion has legitimately moved past;
  3 hit an un-mocked real-OS process scan that correctly detects this
  machine's genuinely running prospective stack (same class as the 2
  Task 137-era failures already known). Full detail:
  `full_suite_run_output.txt` (summary + baseline-comparison verdict)
  and `full_suite_failures_detail.txt` (every individual traceback).

## 7. Managed restarts and process ownership

Exactly two components needed the new code: **Intelligence** (Workstream 1A
fairness fix + Workstream 2 notification policy, both imported by
`talonx_ingest.intelligence.service`) and **Original** (Workstream 3's
`message_resolvers` wiring in `run_talonx.py` /
`talonx_dispatch/telegram_listener.py` / `talonx_dispatch/consumer.py`, the
process that owns the single Telegram listener). Experimental, V2 companion
and Dashboard import none of the changed files and were deliberately left
untouched — verified by process listing showing unchanged PIDs throughout.

Both restarts used the established "kill the exact owned shim+real PID
pair, let the already-running supervisor's own dead-child detection
respawn it" procedure (documented precedent: Task 132/134 addenda in
`docs/research/TALONX_RESEARCH_LEDGER.md`) — never a second supervisor
instance, never `talonx_ops.prospective start`. Full before/after PIDs,
supervisor-log evidence, and post-restart verification (single owner per
component, no duplicate stack, accounting matching on every specifically-compared value (cash, position/intent/row counts, outbox state totals -- not a full database byte-for-byte comparison), 0 IN_FLIGHT rows,
no forced resend) are in `before_after_cutover_snapshots.json`.

## 8. Accounting, strategy and freshness preservation

- Original paper trading: `current_cash=10000.0`, `open_positions=0` —
  unchanged before/after.
- V2 paper ledger: `cash=300000.0`, `open_positions=0`,
  `pending_entry_intents=0`, `cooldowns=0` — unchanged before/after.
- V2 frozen fingerprint `11107198c5b81237` — unchanged (recomputed live,
  §1).
- Freshness checks, claim-before-send, AMBIGUOUS handling: untouched code
  paths; `AMBIGUOUS` count unchanged at 2 rows across the restart; 0
  `IN_FLIGHT` rows found post-restart (no forced resend after uncertainty).
- No broker calls, no real-money orders, no new recipients, no artificial
  trading signals, no historical actionable replays, no fabricated fills —
  none of this task's authorized surface touches any of those.

## 9. Remaining limitations and unfinished work

- **Live inbound Telegram reply verification is PENDING** (§5) — requires
  a natural operator reply; not manufactured.
- **No live, naturally-occurring CONCISE-tier IMMEDIATE send was directly
  observed to complete** within this report's observation window. A real
  post-cutover DIGEST send DID occur and was directly verified (message
  958, `2026-09-15T00:07:55Z`, 14 events, including a live confirmation
  of the policy's DIGEST-routing rule — see §4/§5), demonstrating the new
  code path is genuinely live and working; but no qualifying MEDIUM/HIGH-
  with-substantive-trigger or CRITICAL event happened to occur in this
  window to exercise a live CONCISE `IMMEDIATE` send specifically. The
  render path and disposition logic for that case are covered by
  dedicated unit/integration tests. Absence of a qualifying IMMEDIATE
  event in a bounded window is treated as a valid outcome per the task's
  own instruction, not a reason to loosen any rule.
- ~~Intelligence has restarted many times over the course of 2026-09-14
  (9 unexpected exits, code `4294967295`, before this task's own two
  deliberate restarts) — a pre-existing operational pattern, not
  introduced by this task, and out of this task's authorized scope to
  root-cause tonight; flagged here for the operator's attention.~~
  **CORRECTED by Task 139** (2026-09-15, during host-restart recovery):
  this was investigated and fully explained, not left open. All 9
  `code=4294967295` exits individually correlate (within 15-30 seconds)
  to a runtime-code commit message for Tasks 133/134/135/136A/136B/137 —
  i.e. every one is the SAME documented "commit runtime changes, then
  managed restart" cutover pattern this project has used throughout,
  not an unexplained crash. Full timestamp-by-timestamp correlation:
  `docs/research/evidence/task139/exit_classification.md`. This was an
  overcautious mischaracterization in the original report, not a
  discovered defect.
- Full-repository-suite tally: 17 failed / 4,805 passed / 6 skipped,
  every failure independently confirmed pre-existing against the
  `13c9902` baseline (§6) — no open, unexplained full-suite failure
  remains.

## 10. Morning readiness and next operator action

The existing stack (supervisor + Original + Experimental + Intelligence +
Dashboard + V2 companion) is alive and does not need a fresh
`prospective start` — starting it again while it is already running is
explicitly not authorized and was not done. EOD for the CURRENT session
(2026-09-15, closing 2026-09-15T20:00:00Z) reads `NOT_DUE_YET` — no EOD
reconciliation should be run before that boundary; the PRIOR session
(2026-09-14) was already correctly closed under Task 136 with a `PARTIAL`
strict verdict (PIV `NOT_CHECKED`, expected) and `available_scope=true`.

**One concrete next operator action**: at the operator's convenience,
reply "details" to any TalonX informational Telegram card sent since this
cutover to perform the first live, natural inbound-reply verification
(§5's one remaining open item) — no other action is required for continued
normal operation.

## 11. Repository evidence links

- `docs/research/NOTIFICATION_POLICY.md` — the policy document.
- `docs/research/evidence/task138/commit_{96a6457,5734b8c,5eb9f36}_{message,stat}.txt`
- `docs/research/evidence/task138/focused_test_run_output.txt`
- `docs/research/evidence/task138/full_suite_run_output.txt`
- `docs/research/evidence/task138/before_after_cutover_snapshots.json`
- `docs/research/evidence/task138/post_cutover_checkpoint_capture.json`
- `docs/research/evidence/task138/reply_details_945_post_restart.txt`
- `docs/research/evidence/task138/README.md` — index of everything above.
