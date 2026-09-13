# Product status (authoritative, updated 2026-09-13 / Task 130B)

**Programme decision (Task 129): `PAUSE_ALPHA_RESEARCH_UNDER_CURRENT_CONSTRAINTS`**
— see `docs/research/TASK129_RESEARCH_PROGRAM_DECISION.md` and
`TASK129_EVIDENCE_MATRIX.csv`. **Task 130/130A/130B are the user's own
explicit, bounded exception to that pause (Option A: broader V2
discovery)** — it does not reopen the paused free price/volume alpha
space; it extends the ALREADY-`INCONCLUSIVE`-not-rejected
V2/insider-cluster mechanism to a larger, evidence-anchored universe.
Result: **`PASS_FOR_INTEGRATION_REVIEW`** (N=153, net +2.02%/round
trip, both uncertainty methods exclude zero, now on a durable,
session-phased, accession-level-identity-verified implementation) —
see
`docs/research/{TASK130B_QUALIFICATION_ADDENDUM,TASK130B_DURABLE_LIFECYCLE_ACCEPTANCE,TASK130B_CORRECTED_ECONOMIC_DECISION}.md`.
Not a deployment recommendation; integration remains HOLD; the
alpha-research pause otherwise remains in effect for every other
mechanism on this page.

**User objective, unchanged**: configured tickers with intraday and
short/long-horizon alerts, and attributable local paper portfolios.
**Positive aggregate economics is the goal — informational delivery
alone is not success**, and earlier descriptive-product decisions
(Task 96H's "Risk & Event Intelligence" framing) do not override this
latest, explicit user goal. **Long-term opportunities may use a
multi-month research horizon** (Task 127) — the absence of a currently
PASSING multi-month strategy is not a prohibition on testing one; every
BUY/SELL alert contract, short or long horizon, states an explicit
decision/entry/holding-review/exit policy, and SELL only closes an
existing long (no shorting anywhere in this product). An evaluation
never authorizes live deployment or promises profitability.

## Current strategy support by horizon

| lane | horizon | economic evidence | status |
|---|---|---|---|
| Original | intraday | Task 93: current frozen contract (`2ae6216bca70`, unchanged, verified live) fires **1 trade in ~18.7 months** across 35–45 symbols — no sample to evaluate | `INSUFFICIENT_EVIDENCE` (not rejected — no negative-edge evidence exists; not supported — no sample exists) |
| Experimental | intraday (relaxed gates) | **Resolved (Task 121A/121B, 2026-09-12/13)**: the exact `EXPERIMENTAL_RELAXED_V1` contract, corrected exit lifecycle (no EOD flatten, no bearish-close — verified against the release source), full available history (2019-06→2025-08, N=227, 35 issuers): gross P&L **−$612.92** (negative before cost), net **−$896.44**, PF 0.764, win rate 19.4%, 95% CI **[−$8.94,+$1.06]/trade** (does not clear the predeclared ±$1.25 materiality band either way) | `INSUFFICIENT_EVIDENCE` (statistical) / **`DO_NOT_ADVANCE_CURRENT_EXPERIMENTAL_CONTRACT`** (product, Task 122) — archived as an internal research baseline; same-population historical data exhausted; not scheduled for further backtesting |
| V2 | medium (10-trading-day hold) | 39-name live scope, full available history (2019–2026), chronological replay (the real `V2Service.tick()`), N=57, 19 distinct issuers, net@20bps=−0.85%, 95% CI=[−4.57%, +1.11%] — includes zero | `INCONCLUSIVE` (not negative, not positive — genuinely underdetermined at current evidence) |
| V2 | broad 620-name panel (not the live scope) | N=170 (Task 115/116) / N=756 (Task 112R), net@20bps positive, CIs exclude zero | positive, but this is a **different population** than the live 39-name scope and does not transfer automatically |
| V2 | **Discovery Universe v1, 626 names (Task 130, corrected Task 130A, re-verified durable Task 130B)** | durable, `V2Store`-backed, explicitly session-phased (OPEN/CLOSE/POST-CLOSE/MARK) $300k/20-slot isolated replay: N=153, 106 issuers, net@20bps=**+2.02%**/round trip, issuer-block 95% CI **[+0.72%,+3.40%]** and date-block 95% CI **[+0.57%,+3.46%]** — both exclude zero and agree; episode-for-episode IDENTICAL to Task 130A's own result (explained: capacity was never binding in this window under either implementation, not assumed); original trade-count-ranked AND supplemental P&L-ranked issuer-removal sensitivities both stay positive through top-5; 3 of 4 calendar half-years independently positive (2026H1 negative); **true daily mark-to-market drawdown −2.75%** (not recovered within study window; 0 open/0 unresolved after a 20-session settlement tail); invested-capital/equity exposure ratio now computed (12.07%, distinct from 89.62% day-occupancy); all 8 traded ambiguous-CIK symbols `VERIFIED_CONSISTENT` via exact accession-level evidence chains (not a date-range proxy; 11/35 total symbols remain genuinely unresolved, disclosed, none traded); 10/10 real-SQLite failure-path/durability tests pass (crash/reopen, missing-price bounded retry, capacity/cooldown edge cases) | **`PASS_FOR_INTEGRATION_REVIEW`** — a candidate for a LATER, separately-authorized activation-review task; NOT a deployment recommendation; the broader alpha-research pause (Task 129) is otherwise unaffected; integration remains HOLD |
| Overnight attention — daily association | non-actionable, research finding only | **Resolved (Task 123)**: 38 active configured tickers, full available history, N=2,557 triggers/1,905 dates, incremental (trigger-minus-control) net **+0.1687%/event**, date-block-bootstrap 95% CI **[+0.0295%,+0.3085%]** — excludes zero, robust to 2 sensitivities | **`ASSOCIATION_SUPPORTED`** (qualified — CI's lower bound does not fully clear the predeclared ±10bps materiality band) — a real, disclosed research finding, **not actionable**: it depends on same-day final volume, only known at/after that day's own close |
| Overnight attention — actionable pre-close candidate | EOD alert, 15:50 ET decision | **CLOSED (Task 125, extended)**: same frozen contract, 12-symbol primary cohort extended from 7 months/N=31/100 dates to **2.5 years/N=3,201 eligible/158 triggers/542 distinct dates** on independently re-acquired, feed-verified SIP data (feed identity resolved: `task93_canonical_v1` confirmed SIP, not IEX). Incremental net **−0.2284%/event**, 95% CI **[−0.79%,+0.35%]** — includes zero; absolute trigger net return also negative (−0.1196%); negative in all 3 calendar years tested. A +3-symbol added cohort (BABA/SHOP/SPCX) showed a small positive but 58%-single-issuer-concentrated, non-year-stable reading (n=31) that does not change the primary verdict. Correctness check: the original 2025 sub-window re-evaluated on the new data reproduces Task 123's exact original numbers bit-for-bit | Statistical **`INCONCLUSIVE`** / Product **`DO_NOT_ADVANCE`** — closed on a materially larger, multi-year, feed-verified dataset; not scheduled for further reruns of this contract |
| Overnight attention — data-extension feasibility | data question only, no returns computed | **Resolved (Task 124), executed (Task 125)**: existing free Alpaca SIP access, already used in this program, verified (small probes, not mere documentation) to retain 1-min history to at least 2020-03-02; the concrete extension it specified (12 symbols back to 2023-01-01 + BABA/SHOP/SPCX) was acquired and evaluated in Task 125 (60/60 partitions, 0 failures) | **`DATA_EXTENSION_FEASIBLE`** (Task 124) → **executed** (Task 125) — see row above for the resulting economic decision |
| 52-week-high proximity, long-only 6-month hold | multi-month research horizon, authorized (Task 127) | **RUN AND CLOSED (Task 127, corrected Task 128)**: tercile selection (top 30% by close/252-day-high) on the 38 active-covered configured tickers, monthly formation, Jegadeesh-Titman-style overlapping 6-month holds, source-grounded (George & Hwang 2004, verified from the primary record — tercile, not decile as previously described). Absolute net return strongly positive (+10.85%/6mo avg-cohort, CI [+6.25%,+15.99%]) but **consistent with** broad market exposure (no factor regression run): the passive eligible-universe benchmark (no selection at all) returned MORE (+13.70%/6mo avg-cohort). Incremental (selection vs. no-selection) net **−2.846%/6mo**, 95% CI **[−6.96%,+0.23%]** — includes zero, negative in 9/12 non-overlapping (not proven independent) 6-month blocks | Statistical **`INCONCLUSIVE`** / Product **`DO_NOT_ADVANCE`** — did not demonstrate added value over the no-selection benchmark in this evaluation |
| No-selection baseline (all-eligible, equal-weight, same 6-month overlapping contract) | tracking benchmark, not a differentiated alert | **Reconciled as a real chronological $100k portfolio for the first time (Task 128)** — the original +13.70% was an arithmetic mean of 68 cohort returns, not a portfolio return. True chronological result: ending equity $251,128.98, **total return +151.13%, annualized +12.77%**, max drawdown −19.58% (2022-01-03→2022-10-12, recovered in 528 days), 79.3% average capital utilization, 67/68 realized round trips (1 correctly skipped by the no-leverage guard). Same-capital, same-dates SPY comparison (fully invested day 1): +242.68% total / **+17.44% annualized**, max drawdown −33.79% (recovered in 173 days) — the baseline underperforms simple SPY buy-and-hold by ~4.7 points annualized | **`USEFUL_AS_TRACKING_BENCHMARK_ONLY`** — genuine, now-trustworthy research control for judging future long-term candidates; NOT productized as a standalone user-facing alert (no ticker differentiation, underperforms the simplest passive alternative) |
| Turn-of-month calendar effect | ~4-day calendar window | **Assessed, not run (Task 126)**: product-fit gate applied before any return was inspected — the mechanism structurally produces a common calendar-wide exposure identical across all 48 configured tickers, zero ticker-specific differentiation. Remains un-re-evaluated (Tasks 127/128 did not touch it, per explicit instruction) | **`DO_NOT_ADVANCE`** — rejected on structural product-fit grounds, not on statistical or economic evidence |

## Informational lane

Intelligence (filings/earnings/insider-significance delivery) is useful
information, **not** trading profitability — never relabelled a BUY/SELL
recommendation anywhere in this product.

## What this page is not

Not a claim that every possible free-data strategy has been exhausted —
Task 122's shortlist's other two hypotheses (52-week-high proximity;
turn-of-month) were both assessed on product-fit/mechanism grounds in
Task 126; 52-week-high was then corrected, source-verified, and
actually RUN in Task 127 (closed `DO_NOT_ADVANCE` on genuine
incremental-vs-benchmark evidence, not a product-fit block). Turn-of-
month remains un-re-evaluated — its `DO_NOT_ADVANCE` is a product-fit
judgment only, and it was never economically tested or disproven; it
remains re-visitable if the named product decision (accepting a
non-differentiating, calendar-wide alert type) is made. The
overnight-attention DAILY association itself (Task 123) is a genuine,
positive, disclosed research finding — what closed is only the ONE
specific pre-close actionable mechanism tested, not the whole space.
Not a claim that N=57 (V2, live scope) or N=227 (Experimental, full history) is
"properly powered" in a formal statistical-power sense — neither figure
carries that description anywhere in this research program as of Task
121/122's own wording corrections; both are reported as completed,
correctly-engineered computations whose INFERENCE remains inconclusive
at 95% confidence, not as adequately-powered-and-still-negative results.
Not a recommendation to wait years for more V2 live entries as the sole
programme, and not a recommendation to keep re-testing the now-archived
Experimental contract on its now-exhausted historical dataset.

## Full evidence

`docs/research/TASK130B_QUALIFICATION_ADDENDUM.md` +
`TASK130B_DURABLE_LIFECYCLE_ACCEPTANCE.md` + `TASK130B_CORRECTED_ECONOMIC_DECISION.md`
(most recent — accession-level identity evidence for all 8 traded
ambiguous symbols, a durable `V2Store`-backed session-phased replay
with 10/10 real-SQLite failure-path tests, and the full corrected
economics, `PASS_FOR_INTEGRATION_REVIEW`); `docs/research/TASK130A_REPAIR_PROTOCOL.md` +
`TASK130A_PROSPECTIVE_REPLAY_ACCEPTANCE.md` + `TASK130A_CORRECTED_ECONOMIC_DECISION.md`
(prior qualification repair — in-line gating, daily mark-to-market
drawdown); `docs/research/TASK130_OPTION_A_CONTRACT.md` +
`TASK130_FROZEN_EVALUATION_PROTOCOL.md` + `TASK130_OPTION_A_ECONOMIC_DECISION.md`
(original Option A resumption: Discovery Universe v1 four-tier
contract, frozen evaluation protocol, and one offline
$300k-capacity-constrained evaluation, superseded by the two
corrections above);
`docs/research/TASK129_RESEARCH_PROGRAM_DECISION.md` +
`TASK129_EVIDENCE_MATRIX.csv` (authoritative programme-level synthesis
and pause decision); `docs/research/TASK128_BASELINE_CONTRACT_AND_ACCOUNTING.md` +
`TASK128_BASELINE_PRODUCT_DECISION.md` (this task — corrects Task 127's
overclaimed language, builds the first real chronological portfolio
for the no-selection baseline, fair same-capital SPY comparison,
survivorship-bias audit, product specification, and bounded decision);
`docs/research/TASK127_PRODUCT_CONTRACT_CORRECTIONS.md` +
`TASK127_FROZEN_LONG_TERM_PROTOCOL.md` + `TASK127_LONG_TERM_ECONOMIC_DECISION.md`
(this task — corrects Task 126's product restrictions, source-verifies
George & Hwang 2004, freezes and runs one long-only 52-week-high
contract, closed `DO_NOT_ADVANCE`); `docs/research/TASK126_CANDIDATE_SELECTION.md` + `TASK126_ECONOMIC_DECISION.md`
(this task — product-fit gate applied to the two remaining Task 122
candidates, both blocked/rejected before any return was computed;
Task 125 correction record); `docs/research/TASK125_OVERNIGHT_ACTIONABLE_RESULTS.md` (prior task —
extended, feed-verified evaluation and closure of the overnight-
attention actionable candidate); `docs/research/TASK125_FROZEN_EXTENSION_PROTOCOL.md`
+ `TASK125_DATA_ACCEPTANCE.md` (this task's frozen protocol and data
acceptance); `docs/research/TASK124_INTRADAY_DATA_FEASIBILITY.md` (prior task — data-
extension feasibility for the overnight-attention actionable candidate,
no strategy return computed); `docs/research/TASK123_OVERNIGHT_ATTENTION_RESULTS.md` (prior task —
overnight-attention diagnostic + actionable-candidate closure);
`docs/research/TASK122_CANDIDATE_DECISION.md` (Experimental
closure + new-candidate selection); `docs/research/TASK121B_EXTENDED_EXPERIMENTAL_RESULTS.md`
(Experimental's full-history result); `docs/research/TASK120ABC_CORRECTED_BASELINE_AND_DECISION.md`
(V2's 39-name-scope result); `docs/research/PRODUCT_REQUIREMENTS_AND_NEXT_DECISION.md`
(Task 118H, requirement-to-capability table); `results/task93_alpha_foundation/FINAL_REPORT.md`
(release worktree, Original's exact-contract evidence).
