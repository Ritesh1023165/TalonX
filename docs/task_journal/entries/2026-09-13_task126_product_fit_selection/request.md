# Request

Verbatim user request (2026-09-13), immediately following Task 125's
closure of the overnight-attention actionable candidate:

> TASK126 — SELECT ONE PRODUCT-FIT HYPOTHESIS AND COMPLETE ITS FIXED
> EVALUATION
>
> OBJECTIVE
> Make the next economic decision using existing data. Assess the two
> remaining Task122 candidates, select at most one before inspecting
> its returns, and complete its evaluation in this task if feasible.
>
> Do not reopen the overnight-attention contract, tune rejected
> strategies, or start another application-polishing cycle.
>
> BASELINE
> Research branch: research/talonx-profitability-2026-09
> Expected HEAD: 1248a0d7756446f282c7aea1d6c832e8408d5bd7
> Release branch: research/talonx-strategy-validation
> Expected HEAD: f28986999eec5e313cfc89db24e4dbacfb378891
> Verify actual state and preserve unrelated changes.
>
> Research-only authorization: read existing datasets and official
> research sources; implement isolated evaluation code and focused
> tests; commit and push research work normally. No production
> launch, Telegram sends, broker calls, paid data, live configuration
> changes, release merge, or strategy promotion. Preserve all ledgers,
> Redis, and SPCX obligations.
>
> 1. CLOSE TASK125 WITHOUT ANOTHER RERUN — append concise corrections:
>    statistical verdict remains INCONCLUSIVE, product verdict remains
>    DO_NOT_ADVANCE; "confirmed negative edge" is unsupported (the
>    expanded test retained negative point estimates without
>    establishing a statistically negative underlying expectancy); the
>    ±50% return guard is not complete corporate-action handling
>    (split-related volume effects and dividends remain limitations);
>    distinguish eligible dates, trigger dates, and bootstrap blocks.
>    Use stored artifacts only. Do not rerun Task125 or turn its
>    limitations into another repair project. Keep the overnight-
>    attention actionable contract closed.
>
> 2. APPLY A PRODUCT-FIT GATE TO BOTH REMAINING CANDIDATES — A.
>    52-week-high proximity; B. turn-of-month. Read Task122, prior
>    rejection history, current product requirements, and the original
>    papers using primary sources. For each candidate establish: the
>    exact mechanism the source studies; whether it requires shorting,
>    cross-sectional ranking, or a different universe; signal
>    availability and earliest causal entry; intended holding period;
>    whether it creates meaningful ticker-specific alerts or only a
>    common calendar exposure; its distinction from previously tested/
>    rejected TalonX contracts; existing-data coverage and corporate-
>    action requirements; an appropriate simple benchmark; the
>    implementation changes needed to translate the published mechanism
>    into the proposed long-only product. Do not assume a published
>    long-short or market-wide result transfers to a configured-ticker
>    long-only strategy. The product supports short/long-term alerts,
>    but do not silently redefine that as a six- or twelve-month
>    holding mandate. If a candidate requires an unsettled horizon
>    choice, make that an explicit product decision rather than
>    inventing a convenient shorter holding period.
>
> 3. SELECT AT MOST ONE BEFORE LOOKING AT RETURNS — record a concise
>    selection matrix and choose: ONE_CANDIDATE_SELECTED, or
>    NO_CANDIDATE_PASSES_PRODUCT_AND_DATA_GATES. Selection must use
>    mechanism, product fit, prior-research overlap, and data
>    feasibility — not preliminary performance. Do not evaluate both
>    candidates and then choose the winner. If neither passes: complete
>    the task with a concrete explanation, identify the smallest
>    product constraint or evidence requirement that must change, do
>    not invent a third hypothesis, start broad literature discovery,
>    or recommend indefinite live waiting. If one passes, proceed
>    through the remaining steps without stopping for another prompt.
>
> 4. FREEZE AN EXECUTABLE RESEARCH PROTOCOL — commit the protocol
>    before computing candidate returns [full field list, see prompt].
>    Use a source-grounded contract or clearly label a novel
>    adaptation. Do not search multiple lookbacks, thresholds,
>    horizons, or ticker subsets. Do not impose a 50-60% win-rate
>    requirement — positive net economics, loss exposure, and
>    robustness matter more.
>
> 5. VALIDATE THE DATA AND CAUSAL IMPLEMENTATION — [full checklist, see
>    prompt]. Use focused fixtures. Do not rebuild a backtest platform.
>
> 6. COMPLETE ONE EVALUATION — [full reporting requirements, see
>    prompt]. A positive benchmark-relative result cannot rescue
>    negative absolute long-only economics. A positive historical
>    estimate does not establish executable profitability.
>
> 7. ISSUE SEPARATE VERDICTS — Statistical: SUPPORTS_PREDECLARED_EFFECT
>    / DOES_NOT_SUPPORT_PREDECLARED_EFFECT / INCONCLUSIVE. Product:
>    ADVANCE_TO_FURTHER_VALIDATION / DO_NOT_ADVANCE /
>    BLOCKED_BY_SPECIFIC_PRODUCT_OR_DATA_REQUIREMENT. Apply the frozen
>    criteria. Do not rewrite them after seeing results. ADVANCE means
>    one further validation step, not deployment. For a rejected
>    result, archive the tested contract. For an inconclusive result,
>    identify the specific uncertainty and whether resolving it is
>    realistically feasible. Do not automatically prescribe a larger
>    rerun. Select one next action, or an explicit stop decision.
>
> 8. JOURNAL AND PUBLISH — update the existing journal with this exact
>    request, starting/final SHAs, candidate-selection reasoning,
>    protocol-freeze commit, data exposure and provenance, tests,
>    outcomes, corrections, and next decision. Publish
>    TASK126_CANDIDATE_SELECTION.md; TASK126_FROZEN_PROTOCOL.md if a
>    candidate passes; TASK126_ECONOMIC_DECISION.md; compact
>    machine-readable evidence; relevant scripts and focused tests;
>    PRODUCT_STATUS.md and research-ledger updates. Keep secrets, bulk
>    data, caches, and production databases out of Git. Commit and
>    push normally to the research branch. Checkpoint commits are
>    allowed. Do not merge into release/main.
>
> FINAL RESPONSE — TEN ITEMS: 1. Selection, statistical, and product
> verdicts. 2. Starting/final SHAs and push result. 3. Why the
> selected candidate fits — or why neither does. 4. Exact causal
> contract and holding period. 5. Coverage, costs, and corporate-
> action treatment. 6. Absolute and benchmark-relative economics. 7.
> Uncertainty, concentration, and limitations. 8. One next action or
> explicit stop decision. 9. Production preservation and process
> cleanup. 10. Journal, protocol, results, and evidence links.
>
> Priority: product fit → frozen contract → valid computation →
> economic decision. Complete the economic evaluation in this task
> when the gates pass; avoid another sequence of selection-only
> handoffs.
