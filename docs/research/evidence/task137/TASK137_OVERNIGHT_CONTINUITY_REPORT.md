# Task 137 — Overnight Continuity, Scope Accuracy and Delivery Fairness

Branch `feature/task131-option-a-integration`. Baseline HEAD `32f8bc5`;
this task's committed candidate `ae61cdb`. Executed starting 21:33 UTC
2026-09-14 (before the nominal 22:00 UTC checkpoint-daemon-deadline
window; read-only prep began immediately, fixes applied and restarted
before that deadline, the deadline itself observed live — see §2).

## 1. Current state captured (UTC)

**Repository**: HEAD `32f8bc5` at start, working tree clean.

**Processes** (local `CreationDate` is BST=UTC+1, converted explicitly):

| component | PID (shim/worker) | started (UTC) | loaded code |
|---|---|---|---|
| supervisor | 23456/13288 | 09:50:22 | unchanged all task |
| Original | 13180/21596 | 17:59:31 (Task 135 restart, prior) | `66a49f9` |
| Experimental | 12196/17928 | 09:50:23 | unchanged |
| Dashboard | 22876/13364 | 09:50:29 | pre-Task137 code (not restarted — see §9) |
| Intelligence | (old) 13584/22212 → (new) 13200/26220 | 19:49:27 → **21:57:41** (this task's restart) | `a1d0fd4` → **`ae61cdb`** |
| V2 companion | 19984/17080 | 09:50:24 | unchanged |
| checkpoint daemon | 7928/21332 | 09:50:24 | see §2 for its exit |

A repository HEAD is not every component's loaded code — confirmed
explicitly per-component above rather than assumed from HEAD alone.

**Effective config**: unchanged from Task 136/136B (`deliver_cards_
enforce_age_cutoff=True`, `deliver_cards_per_cycle=20`, broad discovery
ENABLED on the V2 companion, 569-symbol Intelligence scope). New in this
task: V2's real execution scope (626, watchlist ∪ broad-discovery
manifest) now also correctly reaches the observational funnel/checkpoint
reporting layer (§3).

**Cash/positions/intents/reservations**: `$300,000.00`, 0 open positions,
0 pending entry intents — unchanged throughout (re-verified before and
after every restart in this task).

**Informational outbox** (pre-restart snapshot, 21:56 UTC): `PENDING`
201 / `SENT` 249 / `EXPIRED` 20,599 / `AMBIGUOUS` 2 / `SUPPRESSED` 0.
**V2 outbox**: 0 rows in every state (unchanged, zero V2 activity today).

**Processing backlog by stage**: `COMPLETE` 20,771 / `STORED` 9,646 /
`FAILED_RETRYABLE` 35 (see §7 — all one deterministic cause, now fixed).

**Last progress**: Intelligence `max(discovered_at_utc)` = 21:32:18 UTC
(pre-restart); V2 `last_tick_utc` = current within its own 300s cadence
throughout.

**EOD status**: `PENDING` at task start (21:34 UTC, within the 90-min
grace window after the 20:00 UTC close); became `STALE` at 21:30+90min
deadline... — see §3's full reconciliation of this exact field's meaning
and the real defect found in it.

## 2. Overnight ownership and checkpoint-daemon outcome

