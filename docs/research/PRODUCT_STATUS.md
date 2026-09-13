# Product status (authoritative, updated 2026-09-13 / Task 123)

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
| Overnight attention — daily association | non-actionable, research finding only | **Resolved (Task 123)**: 38 active configured tickers, full available history, N=2,557 triggers/1,905 dates, incremental (trigger-minus-control) net **+0.1687%/event**, date-block-bootstrap 95% CI **[+0.0295%,+0.3085%]** — excludes zero, robust to 2 sensitivities | **`ASSOCIATION_SUPPORTED`** (qualified — CI's lower bound does not fully clear the predeclared ±10bps materiality band) — a real, disclosed research finding, **not actionable**: it depends on same-day final volume, only known at/after that day's own close |
| Overnight attention — actionable pre-close candidate | EOD alert, 15:50 ET decision | **Resolved (Task 123)**: 12 symbols with existing 1-min coverage, common 7-month window, N=31 triggers, incremental net **−0.5504%/event**, 95% CI **[−2.14%,+1.21%]** — includes zero, small-sample-limited | **`NOT_SUPPORTED_UNDER_TESTED_CONTRACT`** — closed as an actionable candidate on currently available data; exact missing input named (broader/longer intraday coverage), not pursued |

## Informational lane

Intelligence (filings/earnings/insider-significance delivery) is useful
information, **not** trading profitability — never relabelled a BUY/SELL
recommendation anywhere in this product.

## What this page is not

Not a claim that every possible free-data strategy has been exhausted —
Task 122's shortlist still names two untouched hypotheses (52-week-high
proximity; turn-of-month), and the overnight-attention DAILY association
itself (Task 123) is a genuine, positive, disclosed research finding —
what closed is only the ONE specific pre-close actionable mechanism
tested, not the whole space. Not a claim that N=57 (V2, live scope) or
N=227 (Experimental, full history) is
"properly powered" in a formal statistical-power sense — neither figure
carries that description anywhere in this research program as of Task
121/122's own wording corrections; both are reported as completed,
correctly-engineered computations whose INFERENCE remains inconclusive
at 95% confidence, not as adequately-powered-and-still-negative results.
Not a recommendation to wait years for more V2 live entries as the sole
programme, and not a recommendation to keep re-testing the now-archived
Experimental contract on its now-exhausted historical dataset.

## Full evidence

`docs/research/TASK123_OVERNIGHT_ATTENTION_RESULTS.md` (this task —
overnight-attention diagnostic + actionable-candidate closure);
`docs/research/TASK122_CANDIDATE_DECISION.md` (Experimental
closure + new-candidate selection); `docs/research/TASK121B_EXTENDED_EXPERIMENTAL_RESULTS.md`
(Experimental's full-history result); `docs/research/TASK120ABC_CORRECTED_BASELINE_AND_DECISION.md`
(V2's 39-name-scope result); `docs/research/PRODUCT_REQUIREMENTS_AND_NEXT_DECISION.md`
(Task 118H, requirement-to-capability table); `results/task93_alpha_foundation/FINAL_REPORT.md`
(release worktree, Original's exact-contract evidence).
