# Task 79E-R2-2 → Task 80 Launch Handoff Refresh

This REFRESHES (does not replace) the existing handoff chain:
`results/task79g_pre_live_qualification/task80_launch_handoff.md` (primary,
read first) →
`results/task79e_experimental_authorization/task80_launch_handoff_refresh.md`
(Task 79E) →
`results/task79e_r1_activation_safety/task80_launch_handoff_refresh.md`
(Task 79E-R1) →
`results/task79e_r2_activation_safety/task80_launch_handoff_refresh.md`
(Task 79E-R2). This file covers only what changed because of this
round's (Task 79E-R2-2's) fixes, and corrects one instruction in the R2
handoff that is no longer fully accurate.

## Correction to Task 79E-R2's handoff (read this first if you already read R2's)

R2's handoff said: *"a full process restart requires RE-AUTHORING the
[authorization] file with the new session_id even if nothing else about
the authorization should change... there is no 'resume the same
session_id across a full process restart' mechanism in `cli.py` today."*

**This is no longer fully true.** `cli.py::main()` now calls
`session_identity.resolve_session_identity(config)` instead of
unconditionally minting a fresh identity — a genuinely still-live
session (same trading day, `session_enabled=True`,
`kill_switch is not True` in the persisted `lifecycle_state.json`)
reuses its EXISTING `session_id` across a full process restart. An
authorization file authored for a still-live session's `session_id`
therefore now remains valid across a crash/restart of that same session,
rather than requiring re-authoring every time. Re-authoring IS still
required whenever a genuinely NEW session starts (a new trading day, or
after an EOD flatten / kill-switch, both of which correctly mint a fresh
identity) — this part of R2's guidance is unchanged.

## What changed since Task 79E-R2's own handoff

This round closed 4 items R2's own report had disclosed but treated as
non-blocking — see `findings_and_tests_report_ADDENDUM_R2_2.md` for the
full detail. In summary:

- Uncertain broker submissions are no longer auto-resolved as
  "confirmed not submitted" after any fixed count of not-found results —
  only a verified matching order or an explicit operator confirmation
  (`operator_resolve_uncertain_submission`) resolves one. This closes a
  real risk of releasing a reservation for an order that later becomes
  visible on the broker's side.
- Natural (non-EOD-forced) exit price checks now require a positively
  known fill time (`first_fill_observed_at`, sourced from the broker's
  own response, never `datetime.now()`) that is provably earlier than
  the evaluated bar. Unknown timing always blocks the check — it never
  authorizes a pre-fill price exit. Forced EOD flattening is unaffected.
- The broker-entry guard now derives its own session identity directly
  from the lifecycle's `EventBus` rather than trusting whatever value
  the caller supplies — see the correction above for the related
  full-process session-recovery mechanism.
- The live tick loop now runs bounded, rate-limited reconciliation on
  its own (every `SessionRunner.reconcile_interval_seconds`, default
  300s) — self-healing no longer depends on an operator or an external
  call. A full process restart now also restores a pending (not yet
  filled) entry's stop/target plan from its durable intent record, not
  only from an already-OPEN position.

**Still fully inert today**: no `experimental_authorization.json` exists
anywhere in this repository, tracked or untracked — every one of these
fixes, like every fix before them, is dormant until an operator authors
one.

## Activation instructions (updated)

If the operator chooses to author `experimental_authorization.json`
(still NOT recommended as part of Task 80 itself — unchanged from every
prior task's own recommendation):

1. Follow `results/task79e_experimental_authorization/authorization_contract.md`
   for every field EXCEPT `session_scope` — see R2's own handoff
   correction for that field (`session_scope` = the current
   `session_id`, not a fixed category string).
2. Per the correction above, `session_scope` now remains valid across a
   crash/restart of the SAME still-live session — re-authoring is only
   required when a genuinely new session starts (new trading day, or
   after EOD flatten / kill-switch).
3. The file is still re-read FRESH on every entry/submission attempt
   (never cached) — deletion/disablement/narrower bindings still take
   effect on the very next attempt, without a restart.
4. Recovery from an uncertain broker submission that never resolves on
   its own (the broker never confirms it either way after extended
   polling) now requires an explicit operator call to
   `PaperLifecycle.operator_resolve_uncertain_submission(intent_id,
   operator_confirmation=True, operator_note=...)` — there is
   deliberately no automatic path any more. This is a NEW operational
   step that did not exist before this round; an operator running a live
   experimental session should know this method exists and where it
   lives (`talonx_piv/lifecycle.py`).

## Verdict from this round

See `findings_and_tests_report_ADDENDUM_R2_2.md` for the full verdict,
evidence, and regression numbers.

## Build identity

- Task 79E's own final commit: `3f034a3` (docs fill-in: `84d8c73`).
- Task 79E-R1's own final commit: `64cdd16` (docs fill-in: `013d5ae`).
- Task 79E-R2's own final commit: `3d788ca` (docs fill-in: `c9a4994`).
- This round's (Task 79E-R2-2's) starting commit: `c9a4994`.
- This round's final commit SHA: recorded in a follow-up docs-only commit, see repository `git log`.
