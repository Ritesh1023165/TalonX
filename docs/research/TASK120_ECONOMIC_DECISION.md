# Task 120 (Workstream B) — economic/product decision

Protocol written and frozen before running: `TASK120_PROTOCOL_39NAME_SCOPE_REPLAY.md`.
Script: `research/scripts/task120_39name_scope_replay.py`. Raw output:
`results/task120_39name_scope_replay/{result.json,terminal_summary.txt}` (local).

## B1 — the actual product gap (restated, not re-litigated)

The user wants configured-ticker intraday and short/long-horizon alerts
plus attributable local paper portfolios, with positive aggregate economics
as the actual goal. Current evidence, unchanged by this task:

- V2 is sparse on the 39-name configured scope; its only live diagnostic
  (N=10) is negative and inconclusive.
- The broader 620-name panel's positive result (Task 115/116) does not
  automatically transfer to the 39-name scope — they have never been the
  same sample.
- Original is highly selective by design (Task 118/118B); readiness and
  economic edge remain separate, unresolved questions.
- Experimental's exit mechanics now work (Task 118A) but 4 recovery-
  affected losses are not a track record.
- Intelligence is informational, not a validated recommendation.
- Task 119/119A's dashboard work measures these facts; it created no edge.

## B2 — the one bounded analysis actually run

**Question**: does the 39-name live execution scope show a net economic
edge at properly-powered (not N=10) history, under the unchanged frozen
`INSIDER_BUY_CLUSTER_V2@1` contract?

**Result** (full available window, 2019-01-01 → 2026-09-12, the frozen
runtime-semantic entry rule, net@20bps, issuer-block bootstrap 5,000 reps
seed 118120):

| metric | value |
|---|---|
| N (priced episodes) | **27** |
| distinct issuers | 14 |
| net @20bps | **−0.863%** |
| profit factor | 0.782 |
| win rate | 55.6% |
| issuer-block bootstrap 95% CI | **[−7.507%, +2.312%] — includes zero** |
| drop-top-1 sensitivity | +0.761% |

**A genuine, newly-identified data-completeness finding, not a repeat of
any prior audit**: of the 39 live-scope names, only **33** have local
daily-bar price coverage in `results/task95g_broad_cross_sectional/_daily`
(the historical price panel every prior V2 backtest, including Task
115/116, has drawn from). The **6 missing** names are **ABCL, ACHR, ADC,
AGNC, MSTR, SHOP**. **MSTR is among them** — the same name Task 118E/F
already identified as dominating the live prospective sample's
composition. This means **no historical replay of the 39-name scope to
date (including this one) has ever been representative of the actual
live-traded population** — the backtestable subset structurally excludes
exactly the name most implicated in the live result. `drop_mstr_net20_pct`
is undefined here for the same reason: MSTR contributes **zero** episodes
to this sample, not because it was dropped as a sensitivity check, but
because it was never present.

The Task-116-comparable subwindow (2024-09-01→2026-03-31) has only N=3 in
this narrower 33-name intersection — too small to read on its own; the
full-window N=27 result above is the one that matters for this decision.

## B3 — hypothesis generation vs. confirmation

This analysis is exploratory (first look at this exact scope×window
combination) — its result is reported as such, not treated as confirmatory.
No genuinely unused *signal* data exists beyond what the closed research
programme (Task 93–97, 106A, 95A–K) already exhausted; what is newly
identified is a **coverage gap in already-collected price data**, not a new
signal source. Sample size (N=27, 14 distinct issuers) is modest —
consistent with, but not proof of, either a real negative scope effect or
pure noise. The issuer-block CI (which treats each issuer as one
resampling unit, the appropriate unit given repeated-issuer dependence)
spans from clearly negative to modestly positive — it does **not** support
any directional claim. Sensitivity (drop-top-1, predeclared) does not
flip the sign meaningfully (0.761% vs. −0.863%, i.e., the single largest-
weight issuer is not solely responsible for the negative point estimate).

## B4 — decision

**NO_SUPPORTED_STRATEGY_CHANGE.**

The properly-powered 39-name-scope replay (N=27, CI includes zero) neither
confirms nor rules out a real scope-specific effect — it is genuinely
inconclusive, exactly one of the four predeclared outcomes this protocol
named in advance. No threshold, universe, sizing, or holding-period change
is supported by this evidence, and none is made.

**Smallest concrete evidence-acquisition task named** (not performed in
this task — a recommendation, per this task's own "one recommended next
task" instruction):

> Backfill local daily-bar price coverage for the 6 currently-missing
> live-scope names (**ABCL, ACHR, ADC, AGNC, MSTR, SHOP**) using the SAME
> `composite-yf` pricing adapter V2's own live service already uses for
> pricing (no new provider, no new cost) into
> `results/task95g_broad_cross_sectional/_daily`, then re-run this exact,
> already-written, already-predeclared protocol
> (`research/scripts/task120_39name_scope_replay.py`) unmodified. This is
> the **first opportunity for a fully-representative** 39-name-scope
> historical read — every prior read, including this one, has excluded
> the name (MSTR) most implicated in the live sample's own composition.
> **Effort estimate (honest, not a target): small** — a data-backfill +
> unmodified script re-run, not new research design; the CURRENT N=27
> result already exists and does not need to be repeated, only extended
> once the 6 names are priced.

This is NOT: a threshold grid re-run (no threshold is touched); a new
signal family (same frozen contract, same entry rule); a watchlist
expansion (the 39-name scope itself is unchanged, only its OWN existing
members' price *coverage* is completed); a filter derived from this
result (nothing is filtered); or a promised win rate (none is stated).

## Explicit statements required by this task

- **If no demonstrated trading edge exists for the requested horizon**:
  none is demonstrated here, for the 39-name scope specifically, at
  current evidence. Stated plainly. Intelligence's informational
  functionality (filings/earnings/insider-significance delivery) is
  preserved and is not relabelled as a BUY/SELL recommendation anywhere
  in this task's outputs.
- **Live observation is not the sole programme**: the coverage-completion
  task above is a concrete, bounded, non-live-wait action that improves
  the evidence base independent of how many more live V2 trades occur.
- **Measurement improvement (Task 119/119A) is not evidence of
  profitability** — restated here explicitly, per this task's own closing
  instruction.
