# Product status (authoritative, updated 2026-09-13 / Task 122)

**User objective, unchanged**: configured tickers with intraday and
short/long-horizon alerts, and attributable local paper portfolios.
**Positive aggregate economics is the goal — informational delivery
alone is not success**, and earlier descriptive-product decisions
(Task 96H's "Risk & Event Intelligence" framing) do not override this
latest, explicit user goal.

## Current strategy support by horizon

| lane | horizon | economic evidence | status |
|---|---|---|---|
| Original | intraday | Task 93: current frozen contract (`2ae6216bca70`, unchanged, verified live) fires **1 trade in ~18.7 months** across 35–45 symbols — no sample to evaluate | `INSUFFICIENT_EVIDENCE` (not rejected — no negative-edge evidence exists; not supported — no sample exists) |
| Experimental | intraday (relaxed gates) | **Resolved (Task 121A/121B, 2026-09-12/13)**: the exact `EXPERIMENTAL_RELAXED_V1` contract, corrected exit lifecycle (no EOD flatten, no bearish-close — verified against the release source), full available history (2019-06→2025-08, N=227, 35 issuers): gross P&L **−$612.92** (negative before cost), net **−$896.44**, PF 0.764, win rate 19.4%, 95% CI **[−$8.94,+$1.06]/trade** (does not clear the predeclared ±$1.25 materiality band either way) | `INSUFFICIENT_EVIDENCE` (statistical) / **`DO_NOT_ADVANCE_CURRENT_EXPERIMENTAL_CONTRACT`** (product, Task 122) — archived as an internal research baseline; same-population historical data exhausted; not scheduled for further backtesting |
| V2 | medium (10-trading-day hold) | 39-name live scope, full available history (2019–2026), chronological replay (the real `V2Service.tick()`), N=57, 19 distinct issuers, net@20bps=−0.85%, 95% CI=[−4.57%, +1.11%] — includes zero | `INCONCLUSIVE` (not negative, not positive — genuinely underdetermined at current evidence) |
| V2 | broad 620-name panel (not the live scope) | N=170 (Task 115/116) / N=756 (Task 112R), net@20bps positive, CIs exclude zero | positive, but this is a **different population** than the live 39-name scope and does not transfer automatically |
| **New candidate** (unevaluated) | overnight (close-to-open), EOD alert | Feasibility only (Task 122): 35/48 configured tickers have existing free daily-bar coverage; 2,447 volume-attention trigger events over 86 months, 0 zero-trigger months, 0 data-quality issues — no economic outcome computed yet | **`ONE_CANDIDATE_READY_FOR_FIXED_EVALUATION`** — fixed protocol frozen in `TASK122_CANDIDATE_DECISION.md`, not yet run |

## Informational lane

Intelligence (filings/earnings/insider-significance delivery) is useful
information, **not** trading profitability — never relabelled a BUY/SELL
recommendation anywhere in this product.

## What this page is not

Not a claim that every possible free-data strategy has been exhausted —
one new candidate (overnight/attention, Task 122) is specifically named
above with a frozen next-evaluation protocol, not exhausted. Not a claim
that N=57 (V2, live scope) or N=227 (Experimental, full history) is
"properly powered" in a formal statistical-power sense — neither figure
carries that description anywhere in this research program as of Task
121/122's own wording corrections; both are reported as completed,
correctly-engineered computations whose INFERENCE remains inconclusive
at 95% confidence, not as adequately-powered-and-still-negative results.
Not a recommendation to wait years for more V2 live entries as the sole
programme, and not a recommendation to keep re-testing the now-archived
Experimental contract on its now-exhausted historical dataset.

## Full evidence

`docs/research/TASK122_CANDIDATE_DECISION.md` (this task — Experimental
closure + new-candidate selection); `docs/research/TASK121B_EXTENDED_EXPERIMENTAL_RESULTS.md`
(Experimental's full-history result); `docs/research/TASK120ABC_CORRECTED_BASELINE_AND_DECISION.md`
(V2's 39-name-scope result); `docs/research/PRODUCT_REQUIREMENTS_AND_NEXT_DECISION.md`
(Task 118H, requirement-to-capability table); `results/task93_alpha_foundation/FINAL_REPORT.md`
(release worktree, Original's exact-contract evidence).
