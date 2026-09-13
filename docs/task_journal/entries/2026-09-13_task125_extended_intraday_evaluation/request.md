# Request

Verbatim user request (2026-09-13), immediately following Task 124's
data-feasibility verdict:

> TASK125 — ACQUIRE CONSISTENT INTRADAY DATA, VALIDATE IT, AND COMPLETE
> ONE FROZEN ECONOMIC EVALUATION
>
> OBJECTIVE
> Complete the next economic decision in one task: acquire the feasible
> data extension identified by Task124, validate its suitability, and
> evaluate Task123 Track B once.
>
> Do not stop after inventory or acquisition if the required evidence is
> available. Do not tune the strategy or open another dashboard/
> infrastructure workstream.
>
> BASELINE
> Research branch: research/talonx-profitability-2026-09
> Expected HEAD: 79c3591971d09064f8c44f8fed4dcc6ce7d8a71e
> Release branch: research/talonx-strategy-validation
> Expected HEAD: f28986999eec5e313cfc89db24e4dbacfb378891
> Verify actual SHAs and preserve unrelated changes.
>
> AUTHORIZATION
> This task authorizes: historical market-data downloads through
> existing credentialed free access; isolated research code, data
> validation, and the evaluation below; research documentation,
> commits, and normal push. It does not authorize paid access,
> production activation, external messages, broker activity, live
> configuration changes, or strategy promotion. Preserve production
> ledgers, Redis, and outstanding SPCX obligations. Do not instantiate
> production store classes against live paths.
>
> 1. READ THE EXISTING CONTRACT AND FREEZE THE EXTENSION — read Task
>    123's protocol/implementation/evidence and Task124's acquisition
>    spec. Retain Track B's pre-close cutoff, same-time-of-day
>    cumulative-volume definition/window, trigger threshold, 2-minute
>    delay, next-session-open exit, cost convention/sensitivities. Do
>    not substitute final/yesterday volume, a different cutoff, or a
>    different holding period. Before calculating any new returns,
>    commit a protocol addendum: exact ticker list/active-paused
>    snapshot/source; exact start/end dates + pre-roll; original-12 vs.
>    added cohort; feed/adjustment/corporate-action policy; missing-
>    data/early-close treatment; primary estimand/control/uncertainty/
>    materiality; exact decision criteria; prior data exposure/
>    limitations. Use Task124's spec as the starting point (extend the
>    12 symbols back to 2023-01-01, add the 5 identified names).
>    Resolve the common endpoint before outcomes. Distinguish "unused
>    for this hypothesis" from genuinely independent confirmation.
>
> 2. ENSURE CONSISTENT FEED PROVENANCE — resolve Task93's missing feed
>    identity from contemporaneous metadata/acquisition code/logs, not
>    from similar prices/row counts alone. If unresolved, preserve the
>    legacy dataset and download a SEPARATE consistently-SIP dataset;
>    never concatenate unknown-feed history with SIP. Separate feed
>    changes from window/population changes in the results. Reuse
>    existing adapters/rate-limited pagination; no general-purpose
>    ingestion platform.
>
> 3. ACQUIRE DATA WITH RESUMABLE PROGRESS — explicit feed=sip, raw
>    adjustment. Research-only storage paths; bounded concurrency +
>    provider-compliant backoff; durable progress by symbol/date
>    partition; resume rather than restart; record request params/
>    timestamp/feed/adjustment/coverage/row count/file hash; dedup +
>    deterministic sort; preserve provider failures vs. genuine empty
>    responses separately. No credentials printed, no raw data
>    committed. Run a small pilot first, measure throughput/storage,
>    report a revised estimate, then continue. Checkpoint safely and
>    report exact coverage if blocked or over-budget; no duplicate
>    processes left running.
>
> 4. VALIDATE CAUSAL TIMING AND CORPORATE ACTIONS — verify session
>    calendars/next-session lookup, bar timestamp meaning/availability,
>    no decision input later than the cutoff, entry after decision+
>    delay, actual next session (not next arbitrary row), complete
>    prior reference windows, no forward-fill across missing entry/
>    exit, no pre-listing fabricated histories, early-close handling.
>    Apply the predeclared corporate-action policy: raw returns must
>    not treat a split as gain/loss; distinguish price vs. shareholder
>    return; no double-counting dividends; validate volume comparability
>    across splits; exclude+quantify if reliable action info is
>    unavailable. Do not silently swap in adjustment=all and call the
>    estimand unchanged. Produce an eligibility funnel with mutually
>    exclusive exclusion reasons.
>
> 5. RUN ONE EFFICIENT EVALUATION — reuse Task123's implementation,
>    only ingestion/validation/correctness-defect changes. Vectorized
>    per-session reduction, not the QuantScanner replay. Test on a
>    small deterministic fixture first. Compute separately: A. original
>    12 on expanded window; B. newly added symbols; C. combined,
>    explicitly secondary; D. original window on verified SIP to expose
>    feed differences. Do not pick the best cohort after seeing
>    results. Report per cohort: eligible/triggers/issuers/dates, gross
>    and net returns, incremental vs. control, mean/median/win rate/
>    tail losses, concentration + time-period breakdown, cost/exclusion
>    accounting, CIs via the predeclared date-dependence method, only
>    the already-predeclared sensitivities. Preserve common-date
>    dependence/overlap in resampling. Positive incremental alone is
>    insufficient — also needs economically credible positive absolute
>    net returns. No portfolio/drawdown inference beyond event-return
>    statistics unless specified.
>
> 6. MAKE THE ECONOMIC DECISION — separate statistical
>    (EVIDENCE_SUPPORTS_PREDECLARED_EFFECT / EVIDENCE_AGAINST_
>    PREDECLARED_EFFECT / INCONCLUSIVE) and product
>    (ADVANCE_TO_FURTHER_VALIDATION / DO_NOT_ADVANCE /
>    EVALUATION_BLOCKED_BY_DATA_QUALITY) verdicts. Apply frozen criteria
>    without rewriting after results. ADVANCE means further validation
>    only. If negative/economically inadequate, close the contract — no
>    searching thresholds/delays/exits/subsets within this task. If
>    inconclusive, name the exact remaining uncertainty, not another
>    automatic rerun or indefinite live waiting.
>
> 7. JOURNAL, COMMIT, AND PUSH — record the exact request, protocol
>    freeze, actions, SHAs, data provenance, corrections, tests,
>    results, decision. Publish TASK125_FROZEN_EXTENSION_PROTOCOL.md,
>    TASK125_DATA_ACCEPTANCE.md, TASK125_OVERNIGHT_ACTIONABLE_RESULTS.md,
>    machine-readable coverage/exclusion/result summaries, relevant
>    scripts/focused tests, updated PRODUCT_STATUS.md and research
>    ledger. Keep bulk data/credentials/production DBs/generated caches
>    out of Git. Normal research-branch commits/push, checkpoint
>    commits allowed, no release/main merge.
>
> FINAL RESPONSE — TEN ITEMS: 1. Statistical and product verdicts. 2.
> Starting/final SHAs and push result. 3. Acquired coverage, feed
> provenance, exclusions. 4. Contract fidelity and timing validation.
> 5. Corporate-action and cost treatment. 6. Original-cohort and
> added-cohort economics. 7. Absolute vs. incremental net returns and
> uncertainty. 8. Limitations and one next decision. 9. Production
> preservation and process cleanup. 10. Journal, protocol, data
> acceptance, and result links.
>
> Complete acquisition → validation → economic decision in this task
> wherever evidence permits. Avoid further application polishing unless
> a specific defect blocks this evaluation.
