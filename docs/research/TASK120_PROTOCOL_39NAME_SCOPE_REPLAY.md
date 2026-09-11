# Task 120 (B2) — predeclared protocol: 39-name live-scope full-history replay

**Written before running the analysis or looking at its results**, per this
task's own instruction.

## Exact question

Does the **39-name live execution scope** (`resolved-active-watchlist`, the
exact set V2 actually trades against in production, resolved via
`talonx_ops.watchlist_coverage.build_coverage_map()`) show a net economic
edge under the frozen `INSIDER_BUY_CLUSTER_V2@1` contract when evaluated at
**full available historical power**, or is the live scope's only
observation to date (N=10, Task 118 Deliverable A, −2.93%, inconclusive)
consistent with a properly-powered sample on that exact same scope?

## Causal rationale

Two prior results exist and disagree, but they are **not comparable
samples**:
- The 39-name live scope has only ever been observed **prospectively**,
  starting 2026-09-08 (N=10 trades to date) — too small to distinguish a
  real scope-specific effect from sampling noise (Task 118E/F already
  established the live sample is dominated by 1–2 names, e.g. MSTR).
- The positive result (Task 115/116: net@20 +2.196%, N=170, both CIs>0)
  was computed on the **620-name broad cross-sectional panel**
  (`results/task95g_broad_cross_sectional`), never on the 39-name scope.

No one has ever applied the frozen contract to the 39-name scope
specifically at more than N=10. This gap is exactly the
"implementation-versus-economics distinction" this task's own instructions
point at: is the 39-name scope's apparent negative result a real,
scope-specific economic fact (something about these particular 39 large/
mega-cap names structurally disfavors this signal), or is it simply an
artifact of the live sample being too small to be informative?

## Why this is not a repeat

- Not a repeat of Task 116 (different universe: 39 names vs. 620).
- Not a repeat of Task 118 Deliverable A (that IS the N=10 live sample this
  analysis is trying to properly power — it is not rerun, its result is
  reused verbatim as one of the two things being reconciled).
- Not a repeat of Task 118E/F (that tested a different hypothesis —
  pre-entry volatility vs. net return — not scope-restricted full-history
  economics).
- Not a threshold grid, not a new signal family, not a watchlist expansion,
  not a filter derived from this result.

## Dataset / runtime / window

- Source data (100% already collected, free, existing): `talonx_v2`'s
  frozen entry-rule episode detector (`t112rp.runtime_episodes`, the exact
  runtime-semantic reference already established at Task 112R), applied to
  `results/task107a_form4_feasibility/_build/form4_open_market_txn.parquet`
  (Form 4 code-P open-market transactions) — **no new data collection**.
- Universe restriction: the 39 symbols currently resolved by
  `talonx_ops.watchlist_coverage.build_coverage_map()` with
  `v2_collection_scope == "POLLED"` (verified live, this task, 39 names —
  the exact production scope), intersected with symbols that have local
  daily-bar price coverage in `results/task95g_broad_cross_sectional/_daily`
  (SHOP is known to have none — Task 118's own prior finding — so an
  intersection, not the full 39, is expected and will be reported exactly).
- Window: the full available panel window (same as the Task 112R G2b
  reference, 2019–2026) for maximum power, **and** the Task 116-comparable
  2024-09-01→2026-03-31 subwindow for a like-for-like read against the
  already-published broad-panel number.
- Horizon: 10 trading days (the frozen contract's own hold horizon —
  unchanged).

## Primary metric, cost convention, exclusions

- Primary metric: net return at a 20bps round-trip cost assumption (the
  SAME convention as every V2 result published this session — Task 107B,
  112R, 115/116, 118 Deliverable A).
- Exclusions: identical to the frozen contract's own eligibility/staleness
  rules (`t112rp.runtime_episodes`) — no manual exclusion of any name or
  trade.

## Dependence and concentration limitations (predeclared)

- Primary: issuer-block bootstrap CI (resample whole issuers with
  replacement), 5,000 repetitions, seed `118120`, 95% percentile interval —
  the same convention used throughout this session's own research (Task
  95A onward).
- Sensitivity (predeclared, not chosen after seeing results): drop-top-1
  and drop-top-3 issuer concentration check; MSTR is expected, on priors
  from Task 118E/F, to be a material share of this specific 39-name
  sample's total episode count, so an explicit drop-MSTR variant is also
  reported (full population remains primary, per this session's own
  established convention).

## What conclusion would change the next product action

- **N < ~15 even over the full multi-year window**: the 39-name scope is
  structurally low-volume for this signal (a data/opportunity-rate fact,
  not an economics verdict) — the next action is continued observation,
  explicitly not "the strategy failed on this scope."
- **N adequate (≳30) and net@20 CI excludes zero, negative**: real evidence
  the 39-name scope specifically underperforms the broader panel — the
  live scope's N=10 negative draw would be corroborated, not just noise,
  and continued live-only observation would no longer be the sole
  programme (per this task's own instruction).
- **N adequate and net@20 CI excludes zero, positive**: the live N=10
  negative draw would be evidenced as small-sample noise, not a scope
  effect — continued live observation remains justified and is not
  contradicted by history.
- **N adequate and CI includes zero (inconclusive)**: no scope-specific
  effect either way is established; same conclusion as today, now with a
  properly-powered rather than N=10 basis for saying so.

No threshold is relaxed, no name is removed, no new signal is introduced,
and no forced win-rate target is claimed regardless of outcome.
