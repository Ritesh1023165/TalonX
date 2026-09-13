# Task 122 — close Experimental evaluation, select one new candidate

## Objective and acceptance criteria
Stop repeated evaluation of `EXPERIMENTAL_RELAXED_V1`; select at most
ONE materially different, evidence-backed candidate for the configured-
ticker product and complete its bounded feasibility check; end with a
concrete evaluation plan or an explicit `NO_FEASIBLE_CANDIDATE` decision.

## Timing
2026-09-13, continuing the same research thread as Tasks 120-121B.

## Branch / SHA
Release: verified `f28986999eec5e313cfc89db24e4dbacfb378891` unchanged —
no release-branch work this task (research-only). Research `3e6cd9e` →
this commit.

## Requested vs. completed scope

- **PART 1 (close Task 121B): DONE, no rerun.** Two separate verdicts
  recorded: statistical `INSUFFICIENT_EVIDENCE` (the CI's upper bound
  +$1.06/trade sits below the predeclared +$1.25 threshold, conditional
  on the issuer-block-bootstrap estimator; the rule was not rewritten
  after seeing the result) and product `DO_NOT_ADVANCE_CURRENT_EXPERIMENTAL_CONTRACT`
  (a separate judgment, resting on negative gross P&L before any cost,
  PF<1, 19.4% win rate — not on the statistical bar alone). Two
  reporting corrections applied WITHOUT a rerun: (1) the execution
  sensitivity relabelled "repricing sensitivity" (it recomputed shares/
  P&L from the delayed price but held exit price/reason fixed and did
  not re-derive downstream occupancy/cooldown effects — the earlier
  "chronologically propagated" label overstated this); (2) explicit
  statement that daily marked drawdown was never supplied and ending
  equity is not a drawdown figure. Both corrections appended as dated
  addenda to the existing Task 121B documents (originals preserved).
  `EXPERIMENTAL_RELAXED_V1` archived as an internal research baseline —
  not deleted, not scheduled for further backtesting on its now-
  exhausted dataset.
- **PART 2 (replacement contract template): DONE.** A 7-field contract
  template (horizon/action, entry+exit, pre-decision information,
  frequency estimate, data/execution requirements, cost/materiality,
  falsification) applied to every shortlisted hypothesis in Part 3, with
  an explicit "not automatically materially different" bar (a changed
  threshold/removed loser/extra indicator/favorable subperiod does not
  qualify).
