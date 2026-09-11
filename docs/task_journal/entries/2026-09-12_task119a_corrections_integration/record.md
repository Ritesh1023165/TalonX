# Task 119A — corrections to Task 119, integration, Monday handoff (Workstreams A + C)

Companion entry: `../2026-09-12_task120_economic_decision/` (Workstream B).

## Objective and acceptance criteria
Close Task 119's acceptance gaps (one destination, truthful costs, real
calendar), render/commit small durable evidence, integrate into the
release branch after gates pass, and prepare (not execute) the Monday
handoff.

## Timing
- UTC start: 2026-09-11T~22:50 (continuing the same session; system clock
  rolled to 2026-09-12 partway through this task — noted, not treated as
  a new "overnight" gap in monitoring, since no production process was
  ever running to monitor).
- UTC end: 2026-09-12T~02:30.

## Branch / SHA
- Release: verified `d4177b3` at start (exact match to reported baseline,
  confirmed via `git fetch` + `git log d4177b3..origin/...` empty — no
  intervening commits). Hotfix branch `hotfix/task119-paper-performance-dashboard`
  gained a second commit `f289869` (corrections). Fast-forward merged into
  `research/talonx-strategy-validation` → **integrated release SHA
  `f28986999eec5e313cfc89db24e4dbacfb378891`**, pushed.
- Research: `aef24c7` → this entry (+ the Task 120 entry).

## Requested vs. completed scope
- A1: **DONE** — `paper_eod()` folds Original/Experimental's rich
  accounting into their existing blocks (`.performance` key, all
  pre-existing keys byte-unchanged); V2's rich accounting folds into
  `v2_active_strategy()`'s existing $300k ledger card; the separate
  "Paper Performance" tab/route/nav-button/`_UNIFIED_SECTIONS` entry
  removed; `DashboardReadModel.paper_performance()` kept as an internal,
  directly-tested accessor, not a routed destination.
- A2: **DONE** — traced `talonx_paper/engine.py`/`config.py` source:
  spread/slippage IS modeled (`apply_spread`, 5.0bps/side default) for
  Original/Experimental, baked into fill prices; commissions/fees are
  NOT (deliberate). V2 has neither. Four-component cost breakdown per
  lane; reconciliation/valuation-freshness/cost-completeness/recovery-
  provenance/base-PIV/exit-observability kept as independent fields; the
  EOD reconciliation card states explicitly that its EXACT status does
  not imply those other checks are verified.
- A3: **DONE** — added `talonx_signals.market_sessions.session_open_utc()`
  (mirrors the pre-existing `session_close_utc()`); replaced the
  `close - 6h30m` approximation (wrong on early-close half days, proven
  by a regression test); `NON_SESSION_DAY` vs `UNKNOWN` now distinguished
  (independent cross-check against `talonx_v2.calendar.is_session`); SPCX's
  real mark re-verified `POST_CLOSE`.
- A4: **DONE** — re-read `~/.talonx/{paper_trading.db,experimental/experimental_paper.db}`
  read-only at task start; byte-identical to Task 118H/119's reported
  values (5 entries, 4 recovery-affected exits, −$324.4662160270568,
  SPCX open unchanged, V2 flat $300,000).
- A5: **DONE** — rendered the actual integrated SPA at 1360×2600 (desktop)
  and 900×2600 (narrower) for all 6 required scenarios + one Active-V2
  capture; 28/28 independently-traced field checks match; a small (4
  PNG + 1 md, ~820KB) representative set committed under
  `docs/audits/task119a_paper_eod_integration/evidence/`; bulk evidence
  stays local under `results/task119a_integration/` (gitignored, per this
  repo's existing `/results/` convention — confirmed via `git ls-files`
  that this repo has never committed bulk `results/` output for any prior
  task either). "No production processes started/stopped" wording
  corrected to name the isolated test subprocesses and their verified
  cleanup (`psutil` + `netstat`, both clean after every capture).
