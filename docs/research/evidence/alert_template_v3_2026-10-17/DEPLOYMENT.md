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