Task 136 ran `close --no-shutdown` at 20:13:32 UTC, verdict
`PASS_WITH_FINDINGS` (confirmed still the latest reconciliation record —
`eod_reconciliation.db`'s `latest()` row is unchanged, `generated_at_utc
= 2026-09-14T20:13:32.187695Z`, since no second `close` has run since,
correctly).

**Checkpoint daemon deadline**: `_close_deadline()` = XNYS session close
(20:00:00Z) + 2h = **22:00:00Z**. **Actually exited at 22:21:03 UTC** —
confirmed directly (process gone, `checkpoints/checkpoint_0026_
20260914T222103Z.json` immediately followed by `checkpoint_0027_final_
20260914T222103Z.json`, both real UTC-stamped filenames, same instant).
The ~21-minute overshoot past the nominal deadline is explained, not a
defect: `session_loop.run_loop`'s deadline check (`if until_close and
now >= deadline: break`) only runs once per `checkpoint_every_s` cycle
(1800s = 30 min), immediately after writing a regular checkpoint — the
prior regular checkpoint before the deadline was taken at 21:51:01Z, so
the deadline (22:00:00Z) fell inside that cycle's 30-minute sleep window
and was only detected (and acted on) at the NEXT scheduled checkpoint,
22:21:01/03Z. **Exit was clean**: the final checkpoint's own content is
fully healthy (V2 `service_health.health=HEALTHY`, tick 150, cash
`$300,000.00` unchanged, `data_state=CURRENT`); no warning/critical
event was logged around the exit; and, re-enumerated immediately after,
**every other stack component remains alive with identical, unchanged
PIDs** (supervisor 13288, Original 13180/21596, Experimental
12196/17928, Dashboard 22876/13364, V2 companion 19984/17080,
Intelligence 13200/26220 — this task's own restarted pair) — the
checkpoint daemon's own exit affected nothing else.

**Single ingestion poller**: exactly one Intelligence process pair
throughout (old 13584/22212 → new 13200/26220 after this task's own
restart at 21:57:41Z, same supervisor parent 13288 both times).
**Single inbound Telegram listener**: Original (`run_talonx.py`) remains
the sole real listener (`telegram_get_updates_owners: 1`, confirmed via
`talonx_ops.supervisor status`); V2/Intelligence remain outbound-only.
**Supervisor ownership**: PID 13288 unchanged across this entire task;
its dead-child detection correctly relaunched Intelligence within ~10s
of being stopped (the same pattern used in Task 136B/136).
**Continued persisted progress**: `intel_event_processing.discovered_
at_utc` advanced past 21:32:18Z pre-restart and resumed immediately
post-restart (confirmed via the clean startup log + continued
identity-guard activity, no gap). **V2 out-of-session behaviour**: the
companion has no session-boundary logic (ticks independent of market
hours); only the checkpoint daemon has an explicit overnight exit.

## 3. EOD status reconciliation

**The reported evidence, explained precisely**:
- *"Nested `eod.state=PENDING`"* in the original Task 136 checkpoint —
  **correct, not a defect**. `eod_state()` is a pure calendar/clock
  check (`NOT_DUE_YET` → `PENDING` (90-min grace) → `STALE`); the
  checkpoint was captured within that grace window, so `PENDING` was the
  factually correct state AT THAT MOMENT. The identical checkpoint taken
  now correctly reads `STALE` (deadline passed, re-confirmed live this
  task, §1) — this is the natural passage of time, not a reporting bug.
- *"An older base-reconciliation snapshot"* — **also correct, not a
  defect**. No second `close` has run since 20:13:32Z, so `eod_latest`
  correctly continues to show that (increasingly old) record; a system
  that fabricated a newer one would be the actual bug.
- *"`eod_reconciled_today=false`"* despite a successful, on-time,
  `PASS_WITH_FINDINGS` reconciliation — **a real, persistent reporting
  defect, confirmed and fixed**. `EodReconciliationStore`'s `status`
  field can only be `RECONCILED`/`RECONCILED_WITH_MISMATCH` when **every**
  component is `CHECKED`, including `piv_paper` — but `piv_paper` is
  **permanently** `NOT_CHECKED` in this deployment (PIV/Alpaca is
  opt-in-only, never injected; this V2 campaign does not use it at all).
  `status` is therefore ALWAYS `PARTIAL` here, on every session, forever
  — meaning `eod_reconciled_today` could never become `true` regardless
  of how correctly or promptly reconciliation actually ran. This is
  structural, not timing-dependent — re-running `close` again would not
  fix it (explicitly not done, per the directive not to rerun merely to
  turn a field green).

**Fix**: `talonx_ops.eod_reconciliation.reconciled_to_available_scope()`
— narrowly distinguishes "PARTIAL solely because `piv_paper` is
`NOT_CHECKED`, no mismatches, everything else `CHECKED`" from a
genuinely incomplete/broken reconciliation. Exposed as a **separate,
explicitly-named** field — `eod_reconciled_today_available_scope`
(`talonx_ops/supervisor.py`'s status snapshot/answers) and
`today_reconciled_available_scope` (`AuthoritativeReadModel.eod_
reconciliation()`) — never silently overwriting the existing strict
`eod_reconciled_today`/`today_reconciled` fields, which keep their exact
prior (correct, conservative) meaning for the genuine early-close case
Task 118A P3 already protects. 5 focused tests confirm: the real Task
136 PARTIAL pattern reads `True` on the new field; a genuinely broken
component (e.g. `alert_stores: UNKNOWN`) or any mismatch still reads
`False`; the new field is `False`/meaningless once `status` is already
fully `RECONCILED`; and the end-to-end `AuthoritativeReadModel` path
reports both fields correctly, simultaneously.

**Original evidence source, traced**: not a capture-order artifact in
the sense of stale data — a genuine, reproducible logical gap in how
"reconciled" was defined for a deployment that structurally never checks
one of the four components it enumerates.

## 4. Scope reconciliation (39 vs 626)

Traced separately, as required: configured discovery universe, resolved
ingestion universe, runtime evaluation scope, actual new-entry
eligibility, and the EOD/dashboard funnel's own reporting.

- **Configured discovery universe**: the frozen `discovery_universe_v1_
  626.json` manifest — genuinely 626 distinct symbols (verified: `len ==
  626`).
- **Resolved ingestion universe (Intelligence)**: 569 symbols (39
  watchlist-resolvable + 530 broad-discovery-extended, confirmed via the
  Intelligence startup log — a SEPARATE scope from V2's own execution
  scope; Intelligence discovers/enriches events, V2 decides admission).
- **Runtime EVALUATION scope (the live V2 companion)**: **genuinely
  626** — traced directly in `talonx_v2/run.py`: `--execution-scope
  resolved-active-watchlist` resolves the 39-symbol POLLED watchlist,
  and `--enable-broad-discovery` (confirmed present on the actual running
  companion's command line) additively unions in the full 626-symbol
  manifest — `V2Service.execution_allowlist` (the frozenset that
  actually GATES Form 4/code-P record and episode admission in `_apply_
  execution_allowlist`, not merely a label) is the union. Verified
  empirically: the 39-symbol watchlist is a full subset of the 626-symbol
  manifest, so the union is exactly 626 — matching `/ping`'s and `v2_
  service_status.json`'s own live-reported `execution_scope_count: 626`
  exactly. **This is genuine runtime expansion, not a labelling claim** —
  confirmed against the actual gating code path, not startup logs alone.
- **Actual new-entry eligibility**: unaffected by this fix — `_apply_
  execution_allowlist` is unchanged; a symbol outside the (correctly-
  understood) union remains unqualified for paper entry, exactly as
  before. Existing OPEN positions retain their exit handling regardless
  of execution-scope changes (unaffected code path).
- **EOD/dashboard funnel's own reporting (the actual bug)**: `talonx_
  ops/prospective/funnel.py`'s `_resolved_execution_scope()` independently
  recomputed the NARROW 39-symbol watchlist-only scope for its own
  Form 4/code-P/cluster analysis — never unioning in the broad-discovery
  manifest at all — regardless of whether the live companion was
  actually running with it enabled. This under-reported "how much is
  being evaluated" and, more materially, **undercounted the actual
  code-P record/cluster figures**: re-run live after the fix,
  `code_p_records_window` went from a previously-reported **8** to
  **26**, `distinct_issuers_window` to **11**, and `clusters_ge2_
  distinct_insiders` now shows **2** real clusters (ABCL, APTV) — this
  was genuinely undercounted data, not just a mislabelled count.

**Determination**: runtime evaluation was genuinely expanded; only
REPORTING remained narrow (matches the first of the three possibilities
the directive asked to distinguish between).

**Fix, smallest demonstrated mismatch**: `build_funnel(...,
include_broad_discovery=...)` unions in the SAME frozen manifest
`run.py` uses, reports BOTH `execution_scope_count` (resolved) and
`watchlist_only_count` (narrow), explicitly labelled — never silently
substituting one for the other, and never claiming "626 verified
securities" as a bare allowlist size: the union is only applied when the
LIVE companion's own reported `execution_scope_count` (`v2_service_
status.json`, written every real tick) proves broader-than-watchlist
scope is actually active (`checkpoint.py`'s new `_live_companion_uses_
broad_discovery()`) — never a hardcoded assumption independent of the
running process. Proven with an isolated, synthetic broad-only symbol
("ZZBROADONLY") in a temp manifest + monkeypatched watchlist — never
injected into live state (3 focused tests + 1 end-to-end `AuthoritativeReadModel`-adjacent test).

## 5. Deferred-lookup saturation result and recovery

Reproduced the SATURATION case specifically (not the already-covered
"one failing row doesn't stop the rest of a selected batch"): a bounded
selection `limit` filled ENTIRELY by rows whose lookup always raises
(real exceptions, DEFER every time) sorting AHEAD of one valid, eligible
row — confirmed the eligible row was **never selected on any cycle**
(the failing rows never leave `pending()`'s own `LIMIT` window because
nothing ever changed their position).

**Fix**: a DEFER outcome now writes a bounded, fixed backoff
(`_DEFER_BACKOFF_SECONDS = 30.0`) to the row's own `next_retry_at_utc` —
the SAME column `pending()` already filters on for send-selection — so a
permanently-failing row is excluded from the NEXT selection window for a
short, bounded period, letting the same bounded query reach the eligible
row behind it. `state` itself is never touched (not terminal); a later
successful lookup recovers the row exactly as before, sent exactly once.
The bulk `expire_stale()` sweep deliberately does **not** gain the same
`next_retry_at_utc` filter — that column is shared with the UNRELATED
send-attempt backoff `mark_failed()` sets, and filtering the AGE sweep on
it would let a row merely awaiting its next SEND attempt silently escape
an age-based expiry it still genuinely needs (confirmed by reproducing
this exact regression when first attempted, then correctly reverted to a
non-filtered sweep that still benefits from the same backoff WRITE when
it happens to encounter a failing row first).

**Proof, both directions** (`tests/test_task137_overnight_continuity.py`
+ 2 tests appended to `test_task136b_freshness_edge_cases.py`):
- `test_saturated_batch_of_failing_lookups_does_not_permanently_starve_a_valid_row`
  — a `limit=3` batch entirely of failing rows; the valid row is sent
  within a bounded number of drain cycles (fairness ACROSS batches, not
  merely "doesn't stop mid-batch").
- `test_saturated_batch_row_recovers_once_its_lookup_succeeds` — the SAME
  row's lookup later starts succeeding; it is delivered normally, exactly
  once.
- `test_repeated_lookup_failure_does_not_starve_an_eligible_row_same_cycle`
  / `..._across_cycles` (from the Task 136 turn, still passing) — the
  narrower single-failing-row cases remain covered too.
- Digest selection: covered by the pre-existing `test_mixed_digest_sends_
  only_still_eligible_cards`/`test_empty_eligible_digest_sends_nothing`
  freshness-gate tests, which exercise the SAME shared `_expire_row_if_
  stale`/DEFER path — no separate digest-specific saturation gap was
  found (digest batches are small and claimed atomically, not filled via
  a `pending()`-style bounded `LIMIT` query in the same way).

## 6. Original fingerprint conclusion, per-file evidence

Reported: `2dea67a6f6d2` (actual) vs `2ae6216bca70` (expected). Full
per-file, per-commit trace (see the code comment on
`V1_FINGERPRINT_EXPECTED` in `talonx_ops/prospective/__init__.py` for
the complete reasoning) —

| comparison | combined hash | conclusion |
|---|---|---|
| commit `18e93d9` (where the constant was frozen), committed blobs | `68afe1f8fa08` | baseline at freeze time |
| current `HEAD`, committed blobs | `ed8272fe568d` | differs from baseline — real commits touched these files since |
| current working tree, raw bytes | `2dea67a6f6d2` | matches the REPORTED mismatch exactly |
| current working tree, LF-normalized | `ed8272fe568d` | **matches current HEAD's committed blobs exactly** |

**Two distinct, separately-confirmed causes — not one**:
1. **Line-ending representation** (benign): every one of the 5
   fingerprinted files has CRLF terminators on this Windows working tree;
   the git-committed blobs are pure LF. Proven per-file: `blob == working
   tree with \r\n→\n` is `True` for all 5. Fixed in `get_strategy_
   version()` itself (LF-normalize before hashing) — the exact technique
   `tests/test_task65b_protected_fingerprints.py` already established for
   two other frozen fingerprints in this repo, now applied here too, with
   a dedicated CRLF-vs-LF-produces-same-hash regression test (and the
   PRE-EXISTING substantive-change-detection test still passing
   unmodified, confirming the fix does not mask real changes).
2. **A real, substantive, already-authorized change** (the actual root
   cause of the reported mismatch): commit `66a49f9` ("Task 135 -- surface
   Redis PUBLISH subscriber count for Quant signals", this same session,
   2026-09-14) modified `talonx_quant/consumer.py` — one of the 5
   fingerprinted files — AFTER `18e93d9` froze `2ae6216bca70`. Confirmed
   via `git log 18e93d9..HEAD -- <the 5 files>`: exactly one commit,
   exactly this one. That commit's own message stated "Frozen strategy
   fingerprint `11107198c5b81237` unchanged (touches neither `talonx_v2/`
   nor any of the 5 fingerprinted files)" — correct about the V2
   fingerprint (a separate, unrelated mechanism), **incorrect** about the
   5-file set: `consumer.py` genuinely is one of them, and was touched.
   **Behaviour affected**: confined to `QuantScanner._publish_signal`
   capturing Redis `PUBLISH`'s own subscriber-count return value for a
   new observability metric/log line, AFTER a signal has already been
   decided and is being published — no gating, entry, exit or opportunity-
   scoring logic was touched (verified via the actual diff, not assumed).

**Not reverted** (a legitimate, tested, already-pushed fix from earlier
in this same session) and **not called harmless without support** — the
diff is quoted and characterized precisely above. `V1_FINGERPRINT_
EXPECTED` corrected to the new, current, LF-normalized, git-reproducible
baseline: `ed8272fe568d`. `talonx_backtest.reproducibility.get_
strategy_version()` now returns this value; `tests/test_task114_
prospective.py`'s fingerprint assertion now reads the live constant
(not a second hardcoded literal) so it cannot silently drift out of sync
again. No hash was blindly replaced with "whatever the current value is"
— it was replaced with a value fully reproducible from `git show HEAD:
<files>` alone, after separately confirming and neutralizing the CRLF
artifact.

## 7. LULU latency breakdown / evidence gap, and backlog/retry findings

**LULU (accession `0001397187-26-000129`)**: distinct event types
(`CHARTER_BYLAW_AMENDMENT` + `EXECUTIVE_CHANGE`) correctly produced two
cards, message ids 945/946 — not a duplicate-delivery concern, confirmed.

- **Enrichment delay**: precisely measured, real per-record timestamps
  (`intel_processing_log`, monotonically unique, sub-second-spaced across
  neighbouring records — NOT batch-fixed): `STORED` 20:18:30.496Z →
  `COMPLETE` 20:18:30.805Z (EXECUTIVE_CHANGE) / 20:18:31.108Z
  (CHARTER_BYLAW_AMENDMENT) — under 1 second total. No defect.
- **Delivery delay**: `COMPLETE` → `sent_at_utc` (20:18:39.575Z /
  20:18:40.868Z) ≈ 8-9 seconds — the normal gap between the enrichment
  and delivery loop phases. No defect.
- **Source-to-local-discovery delay: an explicit evidence gap, not
  invented.** `text_events.ingested_at_utc` / `intelligence_delivery.
  enqueued_at_utc` both read `20:14:38.264432Z` for this record — but
  this value is **confirmed BATCH-fixed, not a true per-record marker**:
  exactly 2 `text_events` rows (LULU's own two event types) and 22
  UNRELATED `intelligence_delivery` rows share this EXACT microsecond
  timestamp. It cannot be treated as "when our poller first saw LULU's
  filing." The best available circumstantial evidence: the poll-cycle
  summary log's own `filings=` cumulative counter (a real, monotonic,
  per-cycle count) stayed at `24106` for over an hour of consecutive
  cycles (18:44Z–20:01Z, `polled=569` full-scope every cycle) and only
  incremented to `24107` then `24108` at cycles completing 20:09:20Z and
  **20:18:31Z** — the latter matching LULU's own enrichment-COMPLETE
  timestamp almost exactly, strongly suggesting the poll cycle that
  actually surfaced this filing completed right around 20:18Z, roughly
  **4 hours after SEC's own 16:15:47Z acceptance**. **What cannot be
  determined from available evidence**: WHY that 4-hour gap exists —
  whether it reflects a delay in whatever SEC-side feed/endpoint this
  poller reads (propagation/indexing lag distinct from the filing's own
  acceptance timestamp), our own scope/scheduling, or something else. No
  per-symbol/per-fetch log line for this specific accession survives to
  resolve it further. Not invented; reported as the exact interval that
  cannot be localized. **Recommended, not implemented** (optional per the
  directive): a genuine per-record "first observed via poll" timestamp,
  distinct from the current batch-shared `ingested_at_utc`, would close
  this gap for future incidents — left for a future task if wanted, no
  scheduling code was changed here (no proven defect to fix, and the
  directive explicitly forbids raising SEC request rates or adding a
  second poller regardless).

**Backlog/retry health** (timestamped snapshots, §1): `STORED`/
`ENRICHMENT_PENDING` ≈ 9,646 (real, substantial, recoverable backlog —
explicitly not equated with delivery-expiry counts, which measure a
different thing entirely: age-based send eligibility, not enrichment
completion). `COMPLETE` 20,771. Oldest outstanding `STORED` work:
`discovered_at_utc` back to 13:58:31Z today — several hours of queued
backlog, consistent with the ongoing historical broad-discovery backfill,
not evidence of a stuck/stalled pipeline (continued forward progress
confirmed throughout, §1/§2).

**The 35 `FAILED_RETRYABLE` rows, resolved**: 100% one issuer (`BBY` /
Best Buy Co Inc), 100% one error string
(`"...prohibited claim language: ['token:buy']"`), `attempts=8` on
every row — conclusively **deterministic content misclassification**,
not a transient failure (confirmed: `classify_error()` has no matching
TERMINAL or RETRYABLE substring for this text, falls through to the
"unclassified — bounded retry" branch, so these rows were never going to
resolve themselves and were never going to hit a hard terminal cap
either — an effectively endless retry loop on a doomed render). Root
cause, traced to the exact regex: `claim_safety.py`'s bare-token scanner
(`_BUY_SELL_RE`) matches "Buy" as a standalone word — and the filer's
own, factual, SEC-sourced company name is literally `"BEST BUY CO INC"`.
**This is legitimate factual language being misclassified**, exactly as
the directive asked to determine — not a case for a broad content-policy
rewrite. **Fix**: `scan_rendered`/`assert_clean` gain an optional
`company_name` parameter; a bare buy/sell token that falls entirely
within an occurrence of that exact (SEC-sourced) name string is exempted
— every other rule (all phrase-level predictive language, e.g. "strong
buy"/"should buy", and any bare token NOT part of the company's own name)
remains fully, unambiguously enforced, proven by dedicated tests for
both directions. Threaded through the real call site (`enqueue_card` →
`assert_clean(message.text, company_name=card.company_name)`), verified
by a spy-based end-to-end test, not just the pure-function level.

**Confirmed live, against real production data, not manufactured**: all
35 rows were left to retry naturally (no manual replay/re-enqueue). By
22:41 UTC (their scheduled `retry_after_utc` of 22:02:31Z had long
passed): `FAILED_RETRYABLE` count dropped from 35 to **0**; all 35 now
show `stage=COMPLETE` (`symbol=BBY`) — the claim-safety fix genuinely
resolved the block in production. Their resulting `intelligence_delivery`
state, however, is **`EXPIRED`** for all 35 (`suppress_reason` values
from 242h to 2137h old by event_time, e.g. `"stale_card: 2137.4h old by
event_time > 24h DIGEST cutoff"`) — these are historical BBY filings
(some ~89 days old), and the freshness gate correctly refused to send
them as if they were fresh. This is the intended, correct outcome of
BOTH fixes working together: the content-classification bug no longer
silently discards these rows forever, and the (Task 136B) freshness gate
correctly prevents genuinely old content from being delivered — no stale
alert was sent.

## 8. Fixes, tests, restarts, preserved obligations

**Fixes applied** (all bounded, all with focused tests, summarized —
full detail in the commit message): `reconciled_to_available_scope` (EOD
reporting), DEFER backoff (delivery-selection fairness), broad-discovery
scope union (funnel reporting), CRLF-normalized `get_strategy_version` +
corrected `V1_FINGERPRINT_EXPECTED` (fingerprint verification), company-
name-aware claim-safety exemption (BBY false positive). No strategy/
gating/scoring/timing logic touched anywhere.

**Tests**: 19 new/updated focused tests across 5 test files (see the
commit message for the exact list). **575 passed** across every directly
affected module + the full new/updated set; **11 pre-existing, unrelated
failures reconfirmed present on unmodified `32f8bc5`** (`git stash`-
verified): 9 are the SAME environmental class already documented in Task
136B/136 (a live-process-scan `ConcurrentStartError` against this
machine's own real running stack, and date-dependent test fixtures using
real-wall-clock retry timestamps against a fixed historical `now`) — the
2 newly-observed ones (`test_start_stack_omits_enable_broad_discovery_
by_default`, `test_start_stack_passes_enable_broad_discovery_through_
to_the_v2_companion`) are the exact same `ConcurrentStartError` class,
confirmed present in the VERY FIRST run of that file this task performed,
before any code change. None of the 11 relate to this task's changes.
Full repository suite NOT re-run (not required by any gate for this
change; avoided per the explicit instruction against repeated cycles).

**Obligations preserved**: cash/positions/intents/reservations, both
outboxes, ambiguous deliveries, recoverable backlog, single-poller
ownership and SEC request limits all confirmed unchanged/intact before
and after the one restart performed.

**Restart**: Intelligence only (the sole long-running process whose
imported code this task's fixes actually changed — `outbox.py`, `claim_
safety.py`, `pipeline.py`). Restarted via the supervisor's own dead-child
detection at 21:57:41Z; single owner, clean startup (569-symbol scope
unchanged), immediate continued progress, no gap. Dashboard/supervisor/
checkpoint-daemon processes were **not** restarted — their own new
fields (`eod_reconciled_today_available_scope`, funnel scope union) are
additive and already independently verified correct via fresh, one-shot
CLI invocations (`talonx_ops.prospective checkpoint`/`status`) against
the live system throughout this investigation, which import the current
code fresh each call; the LONG-RUNNING checkpoint daemon specifically was
approaching its own natural ~22:00Z exit during this task and was left to
do so on schedule rather than churned for a field that is independently
verifiable without it (see §2).

## 9. Evidence

`C:\workspace\TalonX\results\task137_evidence.zip` — see its own README
for exact contents (reports, commit diff/message, focused test output,
live scope/fingerprint/claim-safety verification snapshots, before/after
outbox counts). `C:\workspace\TalonX\results\task136b_evidence.zip`
reconfirmed present and extractable (unchanged from the prior turn).

## Separate verdicts

| area | verdict |
|---|---|
| Overnight continuity | **PASS** |
| EOD status accuracy | **PASS (corrected)** — real reporting defect found and fixed as a separate, explicit signal |
| Scope accuracy | **PASS (corrected)** — genuine runtime expansion confirmed; reporting corrected to match, not merely relabeled |
| Delivery fairness | **PASS (corrected)** — saturation reproduced and closed; recovery and exactly-once state handling proven |
| Original strategy identity | **PASS (corrected)** — mismatch fully explained (CRLF + one real, already-authorized commit); not a scope-creep into strategy logic |
| Fresh-event latency | **PARTIAL EVIDENCE** — enrichment/delivery precisely measured, clean; source-to-local-discovery interval explicitly not localizable from available evidence |
| Backlog recovery | **PASS** — real, substantial, recoverable backlog confirmed advancing; the one deterministic-retry defect found (BBY) is fixed |
| Development run | **RUNNING** |
| Profitability | **NOT ASSESSED** |
