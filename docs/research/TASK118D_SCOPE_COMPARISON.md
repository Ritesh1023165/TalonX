# Task 118D — matched-scope profitability comparison (2026-09-11)

Measurement only. No parameter tuning, no promotion, no scope change to
the live 39-name configuration. V2 fingerprint `11107198c5b81237`
verified unchanged before every run (script aborts otherwise).

## Part 1 — three explicitly defined, matched populations

| population | definition | n symbols |
|---|---|---:|
| **A** | the live configured 39-name scope | 39 |
| **B** | the full historical panel, **excluding** A's 39 names | 587 |
| **C** | the full historical panel (A ∪ B) | 626 |

**Population C is not Task 116's already-published 620-name figure reused
verbatim.** Verified rather than assumed: Task 116 ran under a
pre-Task-117 vintage of `service.py`/`form4_source.py`/`store.py`
(missing `execution_allowlist` enforcement and the F3 dissemination-slack
fix) — an **unmatched runtime** for this comparison. Separately, **6 of
A's 39 names (ABCL, ACHR, ADC, AGNC, MSTR, SHOP) are not members of
Task 116's 620-name panel at all** — reusing that panel verbatim as "C"
would violate `C ⊇ A` by construction. **C is therefore built explicitly
as (Task 116's 620-name panel) ∪ (the 39-name scope) = 626 names**, and
**B = C − A = 587 names** — both re-run fresh here under the identical
matched runtime/contract A already used, not derived by filtering a
pre-existing trade ledger (own capital pool, own concurrency/cooldown
dynamics — see Part 2).

**Matched, verified identical across A/B/C**: historical window
(2024-09-01→2026-03-31), 45-day rolling causal filing window, runtime
(byte-identical `service.py`/`form4_source.py`/`store.py`/`calendar.py`,
V2 fingerprint checked before each run), price source (same `_daily`/
`_prices` bar directories), eligibility rules (≥2 distinct-insider
code-P cluster, same frozen liquidity/cooldown rules), 10-trading-day
hold, 20bps round-trip cost convention, fixed $10,000/position sizing,
$10,000,000 research-convention starting cash.

**Episode vs. executed-trade reconciliation**: `processed_episode_dispositions`
recorded per run — e.g. Population C: 157 closed round trips from its own
episode set (`ENTERED` dispositions), **exactly** `A(10) + B(147) = 157`,
confirming no double-counting and no leakage between the disjoint A/B
runs. This directly answers "do not compare 170 episodes directly with
10 executed trades": Task 116's originally-published N=170 was an
**episode** count (includes `SKIPPED_*` non-executed dispositions); the
executed-trade counts here (A=10, B=147, C=157) are BUY/SELL **pairs**
only, the comparable unit to A's already-published 10.

**This comparison is exploratory, not an untouched holdout validation** —
the 39-name scope was selected retrospectively (today's live watchlist),
not pre-registered against this specific historical window.

## Part 2 — comparability of existing vs. new artifacts

Population A reuses the existing, already-published artifact (Task 118
Deliverable A) verbatim — it satisfies the matched contract exactly (same
script family, same runtime, same window). **Populations B and C were run
as fresh, independent replays** (not derived by filtering A's or a
combined ledger) specifically because capital constraints, concurrency,
and cooldown dynamics are population-specific and cannot be safely
inferred by filtering a differently-scoped trade list. Verified directly:
at $10,000,000 starting cash and $10,000/position sizing, **no run (A, B,
or C) was ever capacity-constrained** — trivially confirmed since even
B's 147 trades' maximum plausible concurrent exposure is far below the
starting capital (each position is 0.1% of the book).

Sanitized trade tables: `reconciliation/trades_B.csv` (147 rows),
`reconciliation/trades_C.csv` (157 rows), alongside the existing
`reconciliation/trades.csv` (A, 10 rows) — episode id, symbol, entry/exit
price, net return, net P&L per row, identical schema to A's already-
published table.

## Part 3 — economic comparison and uncertainty

### Point estimates

| population | closed trades | distinct issuers | net expectancy (mean) | profit factor | win rate |
|---|---:|---:|---:|---:|---:|
| **A** (known baseline, reconfirmed) | 10 | 6 | **−2.926%** | **0.315** | **30%** |
| **B** | 147 | 101 | **+2.154%** | **2.258** | **63.9%** |
| **C** (A∪B) | 157 | 107 | **+1.831%** | **1.976** | **61.8%** |

A's figures reconfirmed, not blindly copied: net closed-trade P&L
**−$2,926.15** (10 × $10,000 notional at −2.926% mean), matching every
prior Task 118/118A/118B report exactly.

### Corrected equity/drawdown (daily marked, not `portfolio_cash_after`)

Only computed for A (the only population with an already-published,
verified daily equity series — `TASK118B_EQUITY_RECONCILIATION.md`):
real mark-to-market max drawdown **−$7,132.76** (**−0.0713%** on the
$10m book). B/C daily equity curves were not separately reconstructed
here (147/157-trade daily mark-to-market builds are a materially larger
undertaking; not attempted in this bounded session) — **portfolio-level
drawdown for B/C is explicitly UNAVAILABLE**, not substituted with
`portfolio_cash_after` or a summed-return proxy.

### Uncertainty — issuer-block bootstrap, per-trade net expectancy estimand

Method: block bootstrap resampling **issuers** (not individual trades) —
preserves issuer-repetition dependence (MSTR alone is 4/10 of A's
trades). Seed `118118`, 5,000 repetitions, 95% percentile interval.
Script: `results/task118_profitability/bootstrap_comparison.py`
(checked in), output: `reconciliation/bootstrap_comparison.json`.

| | issuer blocks | 95% CI on mean net expectancy |
|---|---:|---|
| A | 6 | **[−7.06%, +2.64%]** — includes zero |
| B | 101 | **[+0.94%, +3.48%]** — entirely positive |
| C (joint) | 107 | **[+0.54%, +3.17%]** — entirely positive |

**A's own interval is inconclusive** (includes zero) — consistent with
Task 118B's corrected protocol; A's small, issuer-concentrated sample
does not by itself support a claim of negative expectancy for this scope.

**A minus B (independent resampling, disjoint populations)**: mean
difference **−4.50 percentage points**, 95% CI **[−9.48%, +0.76%]** —
**the interval includes zero, marginally** (upper bound +0.76%). Per this
task's explicit instruction, **A's own negative interval is not, by
itself, treated as evidence of relative underperformance** — the actual
difference interval is reported here directly, and it **does not
conclusively separate A from B at 95%**, even though the point estimate
is solidly negative and B's own interval excludes zero. This is reported
as a **marginal, not statistically decisive** difference.

**A minus C (joint resampling, C ⊇ A — shared observations preserved,
not treated as independent)**: mean difference **−4.12 percentage
points**, 95% CI **[−9.19%, +1.06%]** — same pattern, same caveat.

**Explicit caveat carried in every A-involving result**: A has only **6**
distinct issuer blocks. A 6-block bootstrap has very few distinct
achievable resample configurations — **too few independent groups for a
well-powered inference**, stated per this task's own allowance rather
than glossed over. Every A-involving interval above should be read as
indicative, not decisive.

### Concentration sensitivity — reported, never substituted for the primary result

MSTR remains 64% of A's absolute closed-trade P&L (unchanged from Task
118, Part 2C). **The complete 10-trade population stays primary
throughout this report** — no result above removes MSTR, and none is
recommended to.

## Part 4 — what this supports for the product

- **Rare opportunities in the configured scope**: confirmed, unchanged —
  A produced only 10 trades across 19 months; nothing in this comparison
  changes that fact or offers a way around it.
- **Observed negative results vs. uncertainty**: A's point estimate is
  negative and its own bootstrap interval includes zero — both are true
  simultaneously; neither cancels the other. The scope has not been shown
  to be profitable, and has not been shown to be unprofitable at 95%
  confidence either.
- **Does scope composition plausibly explain the broader-panel
  difference?** B (the broader panel, matched runtime, N=147, 101
  issuers) shows a credibly positive expectancy interval, while A does
  not — but the **direct A-vs-B difference interval only marginally
  includes zero**, meaning this comparison is **suggestive that scope
  composition matters, not conclusive proof** at A's current sample size.
- **What remains unsupported**: any claim that the 39-name scope
  specifically underperforms (or matches) the broader panel with
  statistical confidence; any claim about *why* a scope difference might
  exist (index membership, size/liquidity screens, sector mix — not
  investigated here).

**A broader panel's positive performance does not authorize expanding
the live watchlist** — not proposed, not implied. **More alerts do not
establish a profitable strategy** — irrelevant to this comparison, which
is about V2 closed-trade economics, not alert volume.

## One recommended next analysis

**Investigate *why* A and the broader panel (B) differ in composition —
specifically, whether A's 6 traded issuers (and especially MSTR, its
dominant contributor) share an observable characteristic (sector,
market-cap tier, historical volatility regime) that differs systematically
from B's 101 issuers**, using data already collected here (the B/C trade
tables + each symbol's own price series) — no new backtest, no new data
collection, no live wait required.

