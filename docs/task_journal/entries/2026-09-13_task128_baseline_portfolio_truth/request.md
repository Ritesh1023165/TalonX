# Request

Verbatim user request (2026-09-13), immediately following Task 127's
52-week-high evaluation closure:

> TASK128 — SIMPLE LONG-TERM BASELINE: PORTFOLIO TRUTH AND PRODUCT
> DECISION
>
> OBJECTIVE
> Determine whether Task127's simple no-selection benchmark merits
> further validation as a useful long-term paper-alert product. Use
> existing artifacts and data. Complete accounting verification,
> product assessment, and one decision in this task. This is not a new
> alpha hypothesis, a claim that passive exposure solves intraday
> trading, or permission to deploy.
>
> BASELINE
> Research branch: research/talonx-profitability-2026-09
> Expected HEAD: 671a07b2bc81f8fd246348985c9904ca268b1876
> Release branch: research/talonx-strategy-validation
> Expected HEAD: f28986999eec5e313cfc89db24e4dbacfb378891
> Verify actual state. Preserve unrelated changes.
>
> Research-only authorization: read existing artifacts and datasets;
> perform necessary isolated portfolio calculations; write focused
> tests, reports, journal entries, and normal research commits/pushes.
> No paid data, external messages, broker calls, application launch,
> production configuration changes, release merge, or strategy
> promotion. Preserve production ledgers, Redis, and outstanding SPCX
> obligations.
>
> 1. CLOSE TASK127 WITH PRECISE LANGUAGE — append dated corrections
>    without rerunning its selection strategy: "adds no value" becomes
>    "did not demonstrate added value in this evaluation"; non-
>    overlapping blocks are not proven statistically independent;
>    positive performance during a rising market does not by itself
>    establish beta attribution; full-period SPY returns and six-month
>    cohort returns are not directly comparable metrics. Keep the
>    52-week-high contract DO_NOT_ADVANCE.
>
> 2. IDENTIFY THE ACTUAL BASELINE — read Task127's benchmark code,
>    frozen protocol, and stored results. Document exactly:
>    eligibility/historical ticker population, formation schedule,
>    weighting, six-month holding/exit behavior, overlapping cohorts,
>    starting capital and capital allocation, costs and dividend
>    treatment, missing-data rules. Determine whether the reported
>    +13.70% is an average cohort return, a portfolio return, or
>    another estimand. Do not silently turn the existing benchmark
>    into a buy-and-hold or monthly-rebalanced strategy — different
>    contracts. If chronological portfolio artifacts already exist and
>    are correct, reuse them; otherwise construct the smallest faithful
>    chronological implementation needed to assess the existing
>    benchmark.
>
> 3. FREEZE THE ASSESSMENT BEFORE NEW CALCULATIONS — commit a short
>    assessment protocol specifying: exact existing baseline contract;
>    evaluation dates/pre-roll; research starting capital, clearly
>    separate from the production V2 campaign; capital allocation
>    across overlapping cohorts; cash-awaiting-investment treatment;
>    costs and the existing adverse-cost sensitivity; fractional
>    shares, dividend accounting, corporate actions; missing prices and
>    unresolved positions; same-period comparator; output metrics and
>    decision criteria. Do not optimize weighting/rebalance frequency/
>    holding period/ticker composition. The purpose is to establish
>    what the baseline delivers and whether that is useful — not to
>    maximize its backtest.
>
> 4. RECONCILE A REAL CHRONOLOGICAL PORTFOLIO — require: no reuse of
>    capital already committed to another cohort; no implicit leverage
>    or negative cash; causal decisions/subsequent reference fills;
>    explicit simultaneous entry/exit treatment; timestamped marks for
>    open positions; cash+marked=equity; costs applied exactly once; no
>    forced liquidation solely to make the report flat. Report:
>    starting/ending equity; realized/unrealized P&L; gross vs. cost-
>    adjusted; total and annualized return over the actual elapsed
>    period; daily marked-equity drawdown and recovery duration;
>    capital utilization/turnover; open positions/unresolved
>    valuations; contribution by issuer and period. Label a synthetic
>    total-return portfolio if adjustment=all only permits that — no
>    double-counted dividends, no claiming adjusted units are actual
>    executable shares. Do not derive portfolio performance by summing/
>    averaging overlapping cohort returns.
>
> 5. MAKE THE COMPARISON FAIR — where data supports it, compare with a
>    simple broad-market reference over identical dates using
>    consistent initial capital, cash deployment timing, dividend
>    treatment, costs, valuation frequency. If capital deployment
>    differs, disclose it and distinguish allocation effects from
>    selection effects. Do not claim alpha from positive absolute
>    returns. Do not require outperformance merely to be useful — but
>    explicitly assess whether the added complexity provides a user
>    benefit.
>
> 6. AUDIT RETROSPECTIVE WATCHLIST BIAS — trace available watchlist
>    history. Distinguish verified historical membership, today's
>    watchlist projected backward, pre-listing exclusions, missing/
>    delisted names, data-availability-driven exclusions. Use existing
>    contribution tables and dated membership evidence. Do not remove
>    names after seeing outcomes. If survivorship bias cannot be
>    quantified, state that directly — do not invent a point-in-time
>    universe or holdout. Do not start a broad historical-membership
>    reconstruction project.
>
> 7. DEFINE THE USER-VISIBLE PRODUCT HONESTLY — describe the smallest
>    faithful paper-alert journey: what causes an initial allocation
>    recommendation, what prompts a scheduled review, what causes a
>    rebalance/exit, expected alert frequency from the frozen schedule,
>    what information each alert contains, how the paper portfolio/
>    dashboard would represent it. Distinguish scheduled allocation/
>    review notifications from evidence-based bullish/bearish
>    forecasts — do not manufacture directional conviction. Assess:
>    does this help manage configured long-term tickers; is it
>    materially more useful than a simple tracker; is the multi-month
>    commitment and drawdown visible; can it coexist with the
>    unresolved intraday goal without being presented as its solution.
>    Specification only — no dashboard/Telegram implementation.
>
> 8. ISSUE A BOUNDED PRODUCT DECISION —
>    BASELINE_READY_FOR_FORWARD_PAPER_VALIDATION /
>    USEFUL_AS_TRACKING_BENCHMARK_ONLY / DO_NOT_ADVANCE /
>    BLOCKED_BY_SPECIFIC_ACCOUNTING_OR_DATA_LIMITATION. Keep historical
>    economic evidence separate from product usefulness. READY means a
>    concrete candidate for later activation review, not launch
>    approval. If READY: one fixed forward-validation contract,
>    operational vs. economic acceptance stated separately, what can be
>    learned promptly vs. requires a full holding period, no promise of
>    rapid statistical confirmation. If not READY: identify the exact
>    reason, one next decision or explicit stop — no automatic new
>    parameter search/literature shortlist/indefinite live waiting.
>
> 9. JOURNAL AND PUBLISH — record this exact prompt, SHAs, protocol
>    freeze, calculations, corrections, limitations, decision. Publish
>    TASK128_BASELINE_CONTRACT_AND_ACCOUNTING.md,
>    TASK128_BASELINE_PRODUCT_DECISION.md, compact machine-readable
>    portfolio reconciliation/results, relevant isolated code and
>    focused tests, updated PRODUCT_STATUS.md and research ledger. Keep
>    bulk data/credentials/caches/production databases out of Git.
>    Commit and push normally to the research branch. No release/main
>    merge.
>
> FINAL RESPONSE: 1. Product verdict and historical-evidence
> limitations. 2. Starting/final SHAs and push result. 3. Exact
> baseline contract and meaning of the original +13.70%. 4.
> Chronological equity, costs, drawdown, and open-position
> reconciliation. 5. Fair benchmark comparison. 6. Historical-
> membership and coverage limitations. 7. Concrete alert journey and
> its usefulness. 8. One next action or stop decision. 9. Production
> preservation and process cleanup. 10. Journal, reports, code, and
> evidence links.
>
> Priority: establish portfolio truth → assess user value → make one
> decision. No new strategy tuning or application-polishing cycle.
