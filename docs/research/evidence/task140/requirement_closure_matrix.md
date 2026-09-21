# Task 139/140 Final Completion — Requirement-to-Code/Test Matrix

Per-requirement status, distinguishing **already implemented with direct
evidence**, **implemented but was missing verification** (closed this
turn), **not implemented** (closed this turn), and any remaining
**blocked-by-evidence-limitation** item.

## 1. Substantive-content requirement (item 2)

**Status: NOT_IMPLEMENTED → IMPLEMENTED_AND_VERIFIED this turn.**

Task 138's `classify_disposition` checked only reason-CODE membership
(`SUBSTANTIVE_REASON_CODES`) and a bare cluster-kind presence check —
exactly the "reason code" / "count of insiders" bypass the newer
requirement forbids as a *sole* justification. A confirmed, separate bug
was found while implementing the fix: `enrichment.py` was passing the
internal policy-audit string (`decision.reason`, e.g. "HIGH band with a
substantive trigger present: [CODE]") into the renderer as
`disposition_reason`, when the renderer's own docstring already claimed
(incorrectly) that this WAS the specific fact text.

- Code: `talonx_ingest/intelligence/delivery/notification_policy.py`
  (`classify_disposition` now takes full `SignificanceReason` objects,
  validates each qualifying code's own `description` is genuinely
  populated, new `DispositionDecision.evidence_text` field);
  `talonx_ingest/intelligence/service/enrichment.py` (fixed
  `disposition_reason=decision.evidence_text`, was `decision.reason`);
  `talonx_ingest/intelligence/delivery/renderer.py` (`render_concise`
  docstring corrected, `_quality_lines` reused for essential
  uncertainty).
- Tests: `tests/test_task138_notification_policy.py` (12 pre-existing
  tests rewritten to the new signature + 6 new, including the exact
  content-gate-failure case and per-trigger evidence-text validation
  against real percentages/dollar figures); `tests/test_task140_
  substantive_content_e2e.py` (4 new, REAL `evaluate_significance` +
  a real `FilingComparison`, not mocked — proves the gate through the
  actual engine, and that the real percentage appears directly in
  `render_concise`'s own output text, not merely in an internal field).
- Backlog enforcement: `reclassify_pending_rows` inherits the stricter
  gate automatically (it calls the same `classify_disposition`); proven
  with a new, explicit old-policy-escape test
  (`test_reclassify_pending_rows_downgrades_an_old_policy_code_only_row_
  task140`).
- Commit: `2c96c8f`.

## 2. Digest-off demonstration (item 5)

**Status: previously cited weaker evidence (`held_reason="digest_not_
due"`) → IMPLEMENTED_AND_VERIFIED this turn with the correct signal.**

- Isolated proof, exactly per spec (fresh DIGEST rows, schedule
  genuinely due — first-ever call on a fresh outbox, `due=True` by
  construction — transport configured, digest explicitly disabled):
  `tests/test_delivery_pipeline.py::
  test_digest_disabled_with_a_genuinely_due_schedule_sends_nothing`.
  Asserts: zero sender calls, no row marked SENT, `held_reason ==
  "delivery_disabled"` (never `"digest_not_due"`), digest schedule meta
  (`last_digest_bucket`/`last_digest_sent_utc`) NOT advanced, a truthful
  HELD log line, and IMMEDIATE delivered independently in the same
  fixture.
- Then-enabled companion test:
  `test_digest_enabled_in_the_isolated_fixture_sends_normally_no_
  duplicates` — 3 rows aggregate into 1 message, correct
  `digest:<id>:<msg>` mapping, a second call in the same bucket sends
  nothing more (no duplicates).
- Live routine digest was NOT toggled on to demonstrate this — the
  isolated fixture is the demonstration, per the directive's own
  instruction not to flip the live setting.
- Live config confirmation (unchanged from the prior GATED-admission
  cutover, re-verified, no restart needed for this alone):
  `TALONX_INTEL_DELIVER_DIGEST_ENABLED` absent from `.env` and the
  environment; `ServiceConfig.deliver_digest_enabled` default `False`.

## 3. Execution/collection scope reconciliation (item 6)

**Status: only enforcement=true was previously cited →
IMPLEMENTED_AND_VERIFIED this turn with membership evidence.**

- **Execution scope (V2)**: live `v2_service_status.json`:
  `execution_scope_count: 626`. Real MEMBERSHIP evidence (not just
  count) from the companion's own startup log
  (`results/prospective_2026-09-15/logs/v2_companion.log`): `"V2
  execution scope ENFORCED -- 39 allowed issuers: [full list]"` followed
  by `"V2 broad discovery ENABLED -- 587 symbols added (manifest=...
  discovery_universe_v1_626.json)"` — 39 + 587 = 626, exactly. Cross-
  checked by INDEPENDENTLY reconstructing the same union from the same
  source files this session (`talonx_ops.watchlist_coverage.build_
  coverage_map()` + the manifest JSON directly) — reconstructed count:
  626, matching the live companion exactly.
- **Collection scope (Intelligence)**: live heartbeat
  `effective_symbols`: 569 entries (verified by direct list length, not
  a summary field) — the SEPARATE, smaller, ingestion-side scope; kept
  explicitly distinct from the 626 execution scope throughout, never
  conflated.
- **GATED admission**: verified from the companion's own
  `v2_service_status.json` (`durable_store_gate_enabled: true`), never
  inferred from the listener's or shell's environment (the Task 140
  reporting-provenance fix from the prior turn).

## 4. Persistent reservation expiry/release exactly once (item 7)

**Status: NOT_IMPLEMENTED (no test existed) → IMPLEMENTED_AND_VERIFIED
this turn.**

- Real mechanism confirmed by direct code inspection FIRST
  (`talonx_v2/service.py::_capacity_rejection_reason`, Task 131
  Remediation Directive 4): a PENDING intent's reservation is a
  COMPUTED deduction (`cash - per_position_allocation_usd * count of
  PENDING intents`), never a literal `store.cash()` debit. No cash-
  credit-on-release was invented, matching the directive's explicit
  warning.
- `tests/test_task140_reservation_expiry_exactly_once.py` (2 new): real
  `V2Service`/`V2Store`, isolated on-disk db, controlled clock. A
  genuine pre-open PENDING intent reservation is created, survives a
  store close/reopen (simulated restart), and is released exactly once
  (terminal `EXPIRED_STALE`, `updated_at_utc` provably unchanged on a
  repeated tick + another close/reopen) once the staleness boundary is
  crossed — cash proven identical ($300,000.00) at every checkpoint, 0
  open positions, 0 trades, no phantom fill/notification.

## 5. Reply-details isolated vs. live (item 3/8)

**Status: unchanged from Task 138/139 — not reopened.**

`reply_correlation.py` was not touched this turn. Isolated: 51 existing
tests (`tests/test_task138_reply_correlation.py`,
`tests/test_task138_telegram_message_resolvers.py`) still pass unchanged
(verified in this turn's regression run). **Live inbound verification
remains `LIVE_INBOUND_PENDING`** — no natural operator reply has occurred;
not manufactured, not claimed from calling the resolver directly.

## 6. V2 actionable route (item 8)

**Status: unchanged.** No file under `talonx_v2/` was modified by the
substantive-content work. Frozen fingerprint `11107198c5b81237`
re-verified unchanged post-cutover (`research.scripts.task112_v2_
release_fingerprint`).

## 7. CORRECTION (same-day follow-up) — Reply-for-details ordering/index/source-link/wording

**Supersedes item 5's "unchanged from Task 138/139 — not reopened"
status.** The operator's live reply against message 958 subsequently
occurred and exposed real defects; this is now closed with real
evidence rather than deferred.

- **Status: NOT correct (5 confirmed real defects) → IMPLEMENTED_AND_VERIFIED
  this turn**, both in isolated tests AND directly re-checked against
  the real historical production message the operator actually replied
  to.
- Root cause + fix: `reply_details_correction_root_cause.md`.
- Code: `talonx_ingest/intelligence/delivery/outbox.py` (new
  `digest_item_ordinal` column + `mark_digest_sent` order contract),
  `pipeline.py` (`digest_display_order` extracted/shared, `process_digest`
  persists the same order it renders, `_digest_row_summary` evidence_urls
  decoding fix), `reply_correlation.py` (order verification, pagination,
  validated source-link resolution, facts/selection-reason separation,
  digest-item wording fix).
- Tests: `tests/test_task140_reply_details_acceptance.py` (14 new,
  real digest renderer + real persisted correlation + real resolver
  against an isolated on-disk store, including an enqueue-order-vs-
  display-order fixture shaped exactly like the real historical digest);
  2 pre-existing wording assertions in `tests/test_task138_reply_
  correlation.py` updated to match the new, more precise fact/reason
  split (not reverted — a deliberate improvement).
- Live diagnostic re-verification (NOT a live Telegram round trip — see
  `reply_details_live_verification_message_958.txt`'s own header):
  directly against the real `~/.talonx/ingestion_ledger.db`, message
  958. `"details"` index and `"details 1"`/`"details 2"` now match the
  operator's own reported real order exactly (`AKAM` then `AMZN` —
  not the confirmed-wrong `PH...`/`APO` order).
- A genuine NEW bug was found and fixed by this same live-verification
  step (evidence_urls raw-JSON-string indexing bug in the digest-line
  reconstruction, production read-only-reader path only) — see the root
  cause doc's own section on it.
- **Isolated-test verdict and live-diagnostic verdict are reported
  SEPARATELY, per instruction**: isolated = PASS (14/14 new + 136/136
  combined focused regression). Live diagnostic = matches real operator
  evidence exactly, both before-fix (reproduced the bug) and after-fix
  (correct). **A corrected LIVE TELEGRAM ROUND TRIP remains separately
  pending** — no inbound reply has been manufactured; the operator must
  naturally reply again to confirm end-to-end over the real transport.