- **Causal rationale**: if A's issuers are systematically higher-beta or
  concentrated in one sector/theme (MSTR being the clearest single
  example), that is a testable, specific hypothesis for *why* the
  difference might be real rather than noise — stronger than treating the
  A-vs-B gap as unexplained.
- **Relationship to prior research**: distinct from the already-closed
  cross-sectional/momentum spaces (Task 95E/95G) — this is a
  **composition-characteristic** question about the *scope*, not a new
  signal-discovery search.
- **Fixed scope/procedure**: compare A's 6 issuers' pre-trade
  volatility/sector profile against B's 101, using already-available bar
  data; no threshold or strategy change.
- **What would reject it**: if A's issuers show no systematic difference
  from a random 6-issuer draw from B (testable via the same issuer-block
  bootstrap machinery, drawing random 6-issuer subsets of B and comparing
  their expectancy distribution to A's), the "scope composition"
  explanation is not supported, and the A-vs-B difference should be
  treated as more likely sampling noise at small N.
- **Expected deliverable**: a short, bounded comparison document — not a
  new backtest, not a new strategy candidate.

**No evidence gap requires new data collection for this specific next
step** — it uses only already-collected trade/price data. Waiting for
more live A-scope trades remains a separate, much slower track (Task
118B's protocol, ≈57 months for raw N=30), explicitly **not** the entire
programme.

## Reproducible scripts and manifest

`results/task118_profitability/run_populations_bc.py` (B/C replay),
`bootstrap_comparison.py` (uncertainty), both checked in.
`reconciliation/population_manifest.json` (exact membership lists, the 6
names absent from Task 116's panel, the constructed C/B lists),
`reconciliation/trades_{B,C}.csv`, `reconciliation/bootstrap_comparison.json`
— all checked in, sanitized (no account/API identifiers).

## Evidence

`results/task118_profitability/baseline_{B,C}_summary.json` (checked in),
`replay_v2_lane_{B,C}.db` (gitignored, local — hashes on request, same
convention as A's already-documented artifacts).
