# Request

Verbatim user request (2026-09-13), the explicit Option A resumption
of Task 129's paused programme:

> TASK130 — OPTION A: FREEZE THE DISCOVERY CONTRACT AND VERIFY ITS
> ECONOMICS
>
> OBJECTIVE
> Resume work specifically for the user-selected Option A: broader V2
> discovery while preserving the configured watchlist. Complete
> universe reconciliation, a frozen prospective execution contract, and
> one offline economic evaluation under the actual portfolio limits.
> This task must answer whether the expansion merits production
> integration. Do not stop at a design document if the required
> evidence and data are available.
>
> AUTHORIZATION
> Authorized: repository/existing-data inspection; narrow primary-
> source verification where necessary; isolated research
> implementation, tests, evaluation; research documentation, commits,
> normal pushes. Not authorized: production integration/activation;
> production ingestion expansion; external messages/broker calls/paid
> data/live configuration changes; release/main merges or production
> ledger modifications. Preserve Redis, the established V2 campaign,
> SPCX obligations. Production remains paused.
>
> BASELINE
> Release: research/talonx-strategy-validation @
> f28986999eec5e313cfc89db24e4dbacfb378891. Research: last confirmed
> documentation SHA 7afdfc7e625066e21be9a6ff2751a3de9c165629 — resolve
> current HEAD; a later documentation-only correction may exist;
> inspect and record it, don't reset. Treat Option A as an explicit,
> bounded resumption — do not reapply Task 129's blanket pause to
> prevent this authorized work.
>
> 1. RECORD THE FOUR-TIER PRODUCT CONTRACT — Tier 1 configured
>    watchlist (resolve actual configured/active/SEC-resolved counts,
>    previous snapshot 48/43/39, distinct populations not hard-coded
>    invariants). Tier 2 discovery universe (a versioned issuer-CIK
>    population anchored to actual Task112R evidence — no unevidenced
>    substitution with all-US-equities/Russell3000/S&P1500). Tier 3
>    alert subscription (WATCHLIST_ONLY/BROAD_DISCOVERY, must not
>    create paper positions/alter eligibility/disable existing exits).
>    Tier 4 paper execution (explicit approved discovery population,
>    own universe/policy versions, existing isolated V2 architecture;
>    existing-position management preserved even if an issuer leaves
>    the entry-eligible universe).
>
> 2. RECONCILE THE RESEARCHED UNIVERSE — inspect Task107B/109/112R and
>    subsequent matched-runtime evidence including Task118D. Resolve
>    from actual artifacts/code: research population/historical
>    membership, membership-OR-liquidity vs. liquidity-only
>    eligibility, price floor/trailing-volume calc, actual filters used
>    by the reported positive replay, episode vs. executed-round-trip
>    counts, runtime differences affecting comparability — not summary
>    labels or fingerprint equality alone. Produce a machine-readable
>    universe manifest (issuer CIK+symbol, membership/eligibility
>    source, effective dates/confidence, inclusion/exclusion reason,
>    price/filing coverage, known mapping ambiguities). No invented
>    market-cap threshold. Name any difference between documented rules
>    and executed research; choose the best-evidenced interpretation
>    before inspecting new returns, label variations explicitly (no
>    automatic Task112R inheritance). Report the exact blocker if the
>    population can't be reconstructed — never substitute a
>    trade-count-maximizing panel.
>
> 3. FREEZE THE SIGNAL AND PROSPECTIVE EXECUTION CONTRACT — preserve
>    INSIDER_BUY_CLUSTER_V2@1 fp 11107198c5b81237, >=2 distinct
>    Code-P owners/10 sessions, causal activation, next-XNYS-open
>    entry, exit add_sessions(entry,10), 5-session fall-forward,
>    5-session cooldown, no adds/shorts/real-capital. Deduplicate per
>    verified existing semantics, no manufactured owners. Prospective-
>    only campaign rule: historical filings/dispositions may be
>    stored; preserve the 45-day catch-up window; a new campaign
>    position requires a durably-recorded intent before the target-
>    entry deadline; a cold-start episode without one must not create
>    a historical-price position or change campaign cash; historical
>    reference calcs stay isolated to research records; delayed
>    reconciliation of a timely intent is permitted with timestamps
>    retained. Do not call this stricter policy "unchanged runtime
>    behavior" — current code permits labelled cold-start reference
>    fills without prior intents; document the change and test it.
>    Record filing availability/ingestion observation/decision+intent
>    creation/target entry deadline/price observation/fill+
>    notification timestamps. No manufactured intraday timestamps where
>    only dates exist.
>
> 4. FREEZE PORTFOLIO AND CAPACITY RULES — isolated $300,000 starting
>    capital, $10,000 entry allocation, max 20 open positions, no
>    borrowing/negative cash, $200,000 max simultaneous entry notional
>    (not a market-value/loss-risk cap), cash evolves with no daily
>    resets. Define before outcomes: reservation of cash/slots for
>    pending intents, release on expiry/cancellation, deterministic
>    ordering under competing capacity, simultaneous entry/exit
>    treatment, late reference-price handling, missing prices/
>    unresolved exits. Selection under capacity must not use future
>    information. Keep qualified signal decisions, capacity-blocked
>    paper outcomes, and notification outcomes separately labelled.
>
> 5. PREDECLARE THE ECONOMIC GATES — commit before new return
>    calculations. Primary: mean net return per closed round trip
>    >+0.50% after 20bps round-trip friction. Statistical: 95%
>    issuer-block bootstrap lower bound >0. Also freeze: a time-
>    dependence sensitivity for shared market periods; a disagreement-
>    between-methods rule; top-1/3/5-issuer-removal sensitivity with
>    "top" defined explicitly; calendar-period stability; concentration
>    measures; cost applied exactly once; benchmark/market-exposure
>    comparison using existing data; portfolio-risk reporting with no
>    invented drawdown tolerance (state risk explicitly, separate from
>    deployment-risk acceptance). Preserve PASS_FOR_INTEGRATION_REVIEW/
>    DO_NOT_ADVANCE/INCONCLUSIVE/BLOCKED_BY_SPECIFIC_EVIDENCE_GAP. Do
>    not rewrite criteria after results — the older +1.01% headline is
>    not an automatic pass for the new population/capacity/policy.
>
> 6. IMPLEMENT THE SMALLEST ISOLATED EVALUATION — reuse the existing V2
>    replay infrastructure and actual production-adjacent logic. Build
>    a dependency/runtime manifest (service/source/calendar/store/
>    pricing/execution modules, not only the 5 fingerprinted files).
>    Isolated databases, explicit paths, never instantiate stores
>    against production. Add focused tests: second-owner activation +
>    duplicate handling; membership/liquidity rule; historical
>    ingestion without historical campaign entries; timely intent +
>    delayed reference reconciliation; restart/intent idempotency;
>    capacity reservations + deterministic ordering; removed-universe
>    issuer with an existing open position; missing entry/exit prices +
>    bounded fall-forward; cost + daily equity reconciliation. A
>    bounded parity slice before the full run; compare with prior
>    research only where population/dates/prices/execution semantics
>    genuinely match; explain expected differences rather than forcing
>    bit-for-bit equality across different contracts.
>
> 7. COMPLETE ONE OFFLINE EVALUATION — one predeclared historical
>    window/population. Report: filings, distinct owners, clusters,
>    eligible episodes, prospective intents, entries, capacity
>    exclusions, stale/backfill exclusions, closed trades, open
>    positions, unresolved obligations, distinct issuers/trigger dates,
>    gross/net expectancy/PF/win rate, issuer and time-dependence
>    uncertainty, top-issuer removal sensitivity, period stability,
>    chronological cash/marked positions/equity, max drawdown/capital
>    utilization with precise definitions, modeled costs, reference-
>    fill limitations. Distinguish A. historical ideal-timing evidence,
>    B. timestamp-proven prospective-policy evidence, C. operational
>    latency evidence requiring later observation. No claiming
>    historical date-only data proves ingestion/notification
>    timeliness. No force-closing positions or omitting open losses.
>
> 8. PREPARE A CONCRETE INTEGRATION HANDOFF ONLY IF JUSTIFIED — if the
>    economic result passes, specify the minimum implementation delta
>    (discovery manifest refresh/staleness; one owned ingestion service
>    for after-hours/pre-open catch-up; shared 8 req/s SEC budget;
>    durable accession dedup + cursor-after-persist; session-close
>    interaction with continuous discovery; existing-position
>    management independent of new-entry eligibility; independent
>    alert subscription/execution scope; base alerts with verified
>    facts + accession links; optional bounded enrichment, no mandatory
>    LLM; lifecycle-specific dedup + ambiguous-send handling; lane
>    counters/dashboard compatibility). Specify the funnel: coverage ->
>    persisted filings -> Code-P records -> distinct owners -> clusters
>    -> eligibility/staleness -> intents -> paper dispositions ->
>    delivery outcomes. No production ingestion/broad delivery/
>    dashboard redesign/live activation in this task. If the evaluation
>    doesn't pass, finish with the economic decision and exact
>    limitation — no continuing integration merely because the design
>    is complete.
>
> 9. BUDGET AND EXECUTION DISCIPLINE — target at most two active
>    working days. Measure any long replay's runtime on a
>    representative slice before extrapolating. Reuse existing data; no
>    large new dataset acquisition without identifying the specific gap
>    and estimated effort. Checkpoint durable progress and commit as
>    appropriate. No silently shortening the frozen study window,
>    leaving duplicate processes, or claiming background monitoring
>    after the task ends. No threshold/horizon/issuer-subset/universe
>    search after outcomes.
>
> 10. JOURNAL AND PUBLISH — record this exact prompt, the explicit
>     Option A resumption, SHAs, protocol freeze, evidence,
>     implementation differences, tests, result, one next decision.
>     Publish TASK130_OPTION_A_CONTRACT.md, versioned universe
>     manifest, TASK130_FROZEN_EVALUATION_PROTOCOL.md,
>     TASK130_OPTION_A_ECONOMIC_DECISION.md, compact reconciliation/
>     gate evidence, relevant isolated code/tests, integration handoff
>     only if justified. Update PRODUCT_STATUS.md and the research
>     ledger minimally. Commit/push normally to the research branch, no
>     release/main merge, secrets/bulk data/caches/production databases
>     out of Git.
>
> FINAL RESPONSE: 1. Economic, statistical, and integration-review
> verdicts. 2. Starting/final SHAs and push result. 3. Exact discovery
> population and eligibility rule. 4. Changes from the old research/
> runtime contract. 5. Prospective-entry and capacity-policy
> acceptance. 6. Net economics, uncertainty, concentration, stability.
> 7. Marked-equity risk and unresolved positions. 8. Timestamp/data
> limitations. 9. One next action and production preservation. 10.
> Journal, protocol, manifests, results, code links.
>
> Success means one defensible decision about this exact V2
> expansion—not more alerts, a preserved fingerprint, or another
> design-only handoff.
