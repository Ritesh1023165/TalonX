# Task 118A — priority hotfixes, validation, controlled restart

## Objective and acceptance criteria
Fix and deploy the four evidenced priority defects from Task 118 today,
with real tests, a controlled same-session restart, and honest reporting
of anything newly discovered — not another audit.

## Timing
- UTC start: 2026-09-11T11:03 (baseline re-verification)
- UTC end: 2026-09-11T~12:10 (deployment + acceptance complete; live
  session still running, pre-EOD)

## Branch / SHA
- Release: `research/talonx-strategy-validation`, starting `fb4b071`,
  deployed **`c88f4d4600735dcc65fb5108c73489e877d16ebe`** (plus docs-only
  `d61b920` for this activation report).
- Hotfix (merged, then kept, not deleted): `hotfix/task118a-experimental-exit-lifecycle`
  (`72baca2`, `c88f4d4`), pushed.
- Research: this entry itself, on `research/talonx-profitability-2026-09`.

## Requested vs. completed scope
- Priority 1 (Experimental exit lifecycle): **DONE** — confirmed, fixed,
  25 tests, live-verified (a real VRT exit fired post-restart).
- Priority 2 (Original warmup): **DONE, documented, no fix** — root cause
  found (transient external yfinance failure), fallback confirmed working.
- Priority 3 (operator-visible correctness): **DONE** for (a)(b)(c)(f);
  (d) addressed as a consequence of Priority 1; (e) **not reproduced** —
  reported as not found, not invented.
- Priority 4 (research corrections): **DONE** — see
  `docs/research/TASK118A_RESEARCH_CORRECTIONS.md` (this branch, same
  commit range as the prior Task 118 entry's corrections).
- Implementation/release process A–E: **DONE** — isolated checkout,
  validation, restart-scope decision with reasoning, full controlled
  deployment sequence, post-restart acceptance with live evidence.
- A second defect (stale `stop.flag` blocking the checkpoint daemon on a
  same-session restart) was discovered **during** the restart itself,
  root-caused, fixed, tested, and merged — not part of the original
  four priorities, reported as an additional finding per this task's own
  "report any newly discovered blockers honestly" instruction.

## Source / runtime / data manifest
See `docs/audits/task118a_priority_hotfixes_2026-09-11/` on the release
branch (`ACTIVATION_REPORT.md` + `PRIORITY1/2/3*.md`) for full module
lists, hashes, log evidence, and reproducible commands. Not duplicated
here per this task's own "link existing reports rather than rewriting
them" instruction (from the prior Task 118 request, still in force).

## Tests / experiments / results / limitations
25 new tests across 4 new files (all passing); a targeted+broad regression
sweep of 835 tests (1 pre-existing, confirmed-unrelated failure); a full
untracked `pytest tests/ -q` run was started for maximum coverage and
intentionally stopped early once the targeted sweep already gave strong,
clean confidence — reported as not fully completed, not claimed as full
green. See `ACTIVATION_REPORT.md` §C for exact figures.

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Operational verdict: **HOTFIX_DEPLOYED_AND_RESTART_VERIFIED** — real
  controlled restart, real preflight/acceptance evidence, one real
  Experimental exit observed live post-deployment.
- Profitability verdict: **unchanged / not applicable** — this task was a
  functional repair, not strategy tuning; no profitability claim is made
  or implied by the successful repair (explicitly required by the task's
  own closing instruction).

## Production effects, external sends, protected-state checks
Real production writes this task: the live `experimental_paper.db` (one
real position closed — VRT, via the newly-wired mechanism) and
`exp_alerts.db` (the corresponding display row updated). `v2_lane.db` and
`ingestion_ledger.db` unaffected beyond normal operation (V2 cash/
positions unchanged at $300,000/0; Intelligence delivery counts unchanged
immediately post-restart, no replay). Zero external sends beyond what the
existing, unmodified natural delivery path would have done anyway — no
new Telegram smoke test was sent (not required by this task), and the
Experimental exit fix explicitly never dispatches externally
(`live_external_sends: 0`, confirmed). Backups of all four affected
databases + `.env` taken before deployment, outside any tracked path.

## Findings
- **Fixed**: Experimental exit lifecycle wiring (2 latent defects: never
  invoked at all, plus the display-log insert-vs-update mismatch);
  Intelligence digest literal-markup + wording; dashboard cards-vs-
  messages count; misleading `today_reconciled`/`eod_reconciled_today`
  flags (2 call sites); stale `stop.flag` blocking a same-session
  checkpoint-daemon restart.
- **Open**: whether today's Original warm-up gap (39/43 symbols still
  live-accumulating pre-open) actually delays qualified evaluation once
  the regular session opens — not observable before 13:30 UTC, explicitly
  left open, not claimed passed.
- **Deferred**: Priority 3(e) ("missing prices displayed as zero") — not
  reproduced; no such computation was found to exist in the dashboard at
  all currently.

## Evidence links
`docs/audits/task118a_priority_hotfixes_2026-09-11/{ACTIVATION_REPORT,
PRIORITY1_EXPERIMENTAL_EXIT_LIFECYCLE,PRIORITY2_ORIGINAL_WARMUP,
PRIORITY3_OPERATOR_VISIBLE_CORRECTNESS}.md` (release branch);
`docs/research/TASK118A_RESEARCH_CORRECTIONS.md` (this branch); commits
`72baca2`, `c88f4d4`, `d61b920`.

## Later corrections
None yet.
