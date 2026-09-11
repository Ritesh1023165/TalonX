# Task 79G → Task 80 Launch Handoff

Short, action-oriented. Full detail lives in `tomorrow_launch_runbook.md`,
`probe_plan.md`, `../task78i_full_application_rehearsal/controlled_paper_review_checklist.md`
(from Task 78I, still current), and `external_readonly_checks.json` — this document does not
duplicate them, it points to them.

## Do this first, fresh (do not trust Task 79G's snapshots)

1. `git status && git rev-parse HEAD` — confirm branch/SHA/clean tree.
2. Re-verify Alpaca PAPER identity, open orders, positions (read-only) — see
   `tomorrow_launch_runbook.md` §8.
3. Confirm no competing process/lock (`{TALONX_PIV_LOCK_DIR}\*.lock`, `Get-Process`).
4. Confirm no stale `session_identity.json` implying an already-running session.
5. Re-verify Redis/Telegram/Gemini reachability if those components will be used.
6. Re-run `.venv/Scripts/python.exe -m talonx_piv.cli preflight --approved-sha <fresh HEAD>` —
   inspect the FULL check list, not just the final status line.

## What is already true (verified/built by prior tasks, unchanged unless Task 80 finds otherwise)

- Real strategies remain `UNVALIDATED` — no natural entry can reach the broker regardless of any
  other setting.
- `paper_entry_settings.json` does not exist — no ticker is entry-enabled.
- Execution ownership, EOD idempotency, partial-fill/oversell protection, notification/shadow
  independence, and Gemini's non-authority are all covered by the passing test suite this task
  re-ran (see `offline_rehearsal_results.csv`/`task79g_final_report.md`).

## Explicit authorisations ONLY Task 80 (the operator) can give

- Whether to launch `supervise` at all today.
- Whether to set `TALONX_PIV_GEMINI_ENABLED=true`.
- Whether to create `paper_entry_settings.json` and for which ticker(s).
- Whether to pass `--confirm-piv-lifecycle-probe` (AND populate `paper_entry_settings.json`) to
  activate the controlled probe — see `probe_plan.md` for the exact proposed limits requiring
  sign-off.
- Any use of the mutating recovery commands (`eod`, `kill-switch --cancel-paper-orders`,
  `cleanup`).

## Verdict from this task

See `task79g_final_report.md` for the full verdict and reasoning. This handoff document is not
itself a launch authorisation.
