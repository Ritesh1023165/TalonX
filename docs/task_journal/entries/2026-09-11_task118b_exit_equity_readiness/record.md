# Task 118B — exit-timing verification, equity correction, live readiness

## Objective and acceptance criteria
Close 4 specific evidence gaps from Task 118A: VRT exit chronology
validity; real (not cash-only) equity drawdown; regular-session readiness
practical impact; a statistically sound observation protocol.

## Timing
- UTC start: 2026-09-11T~12:32 (baseline re-verification)
- UTC end: 2026-09-11T~13:00 (all four reports complete and pushed;
  market still pre-open, no hotfix triggered)

## Branch / SHA
- Release: `research/talonx-strategy-validation`, unchanged code SHA
  `c88f4d4` (no runtime defect proven → **no restart performed**), docs
  commit `813bfc0` (added the missing bundle README).
- Research: this entry, on `research/talonx-profitability-2026-09`.

## Requested vs. completed scope
- Part 1 (VRT exit chronology): **DONE** — `TASK118B_EXIT_TIMING.md`,
  verdict `VALID_UNDER_EXISTING_PAPER_POLICY`.
- Part 2 (equity/drawdown correction): **DONE** —
  `TASK118B_EQUITY_RECONCILIATION.md`, real equity CSVs + script
  committed.
- Part 3 (readiness): **DONE, pre-open snapshot** —
  `TASK118B_READINESS.md`; explicit stated observation gap for the actual
  regular session (market not yet open at completion).
- Part 4 (protocol correction): **DONE** — `TASK118B_RESEARCH_PROTOCOL.md`.
- Part 5 (conditional hotfix): **not triggered** — neither Part 1 nor
  Part 3 proved an active functional defect (Part 1: valid; Part 3: a
  real readiness gap traced to external data availability + thin
  premarket liquidity, not a bounded, safe code defect). Runtime left
  explicitly unchanged.
- Part 6 (EOD): not yet due at completion; required operator action
  stated (see outcome.md).
- README 404: root-caused (the bundle's README.md simply never existed;
  the other 4 files were always present and pushed) and fixed.

## Source / runtime / data manifest
See each `TASK118B_*.md` for full evidence (log line citations, exact
SQL/queries, reproducible script). `build_equity_curve.py` (checked in)
reproduces the equity CSVs from `reconciliation/trades.csv` + the same
frozen bar CSVs the original baseline replay used.

## Tests / experiments / results / limitations
No code changed this task (no defect proven) — no new tests needed or
added. Limitations: Part 1's Redis-level provenance is partially inferred
(Pub/Sub carries no persisted message id); Part 3's regular-session
coverage question remains genuinely open pending market open.

## User-visible outcome
See `outcome.md`.

## Verdicts (kept separate)
- Operational verdict: runtime unchanged, still healthy, still pre-open.
- Profitability verdict: unaffected — this task corrected measurement
  methodology (equity, protocol) and verified one paper-model fill's
  validity; none of this implies or is presented as a profitability
  result.

## Production effects, external sends, protected-state checks
Zero production writes this task — every check was read-only (SQLite
`mode=ro`, live dashboard reads, log file reads). No Redis mutation, no
external send, no strategy/threshold/scope change.

## Findings
- Fixed: none (documentation/analysis task; no defect proven).
- Open: actual regular-session readiness coverage (Part 3, pending
  market open); whether a paired-difference analysis of this scope vs.
  the full panel (Part 4's recommended next analysis) would show a real
  difference — not yet run.
- Deferred: retry/resilience improvements to the preseed fetch path
  (identified as a possible future enhancement, explicitly not a proven
  defect, not attempted).

## Evidence links
`docs/research/TASK118B_{EXIT_TIMING,EQUITY_RECONCILIATION,READINESS,
RESEARCH_PROTOCOL}.md`; `results/task118_profitability/build_equity_curve.py`
+ `reconciliation/equity_curve_{10m,300k}.csv`; release-branch
`docs/audits/task118a_priority_hotfixes_2026-09-11/README.md` (commit
`813bfc0`).

## Later corrections
None yet.
