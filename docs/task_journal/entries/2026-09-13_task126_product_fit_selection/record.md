# Record

## Baseline verification (start of task)

- Research branch `research/talonx-profitability-2026-09` HEAD:
  `1248a0d7756446f282c7aea1d6c832e8408d5bd7` (matches expected exactly).
- Release worktree HEAD: `f28986999eec5e313cfc89db24e4dbacfb378891`
  (matches expected exactly), `git status --short` clean.
- No TalonX process running, no listening ports on 8787/8770/8760/
  8501. Redis reachable, 0 `talonx:*` keys.

## Actions taken, in order

1. Read `docs/research/TASK122_CANDIDATE_DECISION.md` Part 3
   (Hypotheses 2 and 3, already containing detailed primary-source
   citations for George & Hwang 2004 and McConnell & Xu 2008 from
   Task 122's own earlier `WebSearch`-verified citation work) and
   `docs/RESEARCH_STATUS.md`'s "not reopened" list.
2. Appended corrections to Task 125's stored artifacts (Part 1, no
   rerun): `docs/research/TASK125_OVERNIGHT_ACTIONABLE_RESULTS.md` and
   `docs/task_journal/entries/2026-09-13_task125_extended_intraday_evaluation/outcome.md`
   both received a correction blockquote withdrawing the "stress-
   tested and confirmed" framing, clarifying the ±50%-guard's
   incompleteness (split-driven volume-trigger distortion, unadjusted
   dividends), and distinguishing eligible-date (542), trigger-date
   (117), and bootstrap-resampling-block (542, same as eligible)
   counts for Cohort A.
3. Applied the required product-fit gate (mechanism / shorting-
   cross-sectional-universe requirement / signal timing / holding
   period / ticker-differentiation / prior-overlap / data coverage /
   benchmark / implementation-translation) to both remaining
   candidates, reasoning from Task 122's own detailed writeups plus
   `docs/research/PRODUCT_STATUS.md`'s current objective statement.
   Wrote the full assessment and selection matrix in
   `docs/research/TASK126_CANDIDATE_SELECTION.md`.
4. Determined BEFORE any return was computed for either candidate:
   - Candidate A (52-week-high): fails on holding-period
     compatibility — the published construction (6-12 month hold,
     cross-sectional decile rank across thousands of stocks) cannot be
     translated to a TalonX-compatible short horizon without inventing
     an unvalidated adaptation, which this task's own instruction
     explicitly disallows ("make that an explicit product decision
     rather than inventing a convenient shorter holding period").
   - Candidate B (turn-of-month): fails on ticker-specific-alert
     product fit — the mechanism structurally produces an identical
     calendar-wide exposure across all 48 configured tickers, using no
     ticker-specific information at all.
5. Selection: `NO_CANDIDATE_PASSES_PRODUCT_AND_DATA_GATES`. No
   protocol was frozen (Part 4 is conditional on a candidate passing);
   no data validation or evaluation code was written or run (Parts
   5-6 do not apply); no strategy return was computed for either
   candidate at any point in this task.
6. Wrote `docs/research/TASK126_ECONOMIC_DECISION.md` recording the
   two per-candidate product verdicts (`BLOCKED_BY_SPECIFIC_PRODUCT_OR_DATA_REQUIREMENT`
   for A, `DO_NOT_ADVANCE` for B) and the "not applicable" statistical
   verdict, with the smallest unblocking requirement named for each.
7. Wrote `docs/research/evidence/task126/selection_summary.json` (a
   compact machine-readable record of the same decision).
8. Updated `docs/research/PRODUCT_STATUS.md` (two new rows,
   corrected "What this page is not" section — the two remaining
   hypotheses are no longer "untouched," both were assessed and
   blocked/rejected) and `docs/research/TALONX_RESEARCH_LEDGER.md`
   (Task 126 pointer entry appended).
9. Re-verified production/Redis/process preservation (same result as
   baseline).

## No code run, no tests needed

Because no candidate passed the product-fit gate, Parts 4-6 (protocol
freeze, data validation, evaluation) were never reached — there was no
transformation logic to write fixture tests against. This is the
expected, designed outcome for a `NO_CANDIDATE_PASSES` result, not an
omission.

## Production preservation (end of task)

Unchanged from baseline — no process started, no port opened, Redis
`talonx:*` key count still 0, release worktree still clean at
`f28986999eec5e313cfc89db24e4dbacfb378891`.
