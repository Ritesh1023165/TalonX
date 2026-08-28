# Task 79E → Task 80 Launch Handoff Refresh

This REFRESHES (does not replace) `results/task79g_pre_live_qualification/task80_launch_handoff.md`,
which remains the primary handoff document — read it first. This file
covers only what changed because of Task 79E's build.

## What changed since Task 79G's handoff

- New, disabled-by-default experimental-permission mechanism added:
  `talonx_piv/experimental_authorization.py` +
  `Recommendation.EXPERIMENTAL_BUY` + wiring through `decision_contract.py`,
  `lifecycle.py`, `notification_outbox.py`, `shadow_ledger.py`,
  `decision_engine.py`, `observability.py`, and `cli.py`.
- **Inert by construction**: no `experimental_authorization.json` file
  exists anywhere in this repository (only the inactive template at
  `inactive_configuration_example.json`). `cli.py::runtime()` calls
  `load_experimental_authorization(config.state_dir / "experimental_authorization.json")`,
  which returns `None` for a missing file — every session today behaves
  byte-identically to before this task.
- One pre-existing behavioural contract was found regressed by an earlier
  submission-safety fix (raw transport exceptions were being silently
  converted to `PaperGuardError`) and was restored to its documented
  Task 78I contract — see `implementation_plan.md`'s "Regression found and
  fixed." This affects the STRATEGY path too (not experimental-only), so
  it is worth the operator's awareness even if Task 80 never touches the
  experimental feature at all.

## Do this first, fresh (do not trust either task's snapshots) — unchanged from Task 79G

See `../task79g_pre_live_qualification/task80_launch_handoff.md`'s own
"Do this first, fresh" checklist — still fully applicable, re-run against
today's actual HEAD.

## What is still already true

- Real strategies remain `UNVALIDATED` — no natural entry can reach the
  broker regardless of any other setting. This remains true WITH OR WITHOUT
  the experimental mechanism: reaching `EXPERIMENTAL_BUY` never sets
  `strategy_approval_status = APPROVED`.
- `paper_entry_settings.json` does not exist — no ticker is entry-enabled
  for the NORMAL strategy path (experimental PAPER entries are gated by an
  entirely separate, also-absent `experimental_authorization.json`, so both
  gates must be independently absent-turned-present before ANY PAPER order
  of any kind can occur).

## Explicit authorisations ONLY Task 80 (the operator) can give — refreshed list

Everything in Task 79G's own list, PLUS:

- Whether to author a live `experimental_authorization.json` at all today.
  This task recommends NOT doing so as part of Task 80 itself — Task 80 is
  a controlled live-market PAPER/observation session with its own separate
  scope; activating a brand-new, same-day feature during the FIRST live
  session it could possibly run in adds risk this task's own tests cannot
  substitute for a real operator judgement call. If the operator does
  choose to author one, `authorization_contract.md` documents every field
  and its exact binding semantics, and `remaining_issues.md` documents what
  is and is not yet proven about it.

## Verdict from this task

See `final_report.md` for the full verdict and reasoning. Like Task 79G's
own handoff, this document is not itself a launch or activation
authorisation.

## Build identity

- Task 79G's own HEAD at handoff time: `bc8a14a`.
- This task's final commit SHA: **see `final_report.md`** (recorded there
  after the full regression suite passed and the commit was made, so this
  file's own text does not go stale the moment a later task adds a commit).
