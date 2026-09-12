# Product status (authoritative, updated 2026-09-12 / Task 120A–C)

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
| Experimental | intraday (relaxed gates) | Task 93's own volatility-only counterfactual suggests ~zero edge at a relaxed threshold, but the exact combined `EXPERIMENTAL_RELAXED_V1` contract has never been backtested; only a 5-trade live sample exists (already labelled, not a track record) | `INSUFFICIENT_EVIDENCE` — one specific, already-infrastructure-backed next action identified (Task 93's dataset + harness, Experimental's exact gate combination) |
| V2 | medium (10-trading-day hold) | 39-name live scope, full available history (2019–2026), chronological replay (the real `V2Service.tick()`), N=57, 19 distinct issuers, net@20bps=−0.85%, 95% CI=[−4.57%, +1.11%] — includes zero | `INCONCLUSIVE` (not negative, not positive — genuinely underdetermined at current evidence) |
| V2 | broad 620-name panel (not the live scope) | N=170 (Task 115/116) / N=756 (Task 112R), net@20bps positive, CIs exclude zero | positive, but this is a **different population** than the live 39-name scope and does not transfer automatically |

## Informational lane

Intelligence (filings/earnings/insider-significance delivery) is useful
information, **not** trading profitability — never relabelled a BUY/SELL
recommendation anywhere in this product.

## What this page is not

Not a claim that every possible free-data strategy has been exhausted —
Experimental's exact relaxed contract specifically remains open, named
above as the next concrete research action. Not a recommendation to wait
years for more V2 live entries as the sole programme — the 39-name-scope
question has now been answered at N=57 (properly powered, still
inconclusive), and the smallest next actions for both open questions
(V2's price-coverage-complete re-run, already unnecessary post-correction;
Experimental's exact-contract backtest) are both named, bounded, and
reuse existing infrastructure.

## Full evidence

`docs/research/TASK120ABC_CORRECTED_BASELINE_AND_DECISION.md` (this
task); `docs/research/PRODUCT_REQUIREMENTS_AND_NEXT_DECISION.md` (Task
118H, requirement-to-capability table); `results/task93_alpha_foundation/FINAL_REPORT.md`
(release worktree, Original's exact-contract evidence).
