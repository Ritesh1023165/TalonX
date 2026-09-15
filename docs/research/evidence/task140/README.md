# Task 140 Evidence Index — Useful Telegram Alerts (Digest Off by Default)

**Objective**: routine filing-inventory digests were still reaching
Telegram by default under Task 138's policy (DIGEST route + the
periodic digest send itself both still active for non-substantive
events). Task 140 makes the periodic DIGEST send itself an explicit
opt-in, default OFF — routine filings stay fully collected/enriched and
dashboard-visible, but produce no Telegram message unless explicitly
requested.

**Commits**: `55dd31c` (the digest-off-by-default feature),
`bde2d28` (an URGENT sibling fix found live during this same cutover —
`--deliver --transport telegram` had never reached Intelligence's own
delivery enablement at all, only V2's).

## Exact new default

- `ServiceConfig.deliver_digest_enabled` (env
  `TALONX_INTEL_DELIVER_DIGEST_ENABLED`) — **default `False`**.
- Independent of `deliver_intelligence_cards`/`TALONX_INTEL_DELIVER_CARDS`
  (governs `IMMEDIATE` alone, unaffected by this flag).
- Effective in this deployment: OFF (not set in `.env` or environment).
- `prospective start --deliver --transport telegram` now ALSO sets
  `TALONX_INTEL_DELIVER_CARDS=1` / `TALONX_INTEL_DRY_RUN_DELIVERY=0` in
  the launcher's own env (previously only reached V2) — see `bde2d28`.
  `TALONX_INTEL_DELIVER_DIGEST_ENABLED` is a SEPARATE flag, not implied
  by `--deliver`; it stays False even when `--deliver` is passed, exactly
  matching the explicit-opt-in requirement — an operator who wants the
  digest back must set `TALONX_INTEL_DELIVER_DIGEST_ENABLED=1` themselves.

## Mechanism (reused, not a new delivery engine)

`process_digest`'s own pre-existing `mode="disabled"` branch: DIGEST-route
rows stay `PENDING`, logged `HELD`/`"delivery disabled"`, nothing sent,
nothing dropped, nothing mutated otherwise, fully dashboard-visible and
still ages out through the SAME existing freshness/expiry mechanism as
any other row. Gate is re-evaluated on EVERY `deliver_cycle` call, so no
backlog row (old or new) can bypass the default by outliving a one-time
migration.

## File index

| file | what it is |
|---|---|
| `commit_55dd31c_{message,stat}.txt` | the digest-off-default commit (personal email redacted) |
| `commit_bde2d28_{message,stat}.txt` | the urgent delivery-enablement sibling fix (personal email redacted) |
| `focused_test_run_output.txt` | 46/49 pass — 3 known-environmental failures (live-process-scan / live-session-timing, unrelated to this task's code, documented) |
| `post_cutover_heartbeat.json` | live Intelligence heartbeat post-cutover — 569 effective_symbols confirmed |
| `delivery_mode_confirmation.txt` | live proof `delivery.mode: "enabled"` after the urgent fix — before/after SENT-log evidence |
| `admission_provenance_investigation.md` | resolves the follow-up admission=PERMISSIVE report: genuine unchanged behavior (not a regression) + a real reporting-provenance defect found and fixed regardless |
| `commit_56b8fad_{message,stat}.txt` | the admission-provenance fix + integrated launch test (personal email redacted) |
| `gated_admission_activation.md` | the explicit operator authorization to switch to GATED admission, applied via `.env` + one managed restart, verified live in the real companion/dashboard |
| `commit_c9fb63d_{message,stat}.txt` | the exit-eligibility-after-scope-change isolated tests (A4 closure; personal email redacted) |
| `post_gated_admission_cutover_heartbeat.json` | live Intelligence heartbeat after the GATED-admission cutover — 569 symbols, delivery enabled, digest still off, all confirmed together |
| `requirement_closure_matrix.md` | the FINAL, authoritative requirement-to-code/test matrix for the 2026-09-15 follow-up directive (substantive content, digest-off proof, scope reconciliation, reservation expiry) |
| `commit_2c96c8f_{message,stat}.txt` | the substantive-content-requirement fix + reservation-expiry tests (personal email redacted) |
| `post_task140_v2_service_status.json` | live V2 status snapshot showing `execution_scope_count: 626`, `durable_store_gate_enabled: true` |
| `execution_scope_membership_log_excerpt.txt` | the real companion's OWN startup log lines proving 39 (watchlist) + 587 (broad discovery manifest) = 626 by genuine membership, not just count |
| `full_suite_run_output_task140.txt` | the one full-repository-suite run for this final completion pass (see its own CAPTURE LIMITATION note; superseded for current-state comparison by `full_suite_run_output_task140_v2.txt`, below) |
| `reply_details_correction_root_cause.md` | same-day correction: reply-for-details ordering/index/source-link/wording root cause + fix, against real message-958 evidence |
| `reply_details_live_verification_message_958.txt` | diagnostic resolver invocation (not a live round trip) against the real production ledger for message 958, before/after the ordering + evidence_urls fixes |
| `reply_details_focused_regression_output.txt` | 136/136 pass — all Task 138/140 delivery-module tests including the new Task 140 acceptance suite |
| `full_suite_run_output_task140_v2.txt` | complete, properly-captured (no truncation) full-repository-suite run for this correction, superseding the incomplete 4/17-name capture above |

## Before/after example

**Before (Task 138 default)**: a routine, non-substantive Reg FD or 8-K
filing with no qualifying trigger routed to `DIGEST` — and the periodic
digest itself was always sent, so it still reached Telegram, just bundled
with other routine items (the real 14-event digest the operator flagged
as still noisy).

**After (Task 140 default)**: the SAME routine filing still routes
`DIGEST` (§3 of `docs/research/NOTIFICATION_POLICY.md` is unchanged —
this task did not touch per-event classification), but the periodic
digest SEND itself does not happen by default — the row is `HELD`,
visible in the dashboard, and ages out normally. No Telegram message at
all for routine filing activity unless the operator explicitly sets
`TALONX_INTEL_DELIVER_DIGEST_ENABLED=1`.

**A genuinely substantive event** (CRITICAL band, or MEDIUM/HIGH with an
explicit substantive trigger — §3 of the policy, unchanged from Task 138)
still routes `IMMEDIATE` and is sent as a concise 3-5 line alert exactly
as before — this task did not touch that path at all, verified unchanged
via the existing 51+23 Task 138 reply-correlation/notification-policy
tests, all still passing.

## Reply-for-details (B6)

Not modified by this task — `reply_correlation.py` untouched. Verified
unaffected: its 51 isolated tests
(`tests/test_task138_reply_correlation.py`,
`tests/test_task138_telegram_message_resolvers.py`) still pass
unchanged. When digest IS explicitly enabled and a digest is sent, the
existing `digest:<id>:<message_id>` correlation format and multi-item
"details N" indexing are exactly the pre-Task-140 mechanism — nothing
new to verify here beyond what Task 138 already proved. Live inbound
Telegram reply verification remains PENDING (unchanged from Task
138/139 — no natural operator reply has occurred yet); not manufactured.

### CORRECTION (same-day follow-up, after this section was written)

The paragraph above is now **superseded** — kept for the historical
record, not deleted. The operator's live reply DID subsequently occur
(a real round trip against message 958) and it exposed five real,
confirmed defects in `reply_correlation.py` (wrong item order, wrong
"details 2" resolution, a hard 6-item cap with no path to the rest,
a missing source link, and a mislabeled supporting card). All five are
fixed; see `reply_details_correction_root_cause.md` for the full root
cause and fix, `reply_details_live_verification_message_958.txt` for
the diagnostic re-verification against the real production message
(NOT a live Telegram round trip — see that file's own header), and
`reply_details_focused_regression_output.txt` /
`test_task140_reply_details_acceptance.py` (14 new tests) for the
regression coverage. `reply_correlation.py`, `pipeline.py`, and
`outbox.py` are all modified by this correction — the "not modified by
this task" claim above applies only to the digest-off-default work this
README originally documented.

## Limitations

- No live, naturally-occurring send was observed to COMPLETE within this
  report's bounded post-cutover window for either IMMEDIATE (no
  qualifying fresh row existed this cycle) or DIGEST (correctly not yet
  due). `delivery.mode: "enabled"` is directly confirmed, which is the
  load-bearing claim; a specific send completing is a matter of a
  qualifying event occurring, which this report does not manufacture.
- The 3 known-environmental test failures (2 live-process-scan, 1
  live-session-timing) are unrelated to Part B's own code — see
  `focused_test_run_output.txt` and the Task 139 evidence bundle for the
  established pattern.
