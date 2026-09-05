# Task 79E-R1 → Task 80 Launch Handoff Refresh

This REFRESHES (does not replace) the existing handoff chain:
`results/task79g_pre_live_qualification/task80_launch_handoff.md` (primary,
read first) →
`results/task79e_experimental_authorization/task80_launch_handoff_refresh.md`
(Task 79E's own refresh). This file covers only what changed because of
Task 79E-R1's fixes.

## What changed since Task 79E's own handoff

Task 79E's handoff correctly stated the experimental mechanism was inert
(no `experimental_authorization.json` file exists) but explicitly deferred
testing what would happen once one DOES exist. Task 79E-R1 did exactly that
audit and found — and fixed — several real defects that would only have
manifested in *enabled* mode: lost exit plans across a restart, exits
sized to the wrong quantity or abandoned on a failed/partial attempt,
stop/target triggering from price data at or before the entry fill, a
`session_scope` field that was parsed but never enforced, an authorization
object cached at startup so revocation had no live effect, a
concurrent-exposure race between two symbols, unresolved uncertain
submissions, and an unvalidated durable budget record. See
`findings_and_tests_report.md` in this same directory for the full
per-defect breakdown and the 26 new regression tests proving each fix.

**Still fully inert today**: no `experimental_authorization.json` exists
anywhere in this repository, tracked or untracked — every one of these
fixes is dormant until an operator authors one, exactly like Task 79E's own
posture.

## Activation instructions (unchanged mechanism, now actually safe to use)

If the operator chooses to author `experimental_authorization.json` (still
NOT recommended as part of Task 80 itself — see Task 79E's own
recommendation, unchanged):

1. Follow `results/task79e_experimental_authorization/authorization_contract.md`
   for every field's exact binding semantics — all of it still applies.
   `session_scope` must be set to the literal string `"REGULAR"` — this is
   the ONLY value the live natural-strategy decision path will ever match
   (see Area 3 of `findings_and_tests_report.md`); any other value fails
   closed with `WRONG_SESSION_SCOPE`.
2. The file is now re-read FRESH on every entry/submission attempt (never
   cached) — an operator can revoke live by disabling
   (`"enabled": false`), deleting the file, or narrowing
   `allowed_symbols`, and the very next signal/order attempt observes it.
   No process restart is required to revoke, though a restart is still the
   only way to pick up a BRAND NEW authorization if the file did not exist
   at process start (`cli.py::runtime()` still only ever wires the PATH
   once at construction — the path itself doesn't change, but see note
   below).
3. `max_concurrent_exposure` is now enforced correctly across concurrent
   symbols with in-flight (not-yet-filled) entries, not just confirmed
   open positions — safe to rely on as a genuine hard cap.

## Restart / recovery behaviour (new)

- A process restart while an experimental (or ordinary STRATEGY) position
  is open now correctly recovers its stop/target exit plan from
  `lifecycle_state.json` — this previously required a full EOD flatten to
  resolve; it no longer does. No operator action is required for this.
- A restart during a genuinely uncertain submission (order raised an
  exception before a broker order id was received) is resolved by the next
  `reconcile()` call (runs automatically at EOD and at supervised startup)
  via the order's stable `client_order_id` — never a blind resubmission.

## Remaining blockers / disclosed limitations

None of the items below are new activation blockers — they are narrower
residual gaps disclosed for the operator's own risk assessment, same
posture as Task 79E's own `remaining_issues.md` (which still fully
applies, unchanged):

1. The in-memory "an exit has been triggered and must keep being retried"
   latch is not itself persisted — see `findings_and_tests_report.md`'s
   own "Remaining, non-blocking issues" item 1 for the exact (narrow,
   rare) restart window this affects.
2. `find_order_by_client_id`'s reliance on Alpaca's `client_order_id`
   query filter has not been exercised against the real Alpaca paper
   endpoint, only this task's own fakes.
3. Task 79E's own disclosed items 2–4 in
   `results/task79e_experimental_authorization/remaining_issues.md` remain
   unchanged and still apply.

## Verdict from this task

See `findings_and_tests_report.md` for the full verdict, evidence, and
regression numbers.

## Build identity

- Task 79E's own final commit: `3f034a3` (docs fill-in: `84d8c73`).
- This task's final commit SHA: `64cdd16` (parent: `84d8c73`).
