# Task 119A — corrections to Task 119 and integration into release

**Branch**: `hotfix/task119-paper-performance-dashboard` (same branch Task
119 used), second commit on top of Task 119's `d65a410`.
**Status**: implemented, tested, rendered at two viewports, **integrated
into `research/talonx-strategy-validation`** after the gates below passed
(see §Integration). Repository integration is not production activation —
the application was not started.

## What was wrong with Task 119, and why (workflow lesson)

Task 119 was asked, in Task 118H's own words, to build "one read-only
dashboard section... reusing existing read-only accessors." It instead
built a genuinely new, separate tab (`Paper Performance`) alongside the
pre-existing `Paper / EOD` tab. Both tabs read Original/Experimental's
numbers, but from different code paths with different levels of detail —
a user could open two tabs and see the same lane's cash/status/position
count on both, with no link between them and no guarantee they'd ever say
the same thing. Every individual field was correct and every individual
test passed; the acceptance criteria Task 119 wrote for itself never asked
"is this the ONE place a user reads paper-portfolio state," so nothing
caught the duplication.

**Workflow lesson recorded per this task's own instruction**: acceptance
criteria must be checked against the actual requested user journey — here,
"reuse the existing paper view," not merely against whether the new
surface's own fixtures render correctly. A rendered-fixture pass is
necessary but not sufficient; it does not by itself prove the surface
belongs where it was asked to go.

Two further, independent defects were found while correcting the above
(not new work invented for its own sake — found because A2/A3 explicitly
required tracing the actual cost/calendar mechanics against source code):

1. **Cost mislabelling**: Task 119 labelled every lane's costs a blanket
   `"UNMODELED"`. Reading `talonx_paper/engine.py` and
   `talonx_paper/config.py` shows `apply_spread()` DOES simulate a bid-ask
   spread (`simulated_spread_bps`, default 5.0 bps/0.05% per side) on
   EVERY Original/Experimental fill, baked directly into the stored
   `entry_price`/`execution_price` — so those lanes' P&L IS net of
   simulated spread. What is genuinely unmodeled, for those two lanes, is
   an explicit commission (deliberately, per that module's own docstring
   — most modern retail brokers are commission-free). V2
   (`talonx_v2/paper.py`) genuinely has no spread simulation at all — its
   figures really are fully gross, a materially different and more
   informative fact than "everything, everywhere, is unmodeled alike."
2. **Session-open approximation**: Task 119 approximated the regular
   session's open as `close - 6h30m`. That is exactly right on a full
   session but wrong on an early-close (half) day — e.g. the
   post-Thanksgiving half day is a 3.5-hour session (14:30–18:00 UTC), not
   6.5 hours; the approximation would have placed the approximated open at
   11:30 UTC, three hours before the real 14:30 UTC open, misclassifying
   any pre-open mark in that window as `REGULAR_SESSION`. Fixed by adding
   `talonx_signals.market_sessions.session_open_utc()` (mirroring the
   already-existing, already-authoritative `session_close_utc()`) and
   reading the real, DST- and half-day-aware open from
   `exchange_calendars` directly — regression test included
   (`test_half_day_uses_real_open_not_close_minus_6h30m`).

## A1 — one paper-performance destination

`talonx_ops.paper_performance.build_paper_performance()` (the one
accounting implementation) is unchanged in its own logic; what changed is
where its output is surfaced:

- `DashboardReadModel.paper_eod()` now calls it internally and folds each
  lane's richer data into that SAME lane's EXISTING block
  (`original_local_paper.performance`, `experimental_validation_paper.performance`)
  — every pre-existing top-level key on `paper_eod()` is byte-unchanged
  (back-compat), only the new nested `"performance"` key is added.
- V2's richer accounting (equity, arithmetic reconciliation, cost
  breakdown) is folded into `v2_active_strategy()`'s ALREADY-existing
  "$300,000 campaign ledger" card (`ledger.performance`) — V2 never had a
  `paper_eod()` entry before Task 119 either, so it is not given one now;
  it stays in its own one existing destination.
