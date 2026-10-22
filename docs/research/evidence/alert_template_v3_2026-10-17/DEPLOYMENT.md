# RESEARCH_REVIEW_EXPANDABLE_V3: deployment 2026-10-17 22:15Z

**Owner-approved 2026-10-17, presentation only. LIVE from the promotion restart at 2026-10-17 22:15:02Z.** Deployed
before the PDM first session (2026-10-19), so the whole PDM study sees one layout.

| Item | Value |
|---|---|
| Change | Five visible summary lines + the unchanged V2 text in a Telegram expandable quote; `parse_mode=HTML` only for payloads containing `<blockquote expandable>` (`ExpandableHtmlClient`, outside `TracedTransport`) |
| Commit | `d58b294` (fast-forward onto `6a5f97c`) |
| Declaration | #62 `UI_ONLY`, bound to version `46d5867ae07b`; consumed by `20261017T221502Z-promotion-2d60ba` |
| Deployment record | `UI_ONLY`, `RULE:CONFIG_KEY_MAPPED+DECLARED`, version `de24a9891031` → `46d5867ae07b` |
| Unchanged | `PROMOTION_POLICY` `4926c12e5eace04e`, mode PAPER_SIGNAL, `signal_delivery` RESEARCH_REVIEW @ 2026-10-07T22:42:55Z, eligibility, queue/rate/expiry, routing, dedup |
| Restart | `python -m talonx_opportunity restart promotion`. The supervisor performed it: STOPPED 22:15:01Z, RESTARTED 22:15:01Z, START 22:15:02Z. No other component touched |
| State at deploy | 0 QUEUED promotions; Signal outbox all SENT (1598); weekend, so no alert due |
| After | One owner (launcher → interpreter under the Opportunity supervisor), heartbeat fresh, 0 failures, drain enabled |
| PDM | `verify_integrity` OK before and after (no locked file changed) |
| Tests | 168 targeted + 276 Opportunity/notify/delivery passed. 2 pre-existing failures (`.gitattributes` freeze check, dashboard import) fail identically on `6a5f97c` |

- **Preview:** `PREVIEW.md`, built from the real 2026-10-16 TRGP/RTX records. In both cases the V2 re-render equals
  the sent payload.
- **No test message was sent.** The first natural review alert (regular session from 2026-10-19 13:30Z) is the live
  confirmation. Check that the outbox row is SENT with `template_version` `RESEARCH_REVIEW_EXPANDABLE_V3` and the
  trace is `API_ACCEPTED` with a message id.
- **If Telegram rejects the HTML:** the row goes RETRY → FAILED (a definite 400, so no double send).
  - **Rollback:** `git revert d58b294`, declare `UI_ONLY` for the reverted version, then
    `python -m talonx_opportunity restart promotion`.

## Natural verification: 2026-10-19 14:07Z (read-only, nothing sent or retried)

**PASS.** First regular session after deployment (open 13:30Z).

| Check | Result |
|---|---|
| Outbox rows since 13:30Z | 12, all `SENT`, 1 attempt each, no `last_error` |
| Template | 12/12 `RESEARCH_REVIEW_EXPANDABLE_V3`, 12/12 contain the expandable marker |
| Telegram acceptance (HTML) | 12/12 traces `API_ACCEPTED`, error_class none, `TRACE_OK`, message id present, no ambiguous prior attempt |
| Timing | First sent 13:50:43Z (1 s after enqueue), last 14:06:20Z |
| Outbox health | No PENDING/RETRY/AMBIGUOUS/FAILED, 0 duplicate dedup keys |
| Promotion | Version `46d5867ae07b`, RUNNING, 0 failures, no component events since deployment; window 2026-10-19: 12 PROMOTED_SIGNAL, 7 QUEUED (normal rate limit) |

- **Rollback not needed.**
- **Not verifiable from records:** how the message renders on the device (collapsed summary, tap to expand).
  The owner should confirm this on the phone.

## Fix deployed 2026-10-22 09:09Z: bounded SEC context + Telegram length guard

| Item | Value |
|---|---|
| Cause | `OPPORTUNITY_ENGINE:2026-10-21:MS:GAP_UP` FAILED after 5 attempts, "Message is too long" (6,223 UTF-16 units; the SEC line held 5,219 chars of repeated `offering-related 424B2 filed <date>` labels). The defect predates V3 (unbounded field). Not resent. |
| Change | Identical labels collapse with count + date range (max 4 groups, then `+N more filing types`). Details are cut at a line boundary if the visible text would exceed 3,900 UTF-16 units; the policy/universe/reference lines are always kept. Presentation only; discovery `catalysts.py` and PDM-locked files untouched |
| Commit / declaration | `0326dfa`; #63 `UI_ONLY` bound to `28b69c173c9e`; deployment `20261022T090908Z-promotion-200da2`, `RULE:CONFIG_KEY_MAPPED+DECLARED`, `46d5867ae07b` → `28b69c173c9e` |
| Unchanged | `PROMOTION_POLICY` `4926c12e5eace04e`, mode, delivery boundary, eligibility, queue, routing, dedup, trace |
| Regression | All 200 delivered V3 alerts re-render byte-identical (`SEC_LENGTH_FIX_VERIFY.txt`); MS re-renders at 1,160 units, no truncation |
| Tests | 173 targeted + 281 wider passed (same 2 pre-existing release-freeze failures) |
| After | One owner, RUNNING, 0 failures, queue 0, drain enabled; PDM `verify_integrity` OK |
| Rollback | `git revert 0326dfa`, declare `UI_ONLY`, `restart promotion` |