- **PART 3 (shortlist): DONE — 3 hypotheses, none padded.** (1) Overnight
  (close-to-open) return conditioned on same-day abnormal volume as a
  free attention proxy — Berkman/Koch/Tuttle/Zhang (2012, JFQA 47(4):
  715-741) and Lou/Polk/Skouras (2019, JFE 134(1): 192-213), both
  verified via live search (not from memory alone), both studying
  large-cap U.S. equities matching TalonX's configured universe.
  (2) 52-week-high proximity — George & Hwang (2004, JF 59(5): 2145-2176,
  verified via search) — flagged with a real horizon mismatch (published
  6-12 month holds vs. TalonX's short-horizon product) and overlap risk
  with Task 95B's already-rejected short-horizon breakout finding.
  (3) Turn-of-month calendar effect — McConnell & Xu (2008, FAJ 64(2):
  49-64, verified via search) — ranked lowest, likely fails single-
  ticker actionability (an aggregate/index-level effect, not
  differentiating across the 48 configured names). Cross-checked against
  `docs/RESEARCH_STATUS.md`'s explicit "What is NOT reopened" list
  (free intraday/swing/cross-sectional price-volume alpha, earnings-
  reaction mean-reversion, filing-text alpha, risk-exclusion filtering,
  catalyst-displacement) — none of the three reopens a rejected family;
  each has a stated "exact substantive difference."
- **PART 4 (ranking + feasibility): DONE.** Hypothesis 1 ranked highest
  (strongest/most directly-applicable mechanism, lowest overlap risk,
  full existing coverage, lowest complexity) — ranked BEFORE inspecting
  any return data. Bounded feasibility check
  (`research/scripts/task122_overnight_feasibility.py`, existing data
  only — `results/task95g_broad_cross_sectional/_daily`, Alpaca SIP,
  `adjustment=all`, free/entitled, 2019-06-03→2026-08-14): 35/48
  configured tickers covered (13 missing, 6 of those recoverable from a
  second existing dataset not used in this bounded check); 2,447
  same-day-abnormal-volume trigger events across 86 calendar months, 0
  data-quality issues (no duplicates/out-of-order/non-positive/negative-
  volume rows, any of the 35 symbols), 0 zero-trigger calendar months
  universe-wide, per-symbol totals 36-246 (≈0.42-2.86/month). **No
  outcome (overnight) return was computed or inspected** — trigger/
  coverage facts only, per Part 4's own instruction.
- **PART 5 (decision): DONE.** **`ONE_CANDIDATE_READY_FOR_FIXED_EVALUATION`**
  — Hypothesis 1. A fixed evaluation protocol frozen (universe, window,
  signal/entry/exit, cost/benchmark, portfolio constraints, primary
  metric + issuer-block-bootstrap uncertainty, 2 predefined
  sensitivities, missing-data/terminal treatment, fixed stopping rule) —
  labelled EXPLORATORY (no untouched confirmation window exists within
  this same dataset; already inspected once, for trigger frequency only,
  in this task).
- **PART 6 (executable next task): DONE.** Reusable functions named
  (`talonx_backtest.data.load_ohlcv_csv`/`check_dataset_quality`,
  `talonx_paper.engine.apply_spread`, the issuer-block-bootstrap
  pattern); minimal adapter work scoped (a small vectorized daily-bar
  script, reusing the ALREADY-WRITTEN and tested trigger logic from this
  task's own feasibility script — no new engine); a small causal event
  trace already written and passing (`tests/test_task122_overnight_feasibility.py`,
  5 tests) proving the trigger's point-in-time correctness BEFORE any
  historical run; runtime estimated (~63K daily rows, a vectorized
  pandas computation — seconds, not hours; no profiling needed, this is
  not the per-bar-indicator bottleneck that made the Experimental
  replays multi-hour); output artifacts and the exact economic decision
  specified.
- **PART 7 (journal/publication): DONE** — this entry;
  `TASK122_CANDIDATE_DECISION.md` (the primary deliverable, Parts 1-6
  consolidated); `PRODUCT_STATUS.md` updated (Experimental resolved/
  archived, new candidate row added, "properly powered" wording
  corrected); `TALONX_RESEARCH_LEDGER.md` (research worktree) given a
  concise Tasks-120-122 pointer entry (the ledger's own entries stop at
  Task 69Q; 70-119 intentionally not backfilled, out of this task's
  bound — `RESEARCH_STATUS.md` remains the authoritative pointer for
  that span); a new focused test file (5 tests, all pass).

## Source / runtime / data manifest
New: `research/scripts/task122_overnight_feasibility.py` (reuses
pandas/existing CSV data only, no new engine),
`tests/test_task122_overnight_feasibility.py` (5 tests),
`docs/research/TASK122_CANDIDATE_DECISION.md`,
`results/task122_overnight_feasibility/feasibility_summary.json` (local;
a small sanitized copy committed under `docs/research/evidence/task122/`).
Reused unmodified: `results/task95g_broad_cross_sectional/_daily` (Alpaca
SIP daily bars, `adjustment=all`, already-published, no new download).

## Tests / experiments / results / limitations
`pytest tests/test_task122_overnight_feasibility.py -q` → 5 passed. One
real, small (seconds, not hours), read-only computation over already-
downloaded data. Limitations, stated plainly: 13/48 configured tickers
have no located free daily-bar coverage (7 of those with no coverage in
ANY existing dataset checked this task); the selected candidate's
feasibility check used ONLY the trigger/coverage side — its actual
economic outcome (the overnight return itself) is completely unevaluated
and is explicitly the next task's job, not this one's.

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Part 1 (Task 121B closure): `INSUFFICIENT_EVIDENCE` (statistical) /
  `DO_NOT_ADVANCE_CURRENT_EXPERIMENTAL_CONTRACT` (product).
- Part 3/4 (shortlist + feasibility): `RANKED_AND_FEASIBILITY_CHECKED`.
- Part 5 (selection): `ONE_CANDIDATE_READY_FOR_FIXED_EVALUATION`.

## Production effects, external sends, protected-state checks
None — research-only task. Release branch untouched (`f289869`
unchanged, verified at task start and end). No application process
started. Redis/production DBs re-verified clean at task end.

## Findings
- Fixed: Task 121B's two reporting overstatements (execution-sensitivity
  labelling; drawdown never supplied) and `PRODUCT_STATUS.md`'s own
  stale "properly powered" wording (a residual from before Task 121's
  own correction of that phrase elsewhere).
- New: a concrete, literature-grounded, existing-data-feasible candidate
  (overnight/attention) with a materially different mechanism from every
  closed price/volume study in this program, and a real, non-degenerate
  measured trigger frequency.
- Open: the candidate's actual economic outcome (the next task's exact
  scope, not resolved here).
- Deferred: Hypotheses 2/3 (52-week-high, turn-of-month) — ranked but
  not feasibility-checked, per Part 4's own "stop after the top-ranked
  candidate" instruction, available for later reconsideration if
  Hypothesis 1's evaluation is negative/inconclusive.

## Evidence links
`docs/research/TASK122_CANDIDATE_DECISION.md`,
`docs/research/evidence/task122/*` (this commit);
`results/task122_overnight_feasibility/` (local, gitignored).

## Later corrections
None yet.