- The `paper_performance` tab, nav button, `_UNIFIED_SECTIONS` entry, and
  `/api/section/paper_performance` route are **removed**. The
  `DashboardReadModel.paper_performance()` Python method is **kept** (it
  is directly useful and directly tested — `tests/test_task119_paper_performance.py`)
  but is no longer a routed, user-facing destination — `all_sections()`
  no longer returns it.
- PIV's card now carries an explicit clarification: `NOT_CHECKED` means no
  network read was performed, and must never be read as a failure of
  Original/Experimental local paper accounting (A2).

Result: exactly one destination per lane, no competing totals, no
inconsistent period labels — verified by the rendered acceptance below and
by `tests/test_task119_paper_performance.py::test_dashboard_read_model_exposes_paper_performance`,
which now asserts `"paper_performance" not in all_sections()` and that
`paper_eod()`/`v2_active_strategy()` each carry exactly the folded-in
data.

## A2 — truthful accounting and cost labels

`talonx_ops/paper_performance.py` now carries two explicit,
source-code-verified cost breakdowns:

| | spread/slippage | commissions/fees | summary |
|---|---|---|---|
| Original/Experimental | **MODELED** — `apply_spread()`, 5.0 bps/side default, baked into every stored fill price | NOT modelled (deliberate — commission-free-broker assumption) | "net of the simulated bid-ask spread... but gross of commissions... NOT 'net of all costs'" |
| V2 | NOT modelled — exact quoted price, no adjustment | NOT modelled | "fully GROSS... the most optimistic of the three lanes... not 'net of all costs'" |

Kept independent, each its own field/card, never merged into one
combined status (verified in the rendered screenshots below):
ledger arithmetic reconciliation (`reconciliation.status`), valuation
completeness/freshness (`open_positions.marked_value_status`, per-position
`mark_session_classification`/`mark_age_seconds`), cost-model completeness
(`costs`), recovery-affected provenance (`closed_trades[].recovery_affected`),
base/PIV reconciliation (`eod_reconciliation` card vs. the separate PIV
card, each with its own status), and exit-monitoring observability
(`last_exit_evaluation.status = "NOT_TRACKED"`, honestly labelled — no
dedicated exit-check log exists anywhere in this repo to read from). The
`eod_reconciliation` card now carries an explicit note: *"This EXACT/
PARTIAL arithmetic check is independent of valuation-mark freshness,
cost-model completeness, recovery-affected provenance and PIV — an EXACT
reconciliation here never implies those other, separately-shown checks
are also verified."*

Intelligence is confirmed, again, to have no attributable paper ledger and
none is invented (`intelligence_note` field, unchanged claim from Task
119).

## A3 — exchange-calendar session labels

`talonx_signals/market_sessions.py` gained `session_open_utc(d)`, built
exactly like the pre-existing `session_close_utc(d)` (same
`exchange_calendars` XNYS source, same weekday-only fallback if the
calendar package is unavailable). `talonx_ops/paper_performance.py`'s
`classify_valuation_timestamp()` now:

- Uses the real open AND close for every classification (no
  `close - 6h30m` approximation anywhere) — correct on full and half days
  alike, DST-aware (verified: 13:30 UTC open in September, 14:30 UTC in
  November, both read directly from `exchange_calendars`, not computed).
- Distinguishes `NON_SESSION_DAY` (the calendar affirmatively says the
  date is not a trading day — independently cross-checked against
  `talonx_v2.calendar.is_session`, an established fact) from `UNKNOWN`
  (the calendar mechanism itself could not be consulted — e.g.
  `exchange_calendars` unavailable/raised) — never folded together, per
  this task's own "if session classification cannot be established, show
  UNKNOWN" instruction. Regression test:
  `test_calendar_mechanism_failure_reports_unknown_not_non_session_day`
  (monkeypatches the calendar functions to raise).