- A6: **DONE** — 91 passed on the direct surface, 300 passed on the full
  changed-surface set, both before and after integration. Diff inspected
  (7 files, 360+/110− before the correction commit; 14 files total across
  both hotfix commits). Fast-forward merge (no conflicts — no intervening
  release commits existed to lose). V2 fingerprint re-verified unchanged
  (`11107198c5b81237`; zero-line diff in `talonx_v2/` and the
  fingerprint-defining module). Pushed both branches.
- Workstream C: **DONE** — `NEXT_SESSION_HANDOFF.md` updated in place
  (dated update note, not a silent rewrite): new candidate SHA, unchanged
  strategy config, SPCX obligation re-verified read-only, the Task 120
  finding folded into known limitations, the next research action updated
  to point at Task 120's decision. Monday 2026-09-14 re-verified via
  `talonx_v2.calendar.is_session`. **No GO declared, no session launched,
  no recurring job created** — this document states the candidate is
  ready for preflight review, not that preflight has been run.

## Source / runtime / data manifest
Modified (see A1–A3 above): `talonx_ops/paper_performance.py`,
`talonx_ops/dashboard_read.py`, `dashboard_web.py`,
`dashboard_web_static/index.html`, `talonx_signals/market_sessions.py`,
`tests/test_task119_paper_performance.py`,
`tests/test_task100c_unified_dashboard.py`. New:
`docs/audits/task119a_paper_eod_integration/{TASK119A_CORRECTIONS_AND_INTEGRATION.md,evidence/}`.
`results/task119a_integration/spa/{make_fixture.py (reused from Task 119
unmodified),run.sh,build_reconciliation_table.py}` (local).

## Tests / experiments / results / limitations
`pytest tests/test_task119_paper_performance.py tests/test_task100c_unified_dashboard.py tests/test_task99g_forward_outcome_wiring.py -q`
→ 91 passed. `pytest tests/ -k "dashboard or task100c or task114 or task119 or task112 or market_session or task99g" -q`
→ 300 passed, both pre- and post-integration. No unrelated suite re-run.
Limitations unchanged from Task 119 (PIV NOT_CHECKED by design,
last-exit-evaluation NOT_TRACKED — no such log exists anywhere in the
repo).

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Dashboard/operational verdict: `PAPER_EOD_INTEGRATION_ACCEPTED` — one
  destination per lane, truthful costs, real calendar, rendered at two
  viewports, integrated into the release branch, V2 fingerprint
  unchanged, production untouched.
- Economic verdict: see the companion Task 120 entry —
  `NO_SUPPORTED_STRATEGY_CHANGE`. This dashboard work is explicitly not
  evidence of profitability.

## Production effects, external sends, protected-state checks
Zero production writes; zero production process starts/stops (re-verified
`psutil`/`netstat`/`redis.ping()` clean at task end, matching the state at
task start). Isolated test subprocesses (`dashboard_web.py` on loopback
port 8897) were started against isolated fixtures and explicitly killed —
listed, not glossed over, correcting Task 119's own imprecise wording.
SPCX's obligation, V2's flat book, and the Sept 11 session's closed state
are all unchanged. No external send of any kind.

## Findings
- Fixed: the Task 119 tab-duplication defect (A1); the blanket-UNMODELED
  cost mislabelling (A2); the close-6h30m session-open approximation
  (A3, real bug — proven by a half-day regression test).
- Open: heartbeat-lapse locus, "45 candidates" source, mid-session
  recovery gap — all carried forward unchanged, no new evidence.
- Deferred: none — this task's own scope (Workstream A + C) is fully
  delivered.

## Workflow lesson (recorded per this task's own instruction)
Acceptance criteria must be checked against the actual requested user
journey ("reuse the existing paper view," here), not only against whether
a new surface's own isolated fixtures render correctly. A rendered-fixture
pass proves the surface works; it does not by itself prove the surface
belongs where it was asked to go, or that its claims about cost/valuation
mechanics are traced against the actual source code rather than assumed
from a plausible-sounding pattern seen elsewhere in the same task.

## Evidence links
Release `f289869`:
`docs/audits/task119a_paper_eod_integration/TASK119A_CORRECTIONS_AND_INTEGRATION.md`
+ `evidence/` (4 screenshots + reconciliation table, committed). Local:
`results/task119a_integration/spa/`.

## Later corrections
None yet.
