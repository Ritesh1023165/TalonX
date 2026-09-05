# Task 78I — Controlled PAPER Review Checklist

For a human operator to work through BEFORE any future live-adjacent PAPER activity is
considered. **Completing this checklist is not something this task performs, and a
`READY_FOR_CONTROLLED_PAPER_REVIEW` verdict on this task is not permission to start a live
session, approve a strategy, or enable trading.**

## Prerequisites this task deliberately did NOT create
- [ ] A strategy-approval registry exists and a specific strategy/version has been through it
      (none exists today — every real decision resolves `UNVALIDATED` by design).
- [ ] `{state_dir}/paper_entry_settings.json` has been explicitly created and reviewed, listing
      only the specific ticker(s) intended for the review session (the file does not exist by
      default — no ticker is silently carried forward as enabled).

## Environment and credentials
- [ ] `APCA_API_KEY_ID`/`APCA_API_SECRET_KEY` are genuine Alpaca **paper** credentials (never
      live-account credentials) — verify directly with Alpaca, not by trusting local config alone.
- [ ] `TALONX_PIV_BROKER_ENDPOINT` (if overridden at all) still resolves to the immutable paper
      endpoint — `broker.py`/`config.py` refuse a non-paper endpoint structurally, but confirm the
      env var itself was never set to anything else.
- [ ] `TALONX_PIV_REAL_CAPITAL` is unset/false.
- [ ] Telegram token/chat id (if configured) point to a review-only channel, not a shared one.
- [ ] `TALONX_PIV_GEMINI_ENABLED` reviewed deliberately (on or off) — if enabled, real Gemini API
      credentials/quota are understood to be consumed.

## Ownership and process hygiene
- [ ] `python -m talonx_piv.cli preflight` run and reviewed BEFORE `supervise`/`start`.
- [ ] Confirmed no other `run_talonx.py` or `talonx_piv.cli` process is running (the
      `no_duplicate_full_app_or_piv_process` check covers this, but a manual `Get-Process`
      spot-check is cheap insurance).
- [ ] `{TALONX_PIV_LOCK_DIR or default}\*.lock` inspected — no unexpected lock file for this
      account already present.

## Data and state
- [ ] `{state_dir}` reviewed — no stale/unexpected `lifecycle_state.json`,
      `session_identity.json`, or `paper_entry_settings.json` left over from a prior,
      differently-scoped run.
- [ ] `PaperLifecycle.reconcile()`'s report (via `preflight`/`supervise`'s own startup step) shows
      zero unexpected broker positions/orders and no `unexpected_short_detected` flag.

## Scope discipline
- [ ] Confirmed this review remains PAPER-only, no options/leverage/real capital — structurally
      enforced by this codebase, but explicit operator awareness is still required.
- [ ] Confirmed the review's universe/ticker list matches exactly what was intended (no wider
      `paper_entry_settings.json` than reviewed above).
- [ ] Confirmed the review's TIME WINDOW (start/stop) and who will be monitoring it are both
      decided in advance — this task provides no automated "stop after N hours" beyond the
      existing EOD flatten time.

## After the review session
- [ ] `python -m talonx_piv.cli eod` (or the automatic EOD trigger) confirmed `PASSED`, not
      `FAILED`/`INCONCLUSIVE`, before considering the account state settled.
- [ ] `{state_dir}/latest_session_report.json` and `/piv/status` (if the dashboard was running)
      reviewed for `unexpected_broker_symbols`/`missing_broker_symbols` and any
      `UNCONFIRMED`/rejected orders.
- [ ] Notification and shadow backlogs (`gemini_enrichment`/`notification_outbox`/`shadow_ledger`
      status counts) reviewed separately from broker exposure, per this task's own Stage 2
      shutdown requirement.

## Sign-off
This checklist, once completed by a human operator for a SPECIFIC intended review window, is the
actual authorization artifact — this task's own `READY_FOR_CONTROLLED_PAPER_REVIEW` verdict (if
given) means only that the automated safety/integration machinery is believed sound enough to
support such a review, not that the review itself is authorized to begin.