- SPCX's real 2026-09-11T20:08:00Z mark is re-verified to classify
  `POST_CLOSE`, with the note "NOT an official regular-session closing
  price," never combined with an "as of 20:00Z" label — unchanged
  conclusion from Task 119, now on a corrected mechanism.
- Naive (tz-less) timestamps: confirmed, by reading the actual stored
  values in `~/.talonx/paper_trading.db` and
  `~/.talonx/experimental/experimental_paper.db` this task (read-only),
  that every timestamp this repo's own paper-trading stores actually write
  carries an explicit UTC offset — the naive-as-UTC fallback in
  `_parse_ts` is a defensive default, not an exercised source contract,
  documented as such in the module.

## A4 — Friday's accounting, re-verified against source records

Re-read (read-only) `~/.talonx/paper_trading.db` and
`~/.talonx/experimental/experimental_paper.db` at the start of this task
— not copied from Task 118H's or Task 119's report text. Confirmed
byte-identical to what both prior tasks reported:

- Experimental: 5 campaign entries (`trade_history` ids 1–5, Sept 9–10),
  4 exits (`trade_history` ids 6–9, all Sept 11) — all 4 still correctly
  flagged `recovery_affected` under the unchanged Task 118A evidence
  citation.
- Realized total: `portfolio_state.total_realized_pnl_usd` =
  `-324.4662160270568`, exact.
