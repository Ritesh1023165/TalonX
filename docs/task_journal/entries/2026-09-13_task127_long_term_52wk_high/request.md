# Request

Verbatim user request (2026-09-13), immediately following Task 126's
product-fit gate closure:

> TASK127 — LONG-TERM PRODUCT CONTRACT AND ONE 52-WEEK-HIGH EVALUATION
>
> OBJECTIVE
> Correct Task126's unsupported product restrictions, then define and
> evaluate one source-grounded, long-only 52-week-high candidate for
> TalonX's long-term paper-alert lane.
>
> Complete contract definition → data validation → evaluation →
> economic decision in this task where feasible. Do not stop merely
> because the current application lacks a multi-month strategy.
>
> BASELINE
> Research branch: research/talonx-profitability-2026-09
> Expected HEAD: 7c8bcabc362f06dd5d339773475bd6ccd6a7c976
> Release branch: research/talonx-strategy-validation
> Expected HEAD: f28986999eec5e313cfc89db24e4dbacfb378891
> Verify actual SHAs and preserve unrelated changes.
>
> AUTHORIZATION AND PRODUCT INTENT
> The user's product includes configured tickers, intraday and
> short/long-term alerts, and local paper portfolios. This task
> authorizes a research-only multi-month holding contract. Its exact
> implementation is a research candidate, not an approved production
> strategy. No real capital, shorts, broker activity, external
> messages, production launch, live configuration changes, paid data,
> or release merge. Preserve Redis, production ledgers, and SPCX
> obligations.
>
> 1. CORRECT THE PRODUCT RECORD — append dated corrections to Task126
>    without deleting its original conclusions: absence of a current
>    multi-month strategy is not a prohibition on long-term alerts;
>    paper positions do not lock the user's real capital, although
>    allocation and opportunity cost still matter within a simulated
>    portfolio; ticker-specific differentiation was not an explicit
>    user requirement — turn-of-month was not economically evaluated
>    or disproven; "full coverage" requires a named ticker population
>    and date range; corporate-action handling must be verified rather
>    than described as trivial. Do not evaluate turn-of-month in this
>    task. Update the product contract concisely: long-term
>    opportunities may use a multi-month research horizon; BUY/SELL
>    alerts must have a defined decision/entry/holding-review/exit
>    policy; SELL closes an existing long, no shorting; an evaluation
>    does not authorize live deployment or promise profitability.
>
> 2. VERIFY THE ORIGINAL MECHANISM AND PRIOR RESEARCH — read the
>    original George-Hwang research using primary sources, verify its
>    actual formation/ranking/holding/portfolio construction rather
>    than inheriting Task126's description. Review TalonX's prior
>    momentum/52-week-high-related work (Task95B, rejection ledger).
>    Explain what the published result actually establishes, how this
>    candidate differs from previously evaluated TalonX contracts,
>    which changes are needed for a configured-universe long-only
>    implementation, and why those changes remain a coherent
>    hypothesis. A published long-short spread is not evidence its
>    long leg will outperform an appropriate long-only benchmark. If
>    an economically equivalent contract was already evaluated
>    reliably, reuse that evidence and reach a decision — do not rerun
>    it under a new task name.
>
> 3. FREEZE ONE CONTRACT BEFORE INSPECTING RETURNS — select exactly
>    one source-grounded long-only adaptation, no searching alternative
>    thresholds/fractions/lookbacks/horizons. Define and commit: exact
>    configured active-ticker universe and membership snapshot;
>    historical-universe/survivorship limitations; data sources, date
>    window, pre-roll; exact 52-week-high proximity formula; ranking/
>    selection rule and minimum eligible population; decision schedule
>    and information available then; earliest causal reference entry;
>    one source-grounded holding/review period; exit/repeat-selection
>    rules; overlapping-cohort/existing-position treatment; position
>    sizing/capital budget/allocation limits; missing prices/
>    insufficient history/delistings/splits/dividends; costs + one
>    predeclared adverse-cost sensitivity; benchmarks/estimand/
>    uncertainty/materiality; separate statistical/product acceptance
>    criteria. If several implementation choices are reasonable, select
>    one using the source and product simplicity before outcomes;
>    record the reasoning, no approval requests for routine research
>    choices. Do not shorten the published horizon to increase trade
>    counts. All historical results remain exploratory unless a
>    genuinely unexamined evaluation period can be established.
>
> 4. VALIDATE COVERAGE AND CORPORATE ACTIONS — inventory the exact
>    study population; report configured/active/covered/eligible/
>    excluded counts, coverage dates by ticker, missing/pre-listing
>    periods, adjustment conventions, corporate-action availability,
>    source precedence. Do not silently replace missing tickers,
>    broaden the universe, or claim historical point-in-time membership
>    from today's watchlist. Ensure rolling highs use only information
>    available at the decision; selection occurs before the reference
>    fill; splits do not create false proximity signals; dividend
>    treatment is consistent between strategy and benchmark and not
>    double-counted; missing/delisted positions are not dropped to
>    improve results; unresolved valuations remain explicit. Label any
>    retrospective total-return-proxy limitation and assess materiality.
>
> 5. BUILD THE SMALLEST CORRECT EVALUATION — reuse existing
>    infrastructure, efficient daily/session-level processing, no
>    intraday QuantScanner. Add focused tests for causal rolling-high/
>    ranking, decision-to-entry timing, holding/exit dates, repeated
>    selection/overlapping cohorts, capital allocation, costs/
>    corporate actions, missing-data behavior, cash/positions/equity
>    reconciliation. Chronological capital accounting if reporting
>    portfolio returns — no summing overlapping event returns as
>    portfolio performance. Keep signal decisions, simulated fills, and
>    eventual notification feasibility conceptually separate.
>
> 6. RUN ONE FROZEN EVALUATION — report eligible dates/issuers,
>    selection events/entries/exits/ending open positions, holding
>    periods/capital utilization, gross/net P&L, ending marked equity
>    and reconciled cash/position values, marked-equity drawdown,
>    turnover/cost sensitivity, win rate/loss tails/concentration,
>    predeclared period breakdowns. Compare against a simple long-only
>    benchmark (same eligible universe, comparable capital/exposure)
>    and an appropriate market benchmark where data supports it. State
>    what each comparison measures; do not attribute ordinary market
>    exposure to the selection rule. Use uncertainty methods
>    acknowledging overlapping multi-month holdings and common market
>    dates — trade count is not independent-observation count. No
>    "properly powered" claim from an arbitrary sample-size threshold.
>
> 7. MAKE THE ECONOMIC DECISION — Statistical:
>    SUPPORTS_PREDECLARED_EFFECT / DOES_NOT_SUPPORT_PREDECLARED_EFFECT
>    / INCONCLUSIVE. Product: ADVANCE_TO_FURTHER_VALIDATION /
>    DO_NOT_ADVANCE / BLOCKED_BY_SPECIFIC_EVIDENCE_REQUIREMENT.
>    Positive absolute returns during a rising market alone do not
>    justify a more complex selection strategy. Apply the frozen
>    criteria without changing them after the run. ADVANCE means a
>    subsequent validation step, not live activation. If negative or
>    inadequate, archive this exact contract. If inconclusive, identify
>    the specific uncertainty and whether resolving it is practical. Do
>    not automatically propose another parameter variation, ticker
>    subset, shorter holding period, or indefinite live-observation
>    programme. Return one next action or an explicit stop decision.
>
> 8. JOURNAL AND PUBLISH — record this exact prompt, starting/final
>    SHAs, product corrections, source interpretation and prior-
>    research comparison, protocol-freeze commit, data provenance and
>    prior exposure, tests, results, limitations, decision. Publish
>    TASK127_PRODUCT_CONTRACT_CORRECTIONS.md,
>    TASK127_FROZEN_LONG_TERM_PROTOCOL.md,
>    TASK127_LONG_TERM_ECONOMIC_DECISION.md, compact machine-readable
>    evidence, relevant evaluation code and focused tests, updated
>    PRODUCT_STATUS.md and research ledger. Keep credentials,
>    databases, bulk market data, and caches out of Git. Commit and
>    push normally to the research branch. Intermediate checkpoint
>    commits are allowed. Do not merge into release/main.
>
> FINAL RESPONSE: 1. Statistical and product verdicts. 2. Starting/
> final SHAs and push result. 3. Product corrections and source-
> grounded adaptation. 4. Exact signal, holding period, and causal
> execution model. 5. Coverage, costs, and corporate-action
> limitations. 6. Absolute and benchmark-relative portfolio economics.
> 7. Uncertainty, concentration, and drawdown. 8. One next action or
> stop decision. 9. Production preservation and process cleanup. 10.
> Journal, frozen protocol, results, and evidence links.
>
> Priority: correct product intent → one frozen long-term contract →
> complete economic evaluation → decision. No unrelated dashboard or
> operational work.
