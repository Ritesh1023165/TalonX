# Task 79E-R2 → Task 80 Launch Handoff Refresh

This REFRESHES (does not replace) the existing handoff chain:
`results/task79g_pre_live_qualification/task80_launch_handoff.md` (primary,
read first) →
`results/task79e_experimental_authorization/task80_launch_handoff_refresh.md`
(Task 79E) →
`results/task79e_r1_activation_safety/task80_launch_handoff_refresh.md`
(Task 79E-R1). This file covers only what changed because of Task
79E-R2's fixes, and CORRECTS one factual instruction in R1's own handoff
that is no longer true.

## Correction to Task 79E-R1's handoff (read this first if you already read R1's)

R1's handoff said: *"`session_scope` must be set to the literal string
`"REGULAR"` — this is the ONLY value the live natural-strategy decision
path will ever match."* **This is no longer true and was itself an
overclaim even at the time** — see `findings_and_tests_report.md`'s own
Addendum for the full explanation. `session_scope` is now bound to the
REAL, durable live-session identity (`session_id`, minted fresh by
`session_identity.build_session_identity` at every `start`/`supervise`
invocation and persisted to `session_identity.json`), never a fixed
category string. **If an operator ever authors
`experimental_authorization.json`, `session_scope` must be set to the
EXACT `session_id` string found in the CURRENT `session_identity.json` at
the time of authoring** — not `"REGULAR"`. An authorization file left over
from following R1's instruction will now fail closed with
`WRONG_SESSION_SCOPE` (this is fail-CLOSED, i.e. safe -- it can never
under-protect, only require re-authoring).

## What changed since Task 79E-R1's own handoff

Task 79E-R1 fixed a first round of real defects but its own claims about
what it had closed were, in five specific ways, incomplete — see
`findings_and_tests_report.md`'s Addendum for the exact-by-exact
correction. In summary, this task fixed:

- The uncertain-submission reconciliation endpoint (`find_order_by_client_id`)
  was calling a QUERY PARAMETER THAT ALPACA DOES NOT DOCUMENT. It now
  calls the real, documented `GET /v2/orders:by_client_order_id` endpoint,
  verifies the response actually matches the original order before
  adopting it, and requires TWO separate not-found results (not one)
  before concluding an order never reached the broker.
- An entry that takes more than one tick to fill (accepted but not yet
  filled) could have its exit plan silently deleted before it was ever
  protectable. Exit-plan tracking now survives the full pending-entry
  lifecycle correctly.
- A triggered stop/target's "this position must still be sold" fact is
  now persisted durably — a restart between the trigger firing and its
  sell being confirmed no longer loses it, even if price recovers in the
  meantime.
- Fill-causality protection (never using pre-fill price action to trigger
  an exit) now covers a DELAYED fill spanning multiple ticks, not only the
  same tick an entry was opened on.
- `session_scope` is now bound to the real session identity (see the
  correction above).
- A self-healing mechanism was added: an OPEN lifecycle position with no
  in-memory decision-engine plan (e.g. because a SUBMIT_FAILED_UNCERTAIN
  entry was only confirmed-and-filled by a LATER reconcile() call, after
  the raw exception had already propagated past the normal bookkeeping
  point) now automatically rebuilds a plan on the next tick, rather than
  staying a permanently-visible-but-never-healed gap.

**Still fully inert today**: no `experimental_authorization.json` exists
anywhere in this repository, tracked or untracked — every one of these
fixes is dormant until an operator authors one.

## Activation instructions (updated)

If the operator chooses to author `experimental_authorization.json` (still
NOT recommended as part of Task 80 itself — unchanged from every prior
task's own recommendation):

1. Follow `results/task79e_experimental_authorization/authorization_contract.md`
   for every field EXCEPT `session_scope` — see the correction above for
   that one field specifically.
2. `session_scope` = the exact `session_id` string in the CURRENT
   `session_identity.json` at authoring time. Since a genuinely NEW
   process invocation always mints a fresh `session_id` (there is no
   "resume the same session_id across a full process restart" mechanism
   in `cli.py` today — only an IN-PROCESS supervised restart via
   `talonx_piv.supervisor.run_with_bounded_restart` preserves it), a
   full process restart requires RE-AUTHORING the file with the new
   session_id even if nothing else about the authorization should change.
   This is intentional and fail-closed, not a bug to work around.
3. The file is still re-read FRESH on every entry/submission attempt
   (never cached) — deletion/disablement/narrower bindings still take
   effect on the very next attempt, without a restart.
4. The `start` command (not only `supervise`) now reconciles broker state
   before the decision engine begins, matching `supervise`'s own posture.

## Verdict from this task

See `findings_and_tests_report.md` for the full verdict, evidence, and
regression numbers.

## Build identity

- Task 79E's own final commit: `3f034a3` (docs fill-in: `84d8c73`).
- Task 79E-R1's own final commit: `64cdd16` (docs fill-in: `013d5ae`).
- This task's final commit SHA: `3d788ca` (parent: `013d5ae`).
