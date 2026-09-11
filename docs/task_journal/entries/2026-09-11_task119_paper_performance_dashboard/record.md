# Task 119 — attributable paper-performance dashboard

## Objective and acceptance criteria
Implement (not merely design) the per-lane paper-performance surface
selected in Task 118H (Option 3) inside the existing `:8787` dashboard,
with real tests and rendered acceptance against isolated fixtures.

## Timing
- UTC start: 2026-09-11T~21:47 (system clock genuinely 2026-09-11 in this
  environment — verified via `date -u` before building fixtures, since
  fixture "today" classification depends on the real wall clock).
- UTC end: 2026-09-11T~22:40 (implementation, tests, rendered acceptance,
  docs and both branches' commits complete).

## Branch / SHA
- Release baseline verified at task start: HEAD `d4177b3` (matches the
  reported baseline exactly — not assumed).
- New hotfix branch `hotfix/task119-paper-performance-dashboard`,
  parent `d4177b3`, commit `d65a410` (pushed) — **not merged into
  `research/talonx-strategy-validation`** in this task (candidate for
  next session, per the task's own instruction).
- Research: `8829f55` → this entry.

## Requested vs. completed scope
- Part 1: **DONE** — extended the existing `DashboardReadModel`/
  `dashboard_web.py`/`index.html` cockpit with one new section
  (`paper_performance`), reusing the exact same authoritative sources
  `paper_eod()` already reads. No second dashboard, ledger, or
  accounting engine.
- Part 2: **DONE** — full per-lane summary (identity, period, starting
  capital, cash, open count/cost basis, marked value, realized/
  unrealized P&L, costs, equity, reconciliation, valuation timestamp/
  source/session) — see `talonx_ops/paper_performance.py`.
- Part 3: **DONE** — open-position and closed-trade detail tables with
  provenance, recovery-affected flag (evidence-sourced, non-mutating),
  pending-obligation text.
- Part 4: **DONE** — Friday fixture reproduces the exact Task 118H
  evidence; 27/27 field checks match; SPCX labelled `POST_CLOSE`,
  explicitly "NOT an official regular-session closing price," never
  combined with an "as of 20:00Z" label.
- Part 5: **DONE** — reconciliation/valuation/EOD/base-PIV states shown
  independently; zero positions, missing marks, and no-trades states all
  produce explicit, non-fabricated labels (verified by dedicated tests
  and by the `no_trades` fixture screenshot).
- Part 6: **DONE** — 18 focused unit tests + 6 real-SPA isolated-fixture
  screenshots (headless Chrome, actual `dashboard_web.py`, isolated
  `TALONX_HOME`/`TALONX_V2_DB_PATH`, port 8898) + an independent
  27-field reconciliation table. Changed-surface regression run (268
  passed); one pre-existing, unrelated failure disclosed (confirmed via
  `git stash` that it fails identically without this task's changes).
- Part 7: **DONE** — committed + pushed on a dedicated hotfix branch, not
  merged; exact SHA, no-migration statement, rollback procedure, and
  next-session verification steps recorded in the acceptance report.
- Part 8: this entry + `outcome.md` + the release-branch acceptance
  report + reconciliation table + screenshots (local, per this repo's
  `results/` convention).

## Source / runtime / data manifest
New: `talonx_ops/paper_performance.py` (core accounting module),
`tests/test_task119_paper_performance.py` (18 tests),
`results/task119_paper_performance/spa/{make_fixture.py,run.sh,
build_reconciliation_table.py}` (fixture/capture/reconciliation
scripts — local, not committed, per repo convention). Modified:
`talonx_ops/dashboard_read.py` (+`paper_performance()` method, wired
into `all_sections()`), `dashboard_web.py` (+1 entry in
`_UNIFIED_SECTIONS`), `dashboard_web_static/index.html` (+1 nav button,
+`renderPaperPerformance`/`laneCard` JS, +1 `SECTION_RENDER` entry),
`tests/test_task100c_unified_dashboard.py` (3 hardcoded section-count
assertions updated 7→8, disclosed not masked).

Real production data was opened **read-only, exactly once**, at task
start, solely to confirm the live schema/values this module reads
(`~/.talonx/paper_trading.db`, `~/.talonx/experimental/
experimental_paper.db`, `v2_lane.db`) — no write, no process started.
All subsequent development, tests, and rendered acceptance used isolated
`tmp_path`/fixture-directory sqlite files exclusively.

## Tests / experiments / results / limitations
- `pytest tests/test_task119_paper_performance.py -q` → 18 passed.
- `pytest tests/ -k "dashboard or task100c or task114 or task119 or task112" -q`
  → 268 passed.
- `test_task117_release_rehearsal.py::test_bounded_release_rehearsal`
  fails identically with this task's changes `git stash`ed out — disclosed
  as pre-existing/unrelated, not investigated or fixed here (out of this
  task's scope).
- Rendered acceptance: 6 scenarios, real `dashboard_web.py` SPA, isolated
  fixtures, headless-Chrome screenshots at 1360×2600, all inspected
  directly for readability/clipping. Two fixtures were caught with an
  internally-inconsistent cash figure on first render (a fixture-authoring
  arithmetic slip, not a code defect — the reconciliation check correctly
  flagged the inconsistency as `MISMATCH`) and corrected.
- One real code defect found and fixed during this task's own testing: the
  "zero open positions" unrealized-P&L status initially fell through to
  `COMPLETE` with a silent `0.0` rather than the intended
  `"N/A -- zero open positions (a valid 0)"` label, because
  `marked_value_complete` defaults `True` with no open positions to
  falsify it — caught by `test_zero_open_positions_is_a_valid_zero`,
  fixed by checking `not opens` first in both the shared-schema and V2
  snapshot builders.
- Limitations: PIV always `NOT_CHECKED` (by design, no network call);
  "last exit evaluation" always `NOT_TRACKED` (no dedicated exit-check
  log exists anywhere in the repo); regular-session open approximated as
  close − 6h30m (correct for every actual NYSE session, not read
  per-day from `exchange_calendars`).

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Operational verdict: `PAPER_PERFORMANCE_SURFACE_ACCEPTED` — implemented,
  tested, rendered against the real SPA on isolated fixtures, committed
  and pushed as a reviewed next-session candidate.
- Profitability verdict: unchanged and not advanced by this task — this
  is a measurement/reporting surface, not new evidence. Experimental's
  −$324.4662160270568 realized and SPCX's +$50.30 unrealized remain
  small-sample, non-representative figures, now simply easier to read
  consistently.

## Production effects, external sends, protected-state checks
Zero production writes (asserted by test + confirmed by reading the same
`~/.talonx` files' mtimes before/after this task's local read-only
inspection). Zero network sockets opened by the new module (asserted by
test). No application process started, restarted, or stopped. SPCX's
outstanding obligation, V2's $300,000/0-position state, and the Sept 11
session's closed state (Task 118H) are all unchanged — this task only
adds a way to read them more clearly.

## Findings
- Fixed: the zero-open-positions unrealized-status defect described
  above (found and fixed within this task's own test-writing, before any
  external use).
- Open: none new. Carried-forward limitations (heartbeat-lapse locus,
  "45 candidates" source, mid-session recovery gap) are unchanged by this
  task and not revisited.
- Deferred: none — Task 119's own scope (implement the Option 3 surface)
  is fully delivered, not partially specified.

## Evidence links
Release branch `hotfix/task119-paper-performance-dashboard` commit
`d65a410`: `docs/audits/task119_paper_performance_dashboard/
TASK119_PAPER_PERFORMANCE_ACCEPTANCE.md`, `talonx_ops/paper_performance.py`,
`tests/test_task119_paper_performance.py`. Local (not committed, per
repo convention) rendered evidence: `results/task119_paper_performance/
spa/{screenshots/*.png,api/*.json,value_reconciliation.{json,md}}`.

## Later corrections
None yet.