- SPCX still open (`positions` table, unchanged since Task 118H's close):
  entry $148.22755360794068, 16.865960067130683 sh, stop $144.6133321126302,
  target $152.06332906087238.
- Last stored mark: `paper_trading.db.latest_prices` SPCX =
  $151.2100067138672 @ `2026-09-11T20:09:20.853147+00:00` (the
  Task-118H-preserved feed-write timestamp) — the position's own entry
  timestamp is `2026-09-10T19:29:45.777729+00:00`; the SESSION-11
  20:08:00Z figure cited throughout this session's docs is the mark
  Task 118H's own closing snapshot recorded at handoff, reproduced
  identically here in the isolated fixture.
- V2: `v2_lane.db.portfolio.cash` = 300000.0, `positions`/`trades` tables
  both empty — flat, unchanged.
- No value was rewritten to make the fixture agree; the fixture was built
  FROM these re-read source values.

## A5 — rendered acceptance and durable evidence

The actual, now-integrated `dashboard_web.py` SPA, isolated `TALONX_HOME`/
`TALONX_V2_DB_PATH` fixtures (production `~/.talonx` and repo-root
`v2_lane.db` never opened), loopback port 8897, headless Chrome, captured
at **two viewports**: a normal desktop size (1360×2600) and a narrower
usable size (900×2600, above the app's own 640px single-column CSS
breakpoint but well below a full desktop width) — both inspected directly
for readability, clipping, table labels, and timestamps; both render
cleanly with no overlap or truncation at either width.

Local (bulk, gitignored per this repo's `/results/` convention) evidence:
`results/task119a_integration/spa/` — `make_fixture.py` (reused from Task
119 unmodified), `run.sh`, 6 scenarios × 2 viewports + one `Active V2`
capture, `api/*.json` (both `paper_eod` and `v2_active_strategy`
endpoints), `value_reconciliation.{json,md}` (28 independently-traced
field checks, 28/28 match).

**Committed** (small, representative, at this commit's immutable SHA — per
this task's own instruction not to leave everything gitignored):
`docs/audits/task119a_paper_eod_integration/evidence/`:

| file | shows |
|---|---|
| `friday_reconciled_desktop_1360x2600.png` | the Friday reconciliation, desktop |
| `friday_reconciled_narrow_900x2600.png` | the same, narrower viewport — responsive, no clipping |
| `reconciliation_mismatch_desktop_1360x2600.png` | Experimental source-unavailable (`UNKNOWN`) + the em-dash/`UNAVAILABLE` labelling, never a fabricated 0 |
| `active_v2_friday_desktop_1360x2600.png` | V2's folded-in equity/reconciliation/costs in its own existing "$300,000 campaign ledger" card |
| `value_reconciliation.md` | the 28-row field/source reconciliation table |

## A6 — tests and integration

`pytest tests/test_task119_paper_performance.py tests/test_task100c_unified_dashboard.py tests/test_task99g_forward_outcome_wiring.py -q`
→ **91 passed** (22 new/updated Task 119A assertions: cost-breakdown
correctness, calendar half-day/NON_SESSION_DAY/UNKNOWN distinction, the
one-destination wiring). Full changed-surface run
(`-k "dashboard or task100c or task114 or task119 or task112 or market_session or task99g"`)
→ **300 passed**. No unrelated suite re-run without reason.

Diff against `research/talonx-strategy-validation` HEAD (`d4177b3`)
inspected before integration: 7 files, 360 insertions / 110 deletions —
`dashboard_web.py`, `dashboard_web_static/index.html`,
`talonx_ops/dashboard_read.py`, `talonx_ops/paper_performance.py`
(Task 119's own file, corrected), `talonx_signals/market_sessions.py`
(one new function, `session_close_utc` untouched), plus the two test
files above. No other file touched.

**Integration**: this branch (`hotfix/task119-paper-performance-dashboard`,
now carrying both the Task 119 commit `d65a410` and this task's correction
commit) was merged into `research/talonx-strategy-validation`. Fast-
forward (no intervening release-branch commits since `d4177b3` — verified
via `git log d4177b3..origin/research/talonx-strategy-validation`, empty
— so no conflict resolution was needed and no intervening fix could have
been lost). V2 fingerprint re-verified **unchanged**
(`11107198c5b81237`) after integration. See the commit/push evidence at
the end of this document for the exact integrated SHA.

**The production application was NOT started, restarted, or deployed as
part of this integration** — integrating into the release branch's git
history is not the same action as running it.

## Correction to Task 119's own "production preservation" wording

Task 119's acceptance report said "No application process started/
stopped." That wording undersold what actually happened: Task 119 (and
this task) DID start isolated `dashboard_web.py` test subprocesses,
repeatedly, to capture rendered acceptance screenshots — on ports 8898
(Task 119) and 8897 (this task), always against isolated
`TALONX_HOME`/`TALONX_V2_DB_PATH` fixtures, never the production
`~/.talonx` or the repo-root `v2_lane.db`, never bound to a
non-loopback host. Every one of those subprocesses was explicitly
`kill`ed at the end of its capture; independently verified this task via
`psutil.process_iter` (no `dashboard_web` process found) and `netstat`
(no LISTENING socket on 8897/8898/8899) after all captures completed. The
corrected, accurate claim is: **no PRODUCTION process was started or
stopped; isolated test subprocesses were started and cleanly stopped,
verified.**

## Rollback

**Exact integrated candidate SHA**: recorded at the end of this document
(the merge commit / fast-forward tip on `research/talonx-strategy-validation`).
**No migration required** — this remains a pure read-only dashboard
addition; no schema, no write path, no strategy code touched.
**Compatible-code rollback** (Task 119A's own instruction: "do not merge"
is not a rollback plan after integration): `git revert <merge-commit-or-range>`
on `research/talonx-strategy-validation` restores the exact pre-Task-119
`paper_eod()`/`dashboard_web.py`/`index.html` behavior; because every
pre-existing key on every touched function is byte-unchanged and only new
keys/routes were added or one route removed, the revert is a clean,
mechanical operation with no other in-between change to reconcile.

## Known limitations (carried forward, none newly introduced)

Same as Task 119's own list: PIV always `NOT_CHECKED` (no network call, by
design); `last_exit_evaluation` always `NOT_TRACKED` (no dedicated log
exists); `market_sessions.py`'s own graceful-degrade-to-fallback behavior
on a calendar-package failure is pre-existing and unchanged (this task
only added the independent `NON_SESSION_DAY`/`UNKNOWN` distinction on TOP
of that existing behavior, via a second, independent check).
